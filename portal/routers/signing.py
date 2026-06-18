import base64
import datetime as dt
from fastapi import APIRouter, Body, Depends, HTTPException, Response
from portal.db import Document, DocStatus, SessionLocal, SignerStatus
from portal.auth import _current_user
from portal import domain_bridge as bridge
from portal.helpers import (
    _audit,
    _load,
    _doc_to_dict,
    _payload_with_signatures,
    _regenerate,
    _render_marked,
    _assemble_asice,
    _auto_register_for_signing,
)

router = APIRouter(tags=["signing"])


def _is_active_signer(nxt, current_user: dict) -> bool:
    """Чи може цей користувач підписати як активний підписант.

    Signer не має user_id (на відміну від Approver), тож звіряємо по ПІБ
    та сертифікату. Admin може підписати за будь-кого (службова заміна)."""
    role = current_user.get("role")
    if role == "admin":
        return True
    name = (current_user.get("name") or "").strip().lower()
    subject_cn = (current_user.get("kep_subject_cn") or "").strip().lower()
    signer_name = (nxt.full_name or "").strip().lower()
    return signer_name in (name, subject_cn) if signer_name else False


@router.post("/documents/{doc_id}/validate")
def validate_document(
    doc_id: str, current_user: dict = Depends(_current_user)
) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        payload = _payload_with_signatures(doc)
        return bridge.validate(payload)


@router.get("/documents/{doc_id}/manifest")
def signing_manifest(
    doc_id: str, current_user: dict = Depends(_current_user)
) -> Response:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.rendered:
            raise HTTPException(409, "спершу згенеруйте документ (/generate)")
        nxt = doc.next_signer
        if nxt is None:
            raise HTTPException(409, "немає активного підписанта")
        manifest = bridge.manifest_for_signer(
            doc.doc_id, doc.fmt, doc.rendered, nxt.order_index
        )
        return Response(content=manifest, media_type="application/xml")


@router.get("/documents/{doc_id}/download/asice")
def download_asice(
    doc_id: str, current_user: dict = Depends(_current_user)
) -> Response:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.asice:
            raise HTTPException(
                404, "ASiC-E ще не зібрано (документ має бути підписаний усіма)"
            )
        return Response(
            content=doc.asice,
            media_type="application/vnd.etsi.asic-e+zip",
            headers={"Content-Disposition": f'attachment; filename="{doc_id}.asice"'},
        )


@router.post("/documents/{doc_id}/submit")
def submit_for_signing(
    doc_id: str,
    payload: dict = Body(default={}),
    current_user: dict = Depends(_current_user),
) -> dict:
    auto_register = bool(payload.get("auto_register", True))
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.signers:
            raise HTTPException(400, "немає підписантів у черзі")
        if doc.status != DocStatus.DRAFT:
            raise HTTPException(
                409,
                f"документ у статусі «{doc.status.value}» — повторне подання у чергу "
                "неможливе (підписи вже зібрано або процес триває)",
            )

        _auto_register_for_signing(session, doc, auto_register)

        doc.status = DocStatus.PENDING_SIGNATURES
        doc.signers[0].status = SignerStatus.INVITED
        _audit(session, doc, "submitted", actor=current_user.get("name", ""))
        session.commit()
        return _doc_to_dict(doc)


@router.post("/documents/{doc_id}/sign")
def sign_document(
    doc_id: str,
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status != DocStatus.PENDING_SIGNATURES:
            raise HTTPException(409, "документ не у статусі очікування підписів")

        nxt = doc.next_signer
        if nxt is None:
            raise HTTPException(409, "черга підписання порожня")
        idx = int(payload.get("signer_order_index", nxt.order_index))
        if idx != nxt.order_index:
            raise HTTPException(
                409, f"зараз черга підписанта #{nxt.order_index} ({nxt.full_name})"
            )
        # лише активний підписант (або admin) може підписати цим КЕП
        if not _is_active_signer(nxt, current_user):
            raise HTTPException(
                403,
                f"ви не є активним підписувачем ({nxt.full_name}) цього документа",
            )

        sig_b64 = payload.get("signature_b64")
        if not sig_b64:
            raise HTTPException(400, "signature_b64 обовʼязковий (КЕП з клієнта)")

        try:
            sig_bytes = base64.b64decode(sig_b64)
        except Exception:
            raise HTTPException(400, "signature_b64 не є коректним base64")
        if len(sig_bytes) < 256 or sig_bytes[0] != 0x30:
            raise HTTPException(
                422, "недійсний підпис: очікується CMS/p7s (DER) від EUSign, "
                "а не тестове значення"
            )

        nxt.signature = sig_bytes
        cert = bridge.cert_info_from_cms(sig_bytes)
        nxt.certificate_serial = (
            cert.get("certificate_serial") or str(payload.get("certificate_serial", "")) or ""
        )
        nxt.issuer = cert.get("issuer") or str(payload.get("issuer", "")) or ""
        nxt.valid_from = cert.get("valid_from") or ""
        nxt.valid_to = cert.get("valid_to") or ""
        nxt.status = SignerStatus.SIGNED
        nxt.signed_at = dt.datetime.now(dt.timezone.utc)
        _audit(session, doc, "signed", actor=cert.get("signer") or nxt.full_name,
               detail=f"serial={nxt.certificate_serial} issuer={nxt.issuer}")

        following = doc.next_signer
        if following is None:
            doc.status = DocStatus.SIGNED
            _audit(session, doc, "all_signed")
            _assemble_asice(session, doc)
        else:
            following.status = SignerStatus.INVITED

        _render_marked(session, doc)

        session.commit()
        return _doc_to_dict(doc)


@router.post("/documents/{doc_id}/reject")
def reject_document(
    doc_id: str,
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        nxt = doc.next_signer
        if nxt is None:
            raise HTTPException(409, "немає активного підписанта")
        # відхилити може активний підписант (це його право не підписувати) або admin
        if not _is_active_signer(nxt, current_user):
            raise HTTPException(403, "відхилити може лише активний підписувач або admin")
        nxt.status = SignerStatus.REJECTED
        doc.status = DocStatus.DRAFT
        _audit(session, doc, "rejected", actor=nxt.full_name,
               detail=str(payload.get("reason", "")))
        session.commit()
        return _doc_to_dict(doc)


@router.post("/documents/{doc_id}/publish")
def publish_document(
    doc_id: str, current_user: dict = Depends(_current_user)
) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status != DocStatus.SIGNED:
            raise HTTPException(409, "оприлюднення лише після підписання всіма")
        doc.status = DocStatus.PUBLISHED
        _audit(session, doc, "published", actor=current_user.get("name", ""))
        session.commit()
        return _doc_to_dict(doc)


@router.post("/documents/{doc_id}/archive")
def archive_document(
    doc_id: str, current_user: dict = Depends(_current_user)
) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.archived_at is None:
            doc.archived_at = dt.datetime.now(dt.timezone.utc)
            _audit(session, doc, "archived", actor=current_user.get("name", ""))
            session.commit()
        return _doc_to_dict(doc)


@router.post("/documents/{doc_id}/unarchive")
def unarchive_document(
    doc_id: str, current_user: dict = Depends(_current_user)
) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.archived_at is not None:
            doc.archived_at = None
            _audit(session, doc, "unarchived", actor=current_user.get("name", ""))
            session.commit()
        return _doc_to_dict(doc)

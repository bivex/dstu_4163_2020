import base64
import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path
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


# --- конфігурація серверного підпису печаткою (env PORTAL_SEAL_*) ----------
@dataclass(frozen=True)
class SealConfig:
    """Налаштування серверного підпису печаткою юрособи.

    None з _seal_config() = печатка не налаштована (ендпоїнт повертає 503).
    Пароль береться з env, ніколи не логується.
    """

    p12_path: str
    password: str
    cert_cache_dir: str
    crl_cache_dir: str
    with_timestamp: bool = False
    tsp_url: str | None = None
    cmp_url: str | None = None


# Кеш-каталоги сертифікатів/CRL порталу (типові шляхи, як у verify_signature).
_HERE = Path(__file__).resolve().parent.parent  # portal/


def _seal_config() -> SealConfig | None:
    """Налаштування серверної печатки з env. None — якщо PORTAL_SEAL_P12 не задано."""
    p12 = os.environ.get("PORTAL_SEAL_P12", "").strip()
    if not p12:
        return None
    password = os.environ.get("PORTAL_SEAL_PASSWORD", "")
    cert_cache = os.environ.get(
        "PORTAL_SEAL_CERT_CACHE", str(_HERE.parent / ".euscp_store")
    )
    crl_cache = os.environ.get("PORTAL_SEAL_CRL_CACHE", "/tmp/crls")
    return SealConfig(
        p12_path=p12,
        password=password,
        cert_cache_dir=cert_cache,
        crl_cache_dir=crl_cache,
        with_timestamp=os.environ.get("PORTAL_SEAL_WITH_TIMESTAMP") == "1",
        tsp_url=os.environ.get("PORTAL_SEAL_TSP_URL") or None,
        cmp_url=os.environ.get("PORTAL_SEAL_CMP_URL") or None,
    )



def _is_active_signer(nxt, current_user: dict) -> bool:
    """Чи може цей користувач підписати як активний підписант.

    Signer не має user_id (на відміну від Approver), тож звіряємо по ПІБ
    та сертифікату. Admin може підписати за будь-кого (службова заміна).

    Для signer_type='seal' (електронна печатка юрособи) перевіряємо збіг CN
    сертифіката печатки, прив'язаного в кабінеті (organization_cert_cn), із
    назвою юрособи-підписанта. Для person — звіряємо по ПІБ та КЕП-CN як раніше.
    """
    role = current_user.get("role")
    if role == "admin":
        return True

    if getattr(nxt, "signer_type", "person") == "seal":
        org_cn = (current_user.get("organization_cert_cn") or "").strip().lower()
        signer_name = (nxt.full_name or "").strip().lower()
        return bool(signer_name) and signer_name == org_cn

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
        atts = [(a.stored_filename, a.blob) for a in doc.attachments]
        manifest = bridge.manifest_for_signer(
            doc.doc_id, doc.fmt, doc.rendered, atts, nxt.order_index
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
        _apply_signature(session, doc, nxt, sig_bytes, current_user, source="client")
        session.commit()
        return _doc_to_dict(doc)


def _apply_signature(
    session,
    doc: Document,
    nxt,
    sig_bytes: bytes,
    current_user: dict,
    *,
    source: str = "client",
) -> None:
    """Спільна логіка застосування прийнятого CMS-підпису до підписанта черги.

    Використовується як клієнтським ``sign`` (КЕП/печатка з браузера), так і
    серверним ``server-seal`` (печатка з PKCS#12 на сервері). ``source`` потрапляє
    в аудит, щоб розрізнити джерело підпису.

    На вхід: вже провалідований (формат) sig_bytes; ``nxt.signature`` має бути
    встановленим ДО виклику. Виконує: витяг cert-даних, встановлення signer_type
    для печатки, перехід черги, рендер відміток, збірку ASiC-E, аудит.
    """
    cert = bridge.cert_info_from_cms(sig_bytes)
    cert_type = cert.get("cert_type", "esign")
    # якщо CMS несе eSeal-сертифікат — позначаємо підписанта як seal і
    # зберігаємо дані печатки (організація, ідентифікатор). Для КЕП особи
    # signer_type лишається 'person' (як задано при створенні чернетки).
    if cert_type == "eseal":
        nxt.signer_type = "seal"
        nxt.organization = cert.get("organization") or ""
        nxt.identifier = cert.get("identifier") or ""
    nxt.certificate_serial = cert.get("certificate_serial") or ""
    nxt.issuer = cert.get("issuer") or ""
    nxt.valid_from = cert.get("valid_from") or ""
    nxt.valid_to = cert.get("valid_to") or ""
    nxt.status = SignerStatus.SIGNED
    nxt.signed_at = dt.datetime.now(dt.timezone.utc)

    actor = cert.get("signer") or nxt.full_name
    detail = f"source={source} serial={nxt.certificate_serial} issuer={nxt.issuer} type={cert_type}"
    if cert_type == "eseal":
        detail += f" org={nxt.organization} id={nxt.identifier}"
    _audit(session, doc, "signed", actor=actor, detail=detail)

    following = doc.next_signer
    if following is None:
        doc.status = DocStatus.SIGNED
        _audit(session, doc, "all_signed")
        _assemble_asice(session, doc)
    else:
        following.status = SignerStatus.INVITED

    _render_marked(session, doc)


@router.post("/documents/{doc_id}/server-seal")
def server_seal_document(
    doc_id: str,
    current_user: dict = Depends(_current_user),
) -> dict:
    """Накласти електронну печатку юрособи СЕРВЕРОМ (ключ у PKCS#12 на сервері).

    На відміну від ``/sign`` (КЕП з браузера), тут сервер сам генерує CAdES-підпис
    печаткою над маніфестом ASiC-E. Підписант має бути signer_type='seal', а
    поточний користувач — мати прив'язану печатку (organization_cert_cn == CN).

    Потребує PORTAL_SEAL_P12 / PORTAL_SEAL_PASSWORD в оточенні; без них → 503.
    """
    cfg = _seal_config()
    if cfg is None:
        raise HTTPException(
            503,
            "серверний підпис печаткою не налаштований "
            "(задайте PORTAL_SEAL_P12 / PORTAL_SEAL_PASSWORD)",
        )

    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status != DocStatus.PENDING_SIGNATURES:
            raise HTTPException(409, "документ не у статусі очікування підписів")

        nxt = doc.next_signer
        if nxt is None:
            raise HTTPException(409, "черга підписання порожня")
        if getattr(nxt, "signer_type", "person") != "seal":
            raise HTTPException(
                409,
                f"активний підписант #{nxt.order_index} ({nxt.full_name}) не є печаткою "
                "(signer_type='person') — серверний підпис лише для печаток юрособи",
            )
        # авторизація: юзер з прив'язаною печаткою, CN якої збігається з підписантом
        if not _is_active_signer(nxt, current_user):
            raise HTTPException(
                403,
                "у вашому кабінеті не прив'язана печатка цієї юрособи "
                f"(очікується CN = {nxt.full_name})",
            )

        if not doc.rendered:
            raise HTTPException(409, "спершу згенеруйте документ (/generate)")

        atts = [(a.stored_filename, a.blob) for a in doc.attachments]
        # ТОЙ ЖЕ маніфест, що й клієнтський підпис — digest співпадає, ASiC збереться
        manifest = bridge.manifest_for_signer(
            doc.doc_id, doc.fmt, doc.rendered, atts, nxt.order_index
        )

        try:
            from dilovod4.infrastructure.server_seal import (
                ServerSealError,
                sign_with_server_seal,
            )
            from dilovod4.infrastructure.uapki import UapkiError, UapkiLibraryNotFound

            result = sign_with_server_seal(
                manifest,
                p12_path=cfg.p12_path,
                password=cfg.password,
                cert_cache_dir=cfg.cert_cache_dir,
                crl_cache_dir=cfg.crl_cache_dir,
                with_timestamp=cfg.with_timestamp,
                tsp_url=cfg.tsp_url,
                cmp_url=cfg.cmp_url,
            )
        except UapkiLibraryNotFound as exc:
            raise HTTPException(
                503, f"серверний підпис недоступний: {exc}"
            )
        except ServerSealError as exc:
            raise HTTPException(500, f"помилка конфігурації печатки: {exc}")
        except UapkiError as exc:
            raise HTTPException(500, f"помилка підпису печаткою: {exc}")

        sig_bytes = result.container
        if len(sig_bytes) < 256 or sig_bytes[0] != 0x30:
            raise HTTPException(500, "недійсний підпис печатки (очікується CMS/p7s DER)")

        nxt.signature = sig_bytes
        _apply_signature(session, doc, nxt, sig_bytes, current_user, source="server-seal")
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


@router.get("/documents/{doc_id}/signers/{order_index}/download-signature")
def download_signer_signature(
    doc_id: str,
    order_index: int,
    current_user: dict = Depends(_current_user),
):
    from urllib.parse import quote
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        signer = next((s for s in doc.signers if s.order_index == order_index), None)
        if not signer:
            raise HTTPException(404, "Підписанта не знайдено")
        if not signer.signature:
            raise HTTPException(400, "Підпис ще не накладено")

        filename = f"{doc_id}_signature_{order_index + 1}.p7s"
        encoded_filename = quote(filename)
        return Response(
            content=signer.signature,
            media_type="application/pkcs7-signature",
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{encoded_filename}",
                "Access-Control-Expose-Headers": "Content-Disposition",
            }
        )


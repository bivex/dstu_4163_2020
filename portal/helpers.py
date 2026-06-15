import datetime as dt
import json
import os
import tempfile
from fastapi import HTTPException
from . import domain_bridge as bridge
from .db import AuditEvent, Document, Folder, SessionLocal, Signer, SignerStatus


def _audit(session, doc: Document, kind: str, actor: str = "", detail: str = "") -> None:
    session.add(AuditEvent(document_id=doc.id, kind=kind, actor=actor, detail=detail))


def _load(session, doc_id: str) -> Document:
    doc = session.query(Document).filter_by(doc_id=doc_id).first()
    if doc is None:
        raise HTTPException(404, f"документ {doc_id} не знайдено")
    return doc


def _payload_with_signatures(doc: Document) -> dict:
    """Payload документа з реальними КЕП-відмітками із doc.signers (підписані)."""
    payload = bridge.content_from_json(doc.content_json)
    payload["e_signatures"] = [
        {
            "signer": s.full_name,
            "signer_position": s.position,
            "certificate_serial": s.certificate_serial or "—",
            "issuer": s.issuer or "—",
            "valid_from": s.valid_from or "",
            "valid_to": s.valid_to or "",
            "timestamp": s.signed_at.isoformat(timespec="seconds") if s.signed_at else "",
            "status": "Active",
            "is_qualified": True,
        }
        for s in doc.signers
        if s.status == SignerStatus.SIGNED
    ]
    return payload


def _extract_org_name(doc: Document) -> str:
    """Найменування організації з content_json (для пошуку за контрагентом у списку)."""
    try:
        content = bridge.content_from_json(doc.content_json)
        return str(content.get("org_name", "") or "")
    except Exception:
        return ""


def _doc_to_dict(doc: Document, brief: bool = False) -> dict:
    data = {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "status": doc.status.value,
        "fmt": doc.fmt,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "retention_until": doc.retention_until.isoformat() if doc.retention_until else None,
        "signers": [
            {
                "order_index": s.order_index,
                "full_name": s.full_name,
                "position": s.position,
                "status": s.status.value,
                "certificate_serial": s.certificate_serial,
                "signed_at": s.signed_at.isoformat() if s.signed_at else None,
            }
            for s in doc.signers
        ],
        "has_rendered": doc.rendered is not None,
        "has_asice": doc.asice is not None,
        "reg_index": doc.reg_index,
        "reg_date": doc.reg_date,
        "reg_number": doc.reg_number,
        "doc_type": doc.doc_type,
        "registered_at": doc.registered_at.isoformat() if doc.registered_at else None,
        "archived": doc.archived_at is not None,
        "archived_at": doc.archived_at.isoformat() if doc.archived_at else None,
        "is_scanned": bool(doc.is_scanned),
        "folder_id": doc.folder_id,
        "journal_id": doc.journal_id,
        "org_name": _extract_org_name(doc),
        "approval_type": doc.approval_type.value if hasattr(doc.approval_type, "value") else doc.approval_type,
        "approvers": [
            {
                "order_index": a.order_index,
                "user_id": a.user_id,
                "full_name": a.full_name,
                "position": a.position,
                "status": a.status.value if hasattr(a.status, "value") else a.status,
                "comment": a.comment,
                "approved_at": a.approved_at.isoformat() if a.approved_at else None,
            }
            for a in doc.approvers
        ],
    }
    if not brief:
        data["content_json"] = json.loads(doc.content_json) if doc.content_json else {}
        data["conformance"] = (
            json.loads(doc.conformance_json) if doc.conformance_json else None
        )
        data["events"] = [
            {"kind": e.kind, "actor": e.actor, "detail": e.detail,
             "at": e.created_at.isoformat() if e.created_at else None}
            for e in doc.events
        ]
    return data


def _folder_to_dict(folder: Folder, doc_count: int | None = None) -> dict:
    return {
        "id": folder.id,
        "name": folder.name,
        "color": folder.color,
        "position": folder.position,
        "created_at": folder.created_at.isoformat() if folder.created_at else None,
        "doc_count": doc_count,
    }


def _regenerate(session, doc: Document, payload: dict) -> None:
    """Перегенерувати чистий документ + conformance після зміни даних."""
    with tempfile.NamedTemporaryFile(suffix=f".{doc.fmt}", delete=False) as tmp:
        dest = tmp.name
    try:
        out = bridge.generate(payload, doc.fmt, dest)
        with open(out["path"], "rb") as fh:
            doc.rendered = fh.read()
        doc.conformance_json = json.dumps(out["report"], ensure_ascii=False)
    finally:
        for p in (dest, dest + f".{doc.fmt}"):
            if os.path.exists(p):
                os.remove(p)


def _auto_register_for_signing(session, doc: Document, auto_register: bool = True) -> None:
    """Присвоїти реєстраційний індекс/дату й перевести документ у чергу підписання.

    Спільна логіка для ручного /submit та авто-переходу після завершення погодження
    (_complete_approval). Гарантує, що документ отримує реєстрацію в обох випадках.
    Викликати лише коли doc.signers непорожній і doc у DRAFT.
    """
    from . import registry

    content = bridge.content_from_json(doc.content_json)
    doc_type = str(content.get("doc_type", "Документ"))
    manual_index = str(content.get("reg_index", "")).strip()
    manual_date = str(content.get("date_text", "")).strip()
    changed = False

    if auto_register:
        if not manual_index:
            registry.assign_registration(session, doc, doc_type)
            content["reg_index"] = doc.reg_index
            content["date_text"] = manual_date or doc.reg_date
            changed = True
        else:
            doc.doc_type = doc_type
            doc.reg_index = manual_index
            doc.reg_date = manual_date or registry.format_ua_date(
                dt.datetime.now(dt.timezone.utc).date()
            )
            doc.registered_at = dt.datetime.now(dt.timezone.utc)
            content["date_text"] = doc.reg_date
            changed = True

    if changed:
        doc.content_json = bridge.content_to_json(content)
        if doc.rendered is not None and not doc.is_scanned:
            _regenerate(session, doc, content)
        _audit(session, doc, "registered",
               detail=f"reg_index={doc.reg_index} date={doc.reg_date}")


def _render_marked(session, doc: Document) -> None:
    """Перебудувати marked-візуалізацію (PDF/DOCX з відмітками про КЕП + QR)."""
    if doc.is_scanned:
        return
    payload = _payload_with_signatures(doc)
    with tempfile.NamedTemporaryFile(suffix=f".{doc.fmt}", delete=False) as tmp:
        dest = tmp.name
    try:
        path = bridge.render_marked(payload, doc.fmt, dest)
        with open(path, "rb") as fh:
            doc.rendered_marked = fh.read()
        report = bridge.validate(payload)
        doc.conformance_json = json.dumps(report, ensure_ascii=False)
        _audit(session, doc, "marked_rendered",
               detail=f"signatures={len(payload['e_signatures'])} "
                      f"conforms={report.get('conforms')}")
    finally:
        for p in (dest, dest + f".{doc.fmt}"):
            if os.path.exists(p):
                os.remove(p)


def _assemble_asice(session, doc: Document) -> None:
    """Зібрати ASiC-E контейнер після підпису всіма; зберегти у doc.asice."""
    if not doc.rendered:
        return
    sigs = [
        (s.full_name, s.signature)
        for s in doc.signers
        if s.status == SignerStatus.SIGNED and s.signature
    ]
    if not sigs:
        return
    with tempfile.NamedTemporaryFile(suffix=".asice", delete=False) as tmp:
        dest = tmp.name
    try:
        bridge.build_asice(doc.doc_id, doc.fmt, doc.rendered, sigs, dest)
        with open(dest, "rb") as fh:
            doc.asice = fh.read()
        _audit(session, doc, "asice_built", detail=f"signatures={len(sigs)}")
    finally:
        if os.path.exists(dest):
            os.remove(dest)

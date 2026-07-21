import datetime as dt
import json
import os
import tempfile
from fastapi import HTTPException
from . import domain_bridge as bridge
from .db import AuditEvent, Document, DocStatus, Folder, SessionLocal, Signer, SignerStatus, UserRole


def _audit(session, doc: Document, kind: str, actor: str = "", detail: str = "") -> None:
    session.add(AuditEvent(document_id=doc.id, kind=kind, actor=actor, detail=detail))


def _load(session, doc_id: str) -> Document:
    doc = session.query(Document).filter_by(doc_id=doc_id).first()
    if doc is None:
        raise HTTPException(404, f"документ {doc_id} не знайдено")
    return doc


def _assert_editable(doc: Document, current_user: dict | None) -> None:
    """Централізований guard: чи може цей користувач змінювати документ.

    Правило: документ лочиться повністю при виході зі статусу DRAFT
    (pending_approval/pending_signatures/signed/published). Усі, крім admin,
    отримують 409. admin — виняток для службових дій (повертає в draft через
    окремий адмін-маршрут, а не прямим редагуванням).

    current_user — розкодований JWT-dict (з _current_user) або None, якщо
    ендпоїнт ще не авторизований (тоді перевірка лише за статусом — лочить всіх).
    """
    if doc.status == DocStatus.DRAFT:
        return
    role = (current_user or {}).get("role")
    if role != UserRole.ADMIN.value:
        raise HTTPException(
            409,
            f"документ у статусі «{doc.status.value}» — редагування заборонено",
        )


def _payload_with_signatures(doc: Document) -> dict:
    """Payload документа з реальними КЕП/печатка-відмітками із doc.signers."""
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
            # тип відмітки (esign|eseal) + дані печатки. kind виводиться з
            # signer_type: seal → eseal, інакше esign (зворотна сумісність).
            "kind": "eseal" if s.signer_type == "seal" else "esign",
            "organization": s.organization or "",
            "identifier": s.identifier or "",
        }
        for s in doc.signers
        if s.status == SignerStatus.SIGNED
    ]
    payload["_attachment_count"] = len(doc.attachments)
    payload["has_attachments_inventory"] = any(a.stored_filename == "опис_додатків.pdf" for a in doc.attachments)
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
                "signer_type": s.signer_type,
                "organization": s.organization,
                "identifier": s.identifier,
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
        "attachments": [
            {
                "id": att.id,
                "order_index": att.order_index,
                "original_filename": att.original_filename,
                "stored_filename": att.stored_filename,
                "mime": att.mime,
                "size": att.size,
                "created_at": att.created_at.isoformat() if att.created_at else None,
            }
            for att in doc.attachments
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
    payload["_attachment_count"] = len(doc.attachments)
    payload["has_attachments_inventory"] = any(a.stored_filename == "опис_додатків.pdf" for a in doc.attachments)
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
    atts = [(a.stored_filename, a.blob) for a in doc.attachments]
    with tempfile.NamedTemporaryFile(suffix=".asice", delete=False) as tmp:
        dest = tmp.name
    try:
        bridge.build_asice(doc.doc_id, doc.fmt, doc.rendered, atts, sigs, dest)
        with open(dest, "rb") as fh:
            doc.asice = fh.read()
        _audit(session, doc, "asice_built", detail=f"signatures={len(sigs)}")
    finally:
        if os.path.exists(dest):
            os.remove(dest)


def ensure_attachments_inventory(session, doc: Document) -> None:
    """Автоматично генерує та підтримує в актуальному стані опис додатків.
    
    Якщо кількість реальних додатків > 10, створює/оновлює файл 'Опис додатків.pdf'.
    Якщо <= 10, видаляє 'Опис додатків.pdf', якщо він існував.
    """
    # Відфільтровуємо сам опис додатків, щоб не рахувати його рекурсивно
    real_atts = [a for a in doc.attachments if a.stored_filename != "опис_додатків.pdf"]
    real_atts.sort(key=lambda x: x.order_index)

    existing_inv = next((a for a in doc.attachments if a.stored_filename == "опис_додатків.pdf"), None)

    if len(real_atts) > 10:
        pdf_bytes = _generate_inventory_pdf_bytes(doc, real_atts)
        
        if existing_inv:
            existing_inv.blob = pdf_bytes
            existing_inv.size = len(pdf_bytes)
            existing_inv.original_filename = "Опис додатків.pdf"
            existing_inv.mime = "application/pdf"
            # Опис додатків завжди має бути останнім
            max_order = max([a.order_index for a in real_atts], default=-1)
            existing_inv.order_index = max_order + 1
        else:
            max_order = max([a.order_index for a in real_atts], default=-1)
            from .db import Attachment
            inv = Attachment(
                document_id=doc.id,
                order_index=max_order + 1,
                original_filename="Опис додатків.pdf",
                stored_filename="опис_додатків.pdf",
                mime="application/pdf",
                size=len(pdf_bytes),
                blob=pdf_bytes
            )
            session.add(inv)
            doc.attachments.append(inv)
        session.flush()
    else:
        if existing_inv:
            session.delete(existing_inv)
            doc.attachments = [a for a in doc.attachments if a.id != existing_inv.id]
            session.flush()


def _generate_inventory_pdf_bytes(doc: Document, real_attachments: list) -> bytes:
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from dilovod4.infrastructure.fonts import resolve_times_new_roman

    fonts = resolve_times_new_roman()
    pdfmetrics.registerFont(TTFont("TimesNewRoman-Regular", fonts.regular))
    pdfmetrics.registerFont(TTFont("TimesNewRoman-Bold", fonts.bold))

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)

    # 1. Заголовок
    c.setFont("TimesNewRoman-Bold", 14)
    c.drawCentredString(595.27 / 2, 800, "ОПИС ДОДАТКІВ")

    c.setFont("TimesNewRoman-Regular", 12)
    c.drawCentredString(595.27 / 2, 782, f"до документа «{doc.title}»")

    reg_info = []
    if doc.reg_index:
        reg_info.append(f"№ {doc.reg_index}")
    if doc.reg_date:
        reg_info.append(f"від {doc.reg_date}")
    if reg_info:
        c.drawCentredString(595.27 / 2, 765, f"Реєстрація: {' '.join(reg_info)}")
    else:
        c.drawCentredString(595.27 / 2, 765, f"Ідентифікатор: {doc.doc_id}")

    # Лінія розділення
    c.setLineWidth(0.5)
    c.line(85, 750, 567, 750)

    # 2. Таблиця додатків
    col_x = [85, 115, 367, 467, 567]

    # Шапка таблиці
    y = 720
    c.setFont("TimesNewRoman-Bold", 10)
    c.drawString(col_x[0] + 5, y + 5, "№")
    c.drawString(col_x[1] + 5, y + 5, "Назва файлу додатку")
    c.drawString(col_x[2] + 5, y + 5, "Розмір")
    c.drawString(col_x[3] + 5, y + 5, "Формат")

    c.line(85, y, 567, y)
    c.line(85, y + 20, 567, y + 20)
    for x in col_x:
        c.line(x, y, x, y + 20)

    c.setFont("TimesNewRoman-Regular", 10)

    def fmt_bytes(size: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}" if unit != 'B' else f"{size} B"
            size /= 1024.0
        return f"{size:.1f} TB"

    for idx, att in enumerate(real_attachments):
        y -= 20
        if y < 60:
            c.showPage()
            y = 780
            c.setFont("TimesNewRoman-Bold", 10)
            c.drawString(col_x[0] + 5, y + 5, "№")
            c.drawString(col_x[1] + 5, y + 5, "Назва файлу додатку")
            c.drawString(col_x[2] + 5, y + 5, "Розмір")
            c.drawString(col_x[3] + 5, y + 5, "Формат")
            c.line(85, y, 567, y)
            c.line(85, y + 20, 567, y + 20)
            for x in col_x:
                c.line(x, y, x, y + 20)
            c.setFont("TimesNewRoman-Regular", 10)
            y -= 20

        c.drawString(col_x[0] + 5, y + 5, str(idx + 1))
        
        filename = att.original_filename
        if len(filename) > 40:
            filename = filename[:37] + "..."
        c.drawString(col_x[1] + 5, y + 5, filename)
        
        c.drawString(col_x[2] + 5, y + 5, fmt_bytes(att.size))
        
        ext = filename.split(".")[-1].upper() if "." in filename else "ФАЙЛ"
        c.drawString(col_x[3] + 5, y + 5, ext)

        c.line(85, y, 567, y)
        for x in col_x:
            c.line(x, y, x, y + 20)

    c.showPage()
    c.save()
    return buf.getvalue()

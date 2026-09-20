import re
import unicodedata
from urllib.parse import quote
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Response, Body

from portal.db import Attachment, Document, SessionLocal
from portal.auth import _current_user
from portal.helpers import _audit, _assert_editable, _load, ensure_attachments_inventory

router = APIRouter(tags=["attachments"])

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_ATTACHMENT_EXT = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".bmp",
    ".webp",
    ".docx",
    ".xlsx",
    ".doc",
    ".xls",
}


def sanitize_filename(filename: str) -> str:
    # 1. Отримати лише ім'я файлу (без шляху)
    name = Path(filename).name
    # 2. Вирізати заборонені символи / \ : * ? " < > |
    name = re.sub(r'[/\\:*?"<>|]', "", name)
    # 3. NFKC-нормалізація (Unicode дозволено)
    name = unicodedata.normalize("NFKC", name)
    # 4. Вирізати початкові/кінцеві пробіли/крапки
    name = name.strip(" .")
    if not name or name == ".":
        name = "attachment"
    return name


def resolve_stored_filename(doc: Document, sanitized_name: str) -> str:
    reserved = f"{doc.doc_id}.{doc.fmt}".lower()
    existing_filenames = {a.stored_filename.lower() for a in doc.attachments}
    existing_filenames.add(reserved)

    if sanitized_name.lower() not in existing_filenames:
        return sanitized_name

    path = Path(sanitized_name)
    stem = path.stem
    suffix = path.suffix

    counter = 1
    while True:
        candidate = f"{stem}-{counter}{suffix}"
        if candidate.lower() not in existing_filenames:
            return candidate
        counter += 1


@router.get("/documents/{doc_id}/attachments")
def list_attachments(doc_id: str, current_user: dict = Depends(_current_user)):
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        return [
            {
                "id": a.id,
                "order_index": a.order_index,
                "original_filename": a.original_filename,
                "stored_filename": a.stored_filename,
                "mime": a.mime,
                "size": a.size,
                "use_incoming_stamp": a.use_incoming_stamp,
                "use_copy_stamp": a.use_copy_stamp,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in doc.attachments
        ]


@router.post("/documents/{doc_id}/attachments")
async def upload_attachment(
    doc_id: str,
    file: UploadFile = File(...),
    current_user: dict = Depends(_current_user),
):
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        _assert_editable(doc, current_user)

        # 1. Перевірка розширення
        filename = file.filename or ""
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_ATTACHMENT_EXT:
            raise HTTPException(415, f"Непідтримуваний тип файлу додатка: {ext}")

        # 2. Читання та перевірка розміру
        try:
            data = await file.read()
        except Exception as exc:
            raise HTTPException(400, f"Помилка читання файлу: {exc}")

        if len(data) > MAX_ATTACHMENT_BYTES:
            raise HTTPException(413, "Файл додатка завеликий (максимум 25 МБ)")

        # 3. Санітація та вирішення колізій
        sanitized_name = sanitize_filename(filename)
        # переконаємось, що розширення зберіглося після санітації
        if not sanitized_name.lower().endswith(ext):
            sanitized_name += ext

        stored_name = resolve_stored_filename(doc, sanitized_name)

        # 4. Визначення order_index
        next_order = max([a.order_index for a in doc.attachments], default=-1) + 1

        # 5. Створення запису
        att = Attachment(
            document_id=doc.id,
            order_index=next_order,
            original_filename=filename,
            stored_filename=stored_name,
            mime=file.content_type or "application/octet-stream",
            size=len(data),
            blob=data,
        )
        session.add(att)
        doc.attachments.append(att)
        session.flush()

        _audit(
            session,
            doc,
            "attachment_added",
            actor=current_user.get("email", ""),
            detail=stored_name,
        )
        ensure_attachments_inventory(session, doc)
        session.commit()

        return {
            "id": att.id,
            "order_index": att.order_index,
            "original_filename": att.original_filename,
            "stored_filename": att.stored_filename,
            "mime": att.mime,
            "size": att.size,
            "use_incoming_stamp": att.use_incoming_stamp,
            "use_copy_stamp": att.use_copy_stamp,
            "created_at": att.created_at.isoformat() if att.created_at else None,
        }


@router.get("/documents/{doc_id}/attachments/{att_id}")
def download_attachment(
    doc_id: str,
    att_id: int,
    current_user: dict = Depends(_current_user),
):
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        # Знайдемо додаток
        att = session.query(Attachment).filter_by(id=att_id, document_id=doc.id).first()
        if not att:
            raise HTTPException(404, "Додаток не знайдено")

        # Формування правильного заголовка Content-Disposition з RFC 6266 сумісністю
        orig_name = att.original_filename or att.stored_filename
        ascii_fallback = orig_name.encode("ascii", errors="ignore").decode("ascii").strip()
        if not ascii_fallback:
            ascii_fallback = "attachment"
        encoded_filename = quote(orig_name)
        content_disposition = (
            f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded_filename}"
        )

        return Response(
            content=att.blob,
            media_type=att.mime,
            headers={
                "Content-Disposition": content_disposition,
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )


@router.patch("/documents/{doc_id}/attachments/{att_id}")
def update_attachment(
    doc_id: str,
    att_id: int,
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
):
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        _assert_editable(doc, current_user)
        att = session.query(Attachment).filter_by(id=att_id, document_id=doc.id).first()
        if not att:
            raise HTTPException(404, "Додаток не знайдено")
        
        if "use_incoming_stamp" in payload:
            att.use_incoming_stamp = bool(payload["use_incoming_stamp"])
        if "use_copy_stamp" in payload:
            att.use_copy_stamp = bool(payload["use_copy_stamp"])
            
        session.commit()
        return {
            "id": att.id,
            "order_index": att.order_index,
            "original_filename": att.original_filename,
            "stored_filename": att.stored_filename,
            "mime": att.mime,
            "size": att.size,
            "use_incoming_stamp": att.use_incoming_stamp,
            "use_copy_stamp": att.use_copy_stamp,
            "created_at": att.created_at.isoformat() if att.created_at else None,
        }


@router.delete("/documents/{doc_id}/attachments/{att_id}")
def delete_attachment(
    doc_id: str,
    att_id: int,
    current_user: dict = Depends(_current_user),
):
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        _assert_editable(doc, current_user)

        att = session.query(Attachment).filter_by(id=att_id, document_id=doc.id).first()
        if not att:
            raise HTTPException(404, "Додаток не знайдено")

        stored_name = att.stored_filename
        session.delete(att)
        doc.attachments = [a for a in doc.attachments if a.id != att_id]
        ensure_attachments_inventory(session, doc)
        _audit(
            session,
            doc,
            "attachment_removed",
            actor=current_user.get("email", ""),
            detail=stored_name,
        )
        session.commit()

        return {"ok": True}


@router.get("/documents/{doc_id}/merged-pdf")
def get_merged_pdf(
    doc_id: str,
    visa: bool = False,
    current_user: dict = Depends(_current_user),
):
    from portal.services.pdf_merge import build_merged_pdf_with_stamps

    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.rendered:
            raise HTTPException(409, "Спершу згенеруйте PDF документа")

        try:
            merged_bytes = build_merged_pdf_with_stamps(doc, session, visa=bool(visa))
        except Exception as e:
            raise HTTPException(500, f"Помилка створення обʼєднаного PDF: {e}")

        # Filename
        orig_name = f"{doc_id}_merged.pdf"
        encoded_filename = quote(orig_name)
        content_disposition = (
            f"attachment; filename=\"{orig_name}\"; filename*=UTF-8''{encoded_filename}"
        )

        return Response(
            content=merged_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": content_disposition,
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )


@router.post("/documents/{doc_id}/attachments/{att_id}/pack-asic")
def pack_attachment_asic(
    doc_id: str,
    att_id: int,
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
):
    import base64
    import tempfile
    import os
    from dilovod4.infrastructure.asic import build_asic_s, build_asic_e, AsicSignature

    with SessionLocal() as session:
        doc = _load(session, doc_id)
        att = session.query(Attachment).filter_by(id=att_id, document_id=doc.id).first()
        if not att:
            raise HTTPException(404, "Додаток не знайдено")

        sig_bytes = base64.b64decode(payload["signature_b64"])
        asic_type = payload.get("type", "asice")  # default to asice

        with tempfile.NamedTemporaryFile(suffix=f".{asic_type}", delete=False) as tmp:
            dest = tmp.name

        try:
            filename = att.original_filename or att.stored_filename
            if asic_type == "asics":
                build_asic_s(filename, att.blob, sig_bytes, dest)
            else:
                data_files = [(filename, att.blob)]
                sigs = [AsicSignature(cms=sig_bytes)]
                build_asic_e(data_files, sigs, dest)

            with open(dest, "rb") as fh:
                content = fh.read()
        finally:
            if os.path.exists(dest):
                os.remove(dest)

        out_name = f"{filename}.{asic_type}"
        encoded_filename = quote(out_name)
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=\"{out_name}\"; filename*=UTF-8''{encoded_filename}",
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )


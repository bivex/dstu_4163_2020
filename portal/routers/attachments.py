import re
import unicodedata
from urllib.parse import quote
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, File, UploadFile, Response

from portal.db import Attachment, Document, SessionLocal
from portal.auth import _current_user
from portal.helpers import _audit, _assert_editable, _load

router = APIRouter(tags=["attachments"])

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_ATTACHMENT_EXT = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp",
    ".docx", ".xlsx", ".doc", ".xls"
}


def sanitize_filename(filename: str) -> str:
    # 1. Отримати лише ім'я файлу (без шляху)
    name = Path(filename).name
    # 2. Вирізати заборонені символи / \ : * ? " < > |
    name = re.sub(r'[/\\:*?"<>|]', '', name)
    # 3. NFKC-нормалізація (Unicode дозволено)
    name = unicodedata.normalize('NFKC', name)
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

        _audit(session, doc, "attachment_added", actor=current_user.get("email", ""), detail=stored_name)
        session.commit()

        return {
            "id": att.id,
            "order_index": att.order_index,
            "original_filename": att.original_filename,
            "stored_filename": att.stored_filename,
            "mime": att.mime,
            "size": att.size,
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
        encoded_filename = quote(orig_name)
        content_disposition = f"attachment; filename=\"{orig_name}\"; filename*=UTF-8''{encoded_filename}"

        return Response(
            content=att.blob,
            media_type=att.mime,
            headers={
                "Content-Disposition": content_disposition,
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )


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
        _audit(session, doc, "attachment_removed", actor=current_user.get("email", ""), detail=stored_name)
        session.commit()

        return {"ok": True}

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


@router.get("/documents/{doc_id}/merged-pdf")
def get_merged_pdf(
    doc_id: str,
    current_user: dict = Depends(_current_user),
):
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    import io
    import json
    from portal import domain_bridge as bridge

    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.rendered:
            raise HTTPException(409, "Спершу згенеруйте PDF документа")

        # Parse document metadata
        try:
            payload = bridge.content_from_json(doc.content_json)
        except Exception:
            payload = {}
        doc_type = payload.get("doc_type", "")
        reg_index = payload.get("reg_index", "")

        def get_genitive_doc_type(dt_str: str) -> str:
            dt_lower = dt_str.strip().lower()
            mapping = {
                "наказ": "наказу",
                "лист": "листа",
                "протокол": "протоколу",
                "рішення": "рішення",
                "розпорядження": "розпорядження",
                "договір": "договору",
                "акт": "акта",
                "скарга": "скарги",
            }
            return mapping.get(dt_lower, dt_lower)

        writer = PdfWriter()

        # Add main document pages
        try:
            main_reader = PdfReader(io.BytesIO(doc.rendered))
            for page in main_reader.pages:
                writer.add_page(page)
        except Exception as e:
            raise HTTPException(500, f"Помилка читання головного документа: {e}")

        # Setup font for watermark (Cyrillic support)
        try:
            from src.dilovod4.infrastructure.fonts import resolve_times_new_roman
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            fonts = resolve_times_new_roman()
            FONT_REGULAR = "Merged-Font-Regular"
            FONT_BOLD = "Merged-Font-Bold"
            pdfmetrics.registerFont(TTFont(FONT_REGULAR, fonts.regular))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, fonts.bold))
        except Exception:
            FONT_REGULAR = "Helvetica"
            FONT_BOLD = "Helvetica-Bold"

        # Process attachments sorted by order_index
        attachments = sorted(doc.attachments, key=lambda a: a.order_index)
        
        for idx, att in enumerate(attachments, start=1):
            ext = att.stored_filename.split('.')[-1].lower() if '.' in att.stored_filename else ''
            
            # Determine pages to merge
            pages_to_add = []
            
            if ext == 'pdf':
                try:
                    att_reader = PdfReader(io.BytesIO(att.blob))
                    pages_to_add = list(att_reader.pages)
                except Exception as e:
                    print(f"Skipping corrupt PDF attachment {att.stored_filename}: {e}")
                    continue
            elif ext in ['png', 'jpg', 'jpeg', 'bmp', 'webp']:
                try:
                    # Convert image to PDF page
                    from PIL import Image
                    pil_img = Image.open(io.BytesIO(att.blob))
                    
                    # Convert transparent background to white
                    if pil_img.mode in ('RGBA', 'LA') or (pil_img.mode == 'P' and 'transparency' in pil_img.info):
                        bg = Image.new("RGB", pil_img.size, (255, 255, 255))
                        if pil_img.mode == 'RGBA':
                            mask = pil_img.split()[-1]
                        else:
                            mask = pil_img.convert('RGBA').split()[-1]
                        bg.paste(pil_img, mask=mask)
                        pil_img = bg
                    elif pil_img.mode != 'RGB':
                        pil_img = pil_img.convert('RGB')
                        
                    converted_bytes = io.BytesIO()
                    pil_img.save(converted_bytes, format='JPEG')
                    converted_bytes.seek(0)

                    img_packet = io.BytesIO()
                    can = canvas.Canvas(img_packet, pagesize=A4)
                    img = ImageReader(converted_bytes)
                    img_w, img_h = img.getSize()
                    
                    # Scale to fit A4 page
                    max_w, max_h = 535, 781  # Margins 30pt
                    ratio = min(max_w / img_w, max_h / img_h)
                    new_w = img_w * ratio
                    new_h = img_h * ratio
                    
                    x = (595.27 - new_w) / 2
                    y = (841.89 - new_h) / 2
                    
                    can.drawImage(img, x, y, width=new_w, height=new_h)
                    can.save()
                    img_packet.seek(0)
                    
                    img_reader = PdfReader(img_packet)
                    pages_to_add = list(img_reader.pages)
                except Exception as e:
                    print(f"Skipping corrupt image attachment {att.stored_filename}: {e}")
                    continue
            else:
                # Placeholder page for non-visual files (.docx, .xlsx)
                try:
                    placeholder_packet = io.BytesIO()
                    can = canvas.Canvas(placeholder_packet, pagesize=A4)
                    can.setFont(FONT_REGULAR, 12)
                    can.drawString(100, 500, f"Додаток {idx}: {att.original_filename}")
                    can.setFont(FONT_REGULAR, 10)
                    can.drawString(100, 480, "(Вміст файлу не підтримує прямий перегляд у PDF)")
                    can.drawString(100, 460, "Ви можете завантажити оригінал з картки документа.")
                    can.save()
                    placeholder_packet.seek(0)
                    
                    placeholder_reader = PdfReader(placeholder_packet)
                    pages_to_add = list(placeholder_reader.pages)
                except Exception as e:
                    print(f"Skipping placeholder generation for {att.stored_filename}: {e}")
                    continue

            total_pages = len(pages_to_add)
            for page_num, page in enumerate(pages_to_add, start=1):
                # Generate watermark page
                try:
                    watermark_packet = io.BytesIO()
                    can = canvas.Canvas(watermark_packet, pagesize=A4)
                    
                    # Watermark text lines
                    text_lines = [f"Додаток {idx}"]
                    if doc_type and reg_index:
                        text_lines.append(f"до {get_genitive_doc_type(doc_type)} № {reg_index}")
                    text_lines.append(f"Аркуш {page_num} з {total_pages}")
                    
                    y_pos = 810
                    can.setFont(FONT_REGULAR, 9)
                    for line in text_lines:
                        can.drawRightString(565, y_pos, line)
                        y_pos -= 11
                    can.save()
                    watermark_packet.seek(0)
                    
                    watermark = PdfReader(watermark_packet).pages[0]
                    # Merge watermark onto the target page
                    page.merge_page(watermark)
                except Exception as e:
                    print(f"Watermark merging failed: {e}")
                
                writer.add_page(page)

        # Output the merged PDF
        output_stream = io.BytesIO()
        writer.write(output_stream)
        merged_bytes = output_stream.getvalue()

        # Filename
        orig_name = f"{doc_id}_merged.pdf"
        encoded_filename = quote(orig_name)
        content_disposition = f"attachment; filename=\"{orig_name}\"; filename*=UTF-8''{encoded_filename}"

        return Response(
            content=merged_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": content_disposition,
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )


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
                "заява": "заяви",
                "запит": "запиту",
                "довідка": "довідки",
                "службова записка": "службової записки",
                "доповідна записка": "доповідної записки",
                "пояснювальна записка": "пояснювальної записки",
                "угода": "угоди",
                "положення": "положення",
                "інструкція": "інструкції",
                "супровідний лист": "супровідного листа",
                "контракт": "контракту",
                "статут": "статуту",
                "регламент": "регламенту",
                "проект": "проекту",
                "додаток": "додатка",
            }
            return mapping.get(dt_lower, dt_lower)

        writer = PdfWriter()

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

        def _visa_lines(d, session) -> list:
            """Лише погоджені візи. Повертає list[tuple[str, bytes|None]]:
            рядок тексту + blob факсимиле (або None). Дата approved_at
            (UTC-aware) → Europe/Kyiv, %d.%m.%Y. Lookup факсимиле: за
            Approver.user_id (надійніше), інакше за User.name == full_name."""
            from portal.db import ApproverStatus, User

            try:
                from zoneinfo import ZoneInfo

                kyiv = ZoneInfo("Europe/Kyiv")
            except Exception:
                kyiv = None
            lines = []
            for a in getattr(d, "approvers", []) or []:
                if getattr(a, "status", None) != ApproverStatus.APPROVED or not a.approved_at:
                    continue
                dt = a.approved_at
                if kyiv is not None and getattr(dt, "tzinfo", None) is not None:
                    dt = dt.astimezone(kyiv)
                date_s = dt.strftime("%d.%m.%Y")
                posada = (getattr(a, "position", "") or "").strip()
                name = (getattr(a, "full_name", "") or "").strip()
                line = f"{posada} {name} {date_s}".strip()
                # факсимиле: шукаємо за user_id (надійніше), інакше за full_name
                blob = None
                user_id = getattr(a, "user_id", None)
                if user_id:
                    u = session.get(User, user_id)
                    if u is not None:
                        blob = u.facsimile_blob
                else:
                    u = session.query(User).filter(User.name == name).first()
                    if u is not None:
                        blob = u.facsimile_blob
                lines.append((line, blob))
            return lines

        def _draw_visa(can, visa_items, page_w, page_h):
            """Лівий нижній кут: «ВІЗА:» + по рядку на approver. Якщо
            для рядка є blob факсимиле — накладаємо PNG правіше від тексту
            (розмір ~50×20pt, прозорий фон збережено через mask='auto')."""
            from reportlab.pdfbase.pdfmetrics import stringWidth
            from reportlab.lib.utils import ImageReader

            if not visa_items:
                return
            x = 30
            y = 40 + len(visa_items) * 9
            can.setFont(FONT_BOLD, 8)
            can.drawString(x, y, "ВІЗА:")
            y -= 11
            can.setFont(FONT_REGULAR, 7)
            for line, blob in visa_items:
                can.drawString(x, y, line)
                if blob:
                    try:
                        img = ImageReader(io.BytesIO(blob))
                        iw, ih = img.getSize()
                        # розмір блоку ~50×20pt, зберігаємо пропорції
                        box_w, box_h = 50.0, 20.0
                        text_w = stringWidth(line, FONT_REGULAR, 7)
                        fx = x + text_w + 4
                        fy = y - 2
                        can.drawImage(
                            img,
                            fx,
                            fy,
                            width=box_w,
                            height=box_h,
                            mask="auto",
                            preserveAspectRatio=True,
                        )
                    except Exception:
                        pass
                y -= 9

        def _draw_identification(
            can, *, idx, doc_type, reg_index, page_num, total_pages, page_w, page_h, has_copy_stamp=False, depth_offset=0
        ):
            """Правий верхній кут: Додаток N / до ... № X / Аркуш Y з Z."""
            text_lines = [f"Додаток {idx}"]
            if doc_type and reg_index:
                text_lines.append(f"до {get_genitive_doc_type(doc_type)} № {reg_index}")
            text_lines.append(f"Аркуш {page_num} з {total_pages}")
            
            # Автоматичний багатоколонковий розподіл штампів при ультра-глибокій рекурсії (>20 рівнів)
            max_rows_per_col = 20
            col = depth_offset // max_rows_per_col
            row = depth_offset % max_rows_per_col
            
            x_pos = page_w - 20 - (col * 135)
            base_y = (62 if has_copy_stamp else 40) + (row * 35)
            y = page_h - base_y
            can.saveState()
            try:
                can.setFillColorRGB(0.0, 0.2, 0.6)
                can.setFillAlpha(0.8)
                can.setFont(FONT_REGULAR, 8)
                for line in text_lines:
                    can.drawRightString(x_pos, y, line)
                    y -= 9.5
            finally:
                can.restoreState()

        def _draw_copy_stamp(can, page_w, page_h):
            """Малює синій прямокутний штамп «КОПІЯ» у правому верхньому куті (подвійна рамка)."""
            can.saveState()
            try:
                can.setStrokeColorRGB(0.03, 0.14, 0.42)
                can.setFillColorRGB(0.03, 0.14, 0.42)
                mm = 2.83464567
                w = 26 * mm
                h = 8 * mm
                right_margin = 10 * mm
                top_margin = 10 * mm
                x = page_w - right_margin - w
                y = page_h - top_margin - h
                
                # Подвійна рамка
                can.setLineWidth(1.0)
                can.rect(x, y, w, h, stroke=True, fill=False)
                can.setLineWidth(0.4)
                can.rect(x + 1.2, y + 1.2, w - 2.4, h - 2.4, stroke=True, fill=False)
                
                can.setFont(FONT_BOLD, 8.0)
                can.drawCentredString(x + w / 2, y + h / 2 - 2.5, "К О П І Я")
            finally:
                can.restoreState()

        def _draw_incoming_stamp(
            can, *, org_name, reg_index, reg_date, page_w, page_h
        ):
            """Малює синій вхідний реєстраційний штамп організації у правому нижньому куті (подвійна рамка)."""
            can.saveState()
            try:
                can.setStrokeColorRGB(0.03, 0.14, 0.42)
                can.setFillColorRGB(0.03, 0.14, 0.42)
                mm = 2.83464567
                w = 72 * mm
                h = 17 * mm
                right_margin = 10 * mm
                x = page_w - right_margin - w
                y = 25 * mm
                can.setLineWidth(1.2)
                can.rect(x, y, w, h, stroke=True, fill=False)
                can.setLineWidth(0.4)
                can.rect(x + 1.5, y + 1.5, w - 3, h - 3, stroke=True, fill=False)
                can.line(x + 1.5, y + 8.5 * mm, x + w - 1.5, y + 8.5 * mm)
                can.line(x + 30 * mm, y + 1.5, x + 30 * mm, y + 8.5 * mm)
                can.setFont(FONT_BOLD, 7.0)
                org = org_name.removeprefix("Гр. ").removeprefix("АТ ").strip()
                if len(org) > 40:
                    org = org[:37] + "..."
                can.drawCentredString(x + w / 2, y + 11.5 * mm, org)
                can.setFont(FONT_REGULAR, 6.5)
                can.drawString(x + 3.5 * mm, y + 4.0 * mm, f"Вх. № {reg_index}")
                can.drawString(x + 32.5 * mm, y + 4.0 * mm, f"від {reg_date}")
            finally:
                can.restoreState()

        def _overlay_page_for(target_page, drawers):
            """Overlay-сторінка під mediabox цільової сторінки (A3/A4/A5-safe).
            drawers — список callable(can, page_w, page_h). NB: /Rotate не
            коригується (як і в попередньому identification-штампі) — координати
            у просторі mediabox."""
            mb = target_page.mediabox
            page_w = float(mb.width)
            page_h = float(mb.height)
            pkt = io.BytesIO()
            can = canvas.Canvas(pkt, pagesize=(page_w, page_h))
            for drawer in drawers:
                drawer(can, page_w, page_h)
            can.save()
            pkt.seek(0)
            return PdfReader(pkt).pages[0]

        visa = _visa_lines(doc, session) if visa else []

        # Add main document pages (штамп-віза на кожній сторінці, якщо є погоджені)
        try:
            main_reader = PdfReader(io.BytesIO(doc.rendered))
            for page in main_reader.pages:
                if visa:
                    overlay = _overlay_page_for(
                        page, [lambda c, w, h, _v=visa: _draw_visa(c, _v, w, h)]
                    )
                    page.merge_page(overlay)
                writer.add_page(page)
        except Exception as e:
            raise HTTPException(500, f"Помилка читання головного документа: {e}")

        # Process attachments sorted by order_index
        attachments = sorted(doc.attachments, key=lambda a: a.order_index)

        for idx, att in enumerate(attachments, start=1):
            ext = att.stored_filename.split(".")[-1].lower() if "." in att.stored_filename else ""

            # Determine pages to merge
            pages_to_add = []

            if ext == "pdf":
                try:
                    att_reader = PdfReader(io.BytesIO(att.blob))
                    pages_to_add = list(att_reader.pages)
                except Exception as e:
                    print(f"Skipping corrupt PDF attachment {att.stored_filename}: {e}")
                    continue
            elif ext in ["png", "jpg", "jpeg", "bmp", "webp"]:
                try:
                    # Convert image to PDF page
                    from PIL import Image

                    pil_img = Image.open(io.BytesIO(att.blob))

                    # Convert transparent background to white
                    if pil_img.mode in ("RGBA", "LA") or (
                        pil_img.mode == "P" and "transparency" in pil_img.info
                    ):
                        bg = Image.new("RGB", pil_img.size, (255, 255, 255))
                        if pil_img.mode == "RGBA":
                            mask = pil_img.split()[-1]
                        else:
                            mask = pil_img.convert("RGBA").split()[-1]
                        bg.paste(pil_img, mask=mask)
                        pil_img = bg
                    elif pil_img.mode != "RGB":
                        pil_img = pil_img.convert("RGB")

                    converted_bytes = io.BytesIO()
                    pil_img.save(converted_bytes, format="JPEG")
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
            
            matching_inc = None
            if att.use_incoming_stamp:
                matching_inc = session.query(Document).filter(Document.journal_id == 2).order_by(Document.id.desc()).first()

            import re
            for page_num, page in enumerate(pages_to_add, start=1):
                # Identification (top-right) + віза (bottom-left), один merge на сторінку
                try:
                    try:
                        page_txt = page.extract_text() or ""
                        depth_offset = len(re.findall(r"Додаток \d+", page_txt))
                    except Exception:
                        depth_offset = 0

                    has_copy_stamp = (att.use_copy_stamp and page_num == 1)
                    drawers = [
                        lambda c, w, h, _idx=idx, _pn=page_num, _tp=total_pages, _hcs=has_copy_stamp, _do=depth_offset: (
                            _draw_identification(
                                c,
                                idx=_idx,
                                doc_type=doc_type,
                                reg_index=reg_index,
                                page_num=_pn,
                                total_pages=_tp,
                                page_w=w,
                                page_h=h,
                                has_copy_stamp=_hcs,
                                depth_offset=_do,
                            )
                        )
                    ]
                    if visa:
                        drawers.append(lambda c, w, h, _v=visa: _draw_visa(c, _v, w, h))
                    
                    if has_copy_stamp:
                        drawers.append(lambda c, w, h: _draw_copy_stamp(c, w, h))
                    
                    if matching_inc:
                        try:
                            inc_payload = bridge.content_from_json(matching_inc.content_json)
                            org_name = inc_payload.get("org_name", "Організація")
                            reg_index_inc = matching_inc.reg_index or "—"
                            reg_date_inc = matching_inc.reg_date or "—"
                            drawers.append(
                                lambda c, w, h, _org=org_name, _idx_inc=reg_index_inc, _dt_inc=reg_date_inc: (
                                    _draw_incoming_stamp(
                                        c,
                                        org_name=_org,
                                        reg_index=_idx_inc,
                                        reg_date=_dt_inc,
                                        page_w=w,
                                        page_h=h,
                                    )
                                )
                            )
                        except Exception as e:
                            print(f"Failed to append incoming stamp to attachment: {e}")

                    page.merge_page(_overlay_page_for(page, drawers))
                except Exception as e:
                    print(f"Stamp merging failed: {e}")

                writer.add_page(page)

        # Output the merged PDF
        output_stream = io.BytesIO()
        writer.write(output_stream)
        merged_bytes = output_stream.getvalue()

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


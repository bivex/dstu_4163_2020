"""Сервіс злиття PDF головного документа з вкладеннями та накладання службових штампів ДСТУ 4163."""

from __future__ import annotations

import io
import re
from typing import TYPE_CHECKING

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from portal import domain_bridge as bridge

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from portal.db import Document


GENITIVE_DOC_TYPES = {
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


def get_genitive_doc_type(dt_str: str) -> str:
    """Повертає назву виду документа у родовому відмінку («наказ» → «наказу»)."""
    dt_lower = dt_str.strip().lower()
    return GENITIVE_DOC_TYPES.get(dt_lower, dt_lower)


def _setup_fonts() -> tuple[str, str]:
    """Реєстрація шрифтів Times New Roman для ReportLab з фолбеком на Helvetica."""
    try:
        from src.dilovod4.infrastructure.fonts import resolve_times_new_roman
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        fonts = resolve_times_new_roman()
        font_reg = "Merged-Font-Regular"
        font_bold = "Merged-Font-Bold"
        pdfmetrics.registerFont(TTFont(font_reg, fonts.regular))
        pdfmetrics.registerFont(TTFont(font_bold, fonts.bold))
        return font_reg, font_bold
    except Exception:
        return "Helvetica", "Helvetica-Bold"


def _visa_lines(d: Document, session: Session) -> list:
    """Лише погоджені візи. Повертає list[tuple[str, bytes|None]]: рядок тексту + blob факсиміле."""
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
        dt_val = a.approved_at
        if kyiv is not None and getattr(dt_val, "tzinfo", None) is not None:
            dt_val = dt_val.astimezone(kyiv)
        date_s = dt_val.strftime("%d.%m.%Y")
        posada = (getattr(a, "position", "") or "").strip()
        name = (getattr(a, "full_name", "") or "").strip()
        line = f"{posada} {name} {date_s}".strip()

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


def _draw_visa(can, visa_items, page_w, page_h, font_reg, font_bold):
    """Лівий нижній кут: «ВІЗА:» + по рядку на approver з опційним факсиміле."""
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.lib.utils import ImageReader

    if not visa_items:
        return
    x = 30
    y = 40 + len(visa_items) * 9
    can.setFont(font_bold, 8)
    can.drawString(x, y, "ВІЗА:")
    y -= 11
    can.setFont(font_reg, 7)
    for line, blob in visa_items:
        can.drawString(x, y, line)
        if blob:
            try:
                img = ImageReader(io.BytesIO(blob))
                box_w, box_h = 50.0, 20.0
                text_w = stringWidth(line, font_reg, 7)
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
    can, *, idx, doc_type, reg_index, page_num, total_pages, page_w, page_h, font_reg, has_copy_stamp=False, depth_offset=0
):
    """Правий верхній кут: Додаток N / до ... № X / Аркуш Y з Z."""
    text_lines = [f"Додаток {idx}"]
    if doc_type and reg_index:
        text_lines.append(f"до {get_genitive_doc_type(doc_type)} № {reg_index}")
    text_lines.append(f"Аркуш {page_num} з {total_pages}")

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
        can.setFont(font_reg, 8)
        for line in text_lines:
            can.drawRightString(x_pos, y, line)
            y -= 9.5
    finally:
        can.restoreState()


def _draw_copy_stamp(can, page_w, page_h, font_bold):
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

        can.setLineWidth(1.0)
        can.rect(x, y, w, h, stroke=True, fill=False)
        can.setLineWidth(0.4)
        can.rect(x + 1.2, y + 1.2, w - 2.4, h - 2.4, stroke=True, fill=False)

        can.setFont(font_bold, 8.0)
        can.drawCentredString(x + w / 2, y + h / 2 - 2.5, "К О П І Я")
    finally:
        can.restoreState()


def _draw_incoming_stamp(can, *, org_name, reg_index, reg_date, page_w, font_reg, font_bold):
    """Малює синій вхідний реєстраційний штамп організації у правому нижньому куті (подвійна рамка)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

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

        can.setFont(font_bold, 7.0)
        org = org_name.removeprefix("Гр. ").removeprefix("АТ ").strip()
        if len(org) > 40:
            org = org[:37] + "..."
        can.drawCentredString(x + w / 2, y + 11.5 * mm, org)

        left_text = f"Вх. № {reg_index}"
        right_text = f"від {reg_date}"

        w_left = stringWidth(left_text, font_reg, 6.5)
        w_right = stringWidth(right_text, font_reg, 6.5)

        f_size = 6.5
        if w_left + w_right > (w - 7 * mm):
            f_size = 6.0
            w_left = stringWidth(left_text, font_reg, 6.0)
            w_right = stringWidth(right_text, font_reg, 6.0)

        sep_x = 3.5 * mm + w_left + 1.5 * mm
        sep_x = max(30 * mm, min(sep_x, w - w_right - 4.5 * mm))

        can.setFont(font_reg, f_size)
        can.drawString(x + 3.5 * mm, y + 4.0 * mm, left_text)
        can.drawString(x + sep_x + 2.0 * mm, y + 4.0 * mm, right_text)
        can.line(x + sep_x, y + 1.5, x + sep_x, y + 8.5 * mm)
    finally:
        can.restoreState()


def _overlay_page_for(target_page, drawers):
    """Створює overlay-сторінку під mediabox цільової сторінки."""
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


def build_merged_pdf_with_stamps(doc: Document, session: Session, visa: bool = False) -> bytes:
    """Збирає об'єднаний PDF документ із накладанням штампів і віз."""
    from reportlab.lib.utils import ImageReader
    from portal.db import Document as DocModel

    font_reg, font_bold = _setup_fonts()

    try:
        payload = bridge.content_from_json(doc.content_json)
    except Exception:
        payload = {}
    doc_type = payload.get("doc_type", "")
    reg_index = payload.get("reg_index", "")

    writer = PdfWriter()
    visa_items = _visa_lines(doc, session) if visa else []

    # 1. Головний документ
    main_reader = PdfReader(io.BytesIO(doc.rendered))
    for page in main_reader.pages:
        if visa_items:
            overlay = _overlay_page_for(
                page, [lambda c, w, h, _v=visa_items: _draw_visa(c, _v, w, h, font_reg, font_bold)]
            )
            page.merge_page(overlay)
        writer.add_page(page)

    # 2. Вкладення
    attachments = sorted(doc.attachments, key=lambda a: a.order_index)

    for idx, att in enumerate(attachments, start=1):
        ext = att.stored_filename.split(".")[-1].lower() if "." in att.stored_filename else ""
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
                from PIL import Image

                pil_img = Image.open(io.BytesIO(att.blob))
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

                max_w, max_h = 535, 781
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
            try:
                placeholder_packet = io.BytesIO()
                can = canvas.Canvas(placeholder_packet, pagesize=A4)
                can.setFont(font_reg, 12)
                can.drawString(100, 500, f"Додаток {idx}: {att.original_filename}")
                can.setFont(font_reg, 10)
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
            matching_inc = session.query(DocModel).filter(DocModel.journal_id == 2).order_by(DocModel.id.desc()).first()

        for page_num, page in enumerate(pages_to_add, start=1):
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
                            font_reg=font_reg,
                            has_copy_stamp=_hcs,
                            depth_offset=_do,
                        )
                    )
                ]
                if visa_items:
                    drawers.append(lambda c, w, h, _v=visa_items: _draw_visa(c, _v, w, h, font_reg, font_bold))

                if has_copy_stamp:
                    drawers.append(lambda c, w, h: _draw_copy_stamp(c, w, h, font_bold))

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
                                    font_reg=font_reg,
                                    font_bold=font_bold,
                                )
                            )
                        )
                    except Exception as e:
                        print(f"Failed to append incoming stamp to attachment: {e}")

                page.merge_page(_overlay_page_for(page, drawers))
            except Exception as e:
                print(f"Stamp merging failed: {e}")

            writer.add_page(page)

    output_stream = io.BytesIO()
    writer.write(output_stream)
    return output_stream.getvalue()

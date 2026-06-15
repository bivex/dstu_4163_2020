import json
from io import BytesIO
from fastapi import APIRouter, Body, HTTPException, Response
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm

from portal.db import SessionLocal
from portal.helpers import _load

router = APIRouter(tags=["delivery"])

# Register Times New Roman or compatible font
try:
    from src.dilovod4.infrastructure.fonts import resolve_times_new_roman
    fonts = resolve_times_new_roman()
    FONT_REGULAR = "Ukrposhta-Font"
    FONT_BOLD = "Ukrposhta-Font-Bold"
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, fonts.regular))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, fonts.bold))
except Exception:
    FONT_REGULAR = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"


@router.get("/documents/{doc_id}/delivery")
def get_document_delivery(doc_id: str) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        payload = json.loads(doc.content_json) if doc.content_json else {}

        # Default recipient info from document
        recipient_name = payload.get("org_name", "").strip()
        recipient_address = ""
        recipient_phone = ""
        recipient_code = ""
        recipient_type = payload.get("subject_type", "legal")

        # Try to find matching counterparty by name
        from portal.db import Counterparty
        cp = None
        if recipient_name:
            cp = session.query(Counterparty).filter(Counterparty.name == recipient_name).first()
            if not cp:
                cp = session.query(Counterparty).filter(Counterparty.name.like(f"%{recipient_name}%")).first()

        if cp:
            recipient_name = cp.name
            recipient_address = cp.address or ""
            recipient_phone = cp.phone or ""
            recipient_code = cp.code or ""
            recipient_type = cp.subject_type

        # Default sender info (our organization)
        sender_name = "ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»"
        sender_address = "м. Київ, вул. Святошинська, 2"
        sender_phone = "+380444523307"
        sender_code = "12345678"

        # Default list of items in the envelope (the document itself)
        doc_title = doc.title or "Документ"
        doc_type = doc.doc_type or payload.get("doc_type") or "Документ"
        doc_date = doc.reg_date or payload.get("date_text") or "—"
        doc_num = doc.reg_index or payload.get("reg_index") or "—"
        item_text = f"{doc_type} № {doc_num} від {doc_date} «{doc_title}»"

        items = [
            {
                "name": item_text,
                "quantity": 1,
                "declared_value": 1.0
            }
        ]

        return {
            "sender": {
                "name": sender_name,
                "address": sender_address,
                "phone": sender_phone,
                "code": sender_code
            },
            "recipient": {
                "name": recipient_name,
                "address": recipient_address,
                "phone": recipient_phone,
                "code": recipient_code,
                "subject_type": recipient_type
            },
            "items": items
        }


def draw_f107_copy(c: canvas.Canvas, y_offset: float, sender: dict, recipient: dict, items: list) -> None:
    # Top info
    c.setFont(FONT_BOLD, 10)
    c.drawString(15 * mm, y_offset + 130 * mm, "УКРПОШТА")
    c.setFont(FONT_REGULAR, 7)
    c.drawRightString(195 * mm, y_offset + 130 * mm, "Форма 107")

    # Title
    c.setFont(FONT_BOLD, 12)
    c.drawCentredString(105 * mm, y_offset + 122 * mm, "ОПИС ВКЛАДЕННЯ")
    c.setFont(FONT_REGULAR, 8)
    c.drawCentredString(105 * mm, y_offset + 117 * mm, "до рекомендованого листа з оголошеною цінністю")

    # Recipient details
    c.setFont(FONT_REGULAR, 8)
    c.drawString(15 * mm, y_offset + 108 * mm, "Кому (адресат):")
    c.setFont(FONT_BOLD, 9)
    recipient_label = recipient.get("name", "")
    if recipient.get("code"):
        recipient_label += f" (код/ІПН: {recipient['code']})"
    c.drawString(45 * mm, y_offset + 108 * mm, recipient_label)

    c.setFont(FONT_REGULAR, 8)
    c.drawString(15 * mm, y_offset + 102 * mm, "Куди (адреса):")
    c.setFont(FONT_REGULAR, 9)
    c.drawString(45 * mm, y_offset + 102 * mm, recipient.get("address", ""))

    # Table Grid
    table_top = y_offset + 94 * mm
    row_h = 7 * mm
    col_w = [12 * mm, 113 * mm, 20 * mm, 35 * mm]
    x_positions = [15 * mm, 27 * mm, 140 * mm, 160 * mm, 195 * mm]

    # Draw Headers
    c.setFillColorRGB(0.95, 0.95, 0.95)
    c.rect(15 * mm, table_top - row_h, 180 * mm, row_h, fill=1, stroke=1)
    c.setFillColorRGB(0, 0, 0)

    c.setFont(FONT_BOLD, 8)
    c.drawCentredString(21 * mm, table_top - 5 * mm, "№ з/п")
    c.drawString(29 * mm, table_top - 5 * mm, "Найменування предметів")
    c.drawCentredString(150 * mm, table_top - 5 * mm, "Кількість")
    c.drawCentredString(177.5 * mm, table_top - 5 * mm, "Цінність (грн)")

    # Draw Items
    curr_y = table_top - row_h
    total_qty = 0
    total_val = 0.0

    for idx, item in enumerate(items[:6]):  # Max 6 items to fit half page
        idx_str = str(idx + 1)
        name = item.get("name", "")
        qty = int(item.get("quantity", 1))
        val = float(item.get("declared_value", 0.0))

        total_qty += qty
        total_val += val * qty

        # Draw row box
        c.rect(15 * mm, curr_y - row_h, 180 * mm, row_h, stroke=1)

        # Print cells
        c.setFont(FONT_REGULAR, 8)
        c.drawCentredString(21 * mm, curr_y - 5 * mm, idx_str)
        
        # Truncate text if too long
        if len(name) > 65:
            name = name[:62] + "..."
        c.drawString(29 * mm, curr_y - 5 * mm, name)
        c.drawCentredString(150 * mm, curr_y - 5 * mm, str(qty))
        c.drawCentredString(177.5 * mm, curr_y - 5 * mm, f"{val:.2f}")

        curr_y -= row_h

    # Total Row
    c.rect(15 * mm, curr_y - row_h, 180 * mm, row_h, stroke=1)
    c.setFont(FONT_BOLD, 8)
    c.drawString(29 * mm, curr_y - 5 * mm, "Усього предметів")
    c.drawCentredString(150 * mm, curr_y - 5 * mm, str(total_qty))
    c.drawCentredString(177.5 * mm, curr_y - 5 * mm, f"{total_val:.2f}")

    # Draw vertical grid lines
    for xp in x_positions:
        c.line(xp, table_top, xp, curr_y - row_h)

    curr_y -= row_h

    # Signatures
    sig_y = curr_y - 12 * mm
    c.setFont(FONT_REGULAR, 8)
    c.drawString(15 * mm, sig_y, "Відправник:")
    c.line(40 * mm, sig_y, 110 * mm, sig_y)
    c.setFont(FONT_REGULAR, 6)
    c.drawCentredString(75 * mm, sig_y - 2 * mm, "(підпис)")

    c.setFont(FONT_REGULAR, 8)
    c.drawString(15 * mm, sig_y - 8 * mm, "Прийняв працівник зв'язку:")
    c.line(60 * mm, sig_y - 8 * mm, 110 * mm, sig_y - 8 * mm)

    # Stamp box
    stamp_x = 145 * mm
    stamp_y = curr_y - 25 * mm
    c.rect(stamp_x, stamp_y, 45 * mm, 20 * mm, stroke=1)
    c.setFont(FONT_REGULAR, 7)
    c.drawCentredString(stamp_x + 22.5 * mm, stamp_y + 10 * mm, "Відбиток календарного")
    c.drawCentredString(stamp_x + 22.5 * mm, stamp_y + 6 * mm, "штемпеля")


@router.post("/documents/{doc_id}/delivery/export")
def export_delivery_pdf(
    doc_id: str,
    payload: dict = Body(...)
) -> Response:
    sender = payload.get("sender", {})
    recipient = payload.get("recipient", {})
    items = payload.get("items", [])
    generate_f107 = bool(payload.get("generate_f107", True))
    generate_label = bool(payload.get("generate_label", True))

    if not items:
        items = [{"name": "Документ", "quantity": 1, "declared_value": 1.0}]

    pdf_buffer = BytesIO()
    c = canvas.Canvas(pdf_buffer, pagesize=A4)

    if generate_f107:
        # Top half copy
        draw_f107_copy(c, 148.5 * mm, sender, recipient, items)

        # Dashed cut line
        c.setDash([3, 3])
        c.line(0, 148.5 * mm, 210 * mm, 148.5 * mm)
        c.setFont(FONT_REGULAR, 7)
        c.drawCentredString(105 * mm, 149.5 * mm, "----------------- лінія відрізу -----------------")
        c.setDash([])  # Reset

        # Bottom half copy
        draw_f107_copy(c, 0 * mm, sender, recipient, items)

        if generate_label:
            c.showPage()

    if generate_label:
        # Address Label (C5 envelope size: 229x162 mm, fitting nicely centered on A4)
        c.setDash([4, 4])
        # Border box
        box_w = 180 * mm
        box_h = 120 * mm
        box_x = 15 * mm
        box_y = 88 * mm
        c.rect(box_x, box_y, box_w, box_h, stroke=1)
        c.setDash([])  # Reset

        # Logo / Stamp placeholder
        c.setFont(FONT_BOLD, 12)
        c.drawString(box_x + 10 * mm, box_y + box_h - 15 * mm, "УКРПОШТА")
        c.setFont(FONT_REGULAR, 8)
        c.drawRightString(box_x + box_w - 10 * mm, box_y + box_h - 15 * mm, "РЕКОМЕНДОВАНИЙ З ОПИСОМ")

        # Sender top-left
        c.setFont(FONT_BOLD, 7)
        c.drawString(box_x + 10 * mm, box_y + box_h - 26 * mm, "ВІДПРАВНИК:")
        c.setFont(FONT_REGULAR, 8)
        c.drawString(box_x + 10 * mm, box_y + box_h - 32 * mm, sender.get("name", ""))
        c.drawString(box_x + 10 * mm, box_y + box_h - 38 * mm, sender.get("address", ""))
        if sender.get("phone"):
            c.drawString(box_x + 10 * mm, box_y + box_h - 44 * mm, f"Тел: {sender['phone']}")

        # Divider line
        c.setLineWidth(0.5)
        c.line(box_x + 10 * mm, box_y + 60 * mm, box_x + box_w - 10 * mm, box_y + 60 * mm)

        # Recipient bottom-right
        rx = box_x + 80 * mm
        c.setFont(FONT_BOLD, 8)
        c.drawString(rx, box_y + 50 * mm, "АДРЕСАТ:")
        c.setFont(FONT_BOLD, 10)
        c.drawString(rx, box_y + 42 * mm, recipient.get("name", ""))
        c.setFont(FONT_REGULAR, 9)
        c.drawString(rx, box_y + 34 * mm, recipient.get("address", ""))
        if recipient.get("phone"):
            c.drawString(rx, box_y + 26 * mm, f"Тел: {recipient['phone']}")

        # Declared Value info at the bottom
        c.setFont(FONT_REGULAR, 7)
        total_val = sum(float(item.get("declared_value", 0)) * int(item.get("quantity", 1)) for item in items)
        c.drawString(box_x + 10 * mm, box_y + 12 * mm, f"Цінність вкладення: {total_val:.2f} грн")

    c.save()
    pdf_buffer.seek(0)
    pdf_bytes = pdf_buffer.getvalue()

    filename = f"ukrposhta_delivery_{doc_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

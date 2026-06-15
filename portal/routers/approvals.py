import datetime as dt
from io import BytesIO
from fastapi import APIRouter, HTTPException, Depends, Body, Response
from pydantic import BaseModel
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from portal.db import (
    SessionLocal,
    Document,
    Approver,
    DocStatus,
    ApproverStatus,
    ApprovalType,
    SignerStatus,
)
from portal.auth import _current_user
from portal.helpers import _load, _audit

router = APIRouter(tags=["approvals"])

# Font configuration
try:
    from src.dilovod4.infrastructure.fonts import resolve_times_new_roman

    fonts = resolve_times_new_roman()
    FONT_REGULAR = "Approval-Font"
    FONT_BOLD = "Approval-Font-Bold"
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, fonts.regular))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, fonts.bold))
except Exception:
    FONT_REGULAR = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"


class ApprovalActionSchema(BaseModel):
    action: str  # "approve" | "reject"
    comment: str | None = None


@router.post("/documents/{doc_id}/approval/submit")
def submit_for_approval(doc_id: str, current_user: dict = Depends(_current_user)):
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status != DocStatus.DRAFT:
            raise HTTPException(400, "Документ має бути в статусі чернетки")

        if not doc.approvers:
            raise HTTPException(400, "Немає призначених погоджувачів для документа")

        doc.status = DocStatus.PENDING_APPROVAL

        # Reset all approver statuses
        for i, a in enumerate(doc.approvers):
            a.comment = None
            a.approved_at = None
            if doc.approval_type == ApprovalType.PARALLEL:
                a.status = ApproverStatus.INVITED
            else:  # SEQUENTIAL
                if i == 0:
                    a.status = ApproverStatus.INVITED
                else:
                    a.status = ApproverStatus.WAITING

        _audit(session, doc, "submitted_approval", current_user["name"], "Подано на погодження")
        session.commit()
        return {"status": doc.status}


def _matches_user(a: Approver, current_user: dict) -> bool:
    """Чи є погоджувач `a` поточним користувачем.

    Спершу за user_id (надійно), з фолбеком на ПІБ для старих записів без user_id.
    """
    uid = current_user.get("sub")
    if a.user_id is not None and uid is not None:
        try:
            return a.user_id == int(uid)
        except (TypeError, ValueError):
            return False
    return a.full_name.strip().lower() == current_user.get("name", "").strip().lower()


@router.post("/documents/{doc_id}/approval/action")
def approval_action(
    doc_id: str, payload: ApprovalActionSchema, current_user: dict = Depends(_current_user)
):
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status != DocStatus.PENDING_APPROVAL:
            raise HTTPException(400, "Документ не очікує погодження")

        # Find the approver matching active user
        active_approver = None
        for a in doc.approvers:
            if a.status == ApproverStatus.INVITED:
                if _matches_user(a, current_user):
                    active_approver = a
                    break

        if not active_approver:
            # Fallback: if user is admin, allow them to approve for anyone who is currently invited
            invited_names = [
                a.full_name for a in doc.approvers if a.status == ApproverStatus.INVITED
            ]
            raise HTTPException(
                403,
                f"Ви не є активним погоджувачем. Очікується дія від: {', '.join(invited_names)}",
            )

        now = dt.datetime.now(dt.timezone.utc)
        if payload.action == "approve":
            active_approver.status = ApproverStatus.APPROVED
            active_approver.comment = payload.comment
            active_approver.approved_at = now
            _audit(
                session,
                doc,
                "approved",
                current_user["name"],
                f"Погоджено: {payload.comment or 'Без зауважень'}",
            )

            # Check next steps
            if doc.approval_type == ApprovalType.SEQUENTIAL:
                # Invite next sequential approver
                next_a = None
                for a in doc.approvers:
                    if a.status == ApproverStatus.WAITING:
                        next_a = a
                        break

                if next_a:
                    next_a.status = ApproverStatus.INVITED
                else:
                    # No more sequential approvers -> Complete!
                    _complete_approval(session, doc, current_user["name"])
            else:  # PARALLEL
                # Check if all parallel are approved
                all_done = all(a.status == ApproverStatus.APPROVED for a in doc.approvers)
                if all_done:
                    _complete_approval(session, doc, current_user["name"])

        elif payload.action == "reject":
            active_approver.status = ApproverStatus.REJECTED
            active_approver.comment = payload.comment
            active_approver.approved_at = now

            # Reset all other pending approvers back to waiting
            for a in doc.approvers:
                if a.status == ApproverStatus.INVITED:
                    a.status = ApproverStatus.WAITING

            # Return to draft
            doc.status = DocStatus.DRAFT
            _audit(
                session,
                doc,
                "rejected_approval",
                current_user["name"],
                f"Відхилено погодження: {payload.comment or ''}",
            )

        else:
            raise HTTPException(400, "Невідома дія погодження")

        session.commit()
        return {"status": doc.status}


def _complete_approval(session, doc: Document, actor: str):
    _audit(session, doc, "approval_completed", actor, "Погодження успішно пройдено")

    # If signers are configured, transition to pending_signatures and invite the first signer
    if doc.signers:
        doc.status = DocStatus.PENDING_SIGNATURES
        for i, s in enumerate(doc.signers):
            if i == 0:
                s.status = SignerStatus.INVITED
            else:
                s.status = SignerStatus.WAITING
        _audit(
            session,
            doc,
            "submitted_signing",
            actor,
            "Документ автоматично переведено в чергу підписання",
        )
    else:
        # No signers, back to draft but marked ready
        doc.status = DocStatus.DRAFT


@router.get("/documents/{doc_id}/approval/sheet")
def get_approval_sheet(doc_id: str, current_user: dict = Depends(_current_user)):
    with SessionLocal() as session:
        doc = _load(session, doc_id)

        pdf_buffer = BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=A4)

        # Draw Header
        c.setFont(FONT_BOLD, 14)
        c.drawCentredString(105 * mm, 280 * mm, "АРКУШ ПОГОДЖЕННЯ")

        c.setFont(FONT_REGULAR, 10)
        c.drawString(20 * mm, 265 * mm, f"Документ ID: {doc.doc_id}")
        c.drawString(20 * mm, 260 * mm, f"Назва: {doc.title or '(без назви)'}")
        c.drawString(20 * mm, 255 * mm, f"Тип: {doc.doc_type or 'Документ'}")

        reg_str = f"Реєстраційний індекс: {doc.reg_index or '—'} від {doc.reg_date or '—'}"
        c.drawString(20 * mm, 250 * mm, reg_str)

        c.line(20 * mm, 245 * mm, 190 * mm, 245 * mm)

        # Draw Approvals Table
        table_top = 235 * mm
        row_h = 10 * mm

        c.setFont(FONT_BOLD, 10)
        c.drawString(22 * mm, table_top - 6 * mm, "Посада")
        c.drawString(70 * mm, table_top - 6 * mm, "ПІБ")
        c.drawString(120 * mm, table_top - 6 * mm, "Статус")
        c.drawString(145 * mm, table_top - 6 * mm, "Дата")
        c.drawString(170 * mm, table_top - 6 * mm, "Підпис")

        c.line(20 * mm, table_top - 8 * mm, 190 * mm, table_top - 8 * mm)

        curr_y = table_top - 8 * mm
        c.setFont(FONT_REGULAR, 9)

        for a in doc.approvers:
            c.drawString(22 * mm, curr_y - 7 * mm, a.position or "—")
            c.drawString(70 * mm, curr_y - 7 * mm, a.full_name)

            # Status styling
            status_text = "Очікує"
            if a.status == ApproverStatus.APPROVED:
                status_text = "ПОГОДЖЕНО"
            elif a.status == ApproverStatus.REJECTED:
                status_text = "ВІДХИЛЕНО"
            elif a.status == ApproverStatus.INVITED:
                status_text = "На розгляді"

            c.drawString(120 * mm, curr_y - 7 * mm, status_text)

            date_str = a.approved_at.strftime("%d.%m.%Y %H:%M") if a.approved_at else "—"
            c.drawString(145 * mm, curr_y - 7 * mm, date_str)
            c.drawString(170 * mm, curr_y - 7 * mm, "___________")

            # Print comment if exists
            if a.comment:
                c.setFont(FONT_REGULAR, 7)
                c.drawString(22 * mm, curr_y - 12 * mm, f"Зауваження: {a.comment}")
                c.setFont(FONT_REGULAR, 9)
                curr_y -= 6 * mm

            c.line(20 * mm, curr_y - 10 * mm, 190 * mm, curr_y - 10 * mm)
            curr_y -= 10 * mm

            if curr_y < 30 * mm:
                c.showPage()
                curr_y = 270 * mm

        c.save()
        pdf_buffer.seek(0)
        pdf_bytes = pdf_buffer.getvalue()

        filename = f"approval_sheet_{doc.doc_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.get("/approvals/my")
def get_my_approvals(current_user: dict = Depends(_current_user)):
    with SessionLocal() as session:
        results = []
        approvers = session.query(Approver).filter_by(status=ApproverStatus.INVITED).all()
        for a in approvers:
            if not _matches_user(a, current_user):
                continue
            doc = session.query(Document).filter_by(id=a.document_id).first()
            if not doc:
                continue
            results.append(
                {
                    "doc_id": doc.doc_id,
                    "title": doc.title,
                    "status": doc.status.value,
                    "approver_status": a.status.value,
                    "user_id": a.user_id,
                    "full_name": a.full_name,
                    "position": a.position,
                    "order_index": a.order_index,
                    "approval_type": doc.approval_type
                    if isinstance(doc.approval_type, str)
                    else doc.approval_type.value,
                }
            )
        return sorted(results, key=lambda x: x["order_index"])

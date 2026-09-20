"""Трекінг розгляду вихідних документів: статус, очікувана відповідь, нагадування."""
import datetime as dt
import json
from fastapi import APIRouter, Body, Depends, HTTPException
from portal.db import Document, SessionLocal
from portal.auth import _current_user
from portal.helpers import _load

router = APIRouter(tags=["review_tracking"])

_REVIEW_DAYS = 30  # ЗУ «Про звернення громадян»: строк розгляду


def _review_to_dict(doc: Document) -> dict:
    now = dt.datetime.now(dt.timezone.utc)
    expected = doc.expected_response_date
    days_left = None
    days_overdue = None
    if expected:
        # SQLite може зберігати naive datetimes — нормалізуємо до UTC
        if expected.tzinfo is None:
            expected = expected.replace(tzinfo=dt.timezone.utc)
        delta = (expected - now).days
        if delta >= 0:
            days_left = delta
        else:
            days_overdue = abs(delta)
    return {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "review_status": doc.review_status or "not_set",
        "expected_response_date": expected.isoformat() if expected else None,
        "response_received_at": doc.response_received_at.isoformat() if doc.response_received_at else None,
        "review_note": doc.review_note,
        "days_left": days_left,
        "days_overdue": days_overdue,
        "is_overdue": days_overdue is not None and doc.review_status not in ('responded', 'not_applicable'),
        "can_request_status": (
            days_overdue is not None
            and doc.review_status not in ('responded', 'not_applicable')
        ),
    }


@router.get("/documents/{doc_id}/review")
def get_review_status(doc_id: str, current_user: dict = Depends(_current_user)) -> dict:
    """Отримати статус розгляду документа."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        return _review_to_dict(doc)


@router.patch("/documents/{doc_id}/review")
def update_review_status(
    doc_id: str,
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
) -> dict:
    """Оновити статус розгляду документа."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)

        if "review_status" in payload:
            valid = ('pending', 'responded', 'overdue', 'not_applicable')
            if payload["review_status"] not in valid:
                raise HTTPException(400, f"review_status має бути одним із: {valid}")
            doc.review_status = payload["review_status"]

        if "expected_response_date" in payload:
            raw = payload["expected_response_date"]
            if raw:
                doc.expected_response_date = dt.datetime.fromisoformat(raw).replace(tzinfo=dt.timezone.utc)
            else:
                doc.expected_response_date = None

        if "response_received_at" in payload:
            raw = payload["response_received_at"]
            if raw:
                doc.response_received_at = dt.datetime.fromisoformat(raw).replace(tzinfo=dt.timezone.utc)
                # Automatically mark as responded when received_at is set
                if not doc.review_status or doc.review_status == 'pending':
                    doc.review_status = 'responded'
            else:
                doc.response_received_at = None

        if "review_note" in payload:
            doc.review_note = payload["review_note"]

        session.commit()
        return _review_to_dict(doc)


@router.post("/documents/{doc_id}/review/activate")
def activate_review(
    doc_id: str,
    payload: dict = Body(default={}),
    current_user: dict = Depends(_current_user),
) -> dict:
    """Активувати трекінг розгляду. Якщо документ має registered_at, очікувана
    дата відповіді = registered_at + 30 днів. Інакше від now()."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        base_date = doc.registered_at or dt.datetime.now(dt.timezone.utc)
        if base_date.tzinfo is None:
            base_date = base_date.replace(tzinfo=dt.timezone.utc)
        days = int(payload.get("days", _REVIEW_DAYS))
        doc.review_status = 'pending'
        doc.expected_response_date = base_date + dt.timedelta(days=days)
        doc.response_received_at = None
        doc.review_note = payload.get("review_note", None)
        session.commit()
        return _review_to_dict(doc)


@router.get("/review/overdue")
def list_overdue(current_user: dict = Depends(_current_user)) -> list:
    """Список усіх документів з простроченим строком розгляду."""
    now = dt.datetime.now(dt.timezone.utc)
    with SessionLocal() as session:
        docs = (
            session.query(Document)
            .filter(
                Document.review_status == 'pending',
                Document.expected_response_date.isnot(None),
                Document.expected_response_date < now,
            )
            .all()
        )
        # Also auto-mark as overdue
        for doc in docs:
            doc.review_status = 'overdue'
        if docs:
            session.commit()
        return [_review_to_dict(d) for d in docs]


@router.get("/review/pending")
def list_pending(current_user: dict = Depends(_current_user)) -> list:
    """Список усіх документів, що очікують відповіді."""
    with SessionLocal() as session:
        docs = (
            session.query(Document)
            .filter(Document.review_status.in_(['pending', 'overdue']))
            .all()
        )
        return [_review_to_dict(d) for d in docs]


@router.post("/documents/{doc_id}/decontrol")
def decontrol_document(
    doc_id: str,
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
) -> dict:
    """Зняття документа з контролю.
    Підстави:
    - reason_type == 'reply_letter': номер вихідного листа-відповіді
    - reason_type == 'resolution': резолюція керівника про виконання документа
    """
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        reason_type = payload.get("reason_type", "reply_letter")
        reply_number = (payload.get("reply_number") or "").strip()
        resolution_text = (payload.get("resolution_text") or "").strip()
        resolution_author = (payload.get("resolution_author") or current_user.get("name") or "Керівник").strip()
        decontrol_date_raw = payload.get("decontrol_date")
        note = (payload.get("note") or "").strip()

        if decontrol_date_raw:
            try:
                rec_date = dt.datetime.fromisoformat(decontrol_date_raw).replace(tzinfo=dt.timezone.utc)
            except Exception:
                rec_date = dt.datetime.now(dt.timezone.utc)
        else:
            rec_date = dt.datetime.now(dt.timezone.utc)

        if reason_type == "reply_letter":
            if not reply_number:
                raise HTTPException(400, "Необхідно вказати номер вихідного листа-відповіді")
            constructed_note = f"Вихідний лист-відповідь: {reply_number}"
        elif reason_type == "resolution":
            if not resolution_text:
                raise HTTPException(400, "Необхідно вказати текст резолюції про виконання")
            constructed_note = f"Резолюція ({resolution_author}): {resolution_text}"
        else:
            constructed_note = note or "Виконано"

        if note and reason_type != "other" and note != constructed_note:
            constructed_note += f" (Примітка: {note})"

        doc.review_status = "responded"
        doc.response_received_at = rec_date
        doc.review_note = constructed_note

        from portal.db import AuditEvent
        actor_name = (
            current_user.get("full_name") or current_user.get("email") or "користувач"
            if isinstance(current_user, dict)
            else "користувач"
        )
        event = AuditEvent(
            document_id=doc.id,
            kind="decontrol",
            actor=actor_name,
            detail=f"Знято з контролю. Підстава: {constructed_note}",
        )
        session.add(event)
        session.commit()
        return _review_to_dict(doc)


@router.post("/documents/{doc_id}/reopen-control")
def reopen_control(
    doc_id: str,
    payload: dict = Body(default={}),
    current_user: dict = Depends(_current_user),
) -> dict:
    """Повернути документ на контроль."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        doc.review_status = "pending"
        doc.response_received_at = None
        if "expected_response_date" in payload and payload["expected_response_date"]:
            try:
                doc.expected_response_date = dt.datetime.fromisoformat(payload["expected_response_date"]).replace(tzinfo=dt.timezone.utc)
            except Exception:
                pass
        elif not doc.expected_response_date:
            base_date = doc.registered_at or dt.datetime.now(dt.timezone.utc)
            if base_date.tzinfo is None:
                base_date = base_date.replace(tzinfo=dt.timezone.utc)
            doc.expected_response_date = base_date + dt.timedelta(days=30)

        from portal.db import AuditEvent
        actor_name = (
            current_user.get("full_name") or current_user.get("email") or "користувач"
            if isinstance(current_user, dict)
            else "користувач"
        )
        event = AuditEvent(
            document_id=doc.id,
            kind="reopen_control",
            actor=actor_name,
            detail="Повернуто на контроль",
        )
        session.add(event)
        session.commit()
        return _review_to_dict(doc)

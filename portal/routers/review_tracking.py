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

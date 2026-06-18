import datetime as _dt
from fastapi import APIRouter, Depends
from portal.db import Document, SessionLocal
from portal.auth import _current_user

router = APIRouter(tags=["registry"], dependencies=[Depends(_current_user)])


@router.get("/registry")
def registration_journal(year: int | None = None) -> dict:
    target_year = year or _dt.datetime.now(_dt.timezone.utc).year
    with SessionLocal() as session:
        docs = (
            session.query(Document)
            .filter(Document.reg_number.isnot(None))
            .order_by(Document.doc_type, Document.reg_number)
            .all()
        )
        entries = [
            {
                "doc_id": d.doc_id,
                "doc_type": d.doc_type,
                "reg_index": d.reg_index,
                "reg_number": d.reg_number,
                "reg_date": d.reg_date,
                "title": d.title,
                "status": d.status.value,
                "registered_at": d.registered_at.isoformat() if d.registered_at else None,
            }
            for d in docs
            if d.registered_at and d.registered_at.year == target_year
        ]
        return {"year": target_year, "count": len(entries), "entries": entries}

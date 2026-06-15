from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from portal.db import SessionLocal, Journal
from portal.auth import _current_user

router = APIRouter(tags=["journals"])

class JournalSchema(BaseModel):
    id: int
    name: str
    prefix: str
    number_template: str
    next_number: int

    class Config:
        from_attributes = True

class JournalCreateSchema(BaseModel):
    name: str
    prefix: str
    number_template: str

@router.get("/journals", response_model=list[JournalSchema])
def get_journals(current_user: dict = Depends(_current_user)):
    with SessionLocal() as session:
        journals = session.query(Journal).order_by(Journal.id).all()
        return [JournalSchema.model_validate(j) for j in journals]

@router.post("/journals", response_model=JournalSchema)
def create_journal(payload: JournalCreateSchema, current_user: dict = Depends(_current_user)):
    with SessionLocal() as session:
        db_journal = Journal(
            name=payload.name,
            prefix=payload.prefix,
            number_template=payload.number_template,
            next_number=1
        )
        session.add(db_journal)
        session.commit()
        session.refresh(db_journal)
        return JournalSchema.model_validate(db_journal)

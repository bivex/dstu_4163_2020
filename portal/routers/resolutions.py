from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from portal.db import SessionLocal, Document, Resolution, Task, DocStatus, TaskStatus
from portal.auth import _current_user
from portal.helpers import _load, _audit

router = APIRouter(tags=["resolutions"])

class TaskCreateSchema(BaseModel):
    executor: str
    description: str
    due_date: str

class ResolutionCreateSchema(BaseModel):
    text: str
    tasks: list[TaskCreateSchema] = []

class TaskSchema(BaseModel):
    id: int
    executor: str
    description: str
    due_date: str
    status: TaskStatus

    class Config:
        from_attributes = True

class ResolutionSchema(BaseModel):
    id: int
    author: str
    text: str
    created_at: str
    tasks: list[TaskSchema] = []

    class Config:
        from_attributes = True

@router.post("/documents/{doc_id}/resolutions")
def create_resolution(
    doc_id: str,
    payload: ResolutionCreateSchema,
    current_user: dict = Depends(_current_user)
):
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status not in (DocStatus.SIGNED, DocStatus.PUBLISHED):
            raise HTTPException(400, "Резолюцію можна накласти тільки на підписаний документ")

        db_resolution = Resolution(
            document_id=doc.id,
            author=current_user["name"] or current_user["email"],
            text=payload.text
        )
        session.add(db_resolution)
        session.flush() # Populate db_resolution.id

        # Add tasks
        for task_data in payload.tasks:
            db_task = Task(
                document_id=doc.id,
                resolution_id=db_resolution.id,
                executor=task_data.executor,
                description=task_data.description,
                due_date=task_data.due_date,
                status=TaskStatus.PENDING
            )
            session.add(db_task)

        _audit(session, doc, "resolution_added", current_user["name"], f"Накладено резолюцію: {payload.text}")
        session.commit()
        return {"status": "success"}

@router.get("/documents/{doc_id}/resolutions")
def get_resolutions(doc_id: str, current_user: dict = Depends(_current_user)):
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        resolutions = session.query(Resolution).filter_by(document_id=doc.id).order_by(Resolution.created_at.desc()).all()
        
        output = []
        for r in resolutions:
            output.append({
                "id": r.id,
                "author": r.author,
                "text": r.text,
                "created_at": r.created_at.isoformat(),
                "tasks": [
                    {
                        "id": t.id,
                        "executor": t.executor,
                        "description": t.description,
                        "due_date": t.due_date,
                        "status": t.status.value
                    }
                    for t in r.tasks
                ]
            })
        return output

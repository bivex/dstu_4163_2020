import datetime as dt
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from portal.db import SessionLocal, Task, Document, TaskStatus
from portal.auth import _current_user
from portal.helpers import _audit

router = APIRouter(tags=["tasks"])

class TaskStatusUpdateSchema(BaseModel):
    status: TaskStatus

@router.get("/tasks/my")
def get_my_tasks(current_user: dict = Depends(_current_user)):
    with SessionLocal() as session:
        # Search by exact name match (case-insensitive checks)
        username = current_user["name"].strip().lower()
        
        all_tasks = session.query(Task).all()
        my_tasks = []
        for t in all_tasks:
            if t.executor.strip().lower() == username:
                doc = session.query(Document).filter_by(id=t.document_id).first()
                my_tasks.append({
                    "id": t.id,
                    "document_id": doc.doc_id if doc else "unknown",
                    "document_title": doc.title if doc else "Невідомий документ",
                    "description": t.description,
                    "due_date": t.due_date,
                    "status": t.status.value,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                    "created_at": t.created_at.isoformat()
                })
        
        # Sort by status (pending first) and due_date
        return sorted(my_tasks, key=lambda x: (x["status"] == "completed", x["due_date"]))

@router.post("/tasks/{task_id}/status")
def update_task_status(
    task_id: int,
    payload: TaskStatusUpdateSchema,
    current_user: dict = Depends(_current_user)
):
    with SessionLocal() as session:
        task = session.query(Task).filter_by(id=task_id).first()
        if not task:
            raise HTTPException(404, "Завдання не знайдено")

        # Verify ownership
        if task.executor.strip().lower() != current_user["name"].strip().lower():
            raise HTTPException(403, "Ви не є виконавцем цього завдання")

        task.status = payload.status
        if payload.status == TaskStatus.COMPLETED:
            task.completed_at = dt.datetime.now(dt.timezone.utc)
        else:
            task.completed_at = None

        doc = session.query(Document).filter_by(id=task.document_id).first()
        if doc:
            _audit(session, doc, "task_status_updated", current_user["name"], f"Оновлено статус завдання '{task.description[:30]}...' -> {payload.status.value}")

        session.commit()
        return {"status": task.status.value}

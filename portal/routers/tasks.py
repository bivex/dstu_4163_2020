import datetime as dt
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from portal.db import SessionLocal, Task, Document, TaskStatus
from portal.auth import _current_user
from portal.helpers import _audit

router = APIRouter(tags=["tasks"])

class TaskStatusUpdateSchema(BaseModel):
    status: TaskStatus


def _task_matches_user(task: Task, current_user: dict) -> bool:
    """Чи є виконавець завдання поточним користувачем.

    Спершу за executor_user_id (надійно), з фолбеком на ПІБ для старих записів.
    """
    uid = current_user.get("sub")
    if task.executor_user_id is not None and uid is not None:
        try:
            return task.executor_user_id == int(uid)
        except (TypeError, ValueError):
            return False
    return task.executor.strip().lower() == current_user.get("name", "").strip().lower()


@router.get("/tasks/my")
def get_my_tasks(current_user: dict = Depends(_current_user)):
    with SessionLocal() as session:
        all_tasks = session.query(Task).all()
        my_tasks = []
        for t in all_tasks:
            if _task_matches_user(t, current_user):
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
        if not _task_matches_user(task, current_user):
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

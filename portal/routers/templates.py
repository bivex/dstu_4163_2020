"""CRUD-роутер шаблонів процесуальних документів.

GET  /templates            — список шаблонів (можна фільтрувати ?category=)
GET  /templates/{id}       — один шаблон
POST /templates            — створити власний шаблон
PUT  /templates/{id}       — оновити шаблон (вбудовані — тільки admin)
DELETE /templates/{id}     — видалити шаблон (вбудовані не можна)
"""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from portal.db import SessionLocal, DocTemplate
from portal.auth import _current_user

router = APIRouter(tags=["templates"])


def _tpl_to_dict(t: DocTemplate) -> dict:
    return {
        "id":               t.id,
        "category":         t.category,
        "doc_type":         t.doc_type,
        "subject_type":     t.subject_type,
        "title":            t.title,
        "description":      t.description or "",
        "icon":             t.icon or "i-lucide-file-text",
        "title_tpl":        t.title_tpl or "",
        "body":             t.body or "",
        "addressees":       t.addressees or "",
        "sender_contacts":  t.sender_contacts or "",
        "is_builtin":       bool(t.is_builtin),
        "sort_order":       t.sort_order,
        "created_at":       t.created_at.isoformat() if t.created_at else None,
        "updated_at":       t.updated_at.isoformat() if t.updated_at else None,
    }


@router.get("/templates")
def list_templates(
    category: str | None = Query(None),
    current_user: dict = Depends(_current_user),
) -> dict:
    with SessionLocal() as session:
        q = session.query(DocTemplate)
        if category and category != "all":
            q = q.filter(DocTemplate.category == category)
        items = q.order_by(DocTemplate.sort_order, DocTemplate.title).all()
        return {"templates": [_tpl_to_dict(t) for t in items]}


@router.get("/templates/{tpl_id}")
def get_template(tpl_id: int, current_user: dict = Depends(_current_user)) -> dict:
    with SessionLocal() as session:
        t = session.get(DocTemplate, tpl_id)
        if t is None:
            raise HTTPException(404, f"Шаблон {tpl_id} не знайдено")
        return _tpl_to_dict(t)


@router.post("/templates")
def create_template(
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
) -> dict:
    title = str(payload.get("title", "")).strip()
    if not title:
        raise HTTPException(400, "Назва шаблону обов'язкова")
    category = str(payload.get("category", "")).strip()
    if not category:
        raise HTTPException(400, "Категорія шаблону обов'язкова")
    with SessionLocal() as session:
        t = DocTemplate(
            category=category,
            doc_type=str(payload.get("doc_type", "")).strip(),
            subject_type=str(payload.get("subject_type", "legal")).strip(),
            title=title,
            description=str(payload.get("description", "")).strip(),
            icon=str(payload.get("icon", "i-lucide-file-text")).strip(),
            title_tpl=str(payload.get("title_tpl", "")).strip(),
            body=str(payload.get("body", "")),
            addressees=payload.get("addressees") or None,
            sender_contacts=payload.get("sender_contacts") or None,
            is_builtin=False,
            sort_order=int(payload.get("sort_order", 0)),
        )
        session.add(t)
        session.commit()
        session.refresh(t)
        return _tpl_to_dict(t)


@router.put("/templates/{tpl_id}")
def update_template(
    tpl_id: int,
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
) -> dict:
    with SessionLocal() as session:
        t = session.get(DocTemplate, tpl_id)
        if t is None:
            raise HTTPException(404, f"Шаблон {tpl_id} не знайдено")
        # вбудовані шаблони редагують лише адміни
        if t.is_builtin and current_user.get("role") != "admin":
            raise HTTPException(403, "Вбудований шаблон може редагувати лише адміністратор")
        if "title" in payload:
            v = str(payload["title"]).strip()
            if not v:
                raise HTTPException(400, "Назва шаблону не може бути порожньою")
            t.title = v
        if "category"        in payload: t.category        = str(payload["category"]).strip()
        if "doc_type"        in payload: t.doc_type        = str(payload["doc_type"]).strip()
        if "subject_type"    in payload: t.subject_type    = str(payload["subject_type"]).strip()
        if "description"     in payload: t.description     = str(payload["description"]).strip()
        if "icon"            in payload: t.icon            = str(payload["icon"]).strip()
        if "title_tpl"       in payload: t.title_tpl       = str(payload["title_tpl"])
        if "body"            in payload: t.body            = str(payload["body"])
        if "addressees"      in payload: t.addressees      = payload["addressees"] or None
        if "sender_contacts" in payload: t.sender_contacts = payload["sender_contacts"] or None
        if "sort_order"      in payload: t.sort_order      = int(payload["sort_order"])
        session.commit()
        session.refresh(t)
        return _tpl_to_dict(t)


@router.delete("/templates/{tpl_id}")
def delete_template(
    tpl_id: int,
    current_user: dict = Depends(_current_user),
) -> dict:
    with SessionLocal() as session:
        t = session.get(DocTemplate, tpl_id)
        if t is None:
            raise HTTPException(404, f"Шаблон {tpl_id} не знайдено")
        if t.is_builtin:
            raise HTTPException(
                400,
                "Вбудований шаблон не можна видалити. Дублюйте його та редагуйте копію."
            )
        session.delete(t)
        session.commit()
        return {"deleted": tpl_id}

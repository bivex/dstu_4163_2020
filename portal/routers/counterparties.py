from fastapi import APIRouter, Body, Depends, HTTPException
from portal.db import Counterparty, SessionLocal
from portal.auth import _current_user

router = APIRouter(tags=["counterparties"], dependencies=[Depends(_current_user)])


def _counterparty_to_dict(c: Counterparty) -> dict:
    return {
        "id": c.id,
        "name": c.name,
        "code": c.code,
        "subject_type": c.subject_type,
        "email": c.email,
        "phone": c.phone,
        "address": c.address,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("/counterparties")
def list_counterparties() -> dict:
    with SessionLocal() as session:
        counterparties = session.query(Counterparty).order_by(Counterparty.created_at.desc()).all()
        return {"counterparties": [_counterparty_to_dict(c) for c in counterparties]}


@router.post("/counterparties")
def create_counterparty(payload: dict = Body(...)) -> dict:
    name = str(payload.get("name", "")).strip()
    code = str(payload.get("code", "")).strip()
    subject_type = str(payload.get("subject_type", "legal")).strip()
    email = payload.get("email")
    phone = payload.get("phone")
    address = payload.get("address")

    if not name:
        raise HTTPException(400, "Назва контрагента обовʼязкова")
    if not code:
        raise HTTPException(400, "Код ЄДРПОУ / ІПН обовʼязковий")
    if subject_type not in ("legal", "fop", "person"):
        raise HTTPException(400, "Невірний тип субʼєкта")

    if email is not None:
        email = str(email).strip()
    if phone is not None:
        phone = str(phone).strip()
    if address is not None:
        address = str(address).strip()

    with SessionLocal() as session:
        c = Counterparty(
            name=name,
            code=code,
            subject_type=subject_type,
            email=email,
            phone=phone,
            address=address,
        )
        session.add(c)
        session.commit()
        return _counterparty_to_dict(c)


@router.put("/counterparties/{c_id}")
def update_counterparty(c_id: int, payload: dict = Body(...)) -> dict:
    with SessionLocal() as session:
        c = session.get(Counterparty, c_id)
        if c is None:
            raise HTTPException(404, f"Контрагента з ID {c_id} не знайдено")

        if "name" in payload:
            name = str(payload["name"]).strip()
            if not name:
                raise HTTPException(400, "Назва контрагента не може бути порожньою")
            c.name = name

        if "code" in payload:
            code = str(payload["code"]).strip()
            if not code:
                raise HTTPException(400, "Код ЄДРПОУ / ІПН не може бути порожнім")
            c.code = code

        if "subject_type" in payload:
            subject_type = str(payload["subject_type"]).strip()
            if subject_type not in ("legal", "fop", "person"):
                raise HTTPException(400, "Невірний тип субʼєкта")
            c.subject_type = subject_type

        if "email" in payload:
            c.email = str(payload["email"]).strip() if payload["email"] is not None else None

        if "phone" in payload:
            c.phone = str(payload["phone"]).strip() if payload["phone"] is not None else None

        if "address" in payload:
            c.address = str(payload["address"]).strip() if payload["address"] is not None else None

        session.commit()
        return _counterparty_to_dict(c)


@router.delete("/counterparties/{c_id}")
def delete_counterparty(c_id: int) -> dict:
    with SessionLocal() as session:
        c = session.get(Counterparty, c_id)
        if c is None:
            raise HTTPException(404, f"Контрагента з ID {c_id} не знайдено")
        session.delete(c)
        session.commit()
        return {"deleted": c_id}

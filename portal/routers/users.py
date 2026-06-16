from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from portal.db import SessionLocal, User
from portal.auth import _current_user

router = APIRouter(tags=["users"])


class UserSchema(BaseModel):
    id: int
    name: str
    email: str
    position: str
    kep_subject_cn: str | None = None
    kep_serial_number: str | None = None
    kep_certificate_serial: str | None = None

    class Config:
        from_attributes = True


def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "position": u.position,
        "kep_subject_cn": u.kep_subject_cn,
        "kep_serial_number": u.kep_serial_number,
        "kep_certificate_serial": u.kep_certificate_serial,
    }


@router.get("/users", response_model=list[UserSchema])
def list_users(current_user: dict = Depends(_current_user)):
    """Перелік користувачів системи — для вибору погоджувачів/виконавців із реальних юзерів."""
    with SessionLocal() as session:
        users = session.query(User).order_by(User.name).all()
        return [UserSchema.model_validate(u) for u in users]


@router.post("/users")
def create_user(payload: dict = Body(...), current_user: dict = Depends(_current_user)) -> dict:
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    position = str(payload.get("position", "")).strip()
    password = str(payload.get("password", "")).strip()

    if not name:
        raise HTTPException(400, "Імʼя користувача обовʼязкове")
    if not email:
        raise HTTPException(400, "Email обовʼязковий")
    if not password:
        raise HTTPException(400, "Пароль обовʼязковий для нового користувача")

    with SessionLocal() as session:
        existing = session.query(User).filter_by(email=email).first()
        if existing:
            raise HTTPException(409, f"Користувач з email {email} вже існує")
        u = User(
            name=name,
            email=email,
            position=position,
            password_hash=User.hash_password(password),
        )
        session.add(u)
        session.commit()
        session.refresh(u)
        return _user_to_dict(u)


@router.put("/users/{user_id}")
def update_user(user_id: int, payload: dict = Body(...), current_user: dict = Depends(_current_user)) -> dict:
    with SessionLocal() as session:
        u = session.get(User, user_id)
        if u is None:
            raise HTTPException(404, f"Користувача з ID {user_id} не знайдено")

        if "name" in payload:
            name = str(payload["name"]).strip()
            if not name:
                raise HTTPException(400, "Імʼя користувача не може бути порожнім")
            u.name = name

        if "email" in payload:
            email = str(payload["email"]).strip().lower()
            if not email:
                raise HTTPException(400, "Email не може бути порожнім")
            clash = session.query(User).filter(User.email == email, User.id != user_id).first()
            if clash:
                raise HTTPException(409, f"Інший користувач з email {email} вже існує")
            u.email = email

        if "position" in payload:
            u.position = str(payload["position"]).strip()

        # пароль міняємо лише якщо переданий непорожній
        new_password = str(payload.get("password", "")).strip()
        if new_password:
            u.password_hash = User.hash_password(new_password)

        session.commit()
        session.refresh(u)
        return _user_to_dict(u)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(_current_user)) -> dict:
    with SessionLocal() as session:
        u = session.get(User, user_id)
        if u is None:
            raise HTTPException(404, f"Користувача з ID {user_id} не знайдено")
        # не дозволяємо видалити власний акаунт, щоб не залишити систему без доступу
        try:
            if str(u.id) == str(current_user.get("sub")):
                raise HTTPException(400, "Не можна видалити власний обліковий запис")
        except (TypeError, ValueError):
            pass
        session.delete(u)
        session.commit()
        return {"deleted": user_id}

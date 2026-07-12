import io

from fastapi import APIRouter, Body, Depends, HTTPException, File, UploadFile, Response
from pydantic import BaseModel
from portal.db import SessionLocal, User, UserRole
from portal.auth import _current_user, _require_role

router = APIRouter(tags=["users"])


_VALID_ROLES = {r.value for r in UserRole}


class UserSchema(BaseModel):
    id: int
    name: str
    email: str
    position: str
    role: str = UserRole.CLERK.value
    kep_subject_cn: str | None = None
    kep_serial_number: str | None = None
    kep_certificate_serial: str | None = None
    organization_cert_cn: str | None = None
    phone: str | None = None
    address: str | None = None

    class Config:
        from_attributes = True


def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id,
        "name": u.name,
        "email": u.email,
        "position": u.position,
        "role": u.role,
        "kep_subject_cn": u.kep_subject_cn,
        "kep_serial_number": u.kep_serial_number,
        "kep_certificate_serial": u.kep_certificate_serial,
        "organization_cert_cn": u.organization_cert_cn,
        "phone": u.phone,
        "address": u.address,
        "has_facsimile": u.facsimile_blob is not None,
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

    # роль при створенні призначає лише admin; решті — clerk за замовчуванням
    role = UserRole.CLERK.value
    if "role" in payload:
        if current_user.get("role") != UserRole.ADMIN.value:
            raise HTTPException(403, "призначати роль може лише admin")
        role = str(payload["role"]).strip()
        if role not in _VALID_ROLES:
            raise HTTPException(400, f"невідома роль: {role}")

    with SessionLocal() as session:
        existing = session.query(User).filter_by(email=email).first()
        if existing:
            raise HTTPException(409, f"Користувач з email {email} вже існує")
        u = User(
            name=name,
            email=email,
            position=position,
            role=role,
            password_hash=User.hash_password(password),
            phone=str(payload.get("phone", "")).strip() or None,
            address=str(payload.get("address", "")).strip() or None,
        )
        session.add(u)
        session.commit()
        session.refresh(u)
        return _user_to_dict(u)


@router.put("/users/{user_id}")
def update_user(
    user_id: int, payload: dict = Body(...), current_user: dict = Depends(_current_user)
) -> dict:
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

        if "phone" in payload:
            u.phone = str(payload["phone"]).strip() or None

        if "address" in payload:
            u.address = str(payload["address"]).strip() or None

        # Зміну ролі дозволено лише admin. Це єдиний привілейований запис —
        # інакше будь-хто підніме себе до admin.
        if "role" in payload:
            if current_user.get("role") != UserRole.ADMIN.value:
                raise HTTPException(403, "змінювати роль може лише admin")
            new_role = str(payload["role"]).strip()
            if new_role not in _VALID_ROLES:
                raise HTTPException(400, f"невідома роль: {new_role}")
            u.role = new_role

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


# ─── Факсимиле (цифрове зображення рукописного підпису/печатки) ───
# Завантажується поточним користувачем (на себе), накладається на PDF
# у блоці «ВІЗА:» (див. portal/routers/attachments.py). Не є КЕП — візуал.

_FACSIMILE_MAX = (200, 80)  # max розмір після стиску через PIL
_FACSIMILE_MIMES = {"image/png", "image/jpeg"}


@router.post("/users/me/facsimile")
async def upload_facsimile(
    file: UploadFile = File(...),
    current_user: dict = Depends(_current_user),
) -> dict:
    mime = (file.content_type or "").lower()
    if mime not in _FACSIMILE_MIMES:
        raise HTTPException(415, "Допускається лише PNG або JPG (image/png, image/jpeg)")
    try:
        data = await file.read()
    except Exception as exc:
        raise HTTPException(400, f"Помилка читання файлу: {exc}")
    if not data:
        raise HTTPException(400, "Порожній файл")

    # Стиск через PIL до max 200×80, зберігаємо прозорість (PNG).
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as pil_img:
            pil_img = pil_img.copy()
            pil_img.thumbnail(_FACSIMILE_MAX)
            out = io.BytesIO()
            if mime == "image/png":
                pil_img.save(out, format="PNG")
                stored_mime = "image/png"
            else:
                if pil_img.mode in ("RGBA", "LA", "P"):
                    pil_img = pil_img.convert("RGB")
                pil_img.save(out, format="JPEG", quality=90)
                stored_mime = "image/jpeg"
            blob = out.getvalue()
    except Exception as exc:
        raise HTTPException(400, f"Некоректне зображення: {exc}")

    uid = int(current_user["sub"])
    with SessionLocal() as session:
        u = session.get(User, uid)
        if u is None:
            raise HTTPException(404, f"Користувача з ID {uid} не знайдено")
        u.facsimile_blob = blob
        u.facsimile_mime = stored_mime
        session.commit()
        session.refresh(u)
        return _user_to_dict(u)


@router.get("/users/me/facsimile")
def get_facsimile(current_user: dict = Depends(_current_user)) -> Response:
    uid = int(current_user["sub"])
    with SessionLocal() as session:
        u = session.get(User, uid)
        if u is None:
            raise HTTPException(404, f"Користувача з ID {uid} не знайдено")
        if not u.facsimile_blob:
            raise HTTPException(404, "Факсиміле не завантажено")
        return Response(
            content=u.facsimile_blob,
            media_type=u.facsimile_mime or "image/png",
        )


@router.delete("/users/me/facsimile")
def delete_facsimile(current_user: dict = Depends(_current_user)) -> dict:
    uid = int(current_user["sub"])
    with SessionLocal() as session:
        u = session.get(User, uid)
        if u is None:
            raise HTTPException(404, f"Користувача з ID {uid} не знайдено")
        u.facsimile_blob = None
        u.facsimile_mime = None
        session.commit()
        return {"ok": True}

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from portal.db import SessionLocal, User
from portal.auth import _current_user

router = APIRouter(tags=["users"])


class UserSchema(BaseModel):
    id: int
    name: str
    email: str
    position: str

    class Config:
        from_attributes = True


@router.get("/users", response_model=list[UserSchema])
def list_users(current_user: dict = Depends(_current_user)):
    """Перелік користувачів системи — для вибору погоджувачів/підписантів із реальних юзерів."""
    with SessionLocal() as session:
        users = session.query(User).order_by(User.name).all()
        return [UserSchema.model_validate(u) for u in users]

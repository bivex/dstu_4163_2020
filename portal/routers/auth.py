from fastapi import APIRouter, Body, Depends, HTTPException
from portal.auth import _current_user, _make_token
from portal.db import SessionLocal, User

router = APIRouter(tags=["auth"])


@router.post("/auth/login")
def auth_login(payload: dict = Body(...)) -> dict:
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    with SessionLocal() as session:
        user = session.query(User).filter_by(email=email).first()
        if not user or not user.verify_password(password):
            raise HTTPException(401, "Невірний email або пароль")
        token = _make_token(user)
        return {"token": token, "user": {"email": user.email, "name": user.name}}


@router.get("/auth/me")
def auth_me(current: dict = Depends(_current_user)) -> dict:
    return {"email": current["email"], "name": current["name"]}

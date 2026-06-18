import datetime as dt
import os
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from .db import User, UserRole

_JWT_SECRET = os.environ.get("PORTAL_JWT_SECRET", "dilovod-dev-secret-change-in-prod")
_JWT_ALGO = "HS256"
_JWT_TTL_HOURS = 24
_bearer = HTTPBearer(auto_error=False)


def _make_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
        "position": user.position,
        # роль у токен — фронт одразу знає права без додаткового запиту
        "role": user.role,
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=_JWT_TTL_HOURS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if not creds:
        raise HTTPException(401, "Потрібна авторизація")
    try:
        return jwt.decode(creds.credentials, _JWT_SECRET, algorithms=[_JWT_ALGO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Токен прострочений")
    except jwt.PyJWTError:
        raise HTTPException(401, "Недійсний токен")


def _require_role(*roles: UserRole):
    """Залежність FastAPI: пускає лише користувачів із вказаними ролями.

    Використання:
        @router.delete("/dangerous", dependencies=[Depends(_require_role(UserRole.ADMIN))])
        def handler(current_user: dict = Depends(_current_user)): ...
    """

    def dep(current_user: dict = Depends(_current_user)) -> dict:
        if current_user.get("role") not in [r.value for r in roles]:
            raise HTTPException(403, "недостатньо прав для цієї дії")
        return current_user

    return dep

import datetime as dt
import os
import jwt
from fastapi import Depends, HTTPException, Query
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
        # КЕП особи (kep_subject_cn) та печатка юрособи (organization_cert_cn) —
        # щоб _is_active_signer перевіряв право підпису без додаткового запиту БД.
        "kep_subject_cn": user.kep_subject_cn,
        "organization_cert_cn": user.organization_cert_cn,
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=_JWT_TTL_HOURS),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(None),
) -> dict:
    jwt_token = None
    if creds and creds.credentials:
        jwt_token = creds.credentials.strip()
    
    if not jwt_token and token:
        jwt_token = token.strip()

    if not jwt_token:
        raise HTTPException(401, "Потрібна авторизація")
    try:
        return jwt.decode(jwt_token, _JWT_SECRET, algorithms=[_JWT_ALGO])
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

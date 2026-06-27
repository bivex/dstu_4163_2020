from fastapi import APIRouter, Body, Depends, HTTPException
import uuid
import time
import base64
from portal.auth import _current_user, _make_token
from portal.db import SessionLocal, User
from portal import domain_bridge as bridge

router = APIRouter(tags=["auth"])

# Одноразові челенджі для безпечного входу та прив'язки КЕП
_challenges: dict[str, float] = {}


def _user_public(user: User) -> dict:
    """Публічне представлення користувача (КЕП особи + печатка юрособи)."""
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "position": user.position,
        "role": user.role,
        "kep_serial_number": user.kep_serial_number,
        "kep_certificate_serial": user.kep_certificate_serial,
        "kep_subject_cn": user.kep_subject_cn,
        "organization_cert_cn": user.organization_cert_cn,
    }


@router.post("/auth/login")
def auth_login(payload: dict = Body(...)) -> dict:
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    with SessionLocal() as session:
        user = session.query(User).filter_by(email=email).first()
        if not user or not user.verify_password(password):
            raise HTTPException(401, "Невірний email або пароль")
        token = _make_token(user)
        return {"token": token, "user": _user_public(user)}


@router.get("/auth/me")
def auth_me(current: dict = Depends(_current_user)) -> dict:
    user_id = int(current["sub"])
    with SessionLocal() as session:
        user = session.query(User).get(user_id)
        if not user:
            raise HTTPException(404, "Користувача не знайдено")
        return _user_public(user)


@router.get("/auth/challenge")
def get_challenge() -> dict:
    chal = str(uuid.uuid4())
    _challenges[chal] = time.time()
    
    # Очищення старих челенджів (> 5 хвилин)
    now = time.time()
    for k, t in list(_challenges.items()):
        if now - t > 300:
            _challenges.pop(k, None)
            
    return {"challenge": chal}


@router.post("/auth/login-kep")
def login_kep(payload: dict = Body(...)) -> dict:
    chal = str(payload.get("challenge", ""))
    sig_b64 = str(payload.get("signature_b64", ""))
    
    if chal not in _challenges:
        raise HTTPException(400, "Челендж застарів або недійсний")
    _challenges.pop(chal)  # Одноразове використання
    
    try:
        sig_bytes = base64.b64decode(sig_b64)
    except Exception:
        raise HTTPException(400, "Недійсний base64 підпису")
        
    if not bridge.verify_signature(chal.encode(), sig_bytes):
        raise HTTPException(401, "Недійсний підпис КЕП під перевірочними даними")
        
    cert = bridge.cert_info_from_cms(sig_bytes)
    rnopp = cert.get("serialNumber")
    if not rnopp:
        raise HTTPException(400, "Не вдалося витягти РНОКПП (ІПН) з вашого сертифіката КЕП")
        
    with SessionLocal() as session:
        user = session.query(User).filter(User.kep_serial_number == rnopp).first()
        if not user:
            raise HTTPException(401, f"Користувача з РНОКПП {rnopp} не знайдено. Будь ласка, спочатку прив'яжіть КЕП у кабінеті.")
            
        token = _make_token(user)
        return {"token": token, "user": _user_public(user)}


@router.post("/auth/link-kep")
def link_kep(current: dict = Depends(_current_user), payload: dict = Body(...)) -> dict:
    chal = str(payload.get("challenge", ""))
    sig_b64 = str(payload.get("signature_b64", ""))
    user_id = int(current["sub"])

    if chal not in _challenges:
        raise HTTPException(400, "Челендж застарів або недійсний")
    _challenges.pop(chal)

    try:
        sig_bytes = base64.b64decode(sig_b64)
    except Exception:
        raise HTTPException(400, "Недійсний base64 підпису")

    if not bridge.verify_signature(chal.encode(), sig_bytes):
        raise HTTPException(400, "Недійсний підпис КЕП під перевірочними даними")

    cert = bridge.cert_info_from_cms(sig_bytes)
    cert_type = cert.get("cert_type", "esign")
    rnopp = cert.get("serialNumber")
    cert_serial = cert.get("certificate_serial")
    cn = cert.get("signer")

    with SessionLocal() as session:
        user = session.query(User).get(user_id)
        if not user:
            raise HTTPException(404, "Користувача не знайдено")

        if cert_type == "eseal":
            # електронна печатка юрособи: прив'язуємо CN сертифіката печатки
            # (назва юрособи) та organizationIdentifier. РНОКПП тут нема.
            if not cn:
                raise HTTPException(400, "Не вдалося витягти назву юрособи з сертифіката печатки")
            existing = session.query(User).filter(
                User.organization_cert_cn == cn, User.id != user_id
            ).first()
            if existing:
                raise HTTPException(
                    400,
                    f"Ця печатка вже прив'язана до іншого облікового запису ({existing.email})",
                )
            user.organization_cert_cn = cn
        else:
            # КЕП фізособи: прив'язка за РНОКПП (як раніше)
            if not rnopp:
                raise HTTPException(400, "Не вдалося витягти РНОКПП (ІПН) з вашого сертифіката КЕП")
            existing = session.query(User).filter(
                User.kep_serial_number == rnopp, User.id != user_id
            ).first()
            if existing:
                raise HTTPException(400, f"Цей КЕП вже прив'язаний до іншого облікового запису ({existing.email})")
            user.kep_serial_number = rnopp
            user.kep_certificate_serial = cert_serial
            user.kep_subject_cn = cn
        session.commit()

        return {
            "status": "ok",
            "cert_type": cert_type,
            "user": _user_public(user),
        }


@router.post("/auth/unlink-kep")
def unlink_kep(current: dict = Depends(_current_user), payload: dict = Body(default={})) -> dict:
    """Відв'язати КЕП особи та/або печатку юрособи.

    ``payload.cert_type`` ('esign'|'eseal') вказує, ЩО відв'язати; без нього
    відв'язується КЕП особи (зворотна сумісність).
    """
    user_id = int(current["sub"])
    cert_type = str(payload.get("cert_type", "esign"))
    with SessionLocal() as session:
        user = session.query(User).get(user_id)
        if not user:
            raise HTTPException(404, "Користувача не знайдено")

        if cert_type == "eseal":
            user.organization_cert_cn = None
        else:
            user.kep_serial_number = None
            user.kep_certificate_serial = None
            user.kep_subject_cn = None
        session.commit()

        return {"status": "ok", "user": _user_public(user)}

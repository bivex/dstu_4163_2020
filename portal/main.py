"""Портал підписання та редагування документів — FastAPI застосунок.

Бекенд поверх доменного ядра dilovod4 (ДСТУ 4163 + 7 НПА). Реалізує:
  • редагування чернетки документа (DocumentContent);
  • генерацію PDF/DOCX з валідацією за ДСТУ та НПА;
  • чергу багатопідписання (директор → головбух тощо) зі статусами;
  • приймання КЕП-підпису, накладеного на КЛІЄНТІ (EUSign) — приватний ключ
    не покидає браузер (Закон 2155-VIII);
  • аудит подій для ст.13 Закону 851-IV.

Серверний підпис токеном/печаткою (dilovod4 token_sign/asic) — поза скелетом,
підключається окремим маршрутом за потреби (печатка юрособи).
"""

from __future__ import annotations

import base64
import datetime as dt
import os
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path

import jwt
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from . import domain_bridge as bridge
from .db import (
    AuditEvent,
    Document,
    DocStatus,
    SessionLocal,
    Signer,
    SignerStatus,
    User,
    init_db,
)

_JWT_SECRET = os.environ.get("PORTAL_JWT_SECRET", "dilovod-dev-secret-change-in-prod")
_JWT_ALGO = "HS256"
_JWT_TTL_HOURS = 24
_bearer = HTTPBearer(auto_error=False)


def _make_token(user: User) -> str:
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "name": user.name,
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

@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Портал підписання документів (ДСТУ 4163 + НПА)",
    version="0.1.0",
    lifespan=_lifespan,
)

# фронт (Next.js / EUSign) ходить з іншого origin — дозволяємо у dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("PORTAL_CORS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


def _audit(session, doc: Document, kind: str, actor: str = "", detail: str = "") -> None:
    session.add(AuditEvent(document_id=doc.id, kind=kind, actor=actor, detail=detail))


def _cors_origin(request: Request) -> str:
    return request.headers.get("origin", "*")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Повертає CORS заголовок навіть при 500 — інакше браузер бачить CORS error."""
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc)},
        headers={"Access-Control-Allow-Origin": _cors_origin(request),
                 "Access-Control-Allow-Credentials": "true"},
    )


@app.exception_handler(HTTPException)
async def _http_exc(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers={"Access-Control-Allow-Origin": _cors_origin(request),
                 "Access-Control-Allow-Credentials": "true"},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": dt.datetime.now(dt.timezone.utc).isoformat()}


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------

@app.post("/auth/login")
def auth_login(payload: dict = Body(...)) -> dict:
    email = str(payload.get("email", "")).strip().lower()
    password = str(payload.get("password", ""))
    with SessionLocal() as session:
        user = session.query(User).filter_by(email=email).first()
        if not user or not user.verify_password(password):
            raise HTTPException(401, "Невірний email або пароль")
        token = _make_token(user)
        return {"token": token, "user": {"email": user.email, "name": user.name}}


@app.get("/auth/me")
def auth_me(current: dict = Depends(_current_user)) -> dict:
    return {"email": current["email"], "name": current["name"]}


@app.post("/documents")
def create_document(payload: dict = Body(...)) -> dict:
    """Створити чернетку документа з чергою підписантів.

    payload: { doc_id, org_name, doc_type, title, body[], date_text, reg_index,
               fmt(pdf|docx), signers:[{full_name, position, order_index}],
               retention_years }
    """
    doc_id = payload.get("doc_id")
    if not doc_id:
        raise HTTPException(400, "doc_id обовʼязковий")

    with SessionLocal() as session:
        existing = session.query(Document).filter_by(doc_id=doc_id).first()
        if existing:
            # upsert: оновлюємо чернетку якщо вона ще не подана у чергу
            if existing.status != DocStatus.DRAFT:
                raise HTTPException(
                    409,
                    f"документ {doc_id} у статусі «{existing.status.value}» — редагування заборонено",
                )
            existing.title = str(payload.get("title", existing.title))
            existing.fmt = str(payload.get("fmt", existing.fmt))
            existing.content_json = bridge.content_to_json(payload)
            # оновлюємо підписантів
            for s in existing.signers:
                session.delete(s)
            session.flush()
            for s in payload.get("signers", []):
                existing.signers.append(
                    Signer(
                        full_name=str(s.get("full_name", "")),
                        position=str(s.get("position", "")),
                        order_index=int(s.get("order_index", 0)),
                        status=SignerStatus.WAITING,
                    )
                )
            _audit(session, existing, "updated")
            session.commit()
            return _doc_to_dict(existing)

        retention_years = int(payload.get("retention_years", 5))
        doc = Document(
            doc_id=doc_id,
            title=str(payload.get("title", "")),
            fmt=str(payload.get("fmt", "pdf")),
            status=DocStatus.DRAFT,
            content_json=bridge.content_to_json(payload),
            retention_until=dt.datetime.now(dt.timezone.utc)
            + dt.timedelta(days=365 * retention_years),
        )
        for s in payload.get("signers", []):
            doc.signers.append(
                Signer(
                    order_index=int(s.get("order_index", 0)),
                    full_name=str(s["full_name"]),
                    position=str(s.get("position", "")),
                    status=SignerStatus.WAITING,
                )
            )
        session.add(doc)
        session.flush()
        _audit(session, doc, "created", detail=f"signers={len(doc.signers)}")
        session.commit()
        return _doc_to_dict(doc)


@app.get("/documents")
def list_documents() -> dict:
    with SessionLocal() as session:
        docs = session.query(Document).order_by(Document.created_at.desc()).all()
        return {"documents": [_doc_to_dict(d, brief=True) for d in docs]}


@app.get("/documents/{doc_id}")
def get_document(doc_id: str) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        return _doc_to_dict(doc)


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str) -> dict:
    """Видалити документ разом із підписантами та аудитом (каскадно).

    Дозволяє перестворити документ із тим самим doc_id — напр. коли у БД лишився
    застарілий/тестовий підпис, через який зібраний ASiC-E не проходить перевірку.
    """
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        session.delete(doc)  # cascade видаляє signers + audit_events
        session.commit()
        return {"deleted": doc_id}


@app.put("/documents/{doc_id}")
def edit_document(doc_id: str, payload: dict = Body(...)) -> dict:
    """Редагувати чернетку (лише поки DRAFT)."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status != DocStatus.DRAFT:
            raise HTTPException(409, "редагування лише у статусі DRAFT")
        doc.title = str(payload.get("title", doc.title))
        doc.fmt = str(payload.get("fmt", doc.fmt))
        merged = bridge.content_from_json(doc.content_json)
        merged.update(payload)
        doc.content_json = bridge.content_to_json(merged)
        _audit(session, doc, "edited")
        session.commit()
        return _doc_to_dict(doc)


@app.post("/documents/{doc_id}/generate")
def generate_document(doc_id: str) -> dict:
    """Згенерувати PDF/DOCX + валідація за ДСТУ/НПА; зберегти у БД."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        payload = bridge.content_from_json(doc.content_json)
        # валідація обовʼязкових полів перед генерацією
        if not payload.get("body"):
            raise HTTPException(400, "текст документа (body) не може бути порожнім")
        if not payload.get("org_name", "").strip():
            raise HTTPException(400, "найменування організації (org_name) не може бути порожнім")
        with tempfile.NamedTemporaryFile(suffix=f".{doc.fmt}", delete=False) as tmp:
            dest = tmp.name
        try:
            out = bridge.generate(payload, doc.fmt, dest)
            with open(out["path"], "rb") as fh:
                doc.rendered = fh.read()
            import json as _json

            doc.conformance_json = _json.dumps(out["report"], ensure_ascii=False)
        finally:
            for p in (dest, dest + f".{doc.fmt}"):
                if os.path.exists(p):
                    os.remove(p)
        _audit(session, doc, "generated",
               detail=f"conforms={out['report'] and out['report']['conforms']}")
        session.commit()
        return {"doc_id": doc_id, "report": out["report"], "pdfa": out.get("pdfa")}


@app.get("/documents/{doc_id}/download")
def download_document(doc_id: str) -> Response:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        # після підпису віддаємо версію з відмітками про КЕП + QR;
        # до підпису — чистий згенерований документ
        body = doc.rendered_marked or doc.rendered
        if not body:
            raise HTTPException(404, "документ ще не згенеровано")
        media = "application/pdf" if doc.fmt == "pdf" else (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        suffix = "-signed" if doc.rendered_marked else ""
        return Response(
            content=body,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{doc_id}{suffix}.{doc.fmt}"'},
        )


@app.post("/documents/{doc_id}/validate")
def validate_document(doc_id: str) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        payload = bridge.content_from_json(doc.content_json)
        return bridge.validate(payload)


@app.get("/documents/{doc_id}/manifest")
def signing_manifest(doc_id: str) -> Response:
    """Байти ASiCManifest, які поточний підписант у черзі підписує detached.

    Клієнт (EUSign) підписує саме ЦІ байти detached-CAdES (signData з
    isInternalSign=false) і повертає p7s у /sign. Так підпис покриває манІфест
    (digest документа), як вимагає ETSI EN 319 162-1, тож контейнер пройде
    перевірку (а не «помилка 33»).
    """
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.rendered:
            raise HTTPException(409, "спершу згенеруйте документ (/generate)")
        nxt = doc.next_signer
        if nxt is None:
            raise HTTPException(409, "немає активного підписанта")
        manifest = bridge.manifest_for_signer(
            doc.doc_id, doc.fmt, doc.rendered, nxt.order_index
        )
        return Response(content=manifest, media_type="application/xml")


@app.get("/documents/{doc_id}/download/asice")
def download_asice(doc_id: str) -> Response:
    """Завантажити ASiC-E контейнер (документ + усі КЕП-підписи)."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.asice:
            raise HTTPException(
                404, "ASiC-E ще не зібрано (документ має бути підписаний усіма)"
            )
        return Response(
            content=doc.asice,
            media_type="application/vnd.etsi.asic-e+zip",
            headers={"Content-Disposition": f'attachment; filename="{doc_id}.asice"'},
        )


@app.post("/documents/{doc_id}/submit")
def submit_for_signing(doc_id: str) -> dict:
    """Перевести чернетку у чергу підписання: перший підписант → INVITED."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.signers:
            raise HTTPException(400, "немає підписантів у черзі")
        # Подавати у чергу можна лише чернетку. Якщо документ уже у черзі,
        # підписаний або оприлюднений — повторний submit заборонено (інакше
        # він скине статуси підписантів і затре вже зібрані КЕП-підписи).
        if doc.status != DocStatus.DRAFT:
            raise HTTPException(
                409,
                f"документ у статусі «{doc.status.value}» — повторне подання у чергу "
                "неможливе (підписи вже зібрано або процес триває)",
            )
        doc.status = DocStatus.PENDING_SIGNATURES
        doc.signers[0].status = SignerStatus.INVITED
        _audit(session, doc, "submitted")
        session.commit()
        return _doc_to_dict(doc)


@app.post("/documents/{doc_id}/sign")
def sign_document(doc_id: str, payload: dict = Body(...)) -> dict:
    """Прийняти КЕП-підпис від клієнта (EUSign) для поточного підписанта.

    payload: { signer_order_index, signature_b64, certificate_serial, issuer,
               signer (ПІБ), signer_position }
    Підпис накладено у БРАУЗЕРІ — приватний ключ сюди не передається.
    """
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status != DocStatus.PENDING_SIGNATURES:
            raise HTTPException(409, "документ не у статусі очікування підписів")

        nxt = doc.next_signer
        if nxt is None:
            raise HTTPException(409, "черга підписання порожня")
        idx = int(payload.get("signer_order_index", nxt.order_index))
        if idx != nxt.order_index:
            raise HTTPException(
                409, f"зараз черга підписанта #{nxt.order_index} ({nxt.full_name})"
            )

        sig_b64 = payload.get("signature_b64")
        if not sig_b64:
            raise HTTPException(400, "signature_b64 обовʼязковий (КЕП з клієнта)")

        try:
            sig_bytes = base64.b64decode(sig_b64)
        except Exception:  # noqa: BLE001
            raise HTTPException(400, "signature_b64 не є коректним base64")
        # КЕП-підпис — це CMS/p7s у DER: має починатися з SEQUENCE (0x30) і бути
        # достатнього розміру. Відсікаємо тестові заглушки/сміття, щоб вони не
        # потрапили у контейнер і не давали «помилку 33» при перевірці.
        if len(sig_bytes) < 256 or sig_bytes[0] != 0x30:
            raise HTTPException(
                422, "недійсний підпис: очікується CMS/p7s (DER) від EUSign, "
                "а не тестове значення"
            )

        nxt.signature = sig_bytes
        # Дані сертифіката беремо із САМОГО підпису (надійніше за клієнта).
        # Якщо розбір не вдався — падаємо на те, що передав клієнт.
        cert = bridge.cert_info_from_cms(sig_bytes)
        nxt.certificate_serial = (
            cert.get("certificate_serial") or str(payload.get("certificate_serial", "")) or ""
        )
        nxt.issuer = cert.get("issuer") or str(payload.get("issuer", "")) or ""
        nxt.valid_from = cert.get("valid_from") or ""
        nxt.valid_to = cert.get("valid_to") or ""
        nxt.status = SignerStatus.SIGNED
        nxt.signed_at = dt.datetime.now(dt.timezone.utc)
        _audit(session, doc, "signed", actor=cert.get("signer") or nxt.full_name,
               detail=f"serial={nxt.certificate_serial} issuer={nxt.issuer}")

        # активувати наступного у черзі або завершити
        following = doc.next_signer
        if following is None:
            doc.status = DocStatus.SIGNED
            _audit(session, doc, "all_signed")
            # зібрати ASiC-E з документа та всіх КЕП-підписів — лише в кінці
            _assemble_asice(session, doc)
        else:
            following.status = SignerStatus.INVITED

        # прогресивно перебудувати marked-візуалізацію ПІСЛЯ кожного підпису:
        # накопичено показуємо, хто вже підписав (у порядку черги, з часом).
        # Оригінал doc.rendered лишається недоторканим — над ним накладено КЕП.
        _render_marked(session, doc)

        session.commit()
        return _doc_to_dict(doc)


def _render_marked(session, doc: Document) -> None:
    """Перебудувати marked-візуалізацію (PDF/DOCX з відмітками про КЕП + QR).

    Викликається ПІСЛЯ КОЖНОГО підпису: накопичено показує тих, хто вже підписав,
    у порядку черги (signers впорядковані за order_index → перший→останній).
    Дані відміток — реальні, видобуті з CMS при /sign (ПІБ, серійник, видавець,
    строк дії, час). Чистий doc.rendered лишається недоторканим — саме над його
    digest накладено КЕП, які пакуються у ASiC-E.

    Це окреме людино-читане представлення (як у Вчасно/Дія): підписується
    оригінал, а візуалізація лише відображає стан підписання."""
    payload = bridge.content_from_json(doc.content_json)
    payload["e_signatures"] = [
        {
            "signer": s.full_name,
            "signer_position": s.position,
            "certificate_serial": s.certificate_serial or "—",
            "issuer": s.issuer or "—",
            "valid_from": s.valid_from or "",
            "valid_to": s.valid_to or "",
            "timestamp": s.signed_at.isoformat(timespec="seconds") if s.signed_at else "",
            "status": "Active",
            "is_qualified": True,
        }
        for s in doc.signers
        if s.status == SignerStatus.SIGNED
    ]
    with tempfile.NamedTemporaryFile(suffix=f".{doc.fmt}", delete=False) as tmp:
        dest = tmp.name
    try:
        path = bridge.render_marked(payload, doc.fmt, dest)
        with open(path, "rb") as fh:
            doc.rendered_marked = fh.read()
        _audit(session, doc, "marked_rendered",
               detail=f"signatures={len(payload['e_signatures'])}")
    finally:
        for p in (dest, dest + f".{doc.fmt}"):
            if os.path.exists(p):
                os.remove(p)


def _assemble_asice(session, doc: Document) -> None:
    """Зібрати ASiC-E контейнер після підпису всіма; зберегти у doc.asice."""
    if not doc.rendered:
        return  # документ ще не згенеровано — нема що пакувати
    sigs = [
        (s.full_name, s.signature)
        for s in doc.signers
        if s.status == SignerStatus.SIGNED and s.signature
    ]
    if not sigs:
        return
    with tempfile.NamedTemporaryFile(suffix=".asice", delete=False) as tmp:
        dest = tmp.name
    try:
        bridge.build_asice(doc.doc_id, doc.fmt, doc.rendered, sigs, dest)
        with open(dest, "rb") as fh:
            doc.asice = fh.read()
        _audit(session, doc, "asice_built", detail=f"signatures={len(sigs)}")
    finally:
        if os.path.exists(dest):
            os.remove(dest)


@app.post("/documents/{doc_id}/reject")
def reject_document(doc_id: str, payload: dict = Body(...)) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        nxt = doc.next_signer
        if nxt is None:
            raise HTTPException(409, "немає активного підписанта")
        nxt.status = SignerStatus.REJECTED
        doc.status = DocStatus.DRAFT
        _audit(session, doc, "rejected", actor=nxt.full_name,
               detail=str(payload.get("reason", "")))
        session.commit()
        return _doc_to_dict(doc)


@app.post("/documents/{doc_id}/publish")
def publish_document(doc_id: str) -> dict:
    """Оприлюднити підписаний документ (ст.14 996-XIV / ст.15 2939-VI)."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status != DocStatus.SIGNED:
            raise HTTPException(409, "оприлюднення лише після підписання всіма")
        doc.status = DocStatus.PUBLISHED
        _audit(session, doc, "published")
        session.commit()
        return _doc_to_dict(doc)


# --- helpers ---
def _load(session, doc_id: str) -> Document:
    doc = session.query(Document).filter_by(doc_id=doc_id).first()
    if doc is None:
        raise HTTPException(404, f"документ {doc_id} не знайдено")
    return doc


def _doc_to_dict(doc: Document, brief: bool = False) -> dict:
    data = {
        "doc_id": doc.doc_id,
        "title": doc.title,
        "status": doc.status.value,
        "fmt": doc.fmt,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "retention_until": doc.retention_until.isoformat() if doc.retention_until else None,
        "signers": [
            {
                "order_index": s.order_index,
                "full_name": s.full_name,
                "position": s.position,
                "status": s.status.value,
                "certificate_serial": s.certificate_serial,
                "signed_at": s.signed_at.isoformat() if s.signed_at else None,
            }
            for s in doc.signers
        ],
        "has_rendered": doc.rendered is not None,
        "has_asice": doc.asice is not None,
    }
    if not brief:
        import json as _json

        data["content_json"] = _json.loads(doc.content_json) if doc.content_json else {}
        data["conformance"] = (
            _json.loads(doc.conformance_json) if doc.conformance_json else None
        )
        data["events"] = [
            {"kind": e.kind, "actor": e.actor, "detail": e.detail,
             "at": e.created_at.isoformat() if e.created_at else None}
            for e in doc.events
        ]
    return data


# --- статика: фронт + бібліотека EUSign ---
# Фронт лежить у portal/web; бібліотека EUSign — у submodule external/EUSignES6
# (подається під /eusign/ — той самий origin, тож приватний ключ не покидає
# браузер). Монтуємо в кінці, щоб не перекрити API-маршрути.
_HERE = Path(__file__).resolve().parent
_WEB_DIR = _HERE / "web"
_EUSIGN_DIR = _HERE.parent / "external" / "EUSignES6"


@app.get("/")
def _root() -> RedirectResponse:
    return RedirectResponse(url="/web/")


@app.get("/favicon.ico")
def _favicon() -> Response:
    ico = _EUSIGN_DIR / "favicon.ico"
    if ico.is_file():
        return Response(content=ico.read_bytes(), media_type="image/x-icon")
    return Response(status_code=204)


# --- актуальний перелік КНЕДП з офіційного джерела IIT ---
# EUSign запитує /signdata/CAs.json. Замість застарілого бандла EUSignES6
# проксуємо свіжий перелік з iit.com.ua (через сервер — обходимо CORS), кешуємо
# у памʼяті на годину, із фолбеком на снапшот реєстру dilovod4 (data/CAs.json,
# той самий, що використовує ca_registry для резолву CMP/TSP/OCSP) за збою мережі.
_CAS_URL = os.environ.get("PORTAL_CAS_URL", "https://iit.com.ua/download/productfiles/CAs.json")
_CAS_TTL = int(os.environ.get("PORTAL_CAS_TTL", "3600"))  # секунд
_CAS_FALLBACK = _HERE.parent / "src" / "dilovod4" / "infrastructure" / "data" / "CAs.json"
_cas_cache: dict = {"body": None, "ts": 0.0}


@app.get("/signdata/CAs.json")
def cas_json() -> Response:
    import time
    import urllib.request

    now = time.time()
    if _cas_cache["body"] is not None and now - _cas_cache["ts"] < _CAS_TTL:
        return Response(content=_cas_cache["body"], media_type="application/json")
    try:
        req = urllib.request.Request(_CAS_URL, headers={"User-Agent": "dilovod4-portal"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read()
        # перевірка, що це валідний JSON-перелік
        import json as _json

        if not isinstance(_json.loads(body), list):
            raise ValueError("CAs.json не є переліком")
        _cas_cache.update(body=body, ts=now)
        return Response(content=body, media_type="application/json")
    except Exception:  # noqa: BLE001 — фолбек на снапшот реєстру dilovod4
        if _CAS_FALLBACK.is_file():
            return Response(content=_CAS_FALLBACK.read_bytes(), media_type="application/json")
        raise HTTPException(502, "не вдалося отримати перелік КНЕДП")


if _EUSIGN_DIR.is_dir():
    app.mount("/eusign", StaticFiles(directory=str(_EUSIGN_DIR)), name="eusign")
    # EUSign-бібліотека звертається до своїх даних за АБСОЛЮТНИМ шляхом
    # /signdata/CAs.json та /signdata/CACertificates.p7b (зашито в euscpfactory.js).
    # Монтуємо signdata ще й під корінь, щоб ці запити не давали 404.
    _SIGNDATA = _EUSIGN_DIR / "signdata"
    if _SIGNDATA.is_dir():
        app.mount("/signdata", StaticFiles(directory=str(_SIGNDATA)), name="signdata")
if _WEB_DIR.is_dir():
    app.mount("/web", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")

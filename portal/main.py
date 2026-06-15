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
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from . import domain_bridge as bridge
from .db import (
    AuditEvent,
    Document,
    DocStatus,
    Folder,
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


@app.post("/documents/scan")
async def ingest_scan(
    file: UploadFile = File(...),
    doc_id: str = Form(...),
    title: str = Form(""),
    signers: str = Form(""),
    retention_years: int = Form(5),
) -> dict:
    """Оцифрування паперового документа: залити скан як електронний оригінал.

    Скан (PDF або фото JPEG/PNG/TIFF) стає rendered-оригіналом — документ НЕ
    генерується з полів форми. Далі підписується КЕП через звичайний пайплайн
    (submit → manifest → sign → ASiC-E), тож електронна копія набуває юридичної
    сили (Закон 851-IV, ст.7 ↔ ст.12).

    signers — рядки «ПІБ | посада», розділені переносом рядка.
    """
    from . import scan_ingest

    data = await file.read()
    if not scan_ingest.is_supported(file.content_type or "", file.filename or ""):
        raise HTTPException(
            415,
            "непідтримуваний тип скану — приймаються PDF або зображення "
            "(JPEG/PNG/TIFF/BMP/WEBP)",
        )
    try:
        pdf_bytes = scan_ingest.normalize_to_pdf(
            data, file.content_type or "", file.filename or ""
        )
    except scan_ingest.ScanError as exc:
        raise HTTPException(422, str(exc))

    # розібрати підписантів із «ПІБ | посада» по рядках
    parsed_signers = []
    for i, line in enumerate(s.strip() for s in signers.splitlines()):
        if not line:
            continue
        parts = [p.strip() for p in line.split("|", 1)]
        parsed_signers.append({
            "full_name": parts[0],
            "position": parts[1] if len(parts) > 1 else "",
            "order_index": i,
        })

    with SessionLocal() as session:
        existing = session.query(Document).filter_by(doc_id=doc_id).first()
        if existing and existing.status != DocStatus.DRAFT:
            raise HTTPException(
                409,
                f"документ {doc_id} у статусі «{existing.status.value}» — "
                "заміна скану заборонена",
            )
        doc = existing or Document(doc_id=doc_id)
        doc.title = title or f"Скан {doc_id}"
        doc.fmt = "pdf"  # скан завжди нормалізуємо у PDF
        doc.status = DocStatus.DRAFT
        doc.is_scanned = True
        doc.rendered = pdf_bytes  # скан = електронний оригінал
        doc.rendered_marked = None
        doc.content_json = bridge.content_to_json({
            "doc_id": doc_id, "title": doc.title, "fmt": "pdf",
            "is_scanned": True, "doc_type": "Скан-копія",
        })
        if doc.retention_until is None:
            doc.retention_until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
                days=365 * retention_years
            )
        # перевірка PDF/A архівної придатності (інформаційно)
        try:
            from dilovod4.infrastructure.pdfa_inspector import inspect_pdfa
            import json as _json

            chk = inspect_pdfa(pdf_bytes, require_xmp=False)
            doc.conformance_json = _json.dumps(
                {"conforms": chk.conforms, "findings": list(chk.findings),
                 "scanned": True}, ensure_ascii=False
            )
        except Exception:  # noqa: BLE001 — інформаційно
            pass
        # оновити підписантів
        for s in list(doc.signers):
            session.delete(s)
        session.flush()
        for s in parsed_signers:
            doc.signers.append(Signer(
                order_index=s["order_index"], full_name=s["full_name"],
                position=s["position"], status=SignerStatus.WAITING,
            ))
        if doc.id is None:
            session.add(doc)
        session.flush()
        _audit(session, doc, "scanned",
               detail=f"file={file.filename} size={len(data)} signers={len(parsed_signers)}")
        session.commit()
        return _doc_to_dict(doc)


@app.get("/registry")
def registration_journal(year: int | None = None) -> dict:
    """Реєстраційний журнал: зареєстровані документи з індексами та датами.

    Згруповано за типом документа, відсортовано за номером. Опційний фільтр
    за діловодним роком (default — поточний).
    """
    import datetime as _dt

    target_year = year or _dt.datetime.now(_dt.timezone.utc).year
    with SessionLocal() as session:
        docs = (
            session.query(Document)
            .filter(Document.reg_number.isnot(None))
            .order_by(Document.doc_type, Document.reg_number)
            .all()
        )
        entries = [
            {
                "doc_id": d.doc_id,
                "doc_type": d.doc_type,
                "reg_index": d.reg_index,
                "reg_number": d.reg_number,
                "reg_date": d.reg_date,
                "title": d.title,
                "status": d.status.value,
                "registered_at": d.registered_at.isoformat() if d.registered_at else None,
            }
            for d in docs
            if d.registered_at and d.registered_at.year == target_year
        ]
        return {"year": target_year, "count": len(entries), "entries": entries}


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
        # Скан-копія — це вже готовий електронний оригінал (завантажений файл).
        # Генерація з полів форми його б перезаписала — забороняємо.
        if doc.is_scanned:
            raise HTTPException(
                409,
                "документ є скан-копією — генерація з полів недоступна "
                "(оригіналом є завантажений скан, його лишень підписують)",
            )
        payload = bridge.content_from_json(doc.content_json)
        # валідація обовʼязкових полів перед генерацією
        if not payload.get("body"):
            raise HTTPException(400, "текст документа (body) не може бути порожнім")
        if not payload.get("org_name", "").strip():
            raise HTTPException(400, "найменування організації (org_name) не може бути порожнім")
        # ЧЕРНЕТКА-ПРОЄКТ: до офіційної реєстрації (submit) індекс ще не присвоєно.
        # Щоб згенерований проєкт не був порожнім, підставляємо поточну дату як
        # дату проєкту, якщо вона не задана. Реєстраційний індекс лишається
        # порожнім — він присвоюється тільки при поданні у чергу.
        if not str(payload.get("date_text", "")).strip():
            from . import registry

            payload["date_text"] = registry.format_ua_date(
                dt.datetime.now(dt.timezone.utc).date()
            )
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
        payload = _payload_with_signatures(doc)
        return bridge.validate(payload)


def _payload_with_signatures(doc: Document) -> dict:
    """Payload документа з реальними КЕП-відмітками із doc.signers (підписані).

    Реальні підписи зберігаються у doc.signers (не в content_json), тож для
    валідації ст.7 851-IV (ELECTRONIC_ORIGINAL) їх треба інжектити як
    e_signatures — інакше підписаний документ хибно вважався б не-оригіналом.
    """
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
    return payload


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


@app.get("/documents/archive/export")
def export_archive(
    days: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Response:
    """Експортувати архів документів (ZIP) за вказаний період або за весь час.

    Пакує електронні оригінали (.asice для підписаних, .pdf/.docx для інших),
    а також додає загальний metadata.json зі всією інформацією про документи.
    """
    import io
    import zipfile
    import json

    with SessionLocal() as session:
        query = session.query(Document)
        
        # Фільтр за датою створення
        now = dt.datetime.now(dt.timezone.utc)
        if days is not None:
            start_dt = now - dt.timedelta(days=days)
            query = query.filter(Document.created_at >= start_dt)
        else:
            if start_date:
                try:
                    start_dt = dt.datetime.combine(dt.date.fromisoformat(start_date), dt.time.min).replace(tzinfo=dt.timezone.utc)
                    query = query.filter(Document.created_at >= start_dt)
                except ValueError:
                    raise HTTPException(400, "Невірний формат start_date (очікується YYYY-MM-DD)")
            if end_date:
                try:
                    end_dt = dt.datetime.combine(dt.date.fromisoformat(end_date), dt.time.max).replace(tzinfo=dt.timezone.utc)
                    query = query.filter(Document.created_at <= end_dt)
                except ValueError:
                    raise HTTPException(400, "Невірний формат end_date (очікується YYYY-MM-DD)")

        docs = query.order_by(Document.created_at.desc()).all()
        if not docs:
            raise HTTPException(404, "Документів за вказаний період не знайдено")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            # 1. Записуємо файли документів
            for d in docs:
                content = d.asice or d.rendered_marked or d.rendered
                if not content:
                    continue
                ext = "asice" if d.asice else d.fmt
                filename = f"{d.doc_id}.{ext}"
                zip_file.writestr(filename, content)

            # 2. Записуємо файл метаданих
            meta_list = [_doc_to_dict(d) for d in docs]
            meta_json = json.dumps(meta_list, ensure_ascii=False, indent=2)
            zip_file.writestr("metadata.json", meta_json.encode("utf-8"))

        zip_buffer.seek(0)

        # Формування імені архіву
        zip_filename = "archive_all.zip"
        if days:
            zip_filename = f"archive_last_{days}_days.zip"
        elif start_date or end_date:
            s_label = start_date or "start"
            e_label = end_date or "end"
            zip_filename = f"archive_{s_label}_to_{e_label}.zip"

        return Response(
            content=zip_buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
        )


@app.post("/documents/{doc_id}/submit")
def submit_for_signing(doc_id: str, payload: dict = Body(default={})) -> dict:
    """Перевести чернетку у чергу підписання: перший підписант → INVITED.

    Реєстрація (індекс + дата) опційна:
    - auto_register=True (default) і поля порожні → присвоюються автоматично
      (наскрізний індекс за типом + поточна дата);
    - якщо у картці вже задано reg_index та/або date_text вручну — вони
      поважаються, авто-присвоєння для заданого поля пропускається;
    - auto_register=False → реєстрація не виконується взагалі (беремо що є).
    """
    auto_register = bool(payload.get("auto_register", True))
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

        from . import registry

        content = bridge.content_from_json(doc.content_json)
        doc_type = str(content.get("doc_type", "Документ"))
        manual_index = str(content.get("reg_index", "")).strip()
        manual_date = str(content.get("date_text", "")).strip()
        changed = False

        if auto_register:
            # авто-індекс лише якщо вручну не заданий
            if not manual_index:
                registry.assign_registration(session, doc, doc_type)
                content["reg_index"] = doc.reg_index
                # авто-дата лише якщо вручну не задана
                content["date_text"] = manual_date or doc.reg_date
                changed = True
            else:
                # індекс заданий вручну — фіксуємо його у реєстрі як є
                doc.doc_type = doc_type
                doc.reg_index = manual_index
                doc.reg_date = manual_date or registry.format_ua_date(
                    dt.datetime.now(dt.timezone.utc).date()
                )
                doc.registered_at = dt.datetime.now(dt.timezone.utc)
                content["date_text"] = doc.reg_date
                changed = True

        if changed:
            doc.content_json = bridge.content_to_json(content)
            # перегенерувати документ з індексом і датою (якщо вже рендерився).
            # Скан НЕ перегенеровуємо — оригіналом є саме завантажений файл.
            if doc.rendered is not None and not doc.is_scanned:
                _regenerate(session, doc, content)
            _audit(session, doc, "registered",
                   detail=f"reg_index={doc.reg_index} date={doc.reg_date}")

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


def _regenerate(session, doc: Document, payload: dict) -> None:
    """Перегенерувати чистий документ + conformance після зміни даних (напр.
    присвоєння реєстраційного індексу й дати при поданні у чергу)."""
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


def _render_marked(session, doc: Document) -> None:
    """Перебудувати marked-візуалізацію (PDF/DOCX з відмітками про КЕП + QR).

    Викликається ПІСЛЯ КОЖНОГО підпису: накопичено показує тих, хто вже підписав,
    у порядку черги (signers впорядковані за order_index → перший→останній).
    Дані відміток — реальні, видобуті з CMS при /sign (ПІБ, серійник, видавець,
    строк дії, час). Чистий doc.rendered лишається недоторканим — саме над його
    digest накладено КЕП, які пакуються у ASiC-E.

    Це окреме людино-читане представлення (як у Вчасно/Дія): підписується
    оригінал, а візуалізація лише відображає стан підписання."""
    # Скан-копія не має полів для відмітки — оригіналом є саме завантажений
    # файл. КЕП покриває його digest (ASiC-E), візуалізацію не перебудовуємо.
    if doc.is_scanned:
        return
    payload = _payload_with_signatures(doc)
    with tempfile.NamedTemporaryFile(suffix=f".{doc.fmt}", delete=False) as tmp:
        dest = tmp.name
    try:
        path = bridge.render_marked(payload, doc.fmt, dest)
        with open(path, "rb") as fh:
            doc.rendered_marked = fh.read()
        # ПЕРЕРАХУНОК відповідності з реальними КЕП-відмітками: після підпису
        # ст.7 851-IV (ELECTRONIC_ORIGINAL) проходить — документ став оригіналом.
        import json as _json

        report = bridge.validate(payload)
        doc.conformance_json = _json.dumps(report, ensure_ascii=False)
        _audit(session, doc, "marked_rendered",
               detail=f"signatures={len(payload['e_signatures'])} "
                      f"conforms={report.get('conforms')}")
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


@app.post("/documents/{doc_id}/archive")
def archive_document(doc_id: str) -> dict:
    """Архівувати документ: організаційна позначка, ховає зі звичайного списку.

    Не змінює workflow-статус і не видаляє — документ лишається у розділі
    «Архів» і доступний для відновлення (/unarchive).
    """
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.archived_at is None:
            doc.archived_at = dt.datetime.now(dt.timezone.utc)
            _audit(session, doc, "archived")
            session.commit()
        return _doc_to_dict(doc)


@app.post("/documents/{doc_id}/unarchive")
def unarchive_document(doc_id: str) -> dict:
    """Відновити документ з архіву (повертає у звичайний список)."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.archived_at is not None:
            doc.archived_at = None
            _audit(session, doc, "unarchived")
            session.commit()
        return _doc_to_dict(doc)


# ====================== ПАПКИ-КАТЕГОРІЇ ======================
def _folder_to_dict(folder: Folder, doc_count: int | None = None) -> dict:
    return {
        "id": folder.id,
        "name": folder.name,
        "color": folder.color,
        "position": folder.position,
        "created_at": folder.created_at.isoformat() if folder.created_at else None,
        "doc_count": doc_count,
    }


@app.get("/folders")
def list_folders() -> dict:
    """Перелік папок із лічильником документів у кожній (без архівних)."""
    from sqlalchemy import func

    with SessionLocal() as session:
        folders = session.query(Folder).order_by(Folder.position, Folder.id).all()
        rows = (
            session.query(Document.folder_id, func.count(Document.id))
            .filter(Document.folder_id.isnot(None), Document.archived_at.is_(None))
            .group_by(Document.folder_id)
            .all()
        )
        counts: dict[int, int] = {fid: cnt for fid, cnt in rows if fid is not None}
        return {
            "folders": [_folder_to_dict(f, counts.get(f.id, 0)) for f in folders]
        }


@app.post("/folders")
def create_folder(payload: dict = Body(...)) -> dict:
    """Створити папку. payload: { name, color? }"""
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "назва папки обовʼязкова")
    with SessionLocal() as session:
        max_pos = session.query(Folder).count()
        folder = Folder(
            name=name,
            color=(str(payload["color"]) if payload.get("color") else None),
            position=max_pos,
        )
        session.add(folder)
        session.commit()
        return _folder_to_dict(folder, 0)


@app.put("/folders/{folder_id}")
def rename_folder(folder_id: int, payload: dict = Body(...)) -> dict:
    """Перейменувати папку / змінити колір. payload: { name?, color? }"""
    with SessionLocal() as session:
        folder = session.get(Folder, folder_id)
        if folder is None:
            raise HTTPException(404, f"папку {folder_id} не знайдено")
        if "name" in payload:
            new_name = str(payload["name"]).strip()
            if not new_name:
                raise HTTPException(400, "назва папки не може бути порожньою")
            folder.name = new_name
        if "color" in payload:
            folder.color = str(payload["color"]) if payload["color"] else None
        session.commit()
        return _folder_to_dict(folder)


@app.delete("/folders/{folder_id}")
def delete_folder(folder_id: int) -> dict:
    """Видалити папку. Документи не видаляються — їх folder_id → NULL."""
    with SessionLocal() as session:
        folder = session.get(Folder, folder_id)
        if folder is None:
            raise HTTPException(404, f"папку {folder_id} не знайдено")
        # відвʼязуємо документи (ondelete=SET NULL спрацьовує не на всіх БД —
        # робимо це явно для надійності на SQLite)
        for doc in session.query(Document).filter_by(folder_id=folder_id).all():
            doc.folder_id = None
        session.delete(folder)
        session.commit()
        return {"deleted": folder_id}


@app.post("/documents/{doc_id}/folder")
def set_document_folder(doc_id: str, payload: dict = Body(...)) -> dict:
    """Перемістити документ у папку (або прибрати з папки).

    payload: { folder_id: int|null } — null прибирає документ з папки.
    """
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        folder_id = payload.get("folder_id")
        if folder_id is None:
            doc.folder_id = None
            _audit(session, doc, "folder_cleared")
        else:
            folder = session.get(Folder, int(folder_id))
            if folder is None:
                raise HTTPException(404, f"папку {folder_id} не знайдено")
            doc.folder_id = folder.id
            _audit(session, doc, "folder_set", detail=f"folder={folder.name}")
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
        "reg_index": doc.reg_index,
        "reg_date": doc.reg_date,
        "reg_number": doc.reg_number,
        "doc_type": doc.doc_type,
        "registered_at": doc.registered_at.isoformat() if doc.registered_at else None,
        "archived": doc.archived_at is not None,
        "archived_at": doc.archived_at.isoformat() if doc.archived_at else None,
        "is_scanned": bool(doc.is_scanned),
        "folder_id": doc.folder_id,
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

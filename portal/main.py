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

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import domain_bridge as bridge
from .db import (
    AuditEvent,
    Document,
    DocStatus,
    SessionLocal,
    Signer,
    SignerStatus,
    init_db,
)

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
    allow_origins=os.environ.get("PORTAL_CORS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


def _audit(session, doc: Document, kind: str, actor: str = "", detail: str = "") -> None:
    session.add(AuditEvent(document_id=doc.id, kind=kind, actor=actor, detail=detail))


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "time": dt.datetime.now(dt.timezone.utc).isoformat()}


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
        if session.query(Document).filter_by(doc_id=doc_id).first():
            raise HTTPException(409, f"документ {doc_id} вже існує")

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
        return {"doc_id": doc_id, "report": out["report"]}


@app.get("/documents/{doc_id}/download")
def download_document(doc_id: str) -> Response:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.rendered:
            raise HTTPException(404, "документ ще не згенеровано")
        media = "application/pdf" if doc.fmt == "pdf" else (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        return Response(
            content=doc.rendered,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{doc_id}.{doc.fmt}"'},
        )


@app.post("/documents/{doc_id}/validate")
def validate_document(doc_id: str) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        payload = bridge.content_from_json(doc.content_json)
        return bridge.validate(payload)


@app.post("/documents/{doc_id}/submit")
def submit_for_signing(doc_id: str) -> dict:
    """Перевести чернетку у чергу підписання: перший підписант → INVITED."""
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if not doc.signers:
            raise HTTPException(400, "немає підписантів у черзі")
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

        nxt.signature = base64.b64decode(sig_b64)
        nxt.certificate_serial = str(payload.get("certificate_serial", ""))
        nxt.issuer = str(payload.get("issuer", ""))
        nxt.status = SignerStatus.SIGNED
        nxt.signed_at = dt.datetime.now(dt.timezone.utc)
        _audit(session, doc, "signed", actor=nxt.full_name,
               detail=f"serial={nxt.certificate_serial}")

        # активувати наступного у черзі або завершити
        following = doc.next_signer
        if following is None:
            doc.status = DocStatus.SIGNED
            _audit(session, doc, "all_signed")
        else:
            following.status = SignerStatus.INVITED

        session.commit()
        return _doc_to_dict(doc)


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
    }
    if not brief:
        import json as _json

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

import datetime as dt
import os
import tempfile
import io
import zipfile
import json
from fastapi import APIRouter, Body, Depends, HTTPException, File, Form, UploadFile, Response
from portal.db import Document, DocStatus, SessionLocal, Signer, SignerStatus, Approver, ApproverStatus
from portal.auth import _current_user
from portal import domain_bridge as bridge
from portal.helpers import _audit, _load, _doc_to_dict, _regenerate

router = APIRouter(tags=["documents"])


@router.post("/documents")
def create_document(payload: dict = Body(...)) -> dict:
    doc_id = payload.get("doc_id")
    if not doc_id:
        raise HTTPException(400, "doc_id обовʼязковий")

    with SessionLocal() as session:
        existing = session.query(Document).filter_by(doc_id=doc_id).first()
        if existing:
            if existing.status != DocStatus.DRAFT:
                raise HTTPException(
                    409,
                    f"документ {doc_id} у статусі «{existing.status.value}» — редагування заборонено",
                )
            existing.title = str(payload.get("title", existing.title))
            existing.fmt = str(payload.get("fmt", existing.fmt))
            existing.journal_id = int(payload["journal_id"]) if payload.get("journal_id") else None
            existing.approval_type = payload.get("approval_type", "sequential")
            existing.content_json = bridge.content_to_json(payload)
            for s in existing.signers:
                session.delete(s)
            for a in existing.approvers:
                session.delete(a)
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
            for i, a in enumerate(payload.get("approvers", [])):
                existing.approvers.append(
                    Approver(
                        order_index=i,
                        user_id=int(a["user_id"]) if a.get("user_id") else None,
                        full_name=str(a.get("full_name", "")),
                        position=str(a.get("position", "")),
                        status=ApproverStatus.WAITING
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
            journal_id=int(payload["journal_id"]) if payload.get("journal_id") else None,
            approval_type=payload.get("approval_type", "sequential"),
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
        for i, a in enumerate(payload.get("approvers", [])):
            doc.approvers.append(
                Approver(
                    order_index=i,
                    user_id=int(a["user_id"]) if a.get("user_id") else None,
                    full_name=str(a.get("full_name", "")),
                    position=str(a.get("position", "")),
                    status=ApproverStatus.WAITING
                )
            )
        session.add(doc)
        session.flush()
        _audit(session, doc, "created", detail=f"signers={len(doc.signers)} approvers={len(doc.approvers)}")
        session.commit()
        return _doc_to_dict(doc)


@router.post("/documents/scan")
async def ingest_scan(
    file: UploadFile = File(...),
    doc_id: str = Form(...),
    title: str = Form(""),
    signers: str = Form(""),
    retention_years: int = Form(5),
) -> dict:
    from portal import scan_ingest

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
        doc.fmt = "pdf"
        doc.status = DocStatus.DRAFT
        doc.is_scanned = True
        doc.rendered = pdf_bytes
        doc.rendered_marked = None
        doc.content_json = bridge.content_to_json({
            "doc_id": doc_id, "title": doc.title, "fmt": "pdf",
            "is_scanned": True, "doc_type": "Скан-копія",
        })
        if doc.retention_until is None:
            doc.retention_until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(
                days=365 * retention_years
            )
        try:
            from dilovod4.infrastructure.pdfa_inspector import inspect_pdfa
            chk = inspect_pdfa(pdf_bytes, require_xmp=False)
            doc.conformance_json = json.dumps(
                {"conforms": chk.conforms, "findings": list(chk.findings),
                 "scanned": True}, ensure_ascii=False
            )
        except Exception:
            pass
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


@router.get("/documents")
def list_documents() -> dict:
    with SessionLocal() as session:
        docs = session.query(Document).order_by(Document.created_at.desc()).all()
        return {"documents": [_doc_to_dict(d, brief=True) for d in docs]}


@router.get("/documents/export-json")
def export_documents_json(
    ids: str | None = None,
    current_user: dict = Depends(_current_user),
):
    """Повертає всі (або вибрані) документи як JSON-масив для бекапу/переносу."""
    with SessionLocal() as session:
        q = session.query(Document)
        if ids:
            id_list = [i.strip() for i in ids.split(",") if i.strip()]
            q = q.filter(Document.doc_id.in_(id_list))
        docs = q.order_by(Document.created_at).all()
        result = [_doc_to_dict(d, brief=False) for d in docs]

    payload_bytes = json.dumps(result, ensure_ascii=False, indent=2).encode("utf-8")
    return Response(
        content=payload_bytes,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="dms_backup.json"'},
    )


@router.post("/documents/import-json")
def import_documents_json(
    payload: list[dict] = Body(...),
    current_user: dict = Depends(_current_user),
) -> dict:
    """Відновлює документи з JSON-бекапу.

    Повертає { imported, skipped, errors }.
    Якщо doc_id вже існує — пропускається (не перезаписується).
    Документи відновлюються зі статусом DRAFT.
    """
    imported = 0
    skipped = 0
    errors: list[str] = []

    with SessionLocal() as session:
        for item in payload:
            doc_id = item.get("doc_id", "")
            if not doc_id:
                errors.append("Пропущено запис без doc_id")
                continue

            try:
                existing = session.query(Document).filter_by(doc_id=doc_id).first()
                if existing:
                    skipped += 1
                    continue

                raw_content = item.get("content_json", {})
                if isinstance(raw_content, dict):
                    content_json_str = json.dumps(raw_content, ensure_ascii=False)
                else:
                    content_json_str = str(raw_content)

                created_at = None
                if item.get("created_at"):
                    try:
                        created_at = dt.datetime.fromisoformat(item["created_at"])
                    except Exception:
                        pass
                created_at = created_at or dt.datetime.now(dt.timezone.utc)

                registered_at = None
                if item.get("registered_at"):
                    try:
                        registered_at = dt.datetime.fromisoformat(item["registered_at"])
                    except Exception:
                        pass

                retention_until = None
                if item.get("retention_until"):
                    try:
                        retention_until = dt.datetime.fromisoformat(item["retention_until"])
                    except Exception:
                        pass
                if not retention_until:
                    retention_until = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365 * 5)

                doc = Document(
                    doc_id=doc_id,
                    title=str(item.get("title", "")),
                    fmt=str(item.get("fmt", "pdf")),
                    status=DocStatus.DRAFT,
                    content_json=content_json_str,
                    doc_type=item.get("doc_type"),
                    reg_number=item.get("reg_number"),
                    reg_index=item.get("reg_index"),
                    reg_date=item.get("reg_date"),
                    registered_at=registered_at,
                    approval_type=item.get("approval_type", "sequential"),
                    is_scanned=bool(item.get("is_scanned", False)),
                    created_at=created_at,
                    retention_until=retention_until,
                )

                for s in item.get("signers", []):
                    doc.signers.append(Signer(
                        order_index=int(s.get("order_index", 0)),
                        full_name=str(s.get("full_name", "")),
                        position=str(s.get("position", "")),
                        status=SignerStatus.WAITING,
                    ))

                for i, a in enumerate(item.get("approvers", [])):
                    doc.approvers.append(Approver(
                        order_index=int(a.get("order_index", i)),
                        user_id=int(a["user_id"]) if a.get("user_id") else None,
                        full_name=str(a.get("full_name", "")),
                        position=str(a.get("position", "")),
                        status=ApproverStatus.WAITING,
                    ))

                session.add(doc)
                session.flush()
                _audit(
                    session, doc,
                    "imported",
                    actor=current_user.get("name", ""),
                    detail=f"відновлено з бекапу: {doc.title}",
                )
                imported += 1

            except Exception as exc:
                errors.append(f"{doc_id}: {exc}")

        session.commit()

    return {"imported": imported, "skipped": skipped, "errors": errors}


@router.get("/documents/{doc_id}")
def get_document(doc_id: str) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        return _doc_to_dict(doc)


@router.delete("/documents/{doc_id}")
def delete_document(doc_id: str) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        session.delete(doc)
        session.commit()
        return {"deleted": doc_id}


@router.put("/documents/{doc_id}")
def edit_document(doc_id: str, payload: dict = Body(...)) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.status != DocStatus.DRAFT:
            raise HTTPException(409, "редагування лише у статусі DRAFT")
        doc.title = str(payload.get("title", doc.title))
        doc.fmt = str(payload.get("fmt", doc.fmt))
        if "journal_id" in payload:
            doc.journal_id = int(payload["journal_id"]) if payload["journal_id"] else None
        if "approval_type" in payload:
            doc.approval_type = str(payload["approval_type"])
        if "approvers" in payload:
            for a in doc.approvers:
                session.delete(a)
            session.flush()
            for i, a in enumerate(payload["approvers"]):
                doc.approvers.append(
                    Approver(
                        order_index=i,
                        user_id=int(a["user_id"]) if a.get("user_id") else None,
                        full_name=str(a.get("full_name", "")),
                        position=str(a.get("position", "")),
                        status=ApproverStatus.WAITING
                    )
                )
        merged = bridge.content_from_json(doc.content_json)
        merged.update(payload)
        doc.content_json = bridge.content_to_json(merged)
        _audit(session, doc, "edited")
        session.commit()
        return _doc_to_dict(doc)


@router.post("/documents/{doc_id}/generate")
def generate_document(doc_id: str) -> dict:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        if doc.is_scanned:
            raise HTTPException(
                409,
                "документ є скан-копією — генерація з полів недоступна "
                "(оригіналом є завантажений скан, його лишень підписують)",
            )
        payload = bridge.content_from_json(doc.content_json)
        if not payload.get("body"):
            raise HTTPException(400, "текст документа (body) не може бути порожнім")
        if not payload.get("org_name", "").strip():
            raise HTTPException(400, "найменування організації (org_name) не може бути порожнім")
        if not str(payload.get("date_text", "")).strip():
            from portal import registry
            payload["date_text"] = registry.format_ua_date(
                dt.datetime.now(dt.timezone.utc).date()
            )
        with tempfile.NamedTemporaryFile(suffix=f".{doc.fmt}", delete=False) as tmp:
            dest = tmp.name
        try:
            out = bridge.generate(payload, doc.fmt, dest)
            with open(out["path"], "rb") as fh:
                doc.rendered = fh.read()
            doc.conformance_json = json.dumps(out["report"], ensure_ascii=False)
        finally:
            for p in (dest, dest + f".{doc.fmt}"):
                if os.path.exists(p):
                    os.remove(p)
        _audit(session, doc, "generated",
               detail=f"conforms={out['report'] and out['report']['conforms']}")
        session.commit()
        return {"doc_id": doc_id, "report": out["report"], "pdfa": out.get("pdfa")}


@router.get("/documents/{doc_id}/download")
def download_document(doc_id: str) -> Response:
    with SessionLocal() as session:
        doc = _load(session, doc_id)
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


@router.get("/documents/archive/export")
def export_archive(
    days: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> Response:
    """Експортувати архів документів (ZIP) за вказаний період або за весь час."""
    with SessionLocal() as session:
        query = session.query(Document)
        
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
            for d in docs:
                content = d.asice or d.rendered_marked or d.rendered
                if not content:
                    continue
                ext = "asice" if d.asice else d.fmt
                filename = f"{d.doc_id}.{ext}"
                zip_file.writestr(filename, content)

            meta_list = [_doc_to_dict(d) for d in docs]
            meta_json = json.dumps(meta_list, ensure_ascii=False, indent=2)
            zip_file.writestr("metadata.json", meta_json.encode("utf-8"))

        zip_buffer.seek(0)

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

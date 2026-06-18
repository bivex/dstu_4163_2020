from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import func
from portal.db import Document, Folder, SessionLocal
from portal.auth import _current_user
from portal.helpers import _load, _doc_to_dict, _folder_to_dict, _audit

router = APIRouter(tags=["folders"])


@router.get("/folders")
def list_folders(current_user: dict = Depends(_current_user)) -> dict:
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


@router.post("/folders")
def create_folder(
    payload: dict = Body(...), current_user: dict = Depends(_current_user)
) -> dict:
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


@router.put("/folders/{folder_id}")
def rename_folder(
    folder_id: int,
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
) -> dict:
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


@router.delete("/folders/{folder_id}")
def delete_folder(
    folder_id: int, current_user: dict = Depends(_current_user)
) -> dict:
    with SessionLocal() as session:
        folder = session.get(Folder, folder_id)
        if folder is None:
            raise HTTPException(404, f"папку {folder_id} не знайдено")
        for doc in session.query(Document).filter_by(folder_id=folder_id).all():
            doc.folder_id = None
        session.delete(folder)
        session.commit()
        return {"deleted": folder_id}


@router.post("/documents/{doc_id}/folder")
def set_document_folder(
    doc_id: str,
    payload: dict = Body(...),
    current_user: dict = Depends(_current_user),
) -> dict:
    # Переміщення в папку — це організаційна мітка (folder_id), вона не чіпає
    # ні контент документа, ні підписи/ASiC-E. Тому не лочимо за статусом:
    # підписаний документ можна перемістити в архівну папку без ризику.
    with SessionLocal() as session:
        doc = _load(session, doc_id)
        folder_id = payload.get("folder_id")
        if folder_id is None:
            doc.folder_id = None
            _audit(session, doc, "folder_cleared", actor=current_user.get("name", ""))
        else:
            folder = session.get(Folder, int(folder_id))
            if folder is None:
                raise HTTPException(404, f"папку {folder_id} не знайдено")
            doc.folder_id = folder.id
            _audit(
                session, doc, "folder_set",
                actor=current_user.get("name", ""),
                detail=f"folder={folder.name}",
            )
        session.commit()
        return _doc_to_dict(doc)

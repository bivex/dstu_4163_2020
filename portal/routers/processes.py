import json
from fastapi import APIRouter, Body, Depends, HTTPException
from portal.db import SessionLocal, Process
from portal.auth import _current_user

router = APIRouter(tags=["processes"])


def _process_to_dict(p: Process) -> dict:
    try:
        graph = json.loads(p.graph_json) if p.graph_json else {"nodes": [], "edges": []}
    except (ValueError, TypeError):
        graph = {"nodes": [], "edges": []}
    return {
        "id": p.id,
        "name": p.name,
        "description": p.description or "",
        "graph": graph,
        "is_builtin": bool(p.is_builtin),
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
    }


def _validate_graph(graph: dict) -> str:
    """Перевірити мінімальну коректність BPMN-lite графа, повернути JSON-рядок."""
    if not isinstance(graph, dict):
        raise HTTPException(400, "graph має бути об'єктом {nodes, edges}")
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise HTTPException(400, "nodes та edges мають бути списками")
    valid_types = {"start", "task", "gateway", "end"}
    ids = set()
    for n in nodes:
        if not isinstance(n, dict) or "id" not in n:
            raise HTTPException(400, "кожен вузол потребує id")
        if n.get("type") not in valid_types:
            raise HTTPException(400, f"невідомий тип вузла: {n.get('type')}")
        ids.add(n["id"])
    for e in edges:
        if not isinstance(e, dict) or "from" not in e or "to" not in e:
            raise HTTPException(400, "кожен зв'язок потребує from та to")
        if e["from"] not in ids or e["to"] not in ids:
            raise HTTPException(400, "зв'язок посилається на неіснуючий вузол")
    return json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)


@router.get("/processes")
def list_processes(current_user: dict = Depends(_current_user)) -> dict:
    with SessionLocal() as session:
        items = session.query(Process).order_by(Process.is_builtin.desc(), Process.name).all()
        return {"processes": [_process_to_dict(p) for p in items]}


@router.get("/processes/{proc_id}")
def get_process(proc_id: int, current_user: dict = Depends(_current_user)) -> dict:
    with SessionLocal() as session:
        p = session.get(Process, proc_id)
        if p is None:
            raise HTTPException(404, f"процес {proc_id} не знайдено")
        return _process_to_dict(p)


@router.post("/processes")
def create_process(payload: dict = Body(...), current_user: dict = Depends(_current_user)) -> dict:
    name = str(payload.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "Назва процесу обов'язкова")
    graph_json = _validate_graph(payload.get("graph", {"nodes": [], "edges": []}))
    with SessionLocal() as session:
        p = Process(
            name=name,
            description=str(payload.get("description", "")).strip(),
            graph_json=graph_json,
            is_builtin=False,
        )
        session.add(p)
        session.commit()
        session.refresh(p)
        return _process_to_dict(p)


@router.put("/processes/{proc_id}")
def update_process(proc_id: int, payload: dict = Body(...), current_user: dict = Depends(_current_user)) -> dict:
    with SessionLocal() as session:
        p = session.get(Process, proc_id)
        if p is None:
            raise HTTPException(404, f"процес {proc_id} не знайдено")
        if "name" in payload:
            name = str(payload["name"]).strip()
            if not name:
                raise HTTPException(400, "Назва процесу не може бути порожньою")
            p.name = name
        if "description" in payload:
            p.description = str(payload["description"]).strip()
        if "graph" in payload:
            p.graph_json = _validate_graph(payload["graph"])
        session.commit()
        session.refresh(p)
        return _process_to_dict(p)


@router.delete("/processes/{proc_id}")
def delete_process(proc_id: int, current_user: dict = Depends(_current_user)) -> dict:
    with SessionLocal() as session:
        p = session.get(Process, proc_id)
        if p is None:
            raise HTTPException(404, f"процес {proc_id} не знайдено")
        if p.is_builtin:
            raise HTTPException(400, "Вбудований процес не можна видалити (можна дублювати та змінити копію)")
        session.delete(p)
        session.commit()
        return {"deleted": proc_id}

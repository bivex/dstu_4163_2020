"""Портал підписання та редагування документів — FastAPI застосунок.

Бекенд поверх доменного ядра dilovod4 (ДСТУ 4163 + 7 НПА).
"""

from __future__ import annotations

import os
import time
import urllib.request
import json
import base64
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import auth, documents, signing, folders, registry, counterparties, delivery, journals, approvals, resolutions, tasks, users, processes

_cas_cache: dict = {"body": None, "ts": 0.0}


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Портал підписання документів (ДСТУ 4163 + НПА)",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("PORTAL_CORS", "http://localhost:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


def _cors_origin(request: Request) -> str:
    return request.headers.get("origin", "*")


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
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
    return {"status": "ok", "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


# Реєстрація модульних роутерів
app.include_router(auth.router)
app.include_router(documents.router)
app.include_router(signing.router)
app.include_router(folders.router)
app.include_router(registry.router)
app.include_router(counterparties.router)
app.include_router(delivery.router)
app.include_router(journals.router)
app.include_router(approvals.router)
app.include_router(resolutions.router)
app.include_router(tasks.router)
app.include_router(users.router)
app.include_router(processes.router)


# --- Proxy Handler for KEP (OCSP/TSP requests) ---
@app.api_route("/signdata/ProxyHandler.php", methods=["GET", "POST"])
async def proxy_handler(request: Request, address: str = Query(...)) -> Response:
    body_bytes = await request.body()
    
    if request.method == "POST":
        try:
            req_data = base64.b64decode(body_bytes)
        except Exception:
            raise HTTPException(400, "Invalid base64 payload")
    else:
        req_data = b""

    headers = {}
    path = address.lower()
    if "/ocsp" in path:
        headers["Content-Type"] = "application/ocsp-request"
    elif "/tsp" in path:
        headers["Content-Type"] = "application/timestamp-query"
        
    import httpx
    async with httpx.AsyncClient(verify=False) as client:
        try:
            if request.method == "POST":
                resp = await client.post(address, content=req_data, headers=headers, timeout=15.0)
            else:
                resp = await client.get(address, headers=headers, timeout=15.0)
        except Exception as e:
            raise HTTPException(502, f"Failed to connect to CA server: {e}")
            
    resp_b64 = base64.b64encode(resp.content).decode("ascii")
    return Response(
        content=resp_b64,
        media_type="X-user/base64-data",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate",
            "Access-Control-Allow-Origin": _cors_origin(request),
            "Access-Control-Allow-Credentials": "true",
        }
    )


# --- статика: фронт + бібліотека EUSign ---
_HERE = Path(__file__).resolve().parent
# пріоритет: NUXT_OUTPUT (env, ставить launcher/збірка), потім dev-шлях до
# згенерованого Nuxt-виводу, потім fallback на portal/web/ (стара статика).
_WEB_DIR = Path(os.environ.get("NUXT_OUTPUT",
               _HERE.parent / "external" / "dms-dir" / ".output" / "public"))
if not _WEB_DIR.is_dir():
    _WEB_DIR = _HERE / "web"
_EUSIGN_DIR = _HERE.parent / "external" / "EUSignES6"


@app.get("/", response_model=None)
def _root():
    # Якщо є Nuxt-статика — віддаємо SPA-shell index.html (роутер сам редиректне
    # на /login). Інакше — fallback на API-документацію.
    index = _WEB_DIR / "index.html"
    if index.is_file():
        return FileResponse(str(index))
    return RedirectResponse(url="/docs")


@app.get("/favicon.ico")
def _favicon() -> Response:
    ico = _EUSIGN_DIR / "favicon.ico"
    if ico.is_file():
        return Response(content=ico.read_bytes(), media_type="image/x-icon")
    return Response(status_code=204)


_CAS_URL = os.environ.get("PORTAL_CAS_URL", "https://iit.com.ua/download/productfiles/CAs.json")
_CAS_TTL = int(os.environ.get("PORTAL_CAS_TTL", "3600"))  # секунд
_CAS_FALLBACK = _HERE.parent / "src" / "dilovod4" / "infrastructure" / "data" / "CAs.json"


@app.get("/signdata/CAs.json")
def cas_json() -> Response:
    now = time.time()
    if _cas_cache["body"] is not None and now - _cas_cache["ts"] < _CAS_TTL:
        return Response(content=_cas_cache["body"], media_type="application/json")
    try:
        req = urllib.request.Request(_CAS_URL, headers={"User-Agent": "dilovod4-portal"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read()
        if not isinstance(json.loads(body), list):
            raise ValueError("CAs.json не є переліком")
        _cas_cache.update(body=body, ts=now)
        return Response(content=body, media_type="application/json")
    except Exception:
        if _CAS_FALLBACK.is_file():
            return Response(content=_CAS_FALLBACK.read_bytes(), media_type="application/json")
        raise HTTPException(502, "не вдалося отримати перелік КНЕДП")


if _EUSIGN_DIR.is_dir():
    app.mount("/eusign", StaticFiles(directory=str(_EUSIGN_DIR)), name="eusign")
    # Аліас /api/eusign для статичної збірки Nuxt: у dev фронт йде через Nuxt-proxy
    # /api/eusign/** → /eusign/**, але в packaged-app (Nuxt як статика) проксі
    # нема, тож маунтим той самий каталог під другим шляхом.
    app.mount("/api/eusign", StaticFiles(directory=str(_EUSIGN_DIR)), name="eusign_api")
    _SIGNDATA = _EUSIGN_DIR / "signdata"
    if _SIGNDATA.is_dir():
        app.mount("/signdata", StaticFiles(directory=str(_SIGNDATA)), name="signdata")
if _WEB_DIR.is_dir():
    app.mount("/web", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")


# SPA catch-all: невідомі GET-шляхи (крім API/static) → index.html, щоб
# Vue-router взяв управління клієнтським роутингом (/login, /dashboard тощо).
# Реєструється ОСТАННІМ — після всіх API-роутів і mount-ів, інакше перехопить їх.
if (_WEB_DIR / "index.html").is_file():
    _SPA_INDEX = _WEB_DIR / "index.html"

    @app.get("/{full_path:path}", response_model=None, include_in_schema=False)
    def _spa_fallback(full_path: str):
        # Пропускаємо явно API/static-префікси (вже оброблені вище) — 404 як було.
        if (full_path.startswith(("auth/", "documents", "users", "folders",
                                   "counterparties", "registry", "journals",
                                   "processes", "tasks"))
                or full_path in ("openapi.json", "docs", "redoc", "health")):
            raise HTTPException(404)
        # Якщо шлях збігає з реальним файлом у статиці — віддаємо файл (assets, _nuxt).
        candidate = _WEB_DIR / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        # Інакше — SPA-shell, роутер розбереться на клієнті.
        return FileResponse(str(_SPA_INDEX))

"""Портал підписання та редагування документів — FastAPI застосунок.

Бекенд поверх доменного ядра dilovod4 (ДСТУ 4163 + 7 НПА).
"""

from __future__ import annotations

import os
import time
import urllib.request
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .db import init_db
from .routers import auth, documents, signing, folders, registry

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


# --- статика: фронт + бібліотека EUSign ---
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
    _SIGNDATA = _EUSIGN_DIR / "signdata"
    if _SIGNDATA.is_dir():
        app.mount("/signdata", StaticFiles(directory=str(_SIGNDATA)), name="signdata")
if _WEB_DIR.is_dir():
    app.mount("/web", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")

"""Лаунчер packaged macOS-додатка «Діловод».

Робить 4 речі:
1. Готує оточення (БД-каталог, env-змінні для portal.main та UAPKI).
2. Піднімає uvicorn (portal.main:app) на 127.0.0.1:8000 у фоновому потоці.
3. Чекає /health і відкриває браузер на http://localhost:8000.
4. Trap SIGTERM/SIGINT → graceful shutdown uvicorn.

Всередині PyInstaller bundle шляхи розраховуються від sys._MEIPASS
(каталог розпакування onefile/onedir). datas у spec кладе пласко:
  portal/, src/dilovod4/, external/EUSignES6/, external/UAPKI/.../out/, web/
"""
from __future__ import annotations

import os
import signal
import sys
import threading
import time
import webbrowser
from pathlib import Path

# Корінь розпакованого bundle (PyInstaller onedir/onefile).
# При звичайному запуск (не з .app) — каталог скрипта, для розробки/дебагу.
_BUNDLE_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

# --- 1. Оточення ---
_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "dms-dir"
_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)

_DB_PATH = _SUPPORT_DIR / "portal.db"

# Шляхи всередині bundle (мають співпадати з datas у pyinstaller.spec).
_WEB_DIR = _BUNDLE_ROOT / "web"
_UAPKI_DIR = _BUNDLE_ROOT / "external" / "UAPKI" / "library" / "build" / "out"

os.environ.setdefault("PORTAL_DATABASE_URL", f"sqlite:///{_DB_PATH}")
os.environ.setdefault("NUXT_OUTPUT", str(_WEB_DIR))
# КРИТИЧНО: uapki.py шукає DILOVOD4_UAPKI_LIB, а дефолт parents[3]/.../build/out
# не працює всередині bundle — вказуємо явно на bundled-каталог з dylib+symlinks.
if _UAPKI_DIR.is_dir():
    os.environ.setdefault("DILOVOD4_UAPKI_LIB", str(_UAPKI_DIR / "libuapki.dylib"))
# Робимо importable portal.* та src.dilovod4.* всередині bundle.
sys.path.insert(0, str(_BUNDLE_ROOT))
sys.path.insert(0, str(_BUNDLE_ROOT / "src"))

# Логи -> ~/Library/Logs/Діловод/ (опц., для діагностики користувачем).
_LOG_DIR = Path.home() / "Library" / "Logs" / "Діловод"
try:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    _LOG_DIR = None


def _wait_for_health(timeout: float = 30.0) -> bool:
    """Poll /health поки сервер не стане готовим (або timeout)."""
    import urllib.request
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=1) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(0.3)
    return False


def main() -> None:
    import uvicorn
    from portal.main import app  # noqa: F401  (імпорт ініціалізує додаток)

    config = uvicorn.Config(
        app, host="127.0.0.1", port=8000, log_level="info",
        # без reload/watchfiles у packaged-додатку
    )
    server = uvicorn.Server(config)

    # uvicorn у фоновому потоці, головний потік — цикл подій/сигнали.
    server_thread = threading.Thread(target=server.run, daemon=True)

    def _shutdown(*_):
        server.should_exit = True

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    server_thread.start()

    if _wait_for_health():
        webbrowser.open("http://localhost:8000")
    else:
        # Сервер піднімається довго — відкриваємо anyhow, користувач дочекається.
        webbrowser.open("http://localhost:8000")

    # Блокуємо, поки сервер живий (додаток «відкритий»).
    try:
        while server_thread.is_alive():
            server_thread.join(timeout=1.0)
    except KeyboardInterrupt:
        server.should_exit = True


if __name__ == "__main__":
    main()

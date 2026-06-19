# План: self-contained macOS `.app` + DMG для Діловод (DSTU 4163)

> Архітектура: **один процес — FastAPI віддає і статику Nuxt, і API, і EUSign, і БД** на одному порту `:8000`. PyInstaller збирає все в `.app`, потім `hdiutil`/`create-dmg` → `.dmg`.

## Мета

Самодостатній macOS-додаток (`.app` bundle): запускається з Finder-іконки, піднімає локальний FastAPI на `127.0.0.1:8000`, відкриває браузер на `http://localhost:8000`. БД — `~/Library/Application Support/dms-dir/portal.db` (не зникає при видаленні `.app`). Без Docker, без встановленого Python/Bun на машині користувача.

---

## Етап 1 — Nuxt у статичний режим

**Файли:** `external/dms-dir/nuxt.config.ts`, `external/dms-dir/package.json`

Зараз Nuxt-фронт — фактично SPA: реальні маршрути `/login` і `/dashboard` мають `ssr: false` (routeRules), усі дані йдуть через `$fetch(NUXT_PUBLIC_API_BASE)` (за замовч. `http://localhost:8000`).

1. **`nitro.preset` не заданий** — додати `nitro: { preset: 'static' }` (еквівалент `nuxt generate`).
2. **Скрипта `generate` немає** в package.json — додати `"generate": "nuxt generate"`. Після цього `bun run generate` → `.output/public/` (SPA-shell + assets).
3. **`@nuxt/content` та `nuxt-og-image` прибрані з `modules`**, але **ще є в `package.json` deps** — прибрати з dependencies (мертвий ваг).

**Path-mismatch EUSign (важливо):** Nitro-проксі `/api/eusign/**` → `${backend}/eusign/**` (nuxt.config.ts) **зникає в статичній збірці**. Фронт грузить `/api/eusign/modules/euscpfactory.js` (`useEuSign.ts`, `useKep.ts`). Рішення: **на бекенді додати mount `/api/eusign`** (Етап 2), фронт не чіпати. `/signdata/**` вже співпадає з бекенд-mount — ок.

**Результат:** `external/dms-dir/.output/public/` — чисті статичні файли (перезбрати свіжі; поточний `.output/` застарілий — містить blog/pricing/og від SaaS template).

---

## Етап 2 — FastAPI віддає фронт + EUSign-аліас

**Файл:** `portal/main.py` (~рядки 135-184)

Зараз: `/` → RedirectResponse `/docs`; `/eusign`, `/signdata` mount `external/EUSignES6`; `/signdata/CAs.json` — окремий handler; `app.mount("/web", ...)` вказує на `portal/web/` (старий рукописний UI, не Nuxt).

Зміни:
1. **Перенаправити `_WEB_DIR` на Nuxt-вивід:**
   ```python
   _WEB_DIR = Path(os.environ.get("NUXT_OUTPUT",
       _HERE.parent / "external" / "dms-dir" / ".output" / "public"))
   if not _WEB_DIR.is_dir():
       _WEB_DIR = _HERE / "web"  # fallback на стару статику
   ```
2. **Root `/` → віддавати Nuxt `index.html`** (SPA-shell), а не Redirect на `/docs`. SPA-роутер сам редиректне на `/login`:
   ```python
   @app.get("/")
   def _root():
       return FileResponse(_WEB_DIR / "index.html")
   ```
3. **Додати аліас `/api/eusign`** (для статичної збірки):
   ```python
   if _EUSIGN_DIR.is_dir():
       app.mount("/eusign", StaticFiles(directory=str(_EUSIGN_DIR)), name="eusign")
       app.mount("/api/eusign", StaticFiles(directory=str(_EUSIGN_DIR)), name="eusign_api")
   ```
4. **CORS:** при same-origin (бек віддає і SPA, і API) — не потрібен. Залишити `PORTAL_CORS` env для dev-режиму коли фронт на :3000.

**Результат:** FastAPI на :8000 віддає фронт (/), API, EUSign (/eusign + /api/eusign), CAs.json (/signdata/CAs.json).

---

## Етап 3 — БД у macOS-локацію

**Файл:** `portal/db.py:35` (зараз `DATABASE_URL = os.environ.get("PORTAL_DATABASE_URL", "sqlite:////data/portal.db")`)

Дефолт `/data/portal.db` — Docker-шлях, на macOS не працює. Зміна:
```python
def _default_db_path() -> str:
    """На macOS — ~/Library/Application Support/dms-dir/portal.db;
    на інших — /data/portal.db (Docker)."""
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "dms-dir"
        d.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{d / 'portal.db'}"
    return "sqlite:////data/portal.db"

DATABASE_URL = os.environ.get("PORTAL_DATABASE_URL") or _default_db_path()
```
Лаунчер (Етап 4) також явно ставить `PORTAL_DATABASE_URL` — подвійний захист.

---

## Етап 4 — PyInstaller: launcher + spec

**Нові файли:** `packaging/launcher.py`, `packaging/pyinstaller.spec`

### launcher.py
- Створює `~/Library/Application Support/dms-dir/` (idempotent).
- Виставляє env: `PORTAL_DATABASE_URL`, `NUXT_OUTPUT` (на `sys._MEIPASS/web`), **`DILOVOD4_UAPKI_LIB`** (на bundled-шлях до dylib — КРИТИЧНО, бо `uapki.py` шукає саме цей env, а не `UAPKI_LIB`; дефолт `parents[3]/external/UAPKI/library/build/out` НЕ працює всередині bundle), `PYTHONPATH=sys._MEIPASS`.
- Запускає `uvicorn.run(portal.main:app, host="127.0.0.1", port=8000)` у фоновому потоці.
- Чекає готовності (poll `http://127.0.0.1:8000/health`), відкриває `webbrowser.open("http://localhost:8000")`.
- Trap `SIGTERM/SIGINT` → graceful shutdown uvicorn.

### pyinstaller.spec
`datas` (актуальні шляхи):
```python
datas=[
    ('portal', 'portal'),
    ('src/dilovod4', 'src/dilovod4'),
    ('external/EUSignES6', 'external/EUSignES6'),
    ('external/UAPKI/library/build/out', 'external/UAPKI/library/build/out'),  # ← реальний шлях
    ('external/dms-dir/.output/public', 'web'),  # ← Nuxt статика
],
hiddenimports=[
    'uvicorn.logging', 'uvicorn.protocols', 'uvicorn.lifespan.on',
    'portal.db', 'portal.routers.*', 'portal.scan_ingest', 'portal.domain_bridge',
    'src.dilovod4.infrastructure.uapki', 'src.dilovod4.infrastructure.pdf_writer',
    'src.dilovod4.infrastructure.docx_writer', 'httpx', 'multipart',
],
```
- `BUNDLE(..., name='Dilovod.app', icon='packaging/AppIcon.icns', console=False)`.

**UAPKI-нюанс (важливо):** `uapki.py` вручну `ctypes.CDLL(libuapkic/libuapkif/libcm-pkcs12, mode=RTLD_GLOBAL)` — усі 4 dylibs мають бути в одному каталозі з symlink-ами (формат `build/out`). Лаунчер ставить `DILOVOD4_UAPKI_LIB=<bundle>/external/UAPKI/library/build/out/libuapki.dylib`.

---

## Етап 5 — Info.plist + іконка

**Нові файли:** `packaging/Info.plist.template`, `packaging/AppIcon.icns`

- `CFBundleIdentifier`: `ua.dilovod.dms-dir`, `CFBundleName`: `Діловод`, `LSUIElement: 0` (Dock-іконка).
- Іконка: PNG 1024 → `iconutil -c icns`. Future-work: справжній бренд-арт.

---

## Етап 6 — build.sh

**Новий файл:** `packaging/build.sh`
```bash
#!/usr/bin/env bash
set -euo pipefail
# 1. Nuxt статика (свіжа)
(cd external/dms-dir && bun install && bun run generate)
# 2. Копія статики для PyInstaller
rsync -aL --delete external/dms-dir/.output/public/ portal/web/
# 3. (опц.) UAPKI macos-arm64 білд — якщо symlink-дерево не закомічено
#    bash external/UAPKI/library/build-uapki.sh macos-arm64
# 4. PyInstaller
pyinstaller packaging/pyinstaller.spec --clean --noconfirm
# → dist/Dilovod.app
```

---

## Етап 7 — DMG

**Новий файл:** `packaging/build-dmg.sh`
- Дефолт: `hdiutil` (нативний, без залежностей):
  ```bash
  hdiutil create -volname "Діловод" -srcfolder dist/Dilovod.app \
    -ov -format UDZO -imagekey zlib-level=9 dist/Діловод.dmg
  ```
- Опц.: `create-dmg` (через `npx`) — дає drag-n-drop вікно з `/Applications` link.

---

## Етап 8 — Нотаризація (опц., для дистрибуції поза dev)

`codesign --deep --force ...` → `hdiutil` → `xcrun notarytool submit --wait` → `xcrun stapler staple`. Без неї — «неперевірений розробник» → System Settings → Open Anyway. Не блокує MVP.

---

## Структура після
```
packaging/{launcher.py, pyinstaller.spec, build.sh, build-dmg.sh, Info.plist.template, AppIcon.icns}
dist/{Dilovod.app, Діловод.dmg}
```

## Виправлення неточностей оригінального плану (для історії)
| План говорив | Реальність | Виправлено в |
|---|---|---|
| `external/UAPKI/macOS/lib/` + `build-macos.sh` | `external/UAPKI/library/build/out/` (dylibs+symlinks), `library/build-uapki.sh` | Етап 4 datas |
| DB у `main.py` env | У `portal/db.py:35` | Етап 3 |
| env `UAPKI_LIB` | `DILOVOD4_UAPKI_LIB` (`uapki.py`) | Етап 4 launcher |
| `/` → `/web/` | Зараз → `/docs`; треба → Nuxt index.html | Етап 2 |
| `/web` mount на Nuxt output | Зараз на `portal/web/` (старий UI) | Етап 2 |
| dep-листа без httpx/python-multipart | httpx — runtime (main.py); python-multipart — форми | Етап 4 |
| `nitro.preset: static` вже є | Немає; додати + `generate` script | Етап 1 |

## Що НЕ входить (намірено)
- Electron/Tauri нативне вікно (узгоджено: один процес FastAPI + браузер).
- Автооновлення Sparkle.
- Перенос існуючої Docker-БД (future-work: import-json endpoint вже є).

## Ризики
- **UAPKI dylib symlink-и** в PyInstaller bundle — перевірити що `build/out` зберігає symlink-формат; якщо ні, лаунчер резолвить конкретний `libuapki.2.0.16.dylib`.
- **reportlab шрифти** на macOS — Liberation може бути відсутня; fallback на системну Times New Roman (вже є `resolve_times_new_roman`).
- **Архітектура**: білд і target — однакова (arm64/x86_64); `uvloop`/`httptools` нативні.
- **Перший запуск**: macOS quarantine на `.app` з інтернету — потрібна нотаризація (Етап 8) або ручне «Open Anyway».

## Поточна версія (статус)

Версія 0.1.0 (зараз працює через Docker Compose: FastAPI :8000 + Nuxt :3000).
Цей план переводить у standalone `.app` без Docker.

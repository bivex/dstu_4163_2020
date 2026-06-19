# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec для macOS .app «Діловод».

Збирає в один .app bundle:
  - portal/ (FastAPI)
  - src/dilovod4/ (доменне ядро)
  - external/EUSignES6/ (WASM/JS для клієнтського КЕП)
  - external/UAPKI/library/build/out/ (macOS dylibs + symlinks)
  - external/dms-dir/.output/public/ → web/ (Nuxt статика)

Перед збіркою: запустити packaging/build.sh (генерує Nuxt-статику в portal/web/).
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
# SPECPATH = каталог spec-файлу (packaging/). Корінь проєкту — його батько.
# Усі шляхи в datas/Analysis PyInstaller резолвить відносно cwd запуску, тож
# build.sh має запускати pyinstaller з кореня проєкту (так і робить).
_project_root = Path(SPECPATH).resolve().parent if 'SPECPATH' in globals() else Path.cwd().resolve()

# --- datas: (source, dest_relative_to_bundle_root) ---
datas = [
    (str(_project_root / 'portal'), 'portal'),
    (str(_project_root / 'src' / 'dilovod4'), 'src/dilovod4'),
    (str(_project_root / 'external' / 'EUSignES6'), 'external/EUSignES6'),
    (str(_project_root / 'external' / 'UAPKI' / 'library' / 'build' / 'out'),
     'external/UAPKI/library/build/out'),
    # Nuxt статика: пріоритет — portal/web/ (копія від build.sh), fallback на dms-dir output
    (str(_project_root / 'portal' / 'web' if (_project_root / 'portal' / 'web').is_dir()
      else _project_root / 'external' / 'dms-dir' / '.output' / 'public'), 'web'),
]

# --- hiddenimports: усе що PyInstaller не бачить статично ---
hiddenimports = [
    # uvicorn internals
    'uvicorn.logging', 'uvicorn.protocols', 'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto', 'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on',
    # портал
    'portal.db', 'portal.scan_ingest', 'portal.domain_bridge', 'portal.helpers',
    # роутери (збираємо всі)
    *collect_submodules('portal.routers'),
    # доменне ядро
    'dilovod4.infrastructure.uapki', 'dilovod4.infrastructure.pdf_writer',
    'dilovod4.infrastructure.docx_writer', 'dilovod4.infrastructure.fonts',
    # runtime-deps що тягнуться динамічно
    'httpx', 'multipart', 'anyio', 'h11',
]

# rtld-preload UAPKI dylibs при старті (щоб ctypes.CDLL знайшов їх у bundle).
# Файли .dylib мають потрапити в bundle через datas (вище), а не через binaries,
# бо ми не знаємо точної архітектури на етапі написання spec.

a = Analysis(
    # PyInstaller резолвить шлях скрипта відносно SPECPATH (каталог spec-файлу =
    # packaging/). launcher.py лежить поруч зі spec — вказуємо ім'я напряму.
    ['launcher.py'],
    pathex=[str(_project_root), str(_project_root / 'src')],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest', 'tests'],
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Dilovod',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # GUI-додаток, без вікна термінала
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='packaging/AppIcon.icns',  # розкоментувати коли буде іконка
)

app = BUNDLE(
    exe,
    a.binaries,
    a.datas,
    [],
    name='Діловод.app',
    appname='Діловод',
    logo='packaging/AppIcon.icns',  # опц., ігнорується якщо файлу нема
    info_plist={
        'CFBundleDisplayName': 'Діловод',
        'CFBundleIdentifier': 'ua.dilovod.dms-dir',
        'CFBundleName': 'Діловод',
        'CFBundleShortVersionString': '0.1.0',
        'CFBundleVersion': '1',
        'LSMinimumSystemVersion': '11.0',
        'LSUIElement': False,  # показувати в Dock
        'NSHighResolutionCapable': True,
        'NSAppTransportSecurity': {
            'NSAllowsLocalNetworking': True,  # дозволити http://localhost:8000
        },
    },
)

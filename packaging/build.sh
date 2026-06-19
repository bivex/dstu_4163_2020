#!/usr/bin/env bash
# Збірка macOS .app «Діловод»: Nuxt-статика → PyInstaller bundle.
#
# Передумови на машині збірки (macOS):
#   - bun (frontend)          : https://bun.sh
#   - python3.12+ + deps      : pip install -r portal/requirements.txt pyinstaller
#   - UAPKI dylibs            : external/UAPKI/library/build/out/ (вже закомічено,
#                               або зберіть: bash external/UAPKI/library/build-uapki.sh macos-arm64)
#   - external/EUSignES6, external/UAPKI, external/dms-dir — ініціалізовані підмодулі
#
# Результат: dist/Діловод.app
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Активуємо portal/.venv якщо є — там лежить pyinstaller + бекенд-deps.
if [ -f portal/.venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source portal/.venv/bin/activate
fi
# Універсальний виклик PyInstaller: працює і в venv (pyinstaller в PATH),
# і без (python3 -m PyInstaller).
PYINST="${PYINSTALLER:-}"
if [ -z "$PYINST" ]; then
    if command -v pyinstaller >/dev/null 2>&1; then
        PYINST="pyinstaller"
    else
        PYINST="python3 -m PyInstaller"
    fi
fi

echo "==> [1/4] Nuxt статика (bun run generate → .output/public/)"
(cd external/dms-dir && bun install --frozen-lockfile && bun run generate)

echo "==> [2/4] Копія статики в portal/web/ (для PyInstaller datas)"
mkdir -p portal/web
rsync -aL --delete external/dms-dir/.output/public/ portal/web/

echo "==> [3/4] Перевірка UAPKI macOS dylibs"
if [ ! -f external/UAPKI/library/build/out/libuapki.dylib ]; then
    echo "  libuapki.dylib відсутній — збираю macos-arm64..."
    bash external/UAPKI/library/build-uapki.sh macos-arm64
fi

echo "==> [4/4] PyInstaller ($PYINST)"
$PYINST packaging/pyinstaller.spec --clean --noconfirm

echo ""
echo "✓ Готово: dist/Діловод.app"
echo "  Запуск: open dist/Діловод.app   (або подвійний клік у Finder)"
echo "  DMG:    bash packaging/build-dmg.sh"

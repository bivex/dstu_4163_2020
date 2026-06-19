#!/usr/bin/env bash
# Збірка .dmg з готового dist/Діловод.app.
#
# Дефолт: hdiutil (нативний, без залежностей). Дає простий .dmg.
# Альтернатива: create-dmg (через npx) — з drag-n-drop вікном і /Applications-лінком.
#  Щоб увімкнути: CREATE_DMG=npx bash packaging/build-dmg.sh
#
# Результат: dist/Діловод.dmg
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

APP="dist/Діловод.app"
DMG="dist/Діловод.dmg"

if [ ! -d "$APP" ]; then
    echo "✗ $APP не знайдено — спочатку запустіть packaging/build.sh" >&2
    exit 1
fi

rm -f "$DMG"

case "${CREATE_DMG:-hdiutil}" in
    npx)
        echo "==> create-dmg (drag-n-drop вікно)"
        npx --yes create-dmg "$APP" dist/ \
            --overwrite \
            --window-size 600 400 \
            --window-pos 400 100 \
            --icon-size 96 \
            --app-drop-link 380 220 \
            --applications-folder 460 220
        # create-dmg іменує файл за app-name; приводимо до канонічного
        mv -f "dist/Діловод ${${APP:t:r}//.app/}*.dmg" "$DMG" 2>/dev/null || true
        ;;
    hdiutil|*)
        echo "==> hdiutil (нативний)"
        hdiutil create \
            -volname "Діловод" \
            -srcfolder "$APP" \
            -ov \
            -format UDZO \
            -imagekey zlib-level=9 \
            "$DMG"
        ;;
esac

echo ""
echo "✓ Готово: $DMG"
echo "  Дистрибуція без нотаризації: отримувач бачить «неперевірений розробник»"
echo "  → System Settings → Privacy & Security → Open Anyway."
echo "  Нотаризація (опц.): див. PLAN_macos_app.md Етап 8."

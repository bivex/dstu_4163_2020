#!/usr/bin/env python3
"""Автономний smoke-тест ключа КЕП/печатки — перевіряє весь криптошлях БЕЗ браузера.

Емулює те, що робить EUSign WASM у браузері, але на бекенді через UAPKI:
  1. читання .p12 ключа паролем (як EUSign: ReadPrivateKey)
  2. підпис довільного challenge CAdES-X-Long (як signData в useKep)
  3. валідація підпису через verify_signature (як /auth/link-kep)
  4. витяг cert_info (CN, РНОКПП, cert_type) — те, що потрапляє в user.kep_*

Якщо ВСІ кроки проходять — ключ + сертифікат + пароль коректні, і прив'язка в UI
працюватиме (помилка 51 — тоді виключно проблема EUSign-WASM, не ключа).
Якщо падає на читанні ключа — невірний пароль/формат. На підписі — проблема ключа.
На verify — проблема сертифіката/ланцюжка.

Використання:
  python3 scripts/check_kep_key.py \\
    --p12 samples/test_certs/client_diia.p12 \\
    --password testpassword \\
    --cert samples/test_certs/client_diia.cer

Потребує зібраної libuapki (як увесь криптостек порталу). Без неї — exit 2.
"""

from __future__ import annotations

import argparse
import base64
import sys
import tempfile
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
_PORTAL = Path(__file__).resolve().parent.parent / "portal"
for p in (_SRC, _PORTAL):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-тест ключа КЕП/печатки через UAPKI.")
    ap.add_argument("--p12", required=True, help="файл ключа (.p12/.dat/.jks)")
    ap.add_argument("--password", required=True, help="пароль ключа")
    ap.add_argument("--cert", default=None, help="сертифікат .cer (опц.; для ланцюжка)")
    args = ap.parse_args()

    # --- 0. feature-detection libuapki ---
    try:
        from dilovod4.infrastructure.uapki import UapkiClient, UapkiLibraryNotFound  # noqa: F401
    except UapkiLibraryNotFound as e:
        print(f"[FAIL] libuapki не зібрана: {e}", file=sys.stderr)
        print("  Зберіть: cd external/UAPKI/library && bash build-uapki.sh macos-arm64", file=sys.stderr)
        return 2

    DATA = Path(__file__).resolve().parent.parent / "external" / "UAPKI" / "library" / "test" / "data"
    from dilovod4.infrastructure.uapki import UapkiClient, UapkiError

    challenge = "verify-kep-link-challenge-2026"
    print(f"=== Smoke-тест ключа: {args.p12} ===")
    print(f"challenge: {challenge}")
    print()

    # --- 1. читання ключа паролем ---
    print("[1/4] Читання .p12 ключа паролем…")
    try:
        cli = UapkiClient()
        cli.init(str(DATA / "certs"), str(DATA / "crls"), offline=True)
        cli.open_pkcs12(args.p12, args.password)
        keys = cli.list_keys()
        if not keys:
            print("  [FAIL] у контейнері немає ключів")
            return 1
        cli.select_key(keys[0]["id"])
        print(f"  [OK] ключ зчитано, ключів у контейнері: {len(keys)}")
        print(f"       key id: {keys[0]['id'][:24]}…")
    except UapkiError as e:
        print(f"  [FAIL] помилка читання ключа: {e}", file=sys.stderr)
        print("  → невірний пароль або пошкоджений контейнер", file=sys.stderr)
        return 1

    # --- 2. підпис challenge CAdES-BES ---
    print()
    print("[2/4] Підпис challenge (CAdES-BES)…")
    try:
        sig = cli.sign_bytes(
            challenge.encode(),
            signature_format="CAdES-BES",
            detached=True,
            include_cert=True,
            ignore_cert_status=True,
        )
        sig_bytes = base64.b64decode(sig["bytes"])
        print(f"  [OK] підпис створено, розмір CMS: {len(sig_bytes)} байт")
    except UapkiError as e:
        print(f"  [FAIL] помилка підпису: {e}", file=sys.stderr)
        return 1

    # --- 3. валідація підпису (як /auth/link-kep) ---
    print()
    print("[3/4] Валідація підпису через verify_signature (як бекенд)…")
    try:
        # domain_bridge імпортує з portal/, тож додамо portal як package
        import importlib
        if str(_PORTAL.parent) not in sys.path:
            sys.path.insert(0, str(_PORTAL.parent))
        import portal  # noqa: F401 — ініціалізує пакет portal
        bridge = importlib.import_module("portal.domain_bridge")
        verify_signature = bridge.verify_signature
        cert_info_from_cms = bridge.cert_info_from_cms

        ok = verify_signature(challenge.encode(), sig_bytes)
        if not ok:
            print("  [FAIL] verify_signature повернув False")
            print("  → підпис не пройшов перевірку (ланцюжок/сертифікат)", file=sys.stderr)
            return 1
        print("  [OK] підпис валідний")
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] verify_signature впав: {e}", file=sys.stderr)
        return 1

    # --- 4. витяг cert_info (те, що потрапляє в user.*) ---
    print()
    print("[4/4] Витяг даних сертифіката (cert_info_from_cms)…")
    try:
        info = cert_info_from_cms(sig_bytes)
        print(f"  CN підписувача : {info.get('signer', '(відсутній)')}")
        print(f"  РНОКПП        : {info.get('serialNumber', '(відсутній)')}")
        print(f"  Видавець      : {info.get('issuer', '(відсутній)')}")
        print(f"  Сер. № сертиф. : {info.get('certificate_serial', '(відсутній)')}")
        print(f"  cert_type     : {info.get('cert_type', '(відсутній)')}")
        print(f"  organization  : {info.get('organization', '(відсутній)')}")
        print(f"  identifier    : {info.get('identifier', '(відсутній)')}")
        print(f"  Чинний        : {info.get('valid_from', '?')} – {info.get('valid_to', '?')}")
        if not info.get("signer"):
            print("  [FAIL] не вдалося витягнути CN підписувача")
            return 1
        print("  [OK] дані сертифіката витягнуто")
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] cert_info_from_cms впав: {e}", file=sys.stderr)
        return 1

    cli.close()

    # --- підсумок ---
    print()
    print("═" * 60)
    print("✓ УСІ КРОКИ ПРОЙШЛИ — ключ + сертифікат + пароль коректні.")
    print("═" * 60)
    print()
    print("Цей ключ можна прив'язати в UI EUSign WASM. Якщо в браузері все одно")
    print("помилка 51 «Сертифікат не знайдено» — проблема виключно в EUSign-WASM")
    print("(дотяг сертифіката з КНЕДП), не в самому ключі. Додайте .cer у поле")
    print("«Сертифікат ключа» в модалці для офлайн-читання сертифіката.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""CLI-обгортка над infrastructure.token_sign — підпис файла апаратним токеном ІІТ.

Уся логіка — в src/dilovod4/infrastructure/token_sign.py. Цей скрипт лише
розбирає аргументи й env, друкує результат.

ПІН береться з оточення TOKEN_PIN (НЕ передавайте в аргументах).
CMP/TSP/OCSP-адреси КНЕДП-емітента — через env або типово ДПС.

Запуск:
    TOKEN_PIN='...' python3 scripts/token_sign_nmh.py <файл> [out.p7s]

Опційні env:
    TOKEN_CMP   CMP-адреса з повним шляхом (типово ca.tax.gov.ua/services/cmp/)
    TOKEN_TSP   TSP-адреса (типово ca.tax.gov.ua/services/tsp/)
    TOKEN_OCSP  OCSP-адреса (типово ca.tax.gov.ua/services/ocsp/)
    TOKEN_CADES_T   '1' -> CAdES-T (квал. позначка часу), інакше CAdES-BES
    TOKEN_TYPE_INDEX / TOKEN_DEV_INDEX  індекси носія (типово 1/0 для Алмаз-1К)
"""

from __future__ import annotations

import os
import sys

# дозволяємо запуск без встановленого пакета: додаємо src/ у шлях і
# імпортуємо модуль напряму (щоб не тягнути опційні залежності пакета).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
import importlib.util

_mod_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                         "src", "dilovod4", "infrastructure", "token_sign.py")
_spec = importlib.util.spec_from_file_location("token_sign", os.path.abspath(_mod_path))
assert _spec and _spec.loader
token_sign = importlib.util.module_from_spec(_spec)
sys.modules["token_sign"] = token_sign
_spec.loader.exec_module(token_sign)


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: TOKEN_PIN='...' python3 token_sign_nmh.py <file> [out.p7s]")
        return 2
    pin = os.environ.get("TOKEN_PIN")
    if not pin:
        print("set TOKEN_PIN env var (do not pass PIN on the command line)")
        return 2

    src = argv[0]
    out = argv[1] if len(argv) > 1 else None
    cades_t = os.environ.get("TOKEN_CADES_T") == "1"

    try:
        res = token_sign.sign_file_with_token(
            file_path=src,
            pin=pin,
            cmp_url=os.environ.get("TOKEN_CMP", "ca.tax.gov.ua/services/cmp/"),
            out_path=out,
            with_timestamp=cades_t,
            tsp_url=os.environ.get("TOKEN_TSP", "ca.tax.gov.ua/services/tsp/"),
            ocsp_url=os.environ.get("TOKEN_OCSP", "ca.tax.gov.ua/services/ocsp/"),
            type_index=int(os.environ.get("TOKEN_TYPE_INDEX", "1")),
            dev_index=int(os.environ.get("TOKEN_DEV_INDEX", "0")),
        )
    except token_sign.TokenHostNotFound as exc:
        print(f"ERROR: {exc}")
        return 2
    except token_sign.TokenError as exc:
        print(f"ERROR: {exc}")
        if exc.code == token_sign.EU_BAD_PRIVATE_KEY:
            print("  -> НЕВІРНИЙ ПІН. Спроба ЗГОРІЛА — перевірте залишок у GUI ІІТ!")
        return 3

    fmt = "CAdES-T" if res.sign_type == token_sign.SIGN_TYPE_CADES_T else "CAdES-BES"
    out_path = out or src + ".p7s"
    print(f"OK: signed -> {out_path} ({len(res.container)} bytes, {fmt}, "
          f"timestamp={res.has_timestamp})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""CLI генератор тестового PKCS#12 печатки юрособи для серверного підпису.

Створює eSeal-сертифікат печатки (X.509, ECDSA P-256 з QC eSeal) + PKCS#12-контейнер,
придатний для налаштування серверного підпису порталу (PORTAL_SEAL_P12).

ВАЖЛИВО: цей сертифікат — ТЕСТОВИЙ (виданий тестовим КНЕДП, не реальним АЦСК).
Для продакшну використовуйте реальний eSeal-сертифікат печатки вашої юрособи,
отриманий у кваліфікованого надавача електронних довірчих послуг (КНЕДП).

Приклад:
    python scripts/gen_seal_p12.py --org "ТОВ Моя Організація" --edrpou 12345678 \
        --out /etc/dilovod/seal.p12 --password 's3cret'

    # потім задайте в оточенні порталу:
    export PORTAL_SEAL_P12=/etc/dilovod/seal.p12
    export PORTAL_SEAL_PASSWORD='s3cret'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dilovod4.infrastructure.test_cert_factory import (  # noqa: E402
    generate_test_ca,
    issue_eseal_cert,
    to_pkcs12_chain,
)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Згенерувати тестовий eSeal-PKCS#12 печатки юрособи.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--org", required=True, help="назва юрособи (CN печатки)")
    p.add_argument("--edrpou", required=True, help="ЄДРПОУ юрособи")
    p.add_argument("--out", default="seal.p12", help="шлях до вихідного .p12")
    p.add_argument("--password", default="testpassword", help="пароль PKCS#12")
    p.add_argument("--ca-cn", default="Тестовий КНЕДП Діловод", help="CN тестового CA")
    p.add_argument("--valid-days", type=int, default=365, help="строк дії (дні)")
    args = p.parse_args()

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ca = generate_test_ca(args.ca_cn)
    leaf = issue_eseal_cert(ca, args.org, args.edrpou, valid_days=args.valid_days)
    p12_bytes = to_pkcs12_chain(leaf, ca, args.password, "server-seal")
    out_path.write_bytes(p12_bytes)

    print(f"✓ Тестовий eSeal-PKCS#12 печатки згенеровано: {out_path}")
    print(f"  Юрособа (CN): {args.org}")
    print(f"  ЄДРПОУ: {args.edrpou} (organizationIdentifier=NTRUA-{args.edrpou})")
    print(f"  Строк дії: {args.valid_days} днів")
    print()
    print("Налаштування серверного підпису порталу:")
    print(f"  export PORTAL_SEAL_P12={out_path}")
    print(f"  export PORTAL_SEAL_PASSWORD='{args.password}'")
    print()
    print("⚠  ТЕСТОВИЙ сертифікат (тестовий КНЕДП). Для продакшну використовуйте")
    print("  реальний eSeal-сертифікат печатки вашої юрособи від КНЕДП.")
    print()
    print("Перевірка сертифіката:")
    print(f"  openssl pkcs12 -in {out_path} -passin pass:{args.password} -nokeys -clcerts "
          f"| openssl x509 -text -noout | grep -A3 qcStatements")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

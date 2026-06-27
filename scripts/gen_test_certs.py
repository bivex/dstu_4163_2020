#!/usr/bin/env python3
"""CLI генератор тестових сертифікатів (X.509 eSign/eSeal) для розробки й тестів.

Будує міні-тестовий PKI (CA + КЕП особи + печатка юрособи) у вказаному каталозі.
Сертифікати — криптографічно валідні ECDSA P-256 з українськими QC-розширеннями,
сумісні з EUSign/openssl/UAPKI. Опція --dstu проганяє демонстраційний ДСТУ-keygen
через нативну libuapki (якщо зібрана), але сертифікати усе одно ECDSA (cryptography
не підтримує DSTU як algId сертифіката).

Приклад:
    python scripts/gen_test_certs.py --out samples/test_certs/
    python scripts/gen_test_certs.py --out /tmp/certs --org "ТОВ Моя org" --edrpou 12345678

Файли, що створюються:
    ca.cer, ca.p12             — тестовий КНЕДП (CA)
    person_esign.cer, .p12     — КЕП фізособи (eSign)
    org_eseal.cer, .p12        — печатка юрособи (eSeal)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# доменне ядро лежить у ../src відносно scripts/
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dilovod4.infrastructure.test_cert_factory import write_bundle  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(
        description="Згенерувати тестові сертифікати (CA + eSign + eSeal).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--out", default="samples/test_certs", help="каталог для сертифікатів")
    p.add_argument("--password", default="testpassword", help="пароль PKCS#12-контейнерів")
    p.add_argument("--ca-cn", default="Тестовий КНЕДП Діловод", help="CN тестового CA")
    p.add_argument("--person-cn", default="Тестовий Підписувач КЕП", help="CN КЕП особи")
    p.add_argument("--person-rnopp", default="1234512345", help="РНОКПП (ІПН) особи")
    p.add_argument("--org-name", default="ТОВ Тестова Юридична Особа", help="назва юрособи (печатка)")
    p.add_argument("--edrpou", default="43213421", help="ЄДРПОУ юрособи")
    p.add_argument(
        "--dstu",
        action="store_true",
        help="продемонструвати ДСТУ-keygen через нативну UAPKI (cert усе одно ECDSA)",
    )
    args = p.parse_args()

    paths = write_bundle(
        args.out,
        password=args.password,
        ca_cn=args.ca_cn,
        person_cn=args.person_cn,
        person_rnopp=args.person_rnopp,
        org_name=args.org_name,
        org_edrpou=args.edrpou,
        dstu=args.dstu,
    )

    print(f"✓ Тестові сертифікати згенеровано у: {Path(args.out).resolve()}")
    print(f"  CA (тестовий КНЕДП):  {paths['ca']}")
    print(f"  КЕП особи (eSign):    {paths['esign']}")
    print(f"  Печатка юрособи (eSeal): {paths['eseal']}")
    print()
    print("Пароль PKCS#12-контейнерів: " + args.password)
    print()
    print("Перевірка сертифіката:")
    print(f"  openssl x509 -in {Path(args.out)/'org_eseal.cer'} -text -noout | grep -A5 'qcStatements'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Насіяти штат великої фірми (~30 співробітників) у БД порталу «Діловод».

Створює реалістичний штат ТОВ з розподілом ролей: директор, бухгалтерія, юристи,
кадри, відділи продажів/закупівель/ІТ, клерки. Кожен — email, ПІБ, посада, роль,
пароль. Існуючі користувачі (за email) оновлюються, не дублюються.

Використання:
  python3 scripts/seed_company.py                 # за замовч. 30 людей, пароль 'password123'
  python3 scripts/seed_company.py --count 50 --password 's3cret'
  python3 scripts/seed_company.py --org "ТОВ Рога і Копита" --domain firm.local

Бере DATABASE_URL з PORTAL_DATABASE_URL (або дефолт portal/portal.db).
Адмін admin@dilovod.local лишається (не чіпається). Печатка юрособи НЕ
прив'язується — це окремий flow (link-kep з eSeal-сертифікатом).
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PORTAL = _HERE.parent / "portal"
_SRC = _HERE.parent / "src"
for p in (_PORTAL, _SRC, _PORTAL.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Штат фірми — реалістична структура великої компанії.
# (ПІБ, посада, роль). ПІБ — типові українські імена; посади — реальные позиції.
# Розподіл ролей: 1 директор, кілька accountant, lawyer, hr, IT, решта — clerk.
_STAFF_TEMPLATE = [
    # Керівництво
    ("Кравченко Олександр Михайлович",      "Генеральний директор",         "director"),
    ("Шевченко Тетяна Володимирівна",       "Заступник директора",          "director"),
    # Бухгалтерія (5)
    ("Бондаренко Наталія Петрівна",         "Головний бухгалтер",           "accountant"),
    ("Мельник Олена Іванівна",              "Бухгалтер (заробітна плата)",  "accountant"),
    ("Коваленко Світлана Василівна",        "Бухгалтер (банк/каса)",        "accountant"),
    ("Ткаченко Ірина Сергіївна",            "Бухгалтер (податки/ПДВ)",      "accountant"),
    ("Гриценко Юрій Андрійович",            "Економіст",                    "accountant"),
    # Юридичний відділ (4)
    ("Бойко Андрій Вікторович",             "Начальник юридичного відділу", "director"),
    ("Поліщук Марія Олексіївна",            "Юрист",                        "clerk"),
    ("Ткачук Дмитро Романович",             "Юрист (договори)",             "clerk"),
    ("Кравчук Оксана Богданівна",           "Юрист (корпоративне право)",   "clerk"),
    # Відділ кадрів (3)
    ("Кузьменко Людмила Степанівна",        "Начальник відділу кадрів",     "director"),
    ("Іваненко Олена Григорівна",           "Інспектор з кадрів",           "clerk"),
    ("Лисенко Віталій Павлович",            "Спеціаліст з кадрів",          "clerk"),
    # Відділ продажів (6)
    ("Руденко Сергій Миколайович",          "Комерційний директор",         "director"),
    ("Мороз Анна Володимирівна",            "Менеджер з продажу",           "clerk"),
    ("Власенко Дмитро Олександрович",       "Менеджер з продажу",           "clerk"),
    ("Гончар Оксана Іванівна",              "Менеджер з продажу",           "clerk"),
    ("Дмитренко Павло Богданович",          "Менеджер з продажу",           "clerk"),
    ("Захарченко Юлія Андріївна",           "Менеджер з продажу (ВЕД)",     "clerk"),
    # Відділ закупівель (3)
    ("Кравцов Ігор Валерійович",            "Начальник відділу закупівель", "director"),
    ("Левченко Максим Сергійович",          "Спеціаліст з закупівель",      "clerk"),
    ("Панченко Вікторія Юріївна",           "Спеціаліст з закупівель",      "clerk"),
    # Виробництво (4)
    ("Марченко Петро Іванович",             "Директор з виробництва",       "director"),
    ("Савченко Роман Олегович",             "Начальник цеху",               "clerk"),
    ("Литвин Андрій Миколайович",           "Майстер дільниці",             "clerk"),
    ("Олійник Богдан Васильович",           "Технолог",                     "clerk"),
    # ІТ / АДМ (3)
    ("Назаренко Олексій Дмитрович",         "Начальник ІТ-відділу",         "director"),
    ("Хоменко Володимир Петрович",          "Системний адміністратор",      "clerk"),
    ("Музичко Катерина Павлівна",           "Спеціаліст технічної підтримки","clerk"),
]


def _email_from_name(name: str, domain: str) -> str:
    """ПІБ → email: first.last@domain (транслітерація прізвища+імені)."""
    import unicodedata
    # проста транслітерація кирилиці
    table = {
        "а":"a","б":"b","в":"v","г":"h","ґ":"g","д":"d","е":"e","є":"ie","ж":"zh",
        "з":"z","и":"y","і":"i","ї":"i","й":"i","к":"k","л":"l","м":"m","н":"n",
        "о":"o","п":"p","р":"r","с":"s","т":"t","у":"u","ф":"f","х":"kh","ц":"ts",
        "ч":"ch","ш":"sh","щ":"shch","ь":"","ю":"iu","я":"ia","'":"",
    }
    s = unicodedata.normalize("NFC", name.lower())
    out = []
    for ch in s:
        out.append(table.get(ch, ch if ch.isascii() else ""))
    latin = "".join(out)
    parts = [p for p in latin.replace("-", " ").split() if p]
    # прізвище.і (Кравченко Олександр → kravchenko.a)
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1][0]}@{domain}"
    return f"{parts[0]}@{domain}" if parts else f"emp{abs(hash(name))%10000}@{domain}"


def main() -> int:
    ap = argparse.ArgumentParser(description="Насіяти штат фірми в БД порталу.")
    ap.add_argument("--count", type=int, default=len(_STAFF_TEMPLATE),
                    help=f"кількість співробітників (до {len(_STAFF_TEMPLATE)})")
    ap.add_argument("--password", default="password123", help="пароль для всіх")
    ap.add_argument("--org", default="ТОВ Рога і Копита", help="назва (тільки у вивід)")
    ap.add_argument("--domain", default="rogy-kopyta.com.ua", help="домен email")
    ap.add_argument("--dry-run", action="store_true", help="лише показати, не записувати")
    args = ap.parse_args()

    import os
    db_url = os.environ.get("PORTAL_DATABASE_URL") or f"sqlite:///{_PORTAL}/portal.db"
    os.environ.setdefault("PORTAL_DATABASE_URL", db_url)

    import portal.db as db
    db.init_db()

    staff = _STAFF_TEMPLATE[: args.count]
    if args.count > len(_STAFF_TEMPLATE):
        print(f"[WARN] у шаблоні лише {len(_STAFF_TEMPLATE)} людей; count={args.count}", file=sys.stderr)

    from collections import Counter
    role_count = Counter(r for _, _, r in staff)

    print(f"=== {args.org}: {len(staff)} співробітників ===")
    print(f"БД: {db_url}")
    print(f"Пароль для всіх: {args.password}")
    print(f"Ролі: " + ", ".join(f"{r}={c}" for r, c in sorted(role_count.items())))
    print()
    print(f"{'#':>3}  {'ПІБ':<40} {'Посада':<32} {'Роль':<11} Email")
    print("-" * 120)

    created = updated = 0
    with db.SessionLocal() as session:
        for i, (name, position, role) in enumerate(staff, 1):
            email = _email_from_name(name, args.domain)
            print(f"{i:>3}  {name:<40} {position:<32} {role:<11} {email}")
            if args.dry_run:
                continue
            user = session.query(db.User).filter_by(email=email).first()
            user_phone = f"+38050{random.randint(1000000, 9999999)}"
            user_address = f"вул. Шевченка, {random.randint(1, 150)}, м. Київ, 0{random.randint(1000, 9999)}"
            if user:
                user.name = name
                user.position = position
                user.role = role
                user.password_hash = db.User.hash_password(args.password)
                if not user.phone:
                    user.phone = user_phone
                if not user.address:
                    user.address = user_address
                updated += 1
            else:
                session.add(db.User(
                    email=email, name=name, position=position, role=role,
                    password_hash=db.User.hash_password(args.password),
                    phone=user_phone,
                    address=user_address,
                ))
                created += 1
        if not args.dry_run:
            session.commit()

    if args.dry_run:
        print(f"\n[dry-run] не записано. Запустіть без --dry-run для застосування.")
    else:
        print(f"\n✓ Створено: {created}, оновлено: {updated}")
        print(f"  Вхід: будь-який email вище + пароль '{args.password}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

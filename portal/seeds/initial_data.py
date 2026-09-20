"""Початкові системні дані: адмін, журнали реєстрації, типові контрагенти."""

from __future__ import annotations

import os
from typing import Callable
from sqlalchemy.orm import Session

from portal.db import User, UserRole, Journal, Counterparty


def seed_default_journals(session_factory: Callable[[], Session]) -> None:
    """Створити дефолтні реєстраційні журнали якщо таблиця порожня."""
    with session_factory() as session:
        if session.query(Journal).first():
            return
        j1 = Journal(
            name="Накази з основної діяльності",
            prefix="ОД",
            number_template="{number}-{prefix}",
            next_number=1,
        )
        j2 = Journal(
            name="Вхідне листування",
            prefix="ВХ",
            number_template="{number}/{prefix}",
            next_number=1,
        )
        j3 = Journal(
            name="Вихідне листування",
            prefix="ВИХ",
            number_template="{number}-{prefix}/01-12",
            next_number=1,
        )
        session.add_all([j1, j2, j3])
        session.commit()


def seed_default_admin(session_factory: Callable[[], Session]) -> None:
    """Створити дефолтного адміна admin@dilovod.local / admin якщо немає жодного user."""
    default_email = os.environ.get("PORTAL_ADMIN_EMAIL", "admin@dilovod.local")
    default_pass = os.environ.get("PORTAL_ADMIN_PASSWORD", "admin")
    with session_factory() as session:
        if session.query(User).first():
            bootstrap_admin(session, default_email)
            return
        user = User(
            email=default_email,
            name="Адміністратор",
            position="Адміністратор",
            role=UserRole.ADMIN.value,
            password_hash=User.hash_password(default_pass),
            phone="+38 050 123 45 67",
            address="вул. Садова, 5, кв. 12, м. Київ, 01001",
        )
        session.add(user)
        session.commit()


def bootstrap_admin(session: Session, email: str | None) -> None:
    """Підняти роль вказаного користувача до admin при старті."""
    bootstrap_email = os.environ.get("PORTAL_BOOTSTRAP_ADMIN_EMAIL") or email
    if not bootstrap_email:
        return
    if session.query(User).filter_by(role=UserRole.ADMIN.value).first():
        return
    user = session.query(User).filter_by(email=bootstrap_email).first()
    if user and user.role != UserRole.ADMIN.value:
        user.role = UserRole.ADMIN.value
        session.commit()


def seed_default_counterparties(session_factory: Callable[[], Session]) -> None:
    """Створити дефолтних контрагентів якщо таблиця порожня."""
    with session_factory() as session:
        existing_names = {c.name for c in session.query(Counterparty.name).all()}

        to_add = []
        defaults = [
            ('ТОВ "Дія Консалтинг"', "12345678", "legal", "info@diaconsulting.com.ua", "+380441112233", "м. Київ, вул. Хрещатик, 1"),
            ('АТ "Укрпошта"', "21560043", "legal", "ukrposhta@ukrposhta.ua", "+380442223344", "м. Київ, вул. Хрещатик, 22"),
            ("ФОП Шевченко Тарас Григорович", "3012345678", "fop", "shevchenko@gmail.com", "+380998887766", "м. Канів, вул. Шевченка, 10"),
            ("Національна поліція України", "40108578", "legal", "info@police.gov.ua", "+380442560333", "Голові Національної поліції України\nвул. Академіка Богомольця, 10\nм. Київ, 01601"),
            ("Офіс Генерального прокурора", "00034051", "legal", "zvern@gp.gov.ua", "+380442007624", "Генеральному прокурору\nвул. Різницька, 13/15\nм. Київ, 01011"),
            ("Антимонопольний комітет України", "00032744", "legal", "post@amcu.gov.ua", "+380442516223", "Голові Антимонопольного комітету України\nвул. Митрополита Василя Липківського, 45\nм. Київ, 03035")
        ]

        for name, code, subject_type, email, phone, address in defaults:
            if name not in existing_names:
                to_add.append(Counterparty(
                    name=name,
                    code=code,
                    subject_type=subject_type,
                    email=email,
                    phone=phone,
                    address=address
                ))

        if to_add:
            session.add_all(to_add)
            session.commit()

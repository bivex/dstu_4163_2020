"""Реєстрація документів: автоматичні наскрізні індекси та автодати.

Нормальний документообіг (Типова інструкція з діловодства, ПКМУ № 55/2018):
- реєстраційний індекс — наскрізний порядковий номер у межах діловодного року,
  окремий лічильник для кожного типу документа (накази, листи, протоколи…);
- реєстрація відбувається в момент офіційного входу документа в обіг
  (тут — при поданні у чергу підписання), не при створенні чернетки;
- дата реєстрації — у словесно-цифровому форматі (§5.3 ДСТУ 4163:2020),
  напр. «14 червня 2026 р.».

Лічильник реалізовано як MAX(reg_number)+1 серед документів того ж типу за
поточний рік — атомарно в межах транзакції submit (рядок документа вже
заблоковано). Для SQLite цього достатньо; для Postgres варто додати
SELECT ... FOR UPDATE на лічильнику, але модель та сама.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from .db import Document

# Українські назви місяців у родовому відмінку (для «14 червня 2026 р.»)
_MONTHS_GENITIVE = (
    "",
    "січня", "лютого", "березня", "квітня", "травня", "червня",
    "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
)

# Префікс індексу за типом документа (наказ → «н», лист → «л» тощо).
# За замовчуванням — без літерного префікса (чистий номер).
_TYPE_PREFIX = {
    "Наказ": "",
    "Розпорядження": "",
    "Лист": "",
    "Протокол": "",
    "Акт": "",
    "Доповідна записка": "",
    "Службова записка": "",
}


def format_ua_date(when: dt.date) -> str:
    """Дата у словесно-цифровому форматі ДСТУ: «14 червня 2026 р.»."""
    return f"{when.day} {_MONTHS_GENITIVE[when.month]} {when.year} р."


def next_reg_number(session: Session, doc_type: str, year: int) -> int:
    """Наступний наскрізний номер для типу документа в межах діловодного року.

    Наскрізна нумерація: накази мають власну послідовність 1,2,3…, листи —
    свою, і щороку лічильник стартує з 1 (п. реєстрації Типової інструкції).
    """
    max_num = (
        session.query(func.max(Document.reg_number))
        .filter(
            Document.doc_type == doc_type,
            extract("year", Document.registered_at) == year,
        )
        .scalar()
    )
    return (max_num or 0) + 1


def assign_registration(
    session: Session, doc: Document, doc_type: str, when: dt.datetime | None = None
) -> None:
    """Присвоїти документу реєстраційний індекс і дату (ідемпотентно).

    Якщо документ уже зареєстрований (reg_number не None) — нічого не робимо,
    щоб повторний submit не змінив офіційний номер.
    """
    if doc.reg_number is not None:
        return

    when = when or dt.datetime.now(dt.timezone.utc)
    doc.doc_type = doc_type
    doc.registered_at = when
    number = next_reg_number(session, doc_type, when.year)
    doc.reg_number = number
    prefix = _TYPE_PREFIX.get(doc_type, "")
    doc.reg_index = f"{prefix}{number}" if prefix else str(number)
    doc.reg_date = format_ua_date(when.date())

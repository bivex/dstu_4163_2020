"""Доменна модель: перелічення (1:1 з catala-metadata ДСТУ 4163:2020)."""

from __future__ import annotations

from enum import Enum


class PaperFormat(Enum):
    """§6.1. Формат паперу."""

    A4 = "A4"  # 210 x 297 mm
    A5 = "A5"  # 210 x 148 mm
    A3 = "A3"  # 297 x 420 mm (таблиці)


class BlankType(Enum):
    """§6.9. Тип бланка."""

    GENERAL = "General"  # загальний бланк юридичної особи
    LETTER = "Letter"  # бланк листа
    SPECIFIC_VIEW = "SpecificView"  # бланк конкретного виду документа


class RequisiteAlignment(Enum):
    """§6.7. Спосіб розташування реквізитів бланка."""

    CENTERED = "Centered"  # центрований
    FLAG = "Flag"  # прапоровий


class StorageTerm(Enum):
    """§7.11. Строк зберігання."""

    TEMPORARY = "Temporary"  # до 10 років включно
    LONG_TERM = "LongTerm"  # понад 10 років
    PERMANENT = "Permanent"  # постійне зберігання


class PrintSide(Enum):
    """§7.11. Бік друку."""

    ONE_SIDE = "OneSide"
    BOTH_SIDES = "BothSides"


class DateStyle(Enum):
    """§5.10. Спосіб оформлення дати."""

    DIGITAL = "Digital"  # 07.12.2019  (день.місяць.рік)
    REVERSE_DIGITAL = "ReverseDigital"  # 2019.05.25  (рік.місяць.день)
    VERBAL_NUMERIC = "VerbalNumeric"  # 07 грудня 2019 року

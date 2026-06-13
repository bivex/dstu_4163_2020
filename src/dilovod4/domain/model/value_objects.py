"""Value objects домену.

Незмінні (frozen) обʼєкти-значення без ідентичності. Інваріанти структурної
коректності перевіряються у __post_init__ і кидають InvariantViolation.
Відповідність нормі тут НЕ перевіряється — це робота правил (rules/).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import InvariantViolation
from .enums import (
    BlankType,
    DateStyle,
    PaperFormat,
    RequisiteAlignment,
    StorageTerm,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvariantViolation(message)


@dataclass(frozen=True)
class RequisiteSet:
    """§4.4. Набір присутніх реквізитів документа (DocRequisites у Catala)."""

    org_name: bool  # 04 — найменування юридичної особи
    doc_type: bool  # 09 — назва виду документа
    date: bool  # 10 — дата документа
    reg_index: bool  # 11 — реєстраційний індекс
    title: bool  # 19 — заголовок до тексту
    text: bool  # 20 — текст документа
    paper_signature: bool  # 22 — підпис (паперовий)
    electronic_signature: bool
    electronic_seal: bool


@dataclass(frozen=True)
class PageMargins:
    """§6.2. Поля сторінки в мм."""

    left: int
    right: int
    top: int
    bottom: int

    def __post_init__(self) -> None:
        for name in ("left", "right", "top", "bottom"):
            _require(getattr(self, name) >= 0, f"поле '{name}' не може бути відʼємним")


@dataclass(frozen=True)
class Geometry:
    """§6.1/6.2/6.5. Геометрія сторінки та допуск розташування реквізиту."""

    paper_format: PaperFormat
    margins: PageMargins
    requisite_offset_mm: int  # |фактичне − номінальне|

    def __post_init__(self) -> None:
        _require(self.requisite_offset_mm >= 0, "допуск розташування не може бути відʼємним")


@dataclass(frozen=True)
class Typography:
    """§7.2/7.6. Типографіка."""

    is_times_new_roman: bool
    body_size_pt: int
    small_size_pt: int
    doc_type_size_pt: int
    multiline_row_chars: int

    def __post_init__(self) -> None:
        for name in ("body_size_pt", "small_size_pt", "doc_type_size_pt", "multiline_row_chars"):
            _require(getattr(self, name) >= 0, f"'{name}' не може бути відʼємним")


@dataclass(frozen=True)
class LineSpacing:
    """§7.3. Міжрядковий інтервал."""

    body_spacing: float

    def __post_init__(self) -> None:
        _require(self.body_spacing > 0, "міжрядковий інтервал має бути додатним")


@dataclass(frozen=True)
class LeftIndents:
    """§7.7. Відступи від лівого поля (мм)."""

    paragraph_mm: int
    addressee_mm: int
    approval_mm: int
    restriction_mm: int
    signature_decode_mm: int

    def __post_init__(self) -> None:
        for name in (
            "paragraph_mm",
            "addressee_mm",
            "approval_mm",
            "restriction_mm",
            "signature_decode_mm",
        ):
            _require(getattr(self, name) >= 0, f"відступ '{name}' не може бути відʼємним")


@dataclass(frozen=True)
class PageNumbering:
    """§7.10. Нумерація сторінок."""

    page_count: int
    first_page_numbered: bool
    second_page_numbered: bool
    uses_word_or_punctuation: bool

    def __post_init__(self) -> None:
        _require(self.page_count >= 1, "кількість сторінок має бути ≥ 1")


@dataclass(frozen=True)
class SymbolDimensions:
    """§5.1/5.10/5.31. Розміри зображень та службових зон (мм)."""

    coat_of_arms_height_mm: int
    coat_of_arms_width_mm: int
    emblem_height_mm: int
    qr_side_mm: int
    registration_zone_height_mm: int
    registration_zone_width_mm: int

    def __post_init__(self) -> None:
        for name in (
            "coat_of_arms_height_mm",
            "coat_of_arms_width_mm",
            "emblem_height_mm",
            "qr_side_mm",
            "registration_zone_height_mm",
            "registration_zone_width_mm",
        ):
            _require(getattr(self, name) >= 0, f"розмір '{name}' не може бути відʼємним")


@dataclass(frozen=True)
class BlankSpec:
    """§6.8/6.9. Параметри бланка."""

    blank_type: BlankType
    requisite_code: int  # 1..32
    annual_units: int

    def __post_init__(self) -> None:
        _require(1 <= self.requisite_code <= 32, "код реквізиту має бути в межах 1..32")
        _require(self.annual_units >= 0, "річний тираж не може бути відʼємним")


@dataclass(frozen=True)
class FormattingSpec:
    """§6.7. Оформлення реквізитів бланка."""

    alignment: RequisiteAlignment
    underlined_or_separated: bool


@dataclass(frozen=True)
class DateSpec:
    """§5.10. Дата документа."""

    style: DateStyle
    is_joint_document: bool


# Реекспорт для зручності
__all__ = [
    "RequisiteSet",
    "PageMargins",
    "Geometry",
    "Typography",
    "LineSpacing",
    "LeftIndents",
    "PageNumbering",
    "SymbolDimensions",
    "BlankSpec",
    "FormattingSpec",
    "DateSpec",
    "StorageTerm",
]

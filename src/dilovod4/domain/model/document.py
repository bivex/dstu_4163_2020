"""Document — корінь агрегату.

Збирає всі value objects, що описують оформлення документа. Інваріанти
структурної цілісності перевіряються при створенні. Відповідність ДСТУ —
обовʼязок правил (rules/), не агрегату.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import InvariantViolation
from .enums import StorageTerm
from .value_objects import (
    BlankSpec,
    DateSpec,
    FormattingSpec,
    Geometry,
    LeftIndents,
    LineSpacing,
    PageNumbering,
    RequisiteSet,
    SymbolDimensions,
    Typography,
)


@dataclass(frozen=True)
class Document:
    """Документ юридичної особи, що підлягає перевірці на відповідність ДСТУ 4163:2020.

    Корінь агрегату: зовнішній код працює з документом цілісно, а не з окремими
    value objects. Поля характеризують контекст оформлення (паперовий/електронний,
    лист/не-лист), необхідний правилам §4.4 та §6.9.
    """

    doc_id: str
    is_letter: bool
    is_electronic: bool
    requisites: RequisiteSet
    geometry: Geometry
    formatting: FormattingSpec
    typography: Typography
    line_spacing: LineSpacing
    left_indents: LeftIndents
    page_numbering: PageNumbering
    storage_term: StorageTerm
    addressee_count: int
    appendix_count: int
    blank: BlankSpec
    date: DateSpec
    symbols: SymbolDimensions
    tags: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if not self.doc_id or not self.doc_id.strip():
            raise InvariantViolation("doc_id не може бути порожнім")
        if self.addressee_count < 0:
            raise InvariantViolation("кількість адресатів не може бути відʼємною")
        if self.appendix_count < 0:
            raise InvariantViolation("кількість додатків не може бути відʼємною")
        # §4.4: для листа реквізит 09 (назва виду) не зазначають — структурно
        # дозволено будь-яке значення, тож тут лише узгодженість бланка з типом.
        if self.is_letter and self.is_electronic and self.requisites.paper_signature:
            # не заборона, а допустимо: електронний лист може не мати паперового
            # підпису — це перевіряє правило, не інваріант. Нічого не робимо.
            pass

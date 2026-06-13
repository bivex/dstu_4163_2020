"""Доменна модель ДСТУ 4163:2020."""

from .content import DocumentContent
from .document import Document
from .enums import (
    BlankType,
    DateStyle,
    PaperFormat,
    PrintSide,
    RequisiteAlignment,
    StorageTerm,
)
from .value_objects import (
    BlankSpec,
    DateSpec,
    FormattingSpec,
    Geometry,
    LeftIndents,
    LineSpacing,
    PageMargins,
    PageNumbering,
    RequisiteSet,
    SymbolDimensions,
    Typography,
)

__all__ = [
    "Document",
    "DocumentContent",
    "BlankType",
    "DateStyle",
    "PaperFormat",
    "PrintSide",
    "RequisiteAlignment",
    "StorageTerm",
    "BlankSpec",
    "DateSpec",
    "FormattingSpec",
    "Geometry",
    "LeftIndents",
    "LineSpacing",
    "PageMargins",
    "PageNumbering",
    "RequisiteSet",
    "SymbolDimensions",
    "Typography",
]

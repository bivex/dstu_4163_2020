"""Доменна модель ДСТУ 4163:2020."""

from .content import DocumentContent
from .document import Document
from .enums import (
    BlankType,
    CertificateStatus,
    DateStyle,
    PaperFormat,
    PrintSide,
    RequisiteAlignment,
    StorageTerm,
)
from .signature import ElectronicSignatureMark
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
    "ElectronicSignatureMark",
    "BlankType",
    "CertificateStatus",
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

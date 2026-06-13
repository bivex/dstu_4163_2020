"""Правила відповідності ДСТУ 4163:2020 — по одному на параграф (Catala scope)."""

from .base import ConformanceRule, Finding, RuleResult, Severity
from .blank_date_symbols import (
    BlankRequisitesRule,
    DateRule,
    SymbolDimensionsRule,
    permitted_codes,
)
from .counts_retention import (
    AddresseeRule,
    AppendixRule,
    PrintSideRule,
    prescribed_print_side,
)
from .formatting_typography import RequisiteFormattingRule, TypographyRule
from .geometry import DocumentGeometryRule
from .layout import LeftIndentationRule, LineSpacingRule, PageNumberingRule
from .mandatory_requisites import MandatoryRequisitesRule

ALL_RULE_CLASSES: tuple[type[ConformanceRule], ...] = (
    MandatoryRequisitesRule,
    DocumentGeometryRule,
    RequisiteFormattingRule,
    TypographyRule,
    LineSpacingRule,
    LeftIndentationRule,
    PageNumberingRule,
    PrintSideRule,
    AddresseeRule,
    AppendixRule,
    BlankRequisitesRule,
    DateRule,
    SymbolDimensionsRule,
)

__all__ = [
    "ConformanceRule",
    "Finding",
    "RuleResult",
    "Severity",
    "ALL_RULE_CLASSES",
    "MandatoryRequisitesRule",
    "DocumentGeometryRule",
    "RequisiteFormattingRule",
    "TypographyRule",
    "LineSpacingRule",
    "LeftIndentationRule",
    "PageNumberingRule",
    "PrintSideRule",
    "AddresseeRule",
    "AppendixRule",
    "BlankRequisitesRule",
    "DateRule",
    "SymbolDimensionsRule",
    "permitted_codes",
    "prescribed_print_side",
]

"""Unit-тести доменних правил (по одному параграфу ДСТУ)."""

from __future__ import annotations

import pytest

from dilovod4.domain.model import (
    BlankSpec,
    BlankType,
    DateSpec,
    DateStyle,
    FormattingSpec,
    Geometry,
    LineSpacing,
    PageMargins,
    PageNumbering,
    PaperFormat,
    RequisiteAlignment,
    RequisiteSet,
    StorageTerm,
    SymbolDimensions,
    Typography,
)
from dilovod4.domain.rules import (
    AddresseeRule,
    AppendixRule,
    BlankRequisitesRule,
    DateRule,
    DocumentGeometryRule,
    LeftIndentationRule,
    LineSpacingRule,
    MandatoryRequisitesRule,
    PageNumberingRule,
    PrintSideRule,
    RequisiteFormattingRule,
    SymbolDimensionsRule,
    TypographyRule,
    prescribed_print_side,
)
from dilovod4.domain.rules.blank_date_symbols import permitted_codes

from .builders import conformant_document


def test_conformant_document_passes_all_rules():
    doc = conformant_document()
    for rule_cls in (
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
    ):
        assert rule_cls().evaluate(doc).conforms, rule_cls.rule_id


# §4.4
def test_missing_reg_index_fails():
    doc = conformant_document(
        requisites=RequisiteSet(True, True, True, False, True, True, True, False, False)
    )
    res = MandatoryRequisitesRule().evaluate(doc)
    assert not res.conforms
    assert any("11" in f.message for f in res.findings)


def test_letter_does_not_require_doc_type():
    doc = conformant_document(
        is_letter=True,
        requisites=RequisiteSet(True, False, True, True, True, True, True, False, False),
    )
    assert MandatoryRequisitesRule().evaluate(doc).conforms


def test_electronic_signature_satisfies_signature():
    doc = conformant_document(
        is_electronic=True,
        requisites=RequisiteSet(True, True, True, True, True, True, False, True, False),
    )
    assert MandatoryRequisitesRule().evaluate(doc).conforms


def test_electronic_seal_satisfies_signature():
    doc = conformant_document(
        is_electronic=True,
        requisites=RequisiteSet(True, True, True, True, True, True, False, False, True),
    )
    assert MandatoryRequisitesRule().evaluate(doc).conforms


# §6.1/6.2/6.5
def test_wrong_left_margin_fails():
    doc = conformant_document(
        geometry=Geometry(PaperFormat.A4, PageMargins(25, 10, 20, 20), 1)
    )
    assert not DocumentGeometryRule().evaluate(doc).conforms


def test_offset_at_tolerance_boundary_passes():
    doc = conformant_document(
        geometry=Geometry(PaperFormat.A4, PageMargins(30, 10, 20, 20), 2)
    )
    assert DocumentGeometryRule().evaluate(doc).conforms


def test_offset_above_tolerance_fails():
    doc = conformant_document(
        geometry=Geometry(PaperFormat.A4, PageMargins(30, 10, 20, 20), 3)
    )
    assert not DocumentGeometryRule().evaluate(doc).conforms


# §6.7
def test_underlined_requisite_fails():
    doc = conformant_document(
        formatting=FormattingSpec(RequisiteAlignment.CENTERED, underlined_or_separated=True)
    )
    assert not RequisiteFormattingRule().evaluate(doc).conforms


# §7.2/7.6
@pytest.mark.parametrize("body,ok", [(11, False), (12, True), (14, True), (15, False)])
def test_body_size_boundaries(body, ok):
    doc = conformant_document(
        typography=Typography(True, body, 10, 15, 28)
    )
    assert TypographyRule().evaluate(doc).conforms is ok


def test_row_length_over_28_fails():
    doc = conformant_document(typography=Typography(True, 14, 10, 15, 29))
    assert not TypographyRule().evaluate(doc).conforms


# §7.3
def test_a5_requires_single_spacing():
    doc = conformant_document(
        geometry=Geometry(PaperFormat.A5, PageMargins(30, 10, 20, 20), 1),
        line_spacing=LineSpacing(1.5),
    )
    assert not LineSpacingRule().evaluate(doc).conforms

    doc_ok = conformant_document(
        geometry=Geometry(PaperFormat.A5, PageMargins(30, 10, 20, 20), 1),
        line_spacing=LineSpacing(1.0),
    )
    assert LineSpacingRule().evaluate(doc_ok).conforms


# §7.7
def test_wrong_paragraph_indent_fails():
    doc = conformant_document()
    from dilovod4.domain.model import LeftIndents

    doc = conformant_document(left_indents=LeftIndents(15, 90, 100, 100, 125))
    assert not LeftIndentationRule().evaluate(doc).conforms


# §7.10
def test_first_page_numbered_fails():
    doc = conformant_document(
        page_numbering=PageNumbering(3, True, True, False)
    )
    assert not PageNumberingRule().evaluate(doc).conforms


def test_single_page_needs_no_numbering():
    doc = conformant_document(
        page_numbering=PageNumbering(1, False, False, False)
    )
    assert PageNumberingRule().evaluate(doc).conforms


# §7.11
def test_prescribed_print_side():
    assert prescribed_print_side(StorageTerm.TEMPORARY).value == "BothSides"
    assert prescribed_print_side(StorageTerm.LONG_TERM).value == "OneSide"
    assert prescribed_print_side(StorageTerm.PERMANENT).value == "OneSide"


def test_permanent_both_sides_tag_fails():
    doc = conformant_document(
        storage_term=StorageTerm.PERMANENT, tags=frozenset({"printed_both_sides"})
    )
    assert not PrintSideRule().evaluate(doc).conforms


def test_temporary_both_sides_allowed():
    doc = conformant_document(
        storage_term=StorageTerm.TEMPORARY, tags=frozenset({"printed_both_sides"})
    )
    assert PrintSideRule().evaluate(doc).conforms


# §5.15
@pytest.mark.parametrize("n,ok", [(4, True), (5, False)])
def test_addressee_limit(n, ok):
    doc = conformant_document(addressee_count=n)
    assert AddresseeRule().evaluate(doc).conforms is ok


# §5.21
@pytest.mark.parametrize("n,ok", [(10, True), (11, False)])
def test_appendix_threshold(n, ok):
    doc = conformant_document(appendix_count=n)
    assert AppendixRule().evaluate(doc).conforms is ok


# §6.8/6.9
def test_permitted_codes_by_blank_type():
    assert permitted_codes(BlankType.GENERAL) == frozenset({1, 2, 3, 4, 5, 13})
    assert permitted_codes(BlankType.LETTER) == frozenset({1, 2, 3, 4, 5, 6, 8})
    assert permitted_codes(BlankType.SPECIFIC_VIEW) == frozenset({1, 2, 3, 4, 5, 9, 13})


def test_disallowed_code_for_general_fails():
    doc = conformant_document(blank=BlankSpec(BlankType.GENERAL, 6, 0))
    assert not BlankRequisitesRule().evaluate(doc).conforms


def test_specific_view_below_threshold_fails():
    doc = conformant_document(blank=BlankSpec(BlankType.SPECIFIC_VIEW, 9, 2000))
    assert not BlankRequisitesRule().evaluate(doc).conforms


def test_specific_view_above_threshold_passes():
    doc = conformant_document(blank=BlankSpec(BlankType.SPECIFIC_VIEW, 9, 2001))
    assert BlankRequisitesRule().evaluate(doc).conforms


# §5.10
def test_all_date_styles_valid():
    for style in (DateStyle.DIGITAL, DateStyle.REVERSE_DIGITAL, DateStyle.VERBAL_NUMERIC):
        doc = conformant_document(date=DateSpec(style, False))
        assert DateRule().evaluate(doc).conforms


# §5.1/5.10/5.31
def test_oversized_qr_fails():
    doc = conformant_document(
        symbols=SymbolDimensions(17, 12, 15, 25, 60, 100)
    )
    assert not SymbolDimensionsRule().evaluate(doc).conforms


def test_emblem_at_limit_passes():
    doc = conformant_document(
        symbols=SymbolDimensions(17, 12, 17, 21, 60, 100)
    )
    assert SymbolDimensionsRule().evaluate(doc).conforms

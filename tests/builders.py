"""Будівник конформного документа для тестів (Object Mother)."""

from __future__ import annotations

from dilovod4.domain.model import (
    BlankSpec,
    BlankType,
    DateSpec,
    DateStyle,
    Document,
    FormattingSpec,
    Geometry,
    LeftIndents,
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


def conformant_document(**overrides) -> Document:
    """Повністю конформний документ; overrides замінюють поля верхнього рівня."""
    base = dict(
        doc_id="DOC-TEST",
        is_letter=False,
        is_electronic=False,
        requisites=RequisiteSet(
            org_name=True,
            doc_type=True,
            date=True,
            reg_index=True,
            title=True,
            text=True,
            paper_signature=True,
            electronic_signature=False,
            electronic_seal=False,
        ),
        geometry=Geometry(
            paper_format=PaperFormat.A4,
            margins=PageMargins(left=30, right=10, top=20, bottom=20),
            requisite_offset_mm=1,
        ),
        formatting=FormattingSpec(
            alignment=RequisiteAlignment.CENTERED, underlined_or_separated=False
        ),
        typography=Typography(
            is_times_new_roman=True,
            body_size_pt=14,
            small_size_pt=10,
            doc_type_size_pt=15,
            multiline_row_chars=28,
        ),
        line_spacing=LineSpacing(body_spacing=1.5),
        left_indents=LeftIndents(
            paragraph_mm=10,
            addressee_mm=90,
            approval_mm=100,
            restriction_mm=100,
            signature_decode_mm=125,
        ),
        page_numbering=PageNumbering(
            page_count=3,
            first_page_numbered=False,
            second_page_numbered=True,
            uses_word_or_punctuation=False,
        ),
        storage_term=StorageTerm.PERMANENT,
        addressee_count=2,
        appendix_count=3,
        blank=BlankSpec(blank_type=BlankType.GENERAL, requisite_code=4, annual_units=0),
        date=DateSpec(style=DateStyle.DIGITAL, is_joint_document=False),
        symbols=SymbolDimensions(
            coat_of_arms_height_mm=17,
            coat_of_arms_width_mm=12,
            emblem_height_mm=15,
            qr_side_mm=21,
            registration_zone_height_mm=60,
            registration_zone_width_mm=100,
        ),
        tags=frozenset(),
    )
    base.update(overrides)
    return Document(**base)

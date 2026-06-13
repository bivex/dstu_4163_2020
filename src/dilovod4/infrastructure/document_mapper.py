"""Мапер JSON -> доменний Document (адаптер транспорту).

Анти-корупційний шар: ізолює домен від форми зовнішніх даних. Валідація
структури вхідного JSON відбувається тут, на межі; інваріанти домену —
у самому домені. Помилки розбору — MappingError (технічна, не доменна).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, TypeVar

from ..domain.model import (
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


class MappingError(Exception):
    """Технічна помилка розбору вхідних даних (не доменна)."""


def _req(d: dict[str, Any], key: str) -> Any:
    if key not in d:
        raise MappingError(f"відсутнє обовʼязкове поле: '{key}'")
    return d[key]


E = TypeVar("E", bound=Enum)


def _enum(enum_cls: type[E], value: str, field: str) -> E:
    try:
        return enum_cls(value)
    except ValueError as exc:
        allowed = [e.value for e in enum_cls]
        raise MappingError(
            f"поле '{field}': недопустиме значення '{value}', дозволені {allowed}"
        ) from exc


def document_from_dict(data: dict[str, Any]) -> Document:
    """Зібрати доменний Document зі словника (розпарсений JSON)."""
    try:
        req = _req(data, "requisites")
        geo = _req(data, "geometry")
        margins = _req(geo, "margins")
        fmt = _req(data, "formatting")
        typo = _req(data, "typography")
        indents = _req(data, "left_indents")
        numbering = _req(data, "page_numbering")
        blank = _req(data, "blank")
        date = _req(data, "date")
        symbols = _req(data, "symbols")
    except MappingError:
        raise
    except (TypeError, AttributeError) as exc:
        raise MappingError(f"некоректна структура документа: {exc}") from exc

    return Document(
        doc_id=str(_req(data, "doc_id")),
        is_letter=bool(_req(data, "is_letter")),
        is_electronic=bool(_req(data, "is_electronic")),
        requisites=RequisiteSet(
            org_name=bool(req.get("org_name", False)),
            doc_type=bool(req.get("doc_type", False)),
            date=bool(req.get("date", False)),
            reg_index=bool(req.get("reg_index", False)),
            title=bool(req.get("title", False)),
            text=bool(req.get("text", False)),
            paper_signature=bool(req.get("paper_signature", False)),
            electronic_signature=bool(req.get("electronic_signature", False)),
            electronic_seal=bool(req.get("electronic_seal", False)),
        ),
        geometry=Geometry(
            paper_format=_enum(PaperFormat, _req(geo, "paper_format"), "geometry.paper_format"),
            margins=PageMargins(
                left=int(_req(margins, "left")),
                right=int(_req(margins, "right")),
                top=int(_req(margins, "top")),
                bottom=int(_req(margins, "bottom")),
            ),
            requisite_offset_mm=int(geo.get("requisite_offset_mm", 0)),
        ),
        formatting=FormattingSpec(
            alignment=_enum(RequisiteAlignment, _req(fmt, "alignment"), "formatting.alignment"),
            underlined_or_separated=bool(fmt.get("underlined_or_separated", False)),
        ),
        typography=Typography(
            is_times_new_roman=bool(_req(typo, "is_times_new_roman")),
            body_size_pt=int(_req(typo, "body_size_pt")),
            small_size_pt=int(_req(typo, "small_size_pt")),
            doc_type_size_pt=int(_req(typo, "doc_type_size_pt")),
            multiline_row_chars=int(typo.get("multiline_row_chars", 0)),
        ),
        line_spacing=LineSpacing(body_spacing=float(_req(data, "line_spacing"))),
        left_indents=LeftIndents(
            paragraph_mm=int(_req(indents, "paragraph_mm")),
            addressee_mm=int(_req(indents, "addressee_mm")),
            approval_mm=int(_req(indents, "approval_mm")),
            restriction_mm=int(_req(indents, "restriction_mm")),
            signature_decode_mm=int(_req(indents, "signature_decode_mm")),
        ),
        page_numbering=PageNumbering(
            page_count=int(_req(numbering, "page_count")),
            first_page_numbered=bool(numbering.get("first_page_numbered", False)),
            second_page_numbered=bool(numbering.get("second_page_numbered", False)),
            uses_word_or_punctuation=bool(numbering.get("uses_word_or_punctuation", False)),
        ),
        storage_term=_enum(StorageTerm, _req(data, "storage_term"), "storage_term"),
        addressee_count=int(_req(data, "addressee_count")),
        appendix_count=int(_req(data, "appendix_count")),
        blank=BlankSpec(
            blank_type=_enum(BlankType, _req(blank, "blank_type"), "blank.blank_type"),
            requisite_code=int(_req(blank, "requisite_code")),
            annual_units=int(blank.get("annual_units", 0)),
        ),
        date=DateSpec(
            style=_enum(DateStyle, _req(date, "style"), "date.style"),
            is_joint_document=bool(date.get("is_joint_document", False)),
        ),
        symbols=SymbolDimensions(
            coat_of_arms_height_mm=int(_req(symbols, "coat_of_arms_height_mm")),
            coat_of_arms_width_mm=int(_req(symbols, "coat_of_arms_width_mm")),
            emblem_height_mm=int(_req(symbols, "emblem_height_mm")),
            qr_side_mm=int(_req(symbols, "qr_side_mm")),
            registration_zone_height_mm=int(_req(symbols, "registration_zone_height_mm")),
            registration_zone_width_mm=int(_req(symbols, "registration_zone_width_mm")),
        ),
        tags=frozenset(str(t) for t in data.get("tags", [])),
    )

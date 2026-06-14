"""Приклад документа з грифами погодження/затвердження (реквізити 21/23/24).

Демонструє нові реквізити ДСТУ 4163:2020:
  • 21 — гриф затвердження (ЗАТВЕРДЖУЮ) праворуч угорі;
  • 23 — гриф погодження (ПОГОДЖЕНО) зовнішнє, нижче підпису;
  • 24 — віза (внутрішнє погодження) нижче погоджень.

Генерує один і той самий документ у .docx та .pdf через відповідні адаптери
(LSP: взаємозамінні writer'и) і перевіряє кожен на відповідність нормі.

Запуск:
    PYTHONPATH=src python3 scripts/generate_approval_example.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from dilovod4.application.generate_document import GenerateDocument
from dilovod4.domain.model import (
    Agreement,
    ApprovalGrant,
    BlankSpec,
    BlankType,
    DateSpec,
    DateStyle,
    Document,
    DocumentContent,
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
    Visa,
)
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider


def _geometry() -> Geometry:
    return Geometry(
        paper_format=PaperFormat.A4,
        margins=PageMargins(left=30, right=10, top=20, bottom=20),
        requisite_offset_mm=1,
    )


def _typography() -> Typography:
    return Typography(
        is_times_new_roman=True,
        body_size_pt=14,
        small_size_pt=10,
        doc_type_size_pt=15,
        multiline_row_chars=28,
    )


def _indents() -> LeftIndents:
    return LeftIndents(
        paragraph_mm=10,
        addressee_mm=90,
        approval_mm=100,
        restriction_mm=100,
        signature_decode_mm=125,
    )


def _symbols() -> SymbolDimensions:
    return SymbolDimensions(
        coat_of_arms_height_mm=17,
        coat_of_arms_width_mm=12,
        emblem_height_mm=15,
        qr_side_mm=21,
        registration_zone_height_mm=60,
        registration_zone_width_mm=100,
    )


def build_approved_instruction() -> tuple[Document, DocumentContent]:
    """Затверджена інструкція з зовнішнім погодженням та внутрішньою візою."""
    doc = Document(
        doc_id="INSTR-2026-009",
        is_letter=False,
        is_electronic=False,
        requisites=RequisiteSet(True, True, True, True, True, True, True, False, False),
        geometry=_geometry(),
        formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
        typography=_typography(),
        line_spacing=LineSpacing(1.5),
        left_indents=_indents(),
        page_numbering=PageNumbering(2, False, True, False),
        storage_term=StorageTerm.PERMANENT,
        addressee_count=0,
        appendix_count=0,
        blank=BlankSpec(BlankType.GENERAL, 4, 0),
        date=DateSpec(DateStyle.VERBAL_NUMERIC, False),
        symbols=_symbols(),
    )
    content = DocumentContent(
        org_name="ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        doc_type="Інструкція",
        date_text="14 червня 2026 року",
        reg_index="009",
        title="з діловодства та документообігу",
        body=(
            "1. Ця Інструкція визначає порядок роботи з документами на підприємстві "
            "відповідно до ДСТУ 4163:2020.",
            "2. Документи оформлюють на бланках установленого зразка з дотриманням "
            "вимог щодо складу та розміщення реквізитів.",
            "3. Контроль за дотриманням Інструкції покладається на канцелярію.",
        ),
        signature_position="Начальник канцелярії",
        signature_name="Л. МЕЛЬНИК",
        # 21 — гриф затвердження (персональна форма, ЗАТВЕРДЖУЮ)
        approval=ApprovalGrant(
            position="Директор ДП «УКРНДНЦ»",
            name="О. ПЕТРЕНКО",
            date="14 червня 2026 року",
        ),
        # 23 — зовнішнє погодження (одне персональне, одне через документ)
        agreements=(
            Agreement(
                position="Голова первинної профспілкової організації",
                name="І. БОНДАР",
                date="13 червня 2026 року",
            ),
            Agreement(
                document_reference=(
                    "Протокол засідання технічного комітету\n"
                    "від 12.06.2026 № 7"
                ),
            ),
        ),
        # 24 — внутрішні візи
        visas=(
            Visa(
                position="Начальник юридичного відділу",
                name="О. КОВАЛЬ",
                date="13 червня 2026 року",
            ),
            Visa(
                position="Головний бухгалтер",
                name="Н. ТКАЧЕНКО",
                date="13 червня 2026 року",
                remark="зауважень немає",
            ),
        ),
    )
    return doc, content


def build_committee_protocol() -> tuple[Document, DocumentContent]:
    """Протокол засідання техкомітету — той самий, на який посилається

    гриф погодження інструкції (від 12.06.2026 № 7). Підписують двоє: голова
    та секретар (рукописний підпис, кілька підписантів).
    """
    doc = Document(
        doc_id="PROTOKOL-2026-007",
        is_letter=False,
        is_electronic=False,
        requisites=RequisiteSet(True, True, True, True, True, True, True, False, False),
        geometry=_geometry(),
        formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
        typography=_typography(),
        line_spacing=LineSpacing(1.5),
        left_indents=_indents(),
        page_numbering=PageNumbering(3, False, True, False),
        storage_term=StorageTerm.LONG_TERM,
        addressee_count=0,
        appendix_count=1,
        blank=BlankSpec(BlankType.GENERAL, 4, 0),
        date=DateSpec(DateStyle.VERBAL_NUMERIC, True),
        symbols=_symbols(),
    )
    content = DocumentContent(
        org_name="ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        doc_type="Протокол",
        date_text="12 червня 2026 року",
        reg_index="7",
        title="засідання технічного комітету стандартизації",
        body=(
            "ГОЛОВА: С. БОНДАР. СЕКРЕТАР: М. ЛИСЕНКО.",
            "ПРИСУТНІ: 9 членів комітету.",
            "ПОРЯДОК ДЕННИЙ: 1. Про погодження проєкту Інструкції з діловодства.",
            "СЛУХАЛИ: начальника канцелярії щодо проєкту Інструкції з діловодства.",
            "УХВАЛИЛИ: погодити проєкт Інструкції з діловодства та рекомендувати "
            "до затвердження директором підприємства.",
        ),
        signature_position="Голова комітету",
        signature_name="С. БОНДАР",
        # протокол підписують двоє: голова та секретар
        paper_signatures=(
            ("Голова комітету", "С. БОНДАР"),
            ("Секретар", "М. ЛИСЕНКО"),
        ),
    )
    return doc, content


def build_draft_instruction() -> tuple[Document, DocumentContent]:
    """ПРОЕКТ інструкції — стадія підготовки ДО затвердження.

    Ще немає грифа затвердження (документ не затверджено) — натомість робоча
    позначка «ПРОЕКТ» праворуч угорі. Несе візи розробників (внутрішнє
    погодження), які проставляються на проєкті перед поданням на затвердження.
    Це той самий документ, що його комітет розглядав у протоколі № 7.
    """
    doc = Document(
        doc_id="INSTR-2026-009-DRAFT",
        is_letter=False,
        is_electronic=False,
        requisites=RequisiteSet(True, True, True, True, True, True, True, False, False),
        geometry=_geometry(),
        formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
        typography=_typography(),
        line_spacing=LineSpacing(1.5),
        left_indents=_indents(),
        page_numbering=PageNumbering(2, False, True, False),
        storage_term=StorageTerm.PERMANENT,
        addressee_count=0,
        appendix_count=0,
        blank=BlankSpec(BlankType.GENERAL, 4, 0),
        date=DateSpec(DateStyle.VERBAL_NUMERIC, False),
        symbols=_symbols(),
    )
    content = DocumentContent(
        org_name="ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        doc_type="Інструкція",
        date_text="10 червня 2026 року",
        reg_index="009-пр",
        title="з діловодства та документообігу",
        # робоча позначка стадії підготовки
        marking="ПРОЕКТ",
        body=(
            "1. Ця Інструкція визначає порядок роботи з документами на підприємстві "
            "відповідно до ДСТУ 4163:2020.",
            "2. Документи оформлюють на бланках установленого зразка з дотриманням "
            "вимог щодо складу та розміщення реквізитів.",
            "3. Контроль за дотриманням Інструкції покладається на канцелярію.",
        ),
        signature_position="Начальник канцелярії",
        signature_name="Л. МЕЛЬНИК",
        # на проєкті — лише візи розробників (затвердження ще попереду)
        visas=(
            Visa(
                position="Розробник проєкту, провідний документознавець",
                name="К. ШЕВЧЕНКО",
                date="10 червня 2026 року",
            ),
            Visa(
                position="Начальник юридичного відділу",
                name="О. КОВАЛЬ",
                date="11 червня 2026 року",
                remark="зауважень немає",
            ),
        ),
    )
    return doc, content


def _make_writer(fmt: str):
    if fmt == "docx":
        from dilovod4.infrastructure.docx_writer import DocxDocumentWriter

        return DocxDocumentWriter(), "docx"
    if fmt == "pdf":
        from dilovod4.infrastructure.pdf_writer import PdfDocumentWriter

        return PdfDocumentWriter(), "pdf"
    raise ValueError(f"невідомий формат: {fmt}")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    out_dir = Path(argv[0]) if argv else Path("samples")
    formats = argv[1].split(",") if len(argv) > 1 else ["docx", "pdf"]
    out_dir.mkdir(parents=True, exist_ok=True)

    rule_set = DefaultRuleSetProvider()
    # проєкт інструкції → протокол розгляду → затверджена інструкція (життєвий цикл)
    documents = {
        "instrukciya_proekt": build_draft_instruction(),
        "protokol_komitetu": build_committee_protocol(),
        "instrukciya_pogodzhennia": build_approved_instruction(),
    }

    exit_code = 0
    for fmt in formats:
        fmt = fmt.strip()
        try:
            writer, ext = _make_writer(fmt)
        except Exception as exc:  # noqa: BLE001
            print(f"[ПРОПУЩЕНО] формат {fmt}: {exc}")
            continue

        fmt_dir = out_dir / ext
        fmt_dir.mkdir(parents=True, exist_ok=True)
        use_case = GenerateDocument(writer=writer, rule_set=rule_set)

        for name, (doc, content) in documents.items():
            dest = str(fmt_dir / f"{name}.{ext}")
            result = use_case.execute(doc, content, dest, validate=True)
            report = result.report
            status = "ВІДПОВІДАЄ" if (report and report.conforms) else "НЕ ВІДПОВІДАЄ"
            findings = report.findings_count if report else "?"
            print(f"[{status}] {result.path}  (знахідок: {findings})")
            if report and not report.conforms:
                exit_code = 1
                for r in report.results:
                    for f in r.findings:
                        print(f"    - {r.clause} {f.message}")

    print(f"\nЗгенеровано у: {out_dir.resolve()}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

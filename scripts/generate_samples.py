"""Генератор зразкових документів ДСТУ 4163:2020 у форматі .docx.

Збирає кілька реалістичних документів (наказ, лист, протокол), задає КОНФОРМНІ
параметри оформлення, генерує .docx через DocxDocumentWriter і перевіряє кожен
на відповідність нормі. Композиційний корінь скрипта.

Запуск:
    PYTHONPATH=src python3 scripts/generate_samples.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from dilovod4.application.generate_document import GenerateDocument
from dilovod4.domain.model import (
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
)
from dilovod4.infrastructure.docx_writer import DocxDocumentWriter
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider


def _conformant_geometry(paper: PaperFormat = PaperFormat.A4) -> Geometry:
    return Geometry(
        paper_format=paper,
        margins=PageMargins(left=30, right=10, top=20, bottom=20),
        requisite_offset_mm=1,
    )


def _conformant_typography() -> Typography:
    return Typography(
        is_times_new_roman=True,
        body_size_pt=14,
        small_size_pt=10,
        doc_type_size_pt=15,
        multiline_row_chars=28,
    )


def _conformant_indents() -> LeftIndents:
    return LeftIndents(
        paragraph_mm=10,
        addressee_mm=90,
        approval_mm=100,
        restriction_mm=100,
        signature_decode_mm=125,
    )


def _conformant_symbols() -> SymbolDimensions:
    return SymbolDimensions(
        coat_of_arms_height_mm=17,
        coat_of_arms_width_mm=12,
        emblem_height_mm=15,
        qr_side_mm=21,
        registration_zone_height_mm=60,
        registration_zone_width_mm=100,
    )


def build_order() -> tuple[Document, DocumentContent]:
    """Наказ (не лист), A4, постійне зберігання, бланк конкретного виду."""
    doc = Document(
        doc_id="NAKAZ-2026-014",
        is_letter=False,
        is_electronic=False,
        requisites=RequisiteSet(True, True, True, True, True, True, True, False, False),
        geometry=_conformant_geometry(),
        formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
        typography=_conformant_typography(),
        line_spacing=LineSpacing(1.5),
        left_indents=_conformant_indents(),
        page_numbering=PageNumbering(2, False, True, False),
        storage_term=StorageTerm.PERMANENT,
        addressee_count=0,
        appendix_count=2,
        blank=BlankSpec(BlankType.SPECIFIC_VIEW, 9, 2500),
        date=DateSpec(DateStyle.VERBAL_NUMERIC, False),
        symbols=_conformant_symbols(),
    )
    content = DocumentContent(
        org_name="ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        doc_type="Наказ",
        date_text="13 червня 2026 року",
        reg_index="014-од",
        title="Про затвердження інструкції з діловодства",
        body=(
            "З метою впорядкування роботи з документами та відповідно до вимог "
            "ДСТУ 4163:2020 НАКАЗУЮ:",
            "1. Затвердити Інструкцію з діловодства (додається).",
            "2. Керівникам структурних підрозділів забезпечити дотримання вимог Інструкції.",
            "3. Контроль за виконанням цього наказу залишаю за собою.",
        ),
        signature_position="Директор",
        signature_name="О. ПЕТРЕНКО",
    )
    return doc, content


def build_letter() -> tuple[Document, DocumentContent]:
    """Лист: реквізит 09 не зазначають; бланк листа; адресати."""
    doc = Document(
        doc_id="LIST-2026-241",
        is_letter=True,
        is_electronic=False,
        requisites=RequisiteSet(True, False, True, True, True, True, True, False, False),
        geometry=_conformant_geometry(),
        formatting=FormattingSpec(RequisiteAlignment.FLAG, False),
        typography=_conformant_typography(),
        line_spacing=LineSpacing(1.0),
        left_indents=_conformant_indents(),
        page_numbering=PageNumbering(1, False, False, False),
        storage_term=StorageTerm.TEMPORARY,
        addressee_count=1,
        appendix_count=0,
        blank=BlankSpec(BlankType.LETTER, 6, 0),
        date=DateSpec(DateStyle.DIGITAL, False),
        symbols=_conformant_symbols(),
    )
    content = DocumentContent(
        org_name="ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        doc_type="",  # лист — без назви виду
        date_text="13.06.2026",
        reg_index="241/05-12",
        title="Щодо застосування ДСТУ 4163:2020",
        body=(
            "Шановні колеги!",
            "На ваш запит повідомляємо, що вимоги до оформлення організаційно-"
            "розпорядчих документів визначає ДСТУ 4163:2020, чинний з 01.09.2021.",
            "Додаткові роз’яснення можемо надати за окремим зверненням.",
        ),
        signature_position="Заступник директора",
        signature_name="І. КОВАЛЕНКО",
        addressees=("Міністерство юстиції України\nДепартамент документообігу",),
    )
    return doc, content


def build_protocol() -> tuple[Document, DocumentContent]:
    """Протокол: спільний документ, словесно-цифрова дата, загальний бланк."""
    doc = Document(
        doc_id="PROTOKOL-2026-007",
        is_letter=False,
        is_electronic=False,
        requisites=RequisiteSet(True, True, True, True, True, True, True, False, False),
        geometry=_conformant_geometry(),
        formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
        typography=_conformant_typography(),
        line_spacing=LineSpacing(1.5),
        left_indents=_conformant_indents(),
        page_numbering=PageNumbering(3, False, True, False),
        storage_term=StorageTerm.LONG_TERM,
        addressee_count=0,
        appendix_count=1,
        blank=BlankSpec(BlankType.GENERAL, 4, 0),
        date=DateSpec(DateStyle.VERBAL_NUMERIC, True),
        symbols=_conformant_symbols(),
    )
    content = DocumentContent(
        org_name="ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        doc_type="Протокол",
        date_text="13 червня 2026 року",
        reg_index="07",
        title="засідання технічного комітету стандартизації",
        body=(
            "ПРИСУТНІ: 9 членів комітету.",
            "ПОРЯДОК ДЕННИЙ: 1. Про перегляд ДСТУ 4163:2020.",
            "СЛУХАЛИ: голову комітету щодо стану застосування стандарту.",
            "УХВАЛИЛИ: схвалити звіт та продовжити моніторинг застосування.",
        ),
        signature_position="Голова комітету",
        signature_name="С. БОНДАР",
    )
    return doc, content


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    out_dir = Path(argv[0]) if argv else Path("samples/docx")
    out_dir.mkdir(parents=True, exist_ok=True)

    writer = DocxDocumentWriter()
    rule_set = DefaultRuleSetProvider()
    use_case = GenerateDocument(writer=writer, rule_set=rule_set)

    builders = {
        "nakaz": build_order,
        "lyst": build_letter,
        "protokol": build_protocol,
    }

    exit_code = 0
    for name, builder in builders.items():
        doc, content = builder()
        dest = str(out_dir / f"{name}.docx")
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

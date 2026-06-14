"""Тестовий наказ з грифом обмеження доступу (реквізит 15 ↔ ст.21 З-ну 2657-XII).

Демонструє правомірне обмеження доступу: гриф «Для службового користування»,
вид — службова інформація, тема не належить до переліку ч.4 ст.21, витримано
трискладовий тест (ст.6(2)). Документ генерується у .pdf та .docx і
перевіряється правилом ACCESS_RESTRICTION.

Запуск:
    PYTHONPATH=src python3 scripts/generate_restricted_order.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from dilovod4.application.generate_document import GenerateDocument
from dilovod4.domain.law import RestrictedKind, RestrictionTest, UndisclosableTopic
from dilovod4.domain.model import (
    AccessRestriction,
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
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider


def build_restricted_order() -> tuple[Document, DocumentContent]:
    """Наказ з грифом «Для службового користування» (службова інформація)."""
    doc = Document(
        doc_id="NAKAZ-DSK-2026-044",
        is_letter=False,
        is_electronic=False,
        requisites=RequisiteSet(True, True, True, True, True, True, True, False, False),
        geometry=Geometry(
            paper_format=PaperFormat.A4,
            margins=PageMargins(left=30, right=10, top=20, bottom=20),
            requisite_offset_mm=1,
        ),
        formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
        typography=Typography(
            is_times_new_roman=True,
            body_size_pt=14,
            small_size_pt=10,
            doc_type_size_pt=15,
            multiline_row_chars=28,
        ),
        line_spacing=LineSpacing(1.5),
        left_indents=LeftIndents(
            paragraph_mm=10,
            addressee_mm=90,
            approval_mm=100,
            restriction_mm=100,
            signature_decode_mm=125,
        ),
        page_numbering=PageNumbering(2, False, True, False),
        storage_term=StorageTerm.LONG_TERM,
        addressee_count=0,
        appendix_count=0,
        blank=BlankSpec(BlankType.SPECIFIC_VIEW, 9, 2500),
        date=DateSpec(DateStyle.VERBAL_NUMERIC, False),
        symbols=SymbolDimensions(
            coat_of_arms_height_mm=17,
            coat_of_arms_width_mm=12,
            emblem_height_mm=15,
            qr_side_mm=21,
            registration_zone_height_mm=60,
            registration_zone_width_mm=100,
        ),
    )
    content = DocumentContent(
        org_name="ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        doc_type="Наказ",
        date_text="14 червня 2026 року",
        reg_index="044-дск",
        title="Про затвердження переліку відомостей з обмеженим доступом",
        body=(
            "З метою впорядкування роботи зі службовою інформацією та відповідно до "
            "статті 21 Закону України «Про інформацію» НАКАЗУЮ:",
            "1. Затвердити перелік відомостей, що становлять службову інформацію "
            "підприємства (додається).",
            "2. Керівникам структурних підрозділів забезпечити дотримання режиму "
            "доступу до службової інформації.",
            "3. Контроль за виконанням цього наказу залишаю за собою.",
        ),
        signature_position="Директор",
        signature_name="О. ПЕТРЕНКО",
        # реквізит 15 — правомірний гриф обмеження доступу (ст.21)
        access_restriction=AccessRestriction(
            kind=RestrictedKind.OFFICIAL,
            topic=UndisclosableTopic.OTHER_TOPIC,
            test=RestrictionTest(
                restriction_provided_by_law=True,
                legitimate_aim=True,
                harm_outweighs_public_interest=True,
            ),
            marking="Для службового користування",
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
    doc, content = build_restricted_order()

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
        dest = str(fmt_dir / f"nakaz_dsk.{ext}")
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

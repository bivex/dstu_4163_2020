"""Реальне підписання згенерованого PDF ключем через UAPKI.

Демонструє повний ланцюг: згенерувати документ -> підписати його файл реальним
ключем (DSTU 4145) через UAPKI -> зібрати ElectronicSignatureMark ПОВНІСТЮ з
розібраного сертифіката -> перегенерувати PDF із КЕП-відміткою та QR за реальними
даними підпису. Підпис (.p7s) зберігається поряд.

Запуск:
    PYTHONPATH=src python3 scripts/sign_pdf_with_uapki.py [output_dir]
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
from dilovod4.infrastructure.pdf_writer import PdfDocumentWriter
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider
from dilovod4.infrastructure.uapki import UapkiLibraryNotFound, sign_file_pkcs12

UAPKI_DATA = (
    Path(__file__).resolve().parents[1]
    / "external" / "UAPKI" / "library" / "test" / "data"
)


def _build_e_document():
    doc = Document(
        doc_id="ENAKAZ-UAPKI-001",
        is_letter=False,
        is_electronic=True,
        requisites=RequisiteSet(True, True, True, True, True, True, False, True, False),
        geometry=Geometry(PaperFormat.A4, PageMargins(30, 10, 20, 20), 1),
        formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
        typography=Typography(True, 14, 10, 15, 28),
        line_spacing=LineSpacing(1.5),
        left_indents=LeftIndents(10, 90, 100, 100, 125),
        page_numbering=PageNumbering(1, False, False, False),
        storage_term=StorageTerm.PERMANENT,
        addressee_count=0,
        appendix_count=0,
        blank=BlankSpec(BlankType.SPECIFIC_VIEW, 9, 2500),
        date=DateSpec(DateStyle.VERBAL_NUMERIC, False),
        symbols=SymbolDimensions(17, 12, 15, 21, 60, 100),
    )
    content = DocumentContent(
        org_name="ДЕРЖАВНЕ ПІДПРИЄМСТВО «ДІЯ»",
        doc_type="Наказ",
        date_text="13 червня 2026 року",
        reg_index="001-уапкі",
        title="Про підписання документа реальним ключем",
        body=(
            "Цей документ підписано кваліфікованим електронним підписом через "
            "бібліотеку UAPKI; відмітку та QR сформовано за даними сертифіката.",
        ),
        signature_position="Директор",
        signature_name="(КЕП)",
    )
    return doc, content


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    out_dir = Path(argv[0]) if argv else Path("samples/uapki_signed")
    out_dir.mkdir(parents=True, exist_ok=True)

    p12 = UAPKI_DATA / "test-diia.p12"
    if not p12.is_file():
        print("Тестовий PKCS#12 недоступний:", p12)
        return 1

    writer = PdfDocumentWriter()
    rule_set = DefaultRuleSetProvider()
    doc, content = _build_e_document()

    # 1) Згенерувати PDF (поки що з placeholder-підписом)
    draft = str(out_dir / "draft.pdf")
    GenerateDocument(writer=writer, rule_set=rule_set).execute(doc, content, draft)
    print(f"[1] Чернетку PDF згенеровано: {draft}")

    # 2) Підписати файл реальним ключем -> розібрати сертифікат
    try:
        res = sign_file_pkcs12(
            file_path=draft,
            pkcs12_path=str(p12),
            password="testpassword",
            cert_cache_dir=str(UAPKI_DATA / "certs"),
            crl_cache_dir=str(UAPKI_DATA / "crls"),
            signature_format="CMS",
            detached=True,  # відокремлений підпис .p7s поряд із PDF
        )
    except UapkiLibraryNotFound:
        print("libuapki не зібрана. Зберіть: external/UAPKI/library/bash build-uapki.sh macos-arm64")
        return 1

    p7s = out_dir / "draft.pdf.p7s"
    p7s.write_bytes(res.container)
    print(f"[2] Файл підписано (CMS, detached). Контейнер: {len(res.container)}B -> {p7s}")

    # 3) Зібрати КЕП-відмітку ПОВНІСТЮ з реального сертифіката
    mark = res.to_signature_mark_auto()
    print(f"[3] Відмітку зібрано з X.509:")
    print(f"      підписувач: {mark.signer}")
    print(f"      сертифікат: {mark.certificate_serial}")
    print(f"      видавець  : {mark.issuer}")
    print(f"      чинний    : {mark.valid_from} – {mark.valid_to}")
    print(f"      позначка  : {mark.timestamp}")
    print(f"      статус    : {'ЧИННИЙ' if mark.certificate_valid else 'НЕДІЙСНИЙ (Art.24)'}")

    # 4) Перегенерувати фінальний PDF із реальною відміткою + QR
    signed_content = DocumentContent(
        org_name=content.org_name,
        doc_type=content.doc_type,
        date_text=content.date_text,
        reg_index=content.reg_index,
        title=content.title,
        body=content.body,
        signature_position=content.signature_position,
        signature_name=content.signature_name,
        e_signature=mark,
    )
    final = str(out_dir / "signed.pdf")
    GenerateDocument(writer=writer, rule_set=rule_set).execute(doc, signed_content, final)
    print(f"[4] Фінальний PDF із реальною КЕП-відміткою та QR: {final}")
    print(f"\nЗгенеровано у: {out_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

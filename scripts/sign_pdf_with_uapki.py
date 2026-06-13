"""Реальне підписання згенерованого PDF ключем через UAPKI.

Повний ланцюг:
  1. згенерувати чернетку PDF;
  2. підписати її, щоб витягти сертифікат і зібрати ElectronicSignatureMark;
  3. перегенерувати ФІНАЛЬНИЙ PDF із КЕП-відміткою та QR за реальними даними;
  4. підписати САМЕ фінальний PDF -> signed.pdf.p7s (detached);
  5. перевірити пару (signed.pdf + signed.pdf.p7s) -> має бути TOTAL-VALID.

Ключове: detached-підпис покриває той файл, що його показують (signed.pdf),
а не чернетку — інакше дайджест не збігається й верифікація провалюється.

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
from dilovod4.infrastructure.uapki import (
    UapkiLibraryNotFound,
    sign_file_pkcs12,
    verify_signature,
)

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


def _sign(path: str, p12: Path):
    return sign_file_pkcs12(
        file_path=path,
        pkcs12_path=str(p12),
        password="testpassword",
        cert_cache_dir=str(UAPKI_DATA / "certs"),
        crl_cache_dir=str(UAPKI_DATA / "crls"),
        signature_format="CAdES-BES",  # SID issuerAndSerial (v1) — сумісно з czo.gov.ua
        detached=True,  # відокремлений підпис .p7s поряд із PDF
        ignore_cert_status=True,  # тестовий сертифікат прострочений/відкликаний
    )


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

    # 1) Чернетка PDF (placeholder-підпис) — лише щоб витягти сертифікат
    draft = str(out_dir / "draft.pdf")
    GenerateDocument(writer=writer, rule_set=rule_set).execute(doc, content, draft)
    print(f"[1] Чернетку згенеровано: {draft}")

    # 2) Підписати чернетку -> розібрати сертифікат -> зібрати відмітку
    try:
        res_draft = _sign(draft, p12)
    except UapkiLibraryNotFound:
        print("libuapki не зібрана: external/UAPKI/library/ -> bash build-uapki.sh macos-arm64")
        return 1
    mark = res_draft.to_signature_mark_auto()
    print(f"[2] Відмітку зібрано з X.509: {mark.signer} | {mark.certificate_serial}")
    print(f"      статус: {'ЧИННИЙ' if mark.certificate_valid else 'НЕДІЙСНИЙ (Art.24)'}")

    # 3) ФІНАЛЬНИЙ PDF із реальною відміткою + QR
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
    print(f"[3] Фінальний PDF із КЕП-відміткою та QR: {final}")

    # 4) Підписати САМЕ фінальний PDF -> signed.pdf.p7s
    res_final = _sign(final, p12)
    p7s = out_dir / "signed.pdf.p7s"
    p7s.write_bytes(res_final.container)
    print(f"[4] Підпис фінального файла: {len(res_final.container)}B -> {p7s}")

    # 5) Перевірити пару (signed.pdf + signed.pdf.p7s)
    verdict = verify_signature(
        res_final.container,
        cert_cache_dir=str(UAPKI_DATA / "certs"),
        crl_cache_dir=str(UAPKI_DATA / "crls"),
        content=Path(final).read_bytes(),
    )
    print(f"[5] Перевірка пари: status={verdict.status} "
          f"(підпис={verdict.status_signature}, дайджест={verdict.status_message_digest})")

    print(f"\nЗгенеровано у: {out_dir.resolve()}")
    # видаляємо застарілий чернетковий підпис, якщо лишився від старих запусків
    old = out_dir / "draft.pdf.p7s"
    if old.exists():
        old.unlink()
    return 0 if verdict.is_valid else 2


if __name__ == "__main__":
    raise SystemExit(main())

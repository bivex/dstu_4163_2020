"""Одноразова генерація ЕЛЕКТРОННИХ листів між ТОВ та АТ — з КЕП + QR."""

from __future__ import annotations

import sys
from pathlib import Path

from dilovod4.application.generate_document import GenerateDocument
from dilovod4.domain.model import (
    BlankSpec,
    BlankType,
    CertificateStatus,
    DateSpec,
    DateStyle,
    Document,
    DocumentContent,
    ElectronicSignatureMark,
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
from dilovod4.infrastructure.pdf_writer import PdfDocumentWriter
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider


def _e_letter(doc_id, reg_index):
    """Електронний лист: реквізит 22 — КЕП (§4.4), бланк листа, без 09."""
    return Document(
        doc_id=doc_id,
        is_letter=True,
        is_electronic=True,
        # для е-документа підпис = електронний підпис (electronic_signature=True)
        requisites=RequisiteSet(True, False, True, True, True, True, False, True, False),
        geometry=Geometry(PaperFormat.A4, PageMargins(30, 10, 20, 20), 1),
        formatting=FormattingSpec(RequisiteAlignment.FLAG, False),
        typography=Typography(True, 14, 10, 15, 28),
        line_spacing=LineSpacing(1.0),
        left_indents=LeftIndents(10, 90, 100, 100, 125),
        page_numbering=PageNumbering(1, False, False, False),
        storage_term=StorageTerm.TEMPORARY,
        addressee_count=1,
        appendix_count=0,
        blank=BlankSpec(BlankType.LETTER, 6, 0),
        date=DateSpec(DateStyle.DIGITAL, False),
        symbols=SymbolDimensions(17, 12, 15, 21, 60, 100),
    )


def tov_to_at():
    doc = _e_letter("ELIST-TOV-2026-118", "118/02-15")
    content = DocumentContent(
        org_name="ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ТЕХНОПРОМ»",
        doc_type="",
        date_text="13.06.2026",
        reg_index="118/02-15",
        title="Щодо постачання обладнання",
        body=(
            "Шановні партнери!",
            "ТОВ «Технопром» пропонує до постачання промислове обладнання згідно з "
            "доданою специфікацією. Умови оплати та строки погоджуються окремо.",
            "Просимо розглянути нашу пропозицію та повідомити про рішення.",
        ),
        signature_position="Директор ТОВ «Технопром»",
        signature_name="М. ЛИСЕНКО",
        addressees=(
            "АКЦІОНЕРНЕ ТОВАРИСТВО «ЕНЕРГОМАШ»\nГенеральному директору\nп. Ковальчуку В. С.",
        ),
        e_signature=ElectronicSignatureMark(
            signer="ЛИСЕНКО Микола Олександрович",
            certificate_serial="3F1A77B0C9D2E465",
            issuer="КН ЕДП «Дія»",
            valid_from="01.03.2026",
            valid_to="01.03.2028",
            timestamp="13.06.2026 18:05:11 EET",
            is_qualified=True,
            status=CertificateStatus.ACTIVE,
        ),
    )
    return doc, content


def at_to_tov():
    doc = _e_letter("ELIST-AT-2026-204", "204/07-09")
    content = DocumentContent(
        org_name="АКЦІОНЕРНЕ ТОВАРИСТВО «ЕНЕРГОМАШ»",
        doc_type="",
        date_text="13.06.2026",
        reg_index="204/07-09",
        title="Про розгляд комерційної пропозиції",
        body=(
            "Шановний пане директоре!",
            "АТ «Енергомаш» розглянуло Вашу комерційну пропозицію від 13.06.2026 "
            "№ 118/02-15 щодо постачання обладнання.",
            "Повідомляємо про готовність укласти договір на запропонованих умовах "
            "після узгодження графіка постачання.",
        ),
        signature_position="Генеральний директор АТ «Енергомаш»",
        signature_name="В. КОВАЛЬЧУК",
        addressees=(
            "ТОВ «ТЕХНОПРОМ»\nДиректору\nп. Лисенку М. О.",
        ),
        e_signature=ElectronicSignatureMark(
            signer="КОВАЛЬЧУК Володимир Сергійович",
            certificate_serial="A20C5E9148BD7F36",
            issuer="АЦСК АТ «КБ «ПРИВАТБАНК»",
            valid_from="15.02.2026",
            valid_to="15.02.2028",
            timestamp="13.06.2026 18:18:47 EET",
            is_qualified=True,
            status=CertificateStatus.ACTIVE,
        ),
    )
    return doc, content


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    out_dir = Path(argv[0]) if argv else Path("samples/tov_at_e")
    rule_set = DefaultRuleSetProvider()
    builders = {"tov_to_at": tov_to_at, "at_to_tov": at_to_tov}

    for fmt, writer in (("docx", DocxDocumentWriter()), ("pdf", PdfDocumentWriter())):
        fmt_dir = out_dir / fmt
        fmt_dir.mkdir(parents=True, exist_ok=True)
        uc = GenerateDocument(writer=writer, rule_set=rule_set)
        for name, builder in builders.items():
            doc, content = builder()
            dest = str(fmt_dir / f"{name}.{fmt}")
            res = uc.execute(doc, content, dest, validate=True)
            r = res.report
            st = "ВІДПОВІДАЄ" if (r and r.conforms) else "НЕ ВІДПОВІДАЄ"
            print(f"[{st}] {res.path}  (знахідок: {r.findings_count if r else '?'})")
            if r and not r.conforms:
                for rr in r.results:
                    for f in rr.findings:
                        print(f"    - {rr.clause} {f.message}")
    print(f"\nЗгенеровано у: {out_dir.resolve()}")


if __name__ == "__main__":
    main()

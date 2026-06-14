"""Електронний наказ із ДВОМА підписантами (директор + головний бухгалтер).

Два підписанти -> дві КЕП у ASiC-E контейнері. PDF несе два блоки підпису
(посада + розшифрування), кожен підписант підписує власний ASiCManifest.
"""

import os
import sys
sys.path.insert(0, "src")

from dilovod4.application.generate_document import GenerateDocument
from dilovod4.domain.model import (
    BlankSpec, BlankType, CertificateStatus, DateSpec, DateStyle, Document,
    DocumentContent, ElectronicSignatureMark, FormattingSpec, Geometry,
    LeftIndents, LineSpacing, PageMargins, PageNumbering, PaperFormat,
    RequisiteAlignment, RequisiteSet, StorageTerm, SymbolDimensions, Typography,
)
from dilovod4.infrastructure.pdf_writer import PdfDocumentWriter
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider

body = [
    "Відповідно до Закону України «Про електронну ідентифікацію та електронні "
    "довірчі послуги» та з метою впорядкування фінансово-господарської діяльності "
    "установи НАКАЗУЮ:",
    "1. Затвердити кошторис витрат на придбання кваліфікованих сертифікатів "
    "відкритих ключів та захищених носіїв особистих ключів на 2026 рік.",
    "2. Головному бухгалтеру забезпечити облік та оплату послуг кваліфікованих "
    "надавачів електронних довірчих послуг у межах затвердженого кошторису.",
    "3. Контроль за виконанням цього наказу залишаю за собою.",
]

doc = Document(
    doc_id="ENAKAZ-2SIGN-001", is_letter=False, is_electronic=True,
    requisites=RequisiteSet(True, True, True, True, True, True, False, True, False),
    geometry=Geometry(PaperFormat.A4, PageMargins(30, 10, 20, 20), 1),
    formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
    typography=Typography(True, 14, 10, 15, 28),
    line_spacing=LineSpacing(1.5),
    left_indents=LeftIndents(10, 90, 100, 100, 125),
    page_numbering=PageNumbering(1, False, True, False),
    storage_term=StorageTerm.PERMANENT,
    addressee_count=0, appendix_count=0,
    blank=BlankSpec(BlankType.SPECIFIC_VIEW, 9, 2500),
    date=DateSpec(DateStyle.VERBAL_NUMERIC, False),
    symbols=SymbolDimensions(17, 12, 15, 21, 60, 100),
)
content = DocumentContent(
    org_name="ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ТЕХНОПРОМ»",
    doc_type="Наказ",
    date_text="14 червня 2026 року",
    reg_index="58-фг",
    title="Про затвердження кошторису на електронні довірчі послуги",
    body=tuple(body),
    signature_position=" ",
    signature_name=" ",
    e_signatures=(
        ElectronicSignatureMark(
            signer="ПЕТРЕНКО Олександр Іванович",
            certificate_serial="3FAA9288358EC00304000000ABD43A000104E000",
            issuer="КНЕДП ДПС",
            valid_from="07.02.2025", valid_to="05.02.2027",
            timestamp="14.06.2026 02:31:09 EET",
            is_qualified=True, status=CertificateStatus.ACTIVE,
        ),
        ElectronicSignatureMark(
            signer="КОВАЛЕНКО Наталія Сергіївна",
            certificate_serial="10FF6F932221FA003FD01C00000000010E66F73F",
            issuer="КНЕДП monobank | Universal Bank",
            valid_from="31.05.2026", valid_to="30.05.2028",
            timestamp="14.06.2026 02:30:24 EET",
            is_qualified=True, status=CertificateStatus.ACTIVE,
        ),
    ),
)

os.makedirs("samples/two_sign", exist_ok=True)
dest = "samples/two_sign/nakaz_2sign.pdf"
GenerateDocument(writer=PdfDocumentWriter(), rule_set=DefaultRuleSetProvider()).execute(
    doc, content, dest)
print("generated:", dest)

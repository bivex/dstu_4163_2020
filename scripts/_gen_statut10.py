"""Статут (~3 стор.) із 10 підписантами — 10 QR + 10 КЕП-відміток."""

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

# розділи статуту — щоб вийшло ~3 сторінки
body = [
    "1. ЗАГАЛЬНІ ПОЛОЖЕННЯ",
    "1.1. Товариство з обмеженою відповідальністю «ТЕХНОПРОМ» (далі — Товариство) "
    "створене відповідно до Цивільного кодексу України, Господарського кодексу "
    "України та Закону України «Про товариства з обмеженою та додатковою "
    "відповідальністю» на підставі рішення загальних зборів засновників.",
    "1.2. Товариство є юридичною особою приватного права, має самостійний баланс, "
    "рахунки в банках, печатку зі своїм найменуванням, кваліфіковані електронні "
    "підписи уповноважених осіб та інші реквізити.",
    "1.3. Товариство набуває прав та обовʼязків юридичної особи з дня його "
    "державної реєстрації у порядку, встановленому законодавством України.",
    "2. НАЙМЕНУВАННЯ ТА МІСЦЕЗНАХОДЖЕННЯ",
    "2.1. Повне найменування: Товариство з обмеженою відповідальністю «ТЕХНОПРОМ». "
    "Скорочене найменування: ТОВ «ТЕХНОПРОМ».",
    "2.2. Місцезнаходження Товариства визначається у Єдиному державному реєстрі "
    "юридичних осіб, фізичних осіб-підприємців та громадських формувань.",
    "3. МЕТА ТА ПРЕДМЕТ ДІЯЛЬНОСТІ",
    "3.1. Метою діяльності Товариства є здійснення господарської діяльності для "
    "одержання прибутку та задоволення суспільних потреб у товарах, роботах і "
    "послугах у сфері інформаційних технологій та електронних довірчих послуг.",
    "3.2. Предметом діяльності є розроблення програмного забезпечення, надання "
    "послуг з кваліфікованого електронного підпису, консультування з питань "
    "інформатизації та інша діяльність, не заборонена законодавством.",
    "4. СТАТУТНИЙ КАПІТАЛ",
    "4.1. Статутний капітал Товариства формується з вкладів його учасників та "
    "визначається у розмірі, погодженому загальними зборами учасників.",
    "4.2. Розмір частки кожного учасника у статутному капіталі пропорційний "
    "вартості його вкладу та визначає кількість голосів на загальних зборах.",
    "4.3. Зміна розміру статутного капіталу здійснюється за рішенням загальних "
    "зборів учасників із внесенням відповідних змін до цього Статуту.",
    "5. ОРГАНИ УПРАВЛІННЯ",
    "5.1. Вищим органом Товариства є загальні збори учасників. Виконавчим "
    "органом є директор, який здійснює керівництво поточною діяльністю.",
    "5.2. Рішення загальних зборів оформлюються протоколом і підписуються "
    "кваліфікованими електронними підписами всіх присутніх учасників.",
    "6. ПРИКІНЦЕВІ ПОЛОЖЕННЯ",
    "6.1. Цей Статут набирає чинності з дня державної реєстрації. Усі зміни до "
    "Статуту оформлюються в електронній формі та підписуються КЕП учасників.",
    "6.2. Питання, не врегульовані цим Статутом, вирішуються відповідно до "
    "чинного законодавства України.",
]

# 10 підписантів (засновники/учасники)
_NAMES = [
    ("ПЕТРЕНКО Олександр Іванович", "КНЕДП ДПС"),
    ("КОВАЛЕНКО Наталія Сергіївна", "КНЕДП monobank | Universal Bank"),
    ("ШЕВЧЕНКО Тарас Григорович", "КН ЕДП «Дія»"),
    ("БОНДАРЕНКО Ірина Петрівна", "АЦСК АТ КБ «ПРИВАТБАНК»"),
    ("ТКАЧЕНКО Андрій Васильович", "КНЕДП ДПС"),
    ("МЕЛЬНИК Оксана Михайлівна", "КН ЕДП «Дія»"),
    ("КРАВЧЕНКО Дмитро Олегович", "КНЕДП monobank | Universal Bank"),
    ("ОЛІЙНИК Світлана Юріївна", "АЦСК АТ КБ «ПРИВАТБАНК»"),
    ("ЛИСЕНКО Микола Анатолійович", "КНЕДП ДПС"),
    ("МАРЧЕНКО Вікторія Романівна", "КН ЕДП «Дія»"),
]
sigs = tuple(
    ElectronicSignatureMark(
        signer=name,
        certificate_serial=f"{(i + 1) * 1111:08X}{'AB12CD34EF56':>12}"[:40].replace(" ", "0"),
        issuer=issuer,
        valid_from="01.01.2026", valid_to="01.01.2028",
        timestamp=f"14.06.2026 03:{i:02d}:00 EET",
        is_qualified=True, status=CertificateStatus.ACTIVE,
    )
    for i, (name, issuer) in enumerate(_NAMES)
)

doc = Document(
    doc_id="STATUT-10SIGN-001", is_letter=False, is_electronic=True,
    requisites=RequisiteSet(True, True, True, True, True, True, False, True, False),
    geometry=Geometry(PaperFormat.A4, PageMargins(30, 10, 20, 20), 1),
    formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
    typography=Typography(True, 14, 10, 15, 28),
    line_spacing=LineSpacing(1.5),
    left_indents=LeftIndents(10, 90, 100, 100, 125),
    page_numbering=PageNumbering(3, False, True, False),
    storage_term=StorageTerm.PERMANENT,
    addressee_count=0, appendix_count=0,
    blank=BlankSpec(BlankType.GENERAL, 9, 2500),
    date=DateSpec(DateStyle.VERBAL_NUMERIC, False),
    symbols=SymbolDimensions(17, 12, 15, 21, 60, 100),
)
content = DocumentContent(
    org_name="ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ТЕХНОПРОМ»",
    doc_type="Статут",
    date_text="14 червня 2026 року",
    reg_index="1",
    title="Затверджено загальними зборами учасників (Протокол № 1)",
    body=tuple(body),
    signature_position=" ",
    signature_name=" ",
    e_signatures=sigs,
)

os.makedirs("samples/statut", exist_ok=True)
dest = "samples/statut/statut_10sign.pdf"
GenerateDocument(writer=PdfDocumentWriter(), rule_set=DefaultRuleSetProvider()).execute(
    doc, content, dest)
print("generated:", dest)

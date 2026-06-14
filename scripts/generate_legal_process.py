"""Генератор документа наскрізного процесу: один е-наказ, що задіює УСІ
кодовані НПА (domain/law) і відображає юридичну трасу прямо в тексті.

Сценарій: ДП «УКРНДНЦ» затверджує та оприлюднює річну фінансову звітність,
підписану КЕП, з обмеженим доступом до частини відомостей, у відповідь на
що надається доступ за запитом. Кожен крок процесу обчислюється чистою нормою
з domain/law, а результат (закон, стаття, вердикт) друкується у тілі документа.

Задіяні закони:
  • № 996-XIV  — категорія підприємства, реквізити первинного документа,
                 обовʼязковість МСФЗ, звітний період, строк оприлюднення;
  • № 851-IV   — завершення створення е-документа, оригінал, цілісність, зберігання;
  • № 80/94-ВР — обробка та захист у ІКС;
  • № 2297-VI  — обробка персональних даних у звітності;
  • № 2657-XII — режим інформації з обмеженим доступом;
  • № 2939-VI  — доступ до публічної інформації за запитом.

Документ також несе КЕП-відмітку (реквізит 22) та гриф обмеження доступу
(реквізит 15), тож проходить правила ELECTRONIC_ORIGINAL (ст.7 851-IV) та
ACCESS_RESTRICTION (ст.21 2657-XII) під час валідації.

Запуск:
    PYTHONPATH=src python3 scripts/generate_legal_process.py [output_dir]
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from dilovod4.application.generate_document import GenerateDocument
from dilovod4.domain import law
from dilovod4.domain.model import (
    AccessRestriction,
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
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider


@dataclass(frozen=True)
class Step:
    law_no: str  # номер закону
    article: str  # стаття
    question: str  # що перевіряється
    verdict: bool  # результат норми
    detail: str  # людиночитний підсумок


def _ok(b: bool) -> str:
    return "ВІДПОВІДАЄ" if b else "НЕ ВІДПОВІДАЄ"


def build_legal_trace() -> list[Step]:
    """Прогнати чисті норми domain/law для сценарію та зібрати юридичну трасу."""
    steps: list[Step] = []

    # === Закон № 996-XIV — бухоблік та фінансова звітність ===
    metrics = law.SizeMetrics(
        balance_assets_eur=18_000_000, net_revenue_eur=35_000_000, avg_employees=180
    )
    size = law.enterprise_size(metrics)
    steps.append(
        Step(
            "996-XIV", "ст.2",
            "категорія підприємства за критеріями 2-з-3",
            size is law.EnterpriseSize.MEDIUM,
            f"підприємство віднесено до категорії: {size.value} (середнє)",
        )
    )

    pd = law.PrimaryDocRequisites(
        has_title=True, has_date=True, has_enterprise_name=True,
        has_operation_content=True, has_responsible_persons=True, has_signature=True,
    )
    pd_ok = law.primary_doc_valid(pd)
    steps.append(
        Step(
            "996-XIV", "ст.9(2)",
            "обовʼязкові реквізити первинного документа",
            pd_ok,
            "первинний документ містить усі обовʼязкові реквізити (паралель §4.4 ДСТУ)",
        )
    )

    ifrs = law.IfrsObligation(
        public_interest_entity=True, public_joint_stock=False, extractive_industry=False,
        large_group_parent=False, government_listed_activity=False,
    )
    ifrs_req = law.ifrs_mandatory(ifrs)
    steps.append(
        Step(
            "996-XIV", "ст.12-1(2)",
            "обовʼязковість складання звітності за МСФЗ",
            ifrs_req,
            "як підприємство, що становить суспільний інтерес — звітує за МСФЗ",
        )
    )

    period_ok = law.reporting_period_valid(is_newly_created=False, period_months=12)
    steps.append(
        Step(
            "996-XIV", "ст.13",
            "звітний період фінансової звітності",
            period_ok,
            "звітний період — календарний рік (12 місяців)",
        )
    )

    pub_in_time = law.published_in_time(
        law.PublisherKind.PUBLIC_INTEREST_NON_LARGE_ISSUER, publication_day_of_year=118
    )
    steps.append(
        Step(
            "996-XIV", "ст.14(3)",
            "строк оприлюднення річної звітності (до 30 квітня)",
            pub_in_time,
            "звітність оприлюднено 28 квітня — у межах строку",
        )
    )

    # === Закон № 851-IV — електронні документи ===
    created = law.creation_completed(signatures_applied=2, seals_applied=0, required_signers=2)
    steps.append(
        Step(
            "851-IV", "ст.6",
            "завершення створення е-документа (накладання КЕП)",
            created,
            "наказ підписано обома підписувачами — створення завершено",
        )
    )

    original = law.is_original(
        has_mandatory_requisites=True, has_author_signature=True, integrity_provable=True
    )
    steps.append(
        Step(
            "851-IV", "ст.7",
            "статус оригіналу електронного документа",
            original,
            "реквізити + підпис автора + доказувана цілісність — є оригіналом",
        )
    )

    integrity = law.integrity_verifiable(law.SignatureKind.QUALIFIED)
    steps.append(
        Step(
            "851-IV", "ст.12",
            "перевірка цілісності е-документа",
            integrity,
            "цілісність підтверджується кваліфікованим підписом (КЕП)",
        )
    )

    storage = law.storage_admissible(
        law.StorageState(
            e_storage_term_days=2555, paper_term_days=2190,
            information_accessible=True, format_restorable=True, origin_metadata_kept=True,
        )
    )
    steps.append(
        Step(
            "851-IV", "ст.13",
            "припустимість зберігання е-документа",
            storage,
            "строк зберігання ≥ паперового, умови збереження виконано",
        )
    )

    # === Закон № 80/94-ВР — захист інформації в ІКС ===
    proc = law.system_processing_compliant(
        law.ProcessingSetup(
            category=law.InfoCategory.RESTRICTED_BY_LAW,
            owner_type=law.SystemOwnerType.PUBLIC_SECTOR,
            security_authorized=True, has_conformity_certificate=False,
        )
    )
    steps.append(
        Step(
            "80/94-ВР", "ст.8",
            "умови обробки інформації з обмеженим доступом у ІКС",
            proc,
            "обробка в авторизованій з безпеки системі публічного сектору",
        )
    )

    prot = law.protection_compliant(
        law.ProtectionSetup(
            category=law.InfoCategory.RESTRICTED_BY_LAW,
            owner_type=law.SystemOwnerType.PUBLIC_SECTOR,
            cyber_defence_unit_established=True,
        )
    )
    steps.append(
        Step(
            "80/94-ВР", "ст.9",
            "забезпечення захисту (підрозділ із кіберзахисту)",
            prot,
            "утворено підрозділ із кіберзахисту — захист забезпечено",
        )
    )

    # === Закон № 2297-VI — захист персональних даних ===
    pdp = law.processing_compliant(
        law.GeneralRequirements(
            purpose_defined_in_law=True, data_adequate_not_excessive=True,
            accurate_and_updated=True, retained_no_longer_than_needed=True,
        )
    )
    steps.append(
        Step(
            "2297-VI", "ст.6",
            "загальні вимоги до обробки персональних даних у звітності",
            pdp,
            "ПІБ керівників у звітності оброблюються правомірно (мета, адекватність)",
        )
    )

    lawful = law.processing_lawful(law.ProcessingBasis.LEGAL_OBLIGATION_OF_CONTROLLER)
    steps.append(
        Step(
            "2297-VI", "ст.11",
            "підстава для обробки персональних даних",
            lawful,
            "підстава — виконання обовʼязку володільця за законом",
        )
    )

    # === Закон № 2657-XII — інформація з обмеженим доступом ===
    restr = law.restriction_lawful(
        law.UndisclosableTopic.OTHER_TOPIC,
        law.RestrictionTest(
            restriction_provided_by_law=True, legitimate_aim=True,
            harm_outweighs_public_interest=True,
        ),
    )
    steps.append(
        Step(
            "2657-XII", "ст.21",
            "правомірність обмеження доступу до частини відомостей",
            restr,
            "обмеження витримує трискладовий тест (ст.6(2))",
        )
    )

    # === Закон № 2939-VI — доступ до публічної інформації ===
    # фінзвітність — НЕ обмежений доступ (ст.14(2) 996-XIV); тема не підлягає обмеженню
    pub_restr = law.public_restriction_lawful(
        law.NonRestrictableTopic.BUDGET_USE_PROCUREMENT,
        law.ThreePartTest(
            legitimate_interest=True, substantial_harm=True, harm_outweighs_public_interest=True,
        ),
    )
    steps.append(
        Step(
            "2939-VI", "ст.6(5)",
            "спроба обмежити доступ до бюджетних відомостей",
            not pub_restr,  # правомірний результат — обмеження НЕ допускається
            "доступ до бюджетних відомостей обмежити НЕ можна — надається у повному обсязі",
        )
    )

    in_time = law.response_deadline_working_days(law.RequestUrgency.ORDINARY) == 5
    steps.append(
        Step(
            "2939-VI", "ст.20",
            "строк розгляду запиту на публічну інформацію",
            in_time,
            "відповідь на запит надається не пізніше 5 робочих днів",
        )
    )

    return steps


def _trace_paragraphs(steps: list[Step]) -> tuple[str, ...]:
    """Сформувати абзаци тіла документа з юридичної траси."""
    paras = [
        "З метою затвердження та оприлюднення річної фінансової звітності за "
        "звітний рік, складеної за міжнародними стандартами, та забезпечення "
        "правомірного режиму доступу до неї НАКАЗУЮ:",
        "1. Затвердити річну фінансову звітність підприємства за звітний рік.",
        "2. Оприлюднити звітність на офіційному вебсайті у строк, визначений "
        "законодавством, та забезпечити її зберігання.",
        "3. Контроль за виконанням наказу залишаю за собою.",
        "ЮРИДИЧНЕ ОБҐРУНТУВАННЯ (автоматична перевірка за кодованими НПА):",
    ]
    for i, s in enumerate(steps, 1):
        paras.append(
            f"{i}. Закон № {s.law_no}, {s.article} — {s.question}: "
            f"{_ok(s.verdict)}. {s.detail}."
        )
    return tuple(paras)


def build_process_document() -> tuple[Document, DocumentContent]:
    doc = Document(
        doc_id="NAKAZ-FIN-2026-050",
        is_letter=False,
        is_electronic=True,
        requisites=RequisiteSet(True, True, True, True, True, True, False, True, False),
        geometry=Geometry(
            paper_format=PaperFormat.A4,
            margins=PageMargins(left=30, right=10, top=20, bottom=20),
            requisite_offset_mm=1,
        ),
        formatting=FormattingSpec(RequisiteAlignment.CENTERED, False),
        typography=Typography(
            is_times_new_roman=True, body_size_pt=14, small_size_pt=10,
            doc_type_size_pt=15, multiline_row_chars=28,
        ),
        line_spacing=LineSpacing(1.5),
        left_indents=LeftIndents(
            paragraph_mm=10, addressee_mm=90, approval_mm=100,
            restriction_mm=100, signature_decode_mm=125,
        ),
        page_numbering=PageNumbering(2, False, True, False),
        storage_term=StorageTerm.PERMANENT,
        addressee_count=0, appendix_count=0,
        blank=BlankSpec(BlankType.SPECIFIC_VIEW, 9, 2500),
        date=DateSpec(DateStyle.VERBAL_NUMERIC, False),
        symbols=SymbolDimensions(
            coat_of_arms_height_mm=17, coat_of_arms_width_mm=12, emblem_height_mm=15,
            qr_side_mm=21, registration_zone_height_mm=60, registration_zone_width_mm=100,
        ),
    )
    steps = build_legal_trace()
    content = DocumentContent(
        org_name="ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        doc_type="Наказ",
        date_text="28 квітня 2026 року",
        reg_index="050-фін",
        title="Про затвердження та оприлюднення річної фінансової звітності",
        body=_trace_paragraphs(steps),
        signature_position="Директор",
        signature_name="О. ПЕТРЕНКО",
        # реквізит 22 — КЕП-відмітка (ст.6/7/12 851-IV ↔ Art.24 2155-VIII)
        e_signatures=(
            ElectronicSignatureMark(
                signer="ПЕТРЕНКО Олександр Іванович",
                certificate_serial="58E2D9C1F0A4B7E3",
                issuer="КН ЕДП «Дія»",
                valid_from="01.01.2026", valid_to="01.01.2028",
                timestamp="28.04.2026 09:15:00 EET",
                is_qualified=True, status=CertificateStatus.ACTIVE,
            ),
            ElectronicSignatureMark(
                signer="ТКАЧЕНКО Наталія Сергіївна",
                certificate_serial="A1B2C3D4E5F60789",
                issuer="КН ЕДП «Дія»",
                valid_from="01.01.2026", valid_to="01.01.2028",
                timestamp="28.04.2026 09:16:30 EET",
                is_qualified=True, status=CertificateStatus.ACTIVE,
            ),
        ),
        # реквізит 15 — гриф обмеження доступу (ст.21 2657-XII) на частину відомостей
        access_restriction=AccessRestriction(
            kind=law.RestrictedKind.OFFICIAL,
            topic=law.UndisclosableTopic.OTHER_TOPIC,
            test=law.RestrictionTest(
                restriction_provided_by_law=True, legitimate_aim=True,
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
    doc, content = build_process_document()

    # друк траси у консоль для наочності
    print("Юридична траса процесу (закони, що задіяні):")
    laws_used = sorted({s.law_no for s in build_legal_trace()})
    print("  задіяно НПА:", ", ".join(f"№{n}" for n in laws_used))

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
        dest = str(fmt_dir / f"nakaz_process.{ext}")
        result = use_case.execute(doc, content, dest, validate=True)
        report = result.report
        status = "ВІДПОВІДАЄ" if (report and report.conforms) else "НЕ ВІДПОВІДАЄ"
        findings = report.findings_count if report else "?"
        print(f"[{status}] {result.path}  (знахідок ДСТУ/НПА: {findings})")
        if report and not report.conforms:
            exit_code = 1
            for r in report.results:
                for f in r.findings:
                    print(f"    - {r.clause} {f.message}")

    print(f"\nЗгенеровано у: {out_dir.resolve()}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

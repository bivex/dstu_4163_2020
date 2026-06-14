"""Міст порталу до доменного ядра dilovod4.

Будує конформні Document + DocumentContent з мінімального вводу користувача
(організація, вид, заголовок, текст, підписанти): геометрія, поля, типографіка
беруться конформними за замовчуванням (як у scripts/generate_*). Користувач
не зобовʼязаний задавати § ДСТУ — портал гарантує відповідність.

Також: генерація PDF/DOCX, валідація за ДСТУ+7 НПА, перевірка КЕП-відмітки.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Any

# доменне ядро лежить у ../src
_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from dilovod4.application.generate_document import GenerateDocument  # noqa: E402
from dilovod4.application.validate_document import ValidateDocument  # noqa: E402
from dilovod4.domain.model import (  # noqa: E402
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
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider  # noqa: E402

_RULE_SET = DefaultRuleSetProvider()


def _conformant_document(doc_id: str, is_electronic: bool) -> Document:
    """Повністю конформний за ДСТУ 4163:2020 Document (загальний бланк, A4)."""
    return Document(
        doc_id=doc_id,
        is_letter=False,
        is_electronic=is_electronic,
        requisites=RequisiteSet(True, True, True, True, True, True,
                                not is_electronic, is_electronic, False),
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
        blank=BlankSpec(BlankType.GENERAL, 4, 0),
        date=DateSpec(DateStyle.VERBAL_NUMERIC, False),
        symbols=SymbolDimensions(
            coat_of_arms_height_mm=17, coat_of_arms_width_mm=12, emblem_height_mm=15,
            qr_side_mm=21, registration_zone_height_mm=60, registration_zone_width_mm=100,
        ),
    )


def _mark_from_dict(d: dict[str, Any]) -> ElectronicSignatureMark:
    return ElectronicSignatureMark(
        signer=str(d["signer"]),
        certificate_serial=str(d.get("certificate_serial", "—")),
        issuer=str(d.get("issuer", "—")),
        valid_from=str(d.get("valid_from", "")),
        valid_to=str(d.get("valid_to", "")),
        timestamp=str(d.get("timestamp", "")),
        is_qualified=bool(d.get("is_qualified", True)),
        status=CertificateStatus(d.get("status", "Active")),
        signer_position=str(d.get("signer_position", "")),
    )


def build_content(payload: dict[str, Any]) -> DocumentContent:
    """DocumentContent з payload порталу (мінімальний ввід користувача)."""
    return DocumentContent(
        org_name=str(payload["org_name"]),
        doc_type=str(payload.get("doc_type", "Наказ")),
        date_text=str(payload.get("date_text", "")),
        reg_index=str(payload.get("reg_index", "")),
        title=str(payload.get("title", "")),
        body=tuple(payload.get("body", ())),
        signature_position=str(payload.get("signature_position", "")),
        signature_name=str(payload.get("signature_name", "")),
        e_signatures=tuple(_mark_from_dict(m) for m in payload.get("e_signatures", ())),
    )


def generate(payload: dict[str, Any], fmt: str, dest_path: str) -> dict[str, Any]:
    """Згенерувати документ + валідація за ДСТУ/НПА. Повертає шлях і звіт."""
    is_electronic = bool(payload.get("is_electronic", True))
    doc = _conformant_document(str(payload["doc_id"]), is_electronic)
    content = build_content(payload)

    if fmt == "pdf":
        from dilovod4.infrastructure.pdf_writer import PdfDocumentWriter

        writer = PdfDocumentWriter()
    else:
        from dilovod4.infrastructure.docx_writer import DocxDocumentWriter

        writer = DocxDocumentWriter()

    use_case = GenerateDocument(writer=writer, rule_set=_RULE_SET)
    result = use_case.execute(doc, content, dest_path, validate=True)
    return {"path": result.path, "report": _report_to_dict(result.report)}


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    """Перевірити документ за ДСТУ 4163 + content-aware правилами (ст.7/21)."""
    is_electronic = bool(payload.get("is_electronic", True))
    doc = _conformant_document(str(payload["doc_id"]), is_electronic)
    content = build_content(payload)
    report = ValidateDocument(rule_set=_RULE_SET).execute(doc, content)
    return _report_to_dict(report) or {}


def _report_to_dict(report: Any) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "doc_id": report.doc_id,
        "conforms": report.conforms,
        "findings_count": report.findings_count,
        "results": [
            {
                "rule_id": r.rule_id,
                "clause": r.clause,
                "conforms": r.conforms,
                "findings": [
                    {"clause": f.clause, "message": f.message, "severity": f.severity}
                    for f in r.findings
                ],
            }
            for r in report.results
        ],
    }


def content_to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def content_from_json(s: str) -> dict[str, Any]:
    return json.loads(s)


def build_asice(
    doc_id: str, fmt: str, rendered: bytes, signatures: list[tuple[str, bytes]], dest_path: str
) -> str:
    """Зібрати ASiC-E контейнер: документ + КЕП-підписи підписантів.

    signatures — [(label, cms_bytes), ...] у порядку черги.

    ОБМЕЖЕННЯ (скелет): фронт EUSign підписує САМІ ДАНІ (internal CAdES), а
    суворий ASiC-E за ETSI EN 319 162-1 вимагає detached-CAdES НАД МАНІФЕСТОМ.
    Тут пакуємо отримані підписи як signatureNNN.p7s — контейнер містить усі
    КЕП і документ, придатний для архіву/передачі, але для суворої ETSI-
    валідації клієнт має підписувати manifest_for(i, data_files) (TODO продакшн).
    """
    from dilovod4.infrastructure.asic import AsicSignature, build_asic_e

    data_files = [(f"{doc_id}.{fmt}", rendered)]
    sigs = [AsicSignature(cms=cms, label=label) for label, cms in signatures]
    return build_asic_e(data_files, sigs, dest_path)

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


def _subject_name(payload: dict[str, Any]) -> str:
    """Реквізит «найменування» (§5.4 ДСТУ 4163) залежно від типу суб'єкта.

    legal (юрособа) — назва як є («ДЕРЖАВНЕ ПІДПРИЄМСТВО …»).
    fop (ФОП) — ПІБ підприємця з префіксом «ФІЗИЧНА ОСОБА — ПІДПРИЄМЕЦЬ».
    person (фізична особа) — ПІБ як є (без префікса).
    """
    name = str(payload.get("org_name", "")).strip()
    st = str(payload.get("subject_type", "legal"))
    if st == "fop":
        low = name.lower()
        if "фізична особа" not in low and "фоп" not in low:
            name = f"ФІЗИЧНА ОСОБА — ПІДПРИЄМЕЦЬ {name}"
    # person і legal — назва/ПІБ як є
    return name


def build_content(payload: dict[str, Any], *, with_marks: bool = False) -> DocumentContent:
    """DocumentContent з payload порталу (мінімальний ввід користувача).

    with_marks=False (за замовч.) — БЕЗ відміток про КЕП: чистий документ для
    чернетки та для накладання підпису (саме його digest підписується).
    with_marks=True — з e_signatures (відмітка+QR), будується ПІСЛЯ реального
    підпису з даних сертифікатів.
    """
    e_sigs = tuple(_mark_from_dict(m) for m in payload.get("e_signatures", ())) \
        if with_marks else ()
    doc_type = str(payload.get("doc_type", "Наказ"))
    # «Заголовок» — це заголовок до тексту (про що документ), а не вид документа.
    # Якщо користувач продублював вид у полі заголовка (напр. doc_type=«Заява» і
    # title=«Заява»), не друкуємо його вдруге — вид уже виводиться як назва документа.
    title = str(payload.get("title", ""))
    if title.strip().lower() == doc_type.strip().lower():
        title = ""
    return DocumentContent(
        org_name=_subject_name(payload),
        doc_type=doc_type,
        date_text=str(payload.get("date_text", "")),
        reg_index=str(payload.get("reg_index", "")),
        title=title,
        body=tuple(payload.get("body", ())),
        signature_position=str(payload.get("signature_position", "")),
        signature_name=str(payload.get("signature_name", "")),
        e_signatures=e_sigs,
    )


def generate(payload: dict[str, Any], fmt: str, dest_path: str) -> dict[str, Any]:
    """Згенерувати ЧИСТИЙ документ (без відміток про КЕП) + валідація.

    Чернетка не містить відміток про підпис — вони з'являються лише після
    реального накладання КЕП (render_marked). Валідація ж виконується над
    представленням із запланованими підписами (ст.7 851-IV вимагає підпис
    для е-оригіналу), тож звіт показує відповідність майбутнього підписаного
    документа, а сам згенерований файл лишається чистим.
    """
    is_electronic = bool(payload.get("is_electronic", True))
    doc = _conformant_document(str(payload["doc_id"]), is_electronic)
    clean_content = build_content(payload, with_marks=False)

    writer = _writer_for(fmt, pagination_barcode=bool(payload.get("pagination_barcode", False)))

    # рендер чистого документа (без e_signatures)
    path = writer.write(doc, clean_content, dest_path)

    # валідація — над представленням із запланованими КЕП-відмітками
    validation_content = build_content(payload, with_marks=True)
    report = ValidateDocument(rule_set=_RULE_SET).execute(doc, validation_content)

    # PDF/A-3 (ISO 19005-3) — окрема інформаційна перевірка архівної придатності
    # згенерованого PDF. НЕ змішується з conforms ДСТУ (інакше невбудований
    # стандартний шрифт reportlab завалив би валідацію документа).
    pdfa_info: dict[str, Any] | None = None
    if fmt == "pdf":
        try:
            from dilovod4.infrastructure.pdfa_inspector import inspect_pdfa

            with open(path, "rb") as fh:
                chk = inspect_pdfa(fh.read(), require_xmp=False)
            pdfa_info = {"conforms": chk.conforms, "findings": list(chk.findings)}
        except Exception:  # noqa: BLE001 — інформаційно, не валимо генерацію
            pdfa_info = None

    return {"path": path, "report": _report_to_dict(report), "pdfa": pdfa_info}


def render_marked(payload: dict[str, Any], fmt: str, dest_path: str) -> str:
    """Згенерувати документ З відмітками про КЕП + QR (після реального підпису).

    payload["e_signatures"] має містити реальні дані сертифікатів підписантів
    (ПІБ, серійник, видавець, чинність, час). Повертає шлях до файлу.
    """
    is_electronic = bool(payload.get("is_electronic", True))
    doc = _conformant_document(str(payload["doc_id"]), is_electronic)
    marked_content = build_content(payload, with_marks=True)
    writer = _writer_for(fmt, pagination_barcode=bool(payload.get("pagination_barcode", False)))
    return writer.write(doc, marked_content, dest_path)


def _writer_for(fmt: str, *, pagination_barcode: bool = False):
    if fmt == "pdf":
        from dilovod4.infrastructure.pdf_writer import PdfDocumentWriter

        return PdfDocumentWriter(pagination_barcode=pagination_barcode)
    from dilovod4.infrastructure.docx_writer import DocxDocumentWriter

    return DocxDocumentWriter()


def validate(payload: dict[str, Any]) -> dict[str, Any]:
    """Перевірити документ за ДСТУ 4163 + content-aware правилами (ст.7/21)."""
    is_electronic = bool(payload.get("is_electronic", True))
    doc = _conformant_document(str(payload["doc_id"]), is_electronic)
    content = build_content(payload, with_marks=True)
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
    """Зібрати ASiC-E контейнер: документ + detached-CAdES підписи над манІфестами.

    signatures — [(label, detached_cms_bytes), ...] у порядку черги; i-та підпис
    має бути detached-CAdES над manifest_for(i+1, data_files) — саме ці байти
    клієнт отримує з manifest_for_signer() і підписує. build_asic_e перебудовує
    ідентичні манІфести (та сама _build_manifest), тож digest співпадає й
    контейнер проходить ETSI-перевірку.
    """
    from dilovod4.infrastructure.asic import AsicSignature, build_asic_e

    data_files = [(f"{doc_id}.{fmt}", rendered)]
    sigs = [AsicSignature(cms=cms, label=label) for label, cms in signatures]
    return build_asic_e(data_files, sigs, dest_path)


def manifest_for_signer(doc_id: str, fmt: str, rendered: bytes, order_index: int) -> bytes:
    """Точні байти ASiCManifest, які підписант №order_index має підписати detached.

    order_index 0-based (як у черзі) → signatureNNN з NNN=order_index+1.
    Клієнт підписує саме ці байти (detached CAdES), повертає p7s — build_asice
    перебудує ідентичний манІфест, тож підпис верифікується.
    """
    from dilovod4.infrastructure.asic import manifest_for

    data_files = [(f"{doc_id}.{fmt}", rendered)]
    return manifest_for(order_index + 1, data_files)


def _rdn(dn: str, key: str) -> str:
    """Витягти значення RDN (напр. CN, serialNumber) з рядка openssl subject/issuer."""
    import re

    m = re.search(rf"(?:^|,)\s*{key}=([^,]+)", dn)
    return m.group(1).strip() if m else ""


def cert_info_from_cms(sig_bytes: bytes) -> dict[str, str]:
    """Витягти дані сертифіката підписанта з CMS/p7s (DSTU4145) через openssl.

    Дані беруться із САМОГО підпису (не довіряємо клієнту): ПІБ підписувача
    (subject CN), видавець (issuer CN), серійний номер сертифіката, строк дії.
    Повертає {} якщо розбір не вдався (підпис лишиться без розшифрованих даних).
    """
    import re
    import subprocess
    import tempfile

    info: dict[str, str] = {}
    with tempfile.NamedTemporaryFile(suffix=".p7s", delete=False) as tmp:
        tmp.write(sig_bytes)
        path = tmp.name
    try:
        # subject / issuer
        certs = subprocess.run(
            ["openssl", "pkcs7", "-inform", "DER", "-in", path, "-print_certs", "-noout"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        subj = next((ln for ln in certs.splitlines() if ln.startswith("subject=")), "")
        iss = next((ln for ln in certs.splitlines() if ln.startswith("issuer=")), "")
        if subj:
            info["signer"] = _rdn(subj, "CN")
        if iss:
            info["issuer"] = _rdn(iss, "CN")
        # серійник + строк дії — з x509-текстового дампу сертифіката
        x509 = subprocess.run(
            ["openssl", "pkcs7", "-inform", "DER", "-in", path, "-print_certs"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        det = subprocess.run(
            ["openssl", "x509", "-noout", "-serial", "-dates"],
            input=x509, capture_output=True, text=True, timeout=10,
        ).stdout
        ser = re.search(r"serial=([0-9A-Fa-f]+)", det)
        nb = re.search(r"notBefore=(.+)", det)
        na = re.search(r"notAfter=(.+)", det)
        if ser:
            info["certificate_serial"] = ser.group(1)
        if nb:
            info["valid_from"] = nb.group(1).strip()
        if na:
            info["valid_to"] = na.group(1).strip()
    except Exception:  # noqa: BLE001 — розбір best-effort
        pass
    finally:
        import os as _os

        if _os.path.exists(path):
            _os.remove(path)
    return info

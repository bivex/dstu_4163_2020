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


def _get_addressee_count(payload: dict[str, Any]) -> int:
    addrs = payload.get("addressees", [])
    if not isinstance(addrs, (list, tuple)):
        return 1 if addrs else 0
    return len(addrs)


def _conformant_document(doc_id: str, is_electronic: bool, addressee_count: int = 0, appendix_count: int = 0) -> Document:
    """Повністю конформний за ДСТУ 4163:2020 Document (загальний бланк, A4)."""
    is_letter = addressee_count > 0
    return Document(
        doc_id=doc_id,
        is_letter=is_letter,
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
        addressee_count=addressee_count, appendix_count=appendix_count,
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
        # тип відмітки (esign|eseal) та дані печатки (для eSeal). Дефолт esign.
        kind=str(d.get("kind", d.get("cert_type", "esign"))) if d.get("kind") or d.get("cert_type") else "esign",
        organization=str(d.get("organization", "")),
        identifier=str(d.get("identifier", "")),
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
    addrs = payload.get("addressees", [])
    if not isinstance(addrs, (list, tuple)):
        if addrs:
            addrs = [str(addrs)]
        else:
            addrs = []
    
    addressee = payload.get("addressee", "")
    if addressee and not addrs:
        addrs = [addressee]

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
        addressees=tuple(str(a) for a in addrs),
        sender_contacts=str(payload.get("sender_contacts", "")),
        use_stamp=bool(payload.get("use_stamp", False)),
        stamp_type=str(payload.get("stamp_type", "")),
        use_incoming_stamp=bool(payload.get("use_incoming_stamp", False)),
        use_copy_stamp=bool(payload.get("use_copy_stamp", False)),
        use_control_stamp=bool(payload.get("use_control_stamp", False)),
        restriction_stamp=str(payload.get("restriction_stamp", "")),
        use_copy_mark=bool(payload.get("use_copy_mark", False)),
        use_archived_stamp=bool(payload.get("use_archived_stamp", False)),
        use_annulled_stamp=bool(payload.get("use_annulled_stamp", False)),
        use_urgent_stamp=bool(payload.get("use_urgent_stamp", False)),
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
    doc = _conformant_document(
        str(payload["doc_id"]),
        is_electronic,
        addressee_count=_get_addressee_count(payload),
        appendix_count=int(payload.get("_attachment_count", 0)),
    )
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
    doc = _conformant_document(
        str(payload["doc_id"]),
        is_electronic,
        addressee_count=_get_addressee_count(payload),
        appendix_count=int(payload.get("_attachment_count", 0)),
    )
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
    doc = _conformant_document(
        str(payload["doc_id"]),
        is_electronic,
        addressee_count=_get_addressee_count(payload),
        appendix_count=int(payload.get("_attachment_count", 0)),
    )
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


def _data_files(
    doc_id: str,
    fmt: str,
    rendered: bytes,
    attachments: list[tuple[str, bytes]],
) -> list[tuple[str, bytes]]:
    """Детермінований список data_files для ASiC-E — ЄДИНЕ місце його побудови.

    Спершу основний документ (імʼя ``{doc_id}.{fmt}``), потім додатки в отриманому
    порядку. ``attachments`` має бути відсортований викликівником за order_index —
    порядок тут == порядок <asic:DataObjectReference> у маніфесті XML == частина
    підписаного digest. Будь-який зсув ламає верифікацію підпису.

    Кожен кортеж — (stored_filename, blob). stored_filename — точне імʼя всередині
    ZIP, заморожене при завантаженні; ніколи не перераховується.
    """
    files = [(f"{doc_id}.{fmt}", rendered)]
    files.extend(attachments)
    return files


def build_asice(
    doc_id: str,
    fmt: str,
    rendered: bytes,
    attachments: list[tuple[str, bytes]],
    signatures: list[tuple[str, bytes]],
    dest_path: str,
) -> str:
    """Зібрати ASiC-E контейнер: документ + detached-CAdES підписи над манІфестами.

    signatures — [(label, detached_cms_bytes), ...] у порядку черги; i-та підпис
    має бути detached-CAdES над manifest_for(i+1, data_files) — саме ці байти
    клієнт отримує з manifest_for_signer() і підписує. build_asic_e перебудовує
    ідентичні манІфести (та сама _build_manifest), тож digest співпадає й
    контейнер проходить ETSI-перевірку.
    """
    from dilovod4.infrastructure.asic import AsicSignature, build_asic_e

    data_files = _data_files(doc_id, fmt, rendered, attachments)
    sigs = [AsicSignature(cms=cms, label=label) for label, cms in signatures]
    return build_asic_e(data_files, sigs, dest_path)


def manifest_for_signer(
    doc_id: str,
    fmt: str,
    rendered: bytes,
    attachments: list[tuple[str, bytes]],
    order_index: int,
) -> bytes:
    """Точні байти ASiCManifest, які підписант №order_index має підписати detached.

    order_index 0-based (як у черзі) → signatureNNN з NNN=order_index+1.
    Клієнт підписує саме ці байти (detached CAdES), повертає p7s — build_asice
    перебудує ідентичний манІфест, тож підпис верифікується.
    """
    from dilovod4.infrastructure.asic import manifest_for

    data_files = _data_files(doc_id, fmt, rendered, attachments)
    return manifest_for(order_index + 1, data_files)


def _rdn(dn: str, key: str) -> str:
    """Витягти значення RDN (напр. CN, serialNumber) з рядка openssl subject/issuer."""
    import re

    m = re.search(rf"(?:^|,)\s*{key}=([^,]+)", dn)
    return m.group(1).strip() if m else ""


# OID QC-розширень (ETSI EN 319 412-5) — дублюються з test_cert_factory, щоб
# domain_bridge не залежав від інфраструктурного генератора в runtime.
_OID_QC_STATEMENTS_EXT = "1.3.6.1.5.5.7.1.3"
_OID_QC_TYPE_ESIGN = b"\x06\x07\x04\x00\x8e\x46\x01\x05\x01"  # 0.4.0.1862.1.5.1
_OID_QC_TYPE_ESEAL = b"\x06\x07\x04\x00\x8e\x46\x01\x05\x03"  # 0.4.0.1862.1.5.3


def _detect_cert_type(qc_ext_bytes: bytes) -> str:
    """Визначити тип сертифіката (esign|eseal) за сирими байтами qcStatements.

    Якщо extension відсутній — esign (КЕП особи; історичний дефолт парсера).
    """
    if _OID_QC_TYPE_ESEAL in qc_ext_bytes:
        return "eseal"
    return "esign"


def _parse_leaf_cert_fields(cert) -> dict[str, str]:
    """Витягти поля сертифіката через cryptography.x509 (повний розбір QC).

    ``cert`` — cryptography.x509.Certificate. Повертає словник з: signer (CN),
    organization (O), identifier (serialNumber для особи / organizationIdentifier
    для печатки), issuer (CN), certificate_serial, valid_from/to (DD.MM.YYYY),
    cert_type (esign|eseal), subject_dn/issuer_dn (RFC4514, для аудиту).
    """
    from cryptography.x509.oid import NameOID, ObjectIdentifier

    def _attr(name_oid) -> str:
        vals = cert.subject.get_attributes_for_oid(name_oid)
        return vals[0].value if vals else ""

    def _issuer_attr(name_oid) -> str:
        vals = cert.issuer.get_attributes_for_oid(name_oid)
        return vals[0].value if vals else ""

    OID_ORG_ID = ObjectIdentifier("2.5.4.97")  # organizationIdentifier
    cn = _attr(NameOID.COMMON_NAME)
    org = _attr(NameOID.ORGANIZATION_NAME)
    serial_attr = _attr(NameOID.SERIAL_NUMBER)
    org_id = _attr(OID_ORG_ID)

    # QC type → cert_type
    cert_type = "esign"
    try:
        qc_ext = cert.extensions.get_extension_for_oid(
            ObjectIdentifier(_OID_QC_STATEMENTS_EXT)
        )
        # UnrecognizedExtension.value — сирі байти qcStatements
        qc_bytes = qc_ext.value.value  # type: ignore[union-attr]
        cert_type = _detect_cert_type(qc_bytes)
    except Exception:  # noqa: BLE001 — QC може бути відсутнім
        pass

    # ідентифікатор: для печатки — organizationIdentifier, для особи — РНОКПП
    identifier = org_id if cert_type == "eseal" else serial_attr

    # дата у форматі DD.MM.YYYY (стиль §5.10)
    def _fmt_date(d) -> str:
        try:
            return d.strftime("%d.%m.%Y")
        except Exception:  # noqa: BLE001
            return str(d)

    return {
        "signer": cn or org,
        "organization": org,
        "identifier": identifier,
        "serialNumber": serial_attr,  # зворотна сумісність (РНОКПП)
        "organizationIdentifier": org_id,
        "issuer": _issuer_attr(NameOID.COMMON_NAME) or _issuer_attr(NameOID.ORGANIZATION_NAME),
        "certificate_serial": format(cert.serial_number, "X"),
        "valid_from": _fmt_date(getattr(cert, "not_valid_before_utc", None) or cert.not_valid_before),
        "valid_to": _fmt_date(getattr(cert, "not_valid_after_utc", None) or cert.not_valid_after),
        "cert_type": cert_type,
        "subject_dn": cert.subject.rfc4514_string(),
        "issuer_dn": cert.issuer.rfc4514_string(),
    }


def cert_info_from_cms(sig_bytes: bytes) -> dict[str, str]:
    """Витягти дані сертифіката підписанта з CMS/p7s (DSTU4145 / eSeal / eSign).

    Дані беруться із САМОГО підпису (не довіряємо клієнту):
    - ПІБ підписувача або назва юрособи (subject CN),
    - організація (O) та ідентифікатор (РНОКПП / organizationIdentifier=NTRUA-ЄДРПОУ),
    - видавець (issuer CN), серійний номер сертифіката, строк дії,
    - ``cert_type`` ("esign" | "eseal") — за QC statements (ETSI EN 319 412-5).

    Сертифікат витягується з контейнера ``openssl pkcs7 -print_certs`` (працює з
    DSTU-підписами, які cryptography не декодує), далі поля парсяться надійно через
    ``cryptography.x509`` (включно з QC extensions). Повертає {} якщо розбір
    невдалий — підпис лишиться без розшифрованих даних (зворотна сумісність).
    """
    import subprocess
    import tempfile

    info: dict[str, str] = {}
    with tempfile.NamedTemporaryFile(suffix=".p7s", delete=False) as tmp:
        tmp.write(sig_bytes)
        path = tmp.name
    try:
        # openssl витягує leaf-сертифікат з CMS у PEM (працює з DSTU/EUSign-підписами)
        pem = subprocess.run(
            ["openssl", "pkcs7", "-inform", "DER", "-in", path, "-print_certs"],
            capture_output=True, timeout=10,
        ).stdout
        if not pem.strip():
            return info
        # розбір через cryptography: QC extensions + повний subject/issuer
        try:
            from cryptography import x509 as _x509

            cert = _x509.load_pem_x509_certificate(pem)
            return _parse_leaf_cert_fields(cert)
        except Exception:  # noqa: BLE001 — fallback на старий regex-розбір
            return _cert_info_regex_fallback(pem)
    except Exception:  # noqa: BLE001 — розбір best-effort
        return info
    finally:
        import os as _os

        if _os.path.exists(path):
            _os.remove(path)


def _cert_info_regex_fallback(pem: bytes) -> dict[str, str]:
    """Старий regex-розбір (openssl subject/issuer text) — запасний шлях.

    Використовується лише якщо cryptography не зміг розібрати витягнутий сертифікат
    (напр., DSTU SubjectPublicKeyInfo). Не визначає cert_type — повертає esign.
    """
    import subprocess

    info: dict[str, str] = {}
    text = pem.decode("utf-8", "replace")
    det = subprocess.run(
        ["openssl", "x509", "-noout", "-subject", "-issuer", "-serial", "-dates"],
        input=pem, capture_output=True, text=True, timeout=10,
    ).stdout
    import re

    subj = next((ln for ln in det.splitlines() if ln.startswith("subject=")), "")
    iss = next((ln for ln in det.splitlines() if ln.startswith("issuer=")), "")
    if subj:
        info["signer"] = _rdn(subj, "CN")
        info["serialNumber"] = _rdn(subj, "serialNumber")
    if iss:
        info["issuer"] = _rdn(iss, "CN")
    ser = re.search(r"serial=([0-9A-Fa-f]+)", det)
    nb = re.search(r"notBefore=(.+)", det)
    na = re.search(r"notAfter=(.+)", det)
    if ser:
        info["certificate_serial"] = ser.group(1)
    if nb:
        info["valid_from"] = nb.group(1).strip()
    if na:
        info["valid_to"] = na.group(1).strip()
    info["cert_type"] = "esign"  # дефолт: КЕП особи
    del text
    return info


def verify_signature(data_bytes: bytes, sig_bytes: bytes) -> bool:
    """Криптографічна перевірка підпису під даними через UAPKI з fallback на openssl cms.
    Підтримує як detached (від'єднаний), так і attached (приєднаний) підписи.
    """
    import base64
    import os
    import sys
    from dilovod4.infrastructure.uapki import UapkiClient, UapkiLibraryNotFound, UapkiError

    # Спробуємо верифікацію через UAPKI
    try:
        # Визначаємо шлях до кешу сертифікатів
        cert_cache = "/app/.euscp_store"
        if not os.path.exists(cert_cache):
            # Fallback для хост-машини або інших шляхів
            cert_cache = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".euscp_store")
            if not os.path.exists(cert_cache):
                # Тимчасова пуста папка, якщо взагалі немає кешу
                cert_cache = "/tmp/certs"

        crl_cache = "/tmp/crls"
        os.makedirs(cert_cache, exist_ok=True)
        os.makedirs(crl_cache, exist_ok=True)

        with UapkiClient() as client:
            client.init(cert_cache, crl_cache, offline=True)
            sig_b64 = base64.b64encode(sig_bytes).decode("ascii")

            # 1. Спробуємо спочатку як attached (приєднаний) підпис (без передачі content)
            try:
                res = client.verify(sig_b64)
                infos = res.get("signatureInfos", [])
                if infos and infos[0].get("statusSignature") == "VALID":
                    # Перевіряємо, чи повернутий вміст збігається з очікуваними даними
                    content_b64 = res.get("content", {}).get("bytes")
                    if content_b64:
                        content_bytes = base64.b64decode(content_b64)
                        if content_bytes == data_bytes:
                            return True
            except UapkiError as e:
                # Якщо помилка не RET_UAPKI_CONTENT_NOT_PRESENT (4147 / 0x1033), прокинемо її далі
                if e.error_code != 4147:
                    raise

            # 2. Спробуємо як detached (від'єднаний) підпис
            data_b64 = base64.b64encode(data_bytes).decode("ascii")
            res = client.verify(sig_b64, data_b64)
            infos = res.get("signatureInfos", [])
            if infos and infos[0].get("statusSignature") == "VALID":
                return True

            return False

    except UapkiLibraryNotFound:
        # Fallback на openssl, якщо бібліотека UAPKI не зібрана (наприклад, на хост-машині розробника)
        print("UAPKI library not found. Falling back to openssl cms verify.", file=sys.stderr)
    except Exception as e:
        print(f"UAPKI verification failed ({e}). Falling back to openssl cms verify.", file=sys.stderr)

    # Старий код на openssl cms (fallback)
    import tempfile
    import subprocess

    with tempfile.NamedTemporaryFile(suffix=".p7s", delete=False) as sig_tmp, \
         tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as data_tmp, \
         tempfile.NamedTemporaryFile(suffix=".out", delete=False) as out_tmp:
        sig_tmp.write(sig_bytes)
        data_tmp.write(data_bytes)
        sig_path = sig_tmp.name
        data_path = data_tmp.name
        out_path = out_tmp.name

    try:
        # 1. Спочатку спробуємо як detached (від'єднаний) підпис
        cmd_detached = [
            "openssl", "cms", "-verify",
            "-inform", "DER",
            "-content", data_path,
            "-in", sig_path,
            "-noverify",
            "-out", "/dev/null"
        ]
        res = subprocess.run(cmd_detached, capture_output=True, timeout=10)
        if res.returncode == 0:
            return True

        # 2. Якщо не вдалося, спробуємо як attached (приєднаний) підпис
        cmd_attached = [
            "openssl", "cms", "-verify",
            "-inform", "DER",
            "-in", sig_path,
            "-noverify",
            "-out", out_path
        ]
        res = subprocess.run(cmd_attached, capture_output=True, timeout=10)
        if res.returncode == 0:
            with open(out_path, "rb") as f:
                verified_content = f.read()
            return verified_content == data_bytes

        return False
    except Exception:
        return False
    finally:
        for p in (sig_path, data_path, out_path):
            if os.path.exists(p):
                os.remove(p)

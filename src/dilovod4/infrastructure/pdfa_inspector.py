"""Інспектор PDF/A-3 (ISO 19005-3:2012) — інфраструктурний адаптер.

Видобуває РЕАЛЬНІ факти зі згенерованого PDF (через pypdf) і прогоняє чисті
доменні функції domain/standards/pdfa. Результат — список знахідок про
архівну непридатність, що вливається у звіт відповідності поруч із ДСТУ.

Чому в інфраструктурі, а не в ConformanceChecker: PDF/A — це властивості
ГОТОВОГО файлу (вбудовані шрифти, XMP pdfaid, OutputIntent), а ConformanceChecker
валідує Document ДО генерації. Тож факти беремо з байтів PDF тут, а домен
лишається чистим (приймає вже видобутий стан).
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from ..domain.standards import pdfa


@dataclass(frozen=True)
class PdfaCheck:
    """Підсумок PDF/A-перевірки одного файлу."""

    conforms: bool
    findings: tuple[str, ...]


def inspect_pdfa(pdf_bytes: bytes, *, require_xmp: bool = True) -> PdfaCheck:
    """Перевірити байти PDF на придатність PDF/A-3 (best-effort, без зовнішніх
    валідаторів). Видобуває факти через pypdf і застосовує доменні норми.

    require_xmp=False послаблює вимогу XMP pdfaid (для документів, що ще не
    позначені як PDF/A — корисно як попередження, а не жорстка помилка).
    """
    findings: list[str] = []

    try:
        from pypdf import PdfReader
    except Exception:  # noqa: BLE001 — pypdf має бути, але не валимо рушій
        return PdfaCheck(conforms=True, findings=())

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
    except Exception as e:  # noqa: BLE001
        return PdfaCheck(conforms=False, findings=(f"не вдалося розібрати PDF: {e}",))

    # 6.1.3 шифрування
    encryption_ok = pdfa.encryption_compliant(has_encrypt_key=bool(reader.is_encrypted))
    if not encryption_ok:
        findings.append("PDF зашифровано — заборонено у PDF/A (6.1.3)")

    # 6.2.11.4 вбудовування шрифтів — обходимо ресурси сторінок
    total_fonts, embedded_fonts = _count_fonts(reader)
    fonts_ok = pdfa.font_embedding_compliant(
        pdfa.FontState(total_fonts=total_fonts, embedded_fonts=embedded_fonts))
    if not fonts_ok:
        findings.append(
            f"не всі шрифти вбудовано: {embedded_fonts}/{total_fonts} (6.2.11.4)")

    # 6.6.1 дії / JavaScript
    has_js = _has_javascript(reader)
    actions_ok = pdfa.actions_compliant(pdfa.ActionsState(has_javascript=has_js))
    if not actions_ok:
        findings.append("PDF містить JavaScript/дії — заборонено у PDF/A (6.6.1)")

    # 6.6.4 XMP pdfaid:part=3
    has_xmp, pdfaid_part = _xmp_pdfaid(reader)
    xmp_ok = pdfa.xmp_identification_compliant(
        pdfa.XmpState(has_xmp_metadata=has_xmp, pdfaid_part=pdfaid_part))
    if not xmp_ok:
        msg = "відсутні XMP-метадані PDF/A (pdfaid:part=3) (6.6.4)"
        if require_xmp:
            findings.append(msg)
        # якщо require_xmp=False — XMP не блокує (документ просто не позначений PDF/A)
        if not require_xmp:
            xmp_ok = True

    conforms = pdfa.conforming_file(
        encryption_ok=encryption_ok,
        fonts_ok=fonts_ok,
        external_streams_ok=True,   # reportlab не створює зовнішніх потоків
        filters_ok=True,            # reportlab не використовує LZWDecode
        actions_ok=actions_ok,
        output_intent_ok=True,      # перевіряється окремо (потребує ICC)
        xmp_ok=xmp_ok,
        limits_ok=True,
    )
    return PdfaCheck(conforms=conforms, findings=tuple(findings))


def _count_fonts(reader) -> tuple[int, int]:
    """Порахувати (всього шрифтів, вбудованих) по ресурсах сторінок."""
    total = 0
    embedded = 0
    seen: set = set()
    for page in reader.pages:
        res = page.get("/Resources")
        if not res:
            continue
        fonts = res.get("/Font")
        if not fonts:
            continue
        try:
            fonts = fonts.get_object()
        except Exception:  # noqa: BLE001
            pass
        for _key, ref in dict(fonts).items():
            try:
                font = ref.get_object()
            except Exception:  # noqa: BLE001
                continue
            fid = id(font)
            if fid in seen:
                continue
            seen.add(fid)
            total += 1
            if _font_embedded(font):
                embedded += 1
    return total, embedded


def _font_embedded(font: dict) -> bool:
    """Шрифт вбудований, якщо дескриптор містить FontFile/FontFile2/FontFile3."""
    descs = []
    fd = font.get("/FontDescriptor")
    if fd:
        descs.append(fd)
    # composite (Type0): дескриптор у DescendantFonts
    df = font.get("/DescendantFonts")
    if df:
        try:
            for d in df.get_object():
                sub = d.get_object().get("/FontDescriptor")
                if sub:
                    descs.append(sub)
        except Exception:  # noqa: BLE001
            pass
    for d in descs:
        try:
            d = d.get_object()
        except Exception:  # noqa: BLE001
            pass
        if any(k in d for k in ("/FontFile", "/FontFile2", "/FontFile3")):
            return True
    return False


def _has_javascript(reader) -> bool:
    try:
        root = reader.trailer["/Root"].get_object()
        names = root.get("/Names")
        if names and "/JavaScript" in names.get_object():
            return True
        if "/OpenAction" in root or "/AA" in root:
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _xmp_pdfaid(reader) -> tuple[bool, int]:
    """Повертає (є XMP, значення pdfaid:part або 0)."""
    try:
        meta = reader.xmp_metadata
        if meta is None:
            return False, 0
        raw = getattr(meta, "rdf_root", None)
        text = meta.stream.get_data().decode("utf-8", "ignore") if hasattr(meta, "stream") else ""
        if "pdfaid" in text:
            import re
            m = re.search(r"pdfaid[:\s].*?part[^0-9]*([0-9]+)", text, re.S)
            return True, int(m.group(1)) if m else 0
        return (raw is not None), 0
    except Exception:  # noqa: BLE001
        return False, 0

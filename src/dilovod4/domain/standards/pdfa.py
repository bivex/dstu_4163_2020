"""Обчислювані вимоги ISO 19005-3:2012 (PDF/A-3) — перенесені з
pdfa_19005_3.catala_en.

Чисті функції/перевірки над станом PDF-файлу, БЕЗ IO. Кожна функція відповідає
scope catala-специфікації (clause 6 — технічні вимоги до файлу). Не охоплює
поведінку читача (cl.5.5), математику кольору та прозорість (Annex A) —
лише вимоги, що верифікуються над структурою файлу.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class PdfaLevel(str, enum.Enum):
    """Рівень відповідності PDF/A-3 (cl.5)."""

    A = "A"  # повний: + теги (6.7) і ToUnicode (6.2.11.7)
    B = "B"  # базовий: візуальна відтворюваність
    U = "U"  # B + ToUnicode (Unicode-текст), без тегування


# --- cl.5 Conformance levels ------------------------------------------------

def requires_tagging(level: PdfaLevel) -> bool:
    """6.7 — логічна структура/тегування обов'язкові лише для рівня A."""
    return level == PdfaLevel.A


def requires_tounicode(level: PdfaLevel) -> bool:
    """6.2.11.7 — ToUnicode CMap обов'язковий для рівнів A та U."""
    return level in (PdfaLevel.A, PdfaLevel.U)


# --- 6.1.3 Encryption -------------------------------------------------------

def encryption_compliant(has_encrypt_key: bool) -> bool:
    """Ключ Encrypt заборонено у trailer dictionary (шифрування/паролі)."""
    return not has_encrypt_key


# --- 6.2.11.4 Font embedding ------------------------------------------------

@dataclass(frozen=True)
class FontState:
    total_fonts: int  # усі шрифти, що використовуються для рендерингу
    embedded_fonts: int  # з них вбудовано


def font_embedding_compliant(s: FontState) -> bool:
    """Усі шрифти, що рендеряться, мають бути вбудовані."""
    return s.embedded_fonts >= s.total_fonts


# --- 6.1.7 External streams / 6.1.7.2 Filters -------------------------------

@dataclass(frozen=True)
class FileStructureState:
    has_f_key: bool = False
    has_ffilter_key: bool = False
    has_fdecodeparams_key: bool = False
    uses_lzwdecode: bool = False


def external_streams_compliant(s: FileStructureState) -> bool:
    """F / FFilter / FDecodeParams заборонені (зовнішні залежності)."""
    return not (s.has_f_key or s.has_ffilter_key or s.has_fdecodeparams_key)


def filters_compliant(s: FileStructureState) -> bool:
    """LZWDecode заборонено (6.1.7.2)."""
    return not s.uses_lzwdecode


# --- 6.6.1 Actions ----------------------------------------------------------

@dataclass(frozen=True)
class ActionsState:
    has_javascript: bool = False
    has_launch: bool = False
    has_other_forbidden_action: bool = False  # Sound/Movie/ResetForm/Hide/...


def actions_compliant(s: ActionsState) -> bool:
    """JavaScript, Launch та інші виконувані дії заборонені."""
    return not (s.has_javascript or s.has_launch or s.has_other_forbidden_action)


# --- 6.2.3 / 6.2.4 OutputIntent ---------------------------------------------

@dataclass(frozen=True)
class ColourState:
    uses_uncalibrated_colour: bool  # DeviceRGB/DeviceGray/DeviceCMYK
    has_pdfa_output_intent: bool


def output_intent_compliant(s: ColourState) -> bool:
    """За некаліброваного кольору обов'язковий PDF/A OutputIntent."""
    return (not s.uses_uncalibrated_colour) or s.has_pdfa_output_intent


# --- 6.6.4 XMP PDF/A identification -----------------------------------------

@dataclass(frozen=True)
class XmpState:
    has_xmp_metadata: bool
    pdfaid_part: int  # має бути 3 для PDF/A-3


def xmp_identification_compliant(s: XmpState) -> bool:
    """XMP-метадані з pdfaid:part=3 (ідентифікація версії PDF/A)."""
    return s.has_xmp_metadata and s.pdfaid_part == 3


# --- 6.1.13 Implementation limits -------------------------------------------

@dataclass(frozen=True)
class LimitsState:
    max_integer: int
    max_string_bytes: int
    max_name_bytes: int
    indirect_objects: int


def implementation_limits_compliant(s: LimitsState) -> bool:
    """Числові/рядкові/іменні ліміти реалізації (Table C.1)."""
    return (
        s.max_integer <= 2147483647
        and s.max_string_bytes <= 32767
        and s.max_name_bytes <= 127
        and s.indirect_objects <= 8388607
    )


# --- Aggregate --------------------------------------------------------------

def conforming_file(
    *,
    encryption_ok: bool,
    fonts_ok: bool,
    external_streams_ok: bool,
    filters_ok: bool,
    actions_ok: bool,
    output_intent_ok: bool,
    xmp_ok: bool,
    limits_ok: bool,
) -> bool:
    """Файл відповідає PDF/A-3, якщо всі обов'язкові перевірки пройдено."""
    return (
        encryption_ok
        and fonts_ok
        and external_streams_ok
        and filters_ok
        and actions_ok
        and output_intent_ok
        and xmp_ok
        and limits_ok
    )

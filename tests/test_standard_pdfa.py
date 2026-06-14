"""Тести обчислюваних вимог ISO 19005-3:2012 (PDF/A-3) — domain/standards/pdfa.
Дзеркалять scope'и pdfa_19005_3.catala_en.
"""

from __future__ import annotations

from dilovod4.domain.standards import (
    ActionsState,
    ColourState,
    FileStructureState,
    FontState,
    PdfaLevel,
    XmpState,
    actions_compliant,
    conforming_file,
    encryption_compliant,
    external_streams_compliant,
    filters_compliant,
    font_embedding_compliant,
    implementation_limits_compliant,
    output_intent_compliant,
    requires_tagging,
    requires_tounicode,
    xmp_identification_compliant,
)
from dilovod4.domain.standards.pdfa import LimitsState


# --- cl.5 рівні відповідності ---
def test_level_a_requires_tagging_and_tounicode():
    assert requires_tagging(PdfaLevel.A) is True
    assert requires_tounicode(PdfaLevel.A) is True


def test_level_u_requires_tounicode_not_tagging():
    assert requires_tagging(PdfaLevel.U) is False
    assert requires_tounicode(PdfaLevel.U) is True


def test_level_b_requires_neither():
    assert requires_tagging(PdfaLevel.B) is False
    assert requires_tounicode(PdfaLevel.B) is False


# --- 6.1.3 шифрування ---
def test_encryption_forbidden():
    assert encryption_compliant(has_encrypt_key=False) is True
    assert encryption_compliant(has_encrypt_key=True) is False


# --- 6.2.11.4 вбудовування шрифтів ---
def test_all_fonts_embedded_ok():
    assert font_embedding_compliant(FontState(total_fonts=4, embedded_fonts=4)) is True


def test_missing_embedded_font_fails():
    assert font_embedding_compliant(FontState(total_fonts=4, embedded_fonts=3)) is False


def test_zero_fonts_ok():
    assert font_embedding_compliant(FontState(total_fonts=0, embedded_fonts=0)) is True


# --- 6.1.7 зовнішні потоки / 6.1.7.2 фільтри ---
def test_external_stream_keys_forbidden():
    assert external_streams_compliant(FileStructureState()) is True
    assert external_streams_compliant(FileStructureState(has_f_key=True)) is False
    assert external_streams_compliant(FileStructureState(has_ffilter_key=True)) is False
    assert external_streams_compliant(FileStructureState(has_fdecodeparams_key=True)) is False


def test_lzwdecode_forbidden():
    assert filters_compliant(FileStructureState()) is True
    assert filters_compliant(FileStructureState(uses_lzwdecode=True)) is False


# --- 6.6.1 дії ---
def test_javascript_and_launch_forbidden():
    assert actions_compliant(ActionsState()) is True
    assert actions_compliant(ActionsState(has_javascript=True)) is False
    assert actions_compliant(ActionsState(has_launch=True)) is False
    assert actions_compliant(ActionsState(has_other_forbidden_action=True)) is False


# --- 6.2.3 OutputIntent ---
def test_output_intent_required_for_uncalibrated_colour():
    # некалібрований колір без OutputIntent — порушення
    assert output_intent_compliant(
        ColourState(uses_uncalibrated_colour=True, has_pdfa_output_intent=False)) is False
    # некалібрований колір з OutputIntent — ок
    assert output_intent_compliant(
        ColourState(uses_uncalibrated_colour=True, has_pdfa_output_intent=True)) is True
    # без некаліброваного кольору OutputIntent не обов'язковий
    assert output_intent_compliant(
        ColourState(uses_uncalibrated_colour=False, has_pdfa_output_intent=False)) is True


# --- 6.6.4 XMP ідентифікація ---
def test_xmp_pdfa_identification():
    assert xmp_identification_compliant(XmpState(has_xmp_metadata=True, pdfaid_part=3)) is True
    assert xmp_identification_compliant(XmpState(has_xmp_metadata=False, pdfaid_part=3)) is False
    assert xmp_identification_compliant(XmpState(has_xmp_metadata=True, pdfaid_part=2)) is False


# --- 6.1.13 ліміти реалізації ---
def test_implementation_limits():
    ok = LimitsState(max_integer=1000, max_string_bytes=500,
                     max_name_bytes=50, indirect_objects=100)
    assert implementation_limits_compliant(ok) is True
    bad_int = LimitsState(max_integer=2147483648, max_string_bytes=500,
                          max_name_bytes=50, indirect_objects=100)
    assert implementation_limits_compliant(bad_int) is False
    bad_name = LimitsState(max_integer=1000, max_string_bytes=500,
                           max_name_bytes=128, indirect_objects=100)
    assert implementation_limits_compliant(bad_name) is False


# --- агрегат ---
def test_conforming_file_all_pass():
    assert conforming_file(
        encryption_ok=True, fonts_ok=True, external_streams_ok=True,
        filters_ok=True, actions_ok=True, output_intent_ok=True,
        xmp_ok=True, limits_ok=True) is True


def test_conforming_file_one_fail():
    assert conforming_file(
        encryption_ok=True, fonts_ok=False, external_streams_ok=True,
        filters_ok=True, actions_ok=True, output_intent_ok=True,
        xmp_ok=True, limits_ok=True) is False

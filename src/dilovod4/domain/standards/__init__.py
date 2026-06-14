"""Обчислювані технічні вимоги стандартів управління документами.

  • ISO 19005-3:2012 (PDF/A-3) — формат архівного PDF (модуль pdfa).
"""

from .pdfa import (
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

__all__ = [
    "ActionsState",
    "ColourState",
    "FileStructureState",
    "FontState",
    "PdfaLevel",
    "XmpState",
    "actions_compliant",
    "conforming_file",
    "encryption_compliant",
    "external_streams_compliant",
    "filters_compliant",
    "font_embedding_compliant",
    "implementation_limits_compliant",
    "output_intent_compliant",
    "requires_tagging",
    "requires_tounicode",
    "xmp_identification_compliant",
]

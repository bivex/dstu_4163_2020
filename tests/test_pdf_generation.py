"""Тести генерації .pdf (адаптер PdfDocumentWriter) та пошуку шрифтів."""

from __future__ import annotations

import pytest

reportlab = pytest.importorskip("reportlab")

from dilovod4.application.generate_document import GenerateDocument
from dilovod4.domain.model import DocumentContent
from dilovod4.infrastructure.fonts import FontNotFoundError, resolve_times_new_roman
from dilovod4.infrastructure.pdf_writer import PdfDocumentWriter
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider

from .builders import conformant_document


def _content() -> DocumentContent:
    return DocumentContent(
        org_name="ТОВ «ТЕСТ»",
        doc_type="Наказ",
        date_text="13.06.2026",
        reg_index="01",
        title="Тестовий заголовок українською",
        body=("Перший абзац тексту документа.", "Другий абзац тексту документа."),
        signature_position="Директор",
        signature_name="І. ТЕСТ",
    )


def _writer() -> PdfDocumentWriter:
    try:
        return PdfDocumentWriter()
    except FontNotFoundError:
        pytest.skip("Times New Roman TTF недоступний у цьому середовищі")


def test_writes_valid_pdf(tmp_path):
    dest = str(tmp_path / "out.pdf")
    path = _writer().write(conformant_document(), _content(), dest)
    assert path == dest
    with open(path, "rb") as fh:
        assert fh.read(5) == b"%PDF-"


def test_appends_pdf_extension(tmp_path):
    path = _writer().write(conformant_document(), _content(), str(tmp_path / "noext"))
    assert path.endswith(".pdf")


def test_page_size_matches_format(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    dest = str(tmp_path / "geo.pdf")
    _writer().write(conformant_document(), _content(), dest)
    reader = pypdf.PdfReader(dest)
    box = reader.pages[0].mediabox
    w_mm = round(float(box.width) / 72 * 25.4)
    h_mm = round(float(box.height) / 72 * 25.4)
    assert (w_mm, h_mm) == (210, 297)


def test_embeds_times_new_roman_and_cyrillic(tmp_path):
    pypdf = pytest.importorskip("pypdf")
    dest = str(tmp_path / "font.pdf")
    _writer().write(conformant_document(), _content(), dest)
    reader = pypdf.PdfReader(dest)
    page = reader.pages[0]
    base_fonts = {
        str(f.get_object().get("/BaseFont", ""))
        for f in page["/Resources"]["/Font"].values()
    }
    assert any("Times" in bf for bf in base_fonts)
    text = page.extract_text() or ""
    assert any("\u0400" <= ch <= "\u04ff" for ch in text)


def test_generate_use_case_with_pdf_writer(tmp_path):
    dest = str(tmp_path / "uc.pdf")
    use_case = GenerateDocument(writer=_writer(), rule_set=DefaultRuleSetProvider())
    result = use_case.execute(conformant_document(), _content(), dest)
    assert result.report is not None and result.report.conforms
    with open(result.path, "rb") as fh:
        assert fh.read(5) == b"%PDF-"


def test_font_env_override_missing_file(monkeypatch):
    monkeypatch.setenv("DILOVOD4_FONT_REGULAR", "/no/such/font.ttf")
    with pytest.raises(FontNotFoundError):
        resolve_times_new_roman()


def test_font_resolves_on_system_or_skips():
    try:
        fonts = resolve_times_new_roman()
    except FontNotFoundError:
        pytest.skip("системний Times New Roman недоступний")
    import os

    assert os.path.isfile(fonts.regular)
    assert os.path.isfile(fonts.bold)

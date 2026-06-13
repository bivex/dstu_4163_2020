"""Тести генерації .docx (адаптер DocumentWriter + use-case GenerateDocument)."""

from __future__ import annotations

import zipfile

import pytest

docx = pytest.importorskip("docx")

from dilovod4.application.generate_document import GenerateDocument
from dilovod4.domain.errors import InvariantViolation
from dilovod4.domain.model import DocumentContent
from dilovod4.infrastructure.docx_writer import DocxDocumentWriter
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider

from .builders import conformant_document


def _content() -> DocumentContent:
    return DocumentContent(
        org_name="ТОВ «ТЕСТ»",
        doc_type="Наказ",
        date_text="13.06.2026",
        reg_index="01",
        title="Тестовий заголовок",
        body=("Перший абзац.", "Другий абзац."),
        signature_position="Директор",
        signature_name="І. ТЕСТ",
    )


def test_writes_valid_docx(tmp_path):
    dest = str(tmp_path / "out.docx")
    writer = DocxDocumentWriter()
    path = writer.write(conformant_document(), _content(), dest)
    assert path == dest
    assert zipfile.is_zipfile(path)


def test_applies_dstu_geometry_and_typography(tmp_path):
    from docx import Document as DocxDocument

    dest = str(tmp_path / "geo.docx")
    DocxDocumentWriter().write(conformant_document(), _content(), dest)

    d = DocxDocument(dest)
    sec = d.sections[0]
    mm = lambda emu: round(emu / 36000, 1)
    assert (mm(sec.left_margin), mm(sec.right_margin)) == (30.0, 10.0)
    assert (mm(sec.top_margin), mm(sec.bottom_margin)) == (20.0, 20.0)
    assert (mm(sec.page_width), mm(sec.page_height)) == (210.0, 297.0)

    style = d.styles["Normal"]
    assert style.font.name == "Times New Roman"
    assert style.font.size.pt == 14
    assert sec.different_first_page_header_footer is True


def test_page_number_field_present(tmp_path):
    dest = str(tmp_path / "num.docx")
    DocxDocumentWriter().write(conformant_document(), _content(), dest)
    with zipfile.ZipFile(dest) as z:
        header_xml = "".join(
            z.read(n).decode("utf-8", "ignore") for n in z.namelist() if "header" in n
        )
    assert "PAGE" in header_xml


def test_appends_docx_extension(tmp_path):
    dest = str(tmp_path / "noext")
    path = DocxDocumentWriter().write(conformant_document(), _content(), dest)
    assert path.endswith(".docx")


def test_generate_use_case_validates_and_writes(tmp_path):
    dest = str(tmp_path / "uc.docx")
    use_case = GenerateDocument(writer=DocxDocumentWriter(), rule_set=DefaultRuleSetProvider())
    result = use_case.execute(conformant_document(), _content(), dest)
    assert result.report is not None
    assert result.report.conforms
    assert zipfile.is_zipfile(result.path)


def test_content_requires_body():
    with pytest.raises(InvariantViolation):
        DocumentContent(
            org_name="ТОВ",
            doc_type="Наказ",
            date_text="13.06.2026",
            reg_index="01",
            title="X",
            body=(),
            signature_position="Директор",
            signature_name="І. Т.",
        )

"""DocxDocumentWriter — адаптер порту DocumentWriter на базі python-docx.

Фізично відтворює оформлення згідно з параметрами доменного Document:
поля (§6.2), гарнітура та кеглі (§7.2), міжрядковий інтервал (§7.3),
відступи (§7.7), нумерація сторінок (§7.10). Наповнює текстом з DocumentContent.

Це інфраструктура: уся залежність від python-docx ізольована тут.
"""

from __future__ import annotations

from docx import Document as DocxDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml.ns import qn
from docx.shared import Mm, Pt

from ..domain.model import Document, DocumentContent


class DocxDocumentWriter:
    """Записує доменний документ у файл .docx за правилами ДСТУ 4163:2020."""

    def write(self, document: Document, content: DocumentContent, destination: str) -> str:
        doc = DocxDocument()
        self._apply_page_geometry(doc, document)
        self._apply_base_style(doc, document)
        self._enable_page_numbering(doc, document)

        self._add_letterhead(doc, document, content)
        self._add_addressees(doc, document, content)
        self._add_title(doc, document, content)
        self._add_body(doc, document, content)
        self._add_signature(doc, document, content)

        if not destination.endswith(".docx"):
            destination = f"{destination}.docx"
        doc.save(destination)
        return destination

    # --- §6.2 поля ---
    def _apply_page_geometry(self, doc, document: Document) -> None:
        m = document.geometry.margins
        for section in doc.sections:
            section.left_margin = Mm(m.left)
            section.right_margin = Mm(m.right)
            section.top_margin = Mm(m.top)
            section.bottom_margin = Mm(m.bottom)
            # §6.1 формат: A4 210x297, A5 210x148, A3 297x420
            dims = {
                "A4": (210, 297),
                "A5": (210, 148),
                "A3": (297, 420),
            }[document.geometry.paper_format.value]
            section.page_width = Mm(dims[0])
            section.page_height = Mm(dims[1])

    # --- §7.2 гарнітура/кегль, §7.3 інтервал ---
    def _apply_base_style(self, doc, document: Document) -> None:
        style = doc.styles["Normal"]
        font = style.font
        if document.typography.is_times_new_roman:
            font.name = "Times New Roman"
            # кирилиця: явно вказуємо east-asia/cs шрифт через rPr
            rpr = style.element.get_or_add_rPr()
            rfonts = rpr.get_or_add_rFonts()
            rfonts.set(qn("w:ascii"), "Times New Roman")
            rfonts.set(qn("w:hAnsi"), "Times New Roman")
            rfonts.set(qn("w:cs"), "Times New Roman")
        font.size = Pt(document.typography.body_size_pt)

        pf = style.paragraph_format
        spacing = document.line_spacing.body_spacing
        pf.line_spacing = spacing
        pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
        pf.space_after = Pt(0)

    # --- §7.10 нумерація сторінок ---
    def _enable_page_numbering(self, doc, document: Document) -> None:
        section = doc.sections[0]
        # перша сторінка не нумерується (§7.10)
        section.different_first_page_header_footer = True

        # верхній колонтитул решти сторінок: посередині, арабські, без слова
        header = section.header
        header.is_linked_to_previous = False
        para = header.paragraphs[0]
        para.text = ""
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._insert_page_field(para)

        # перша сторінка — порожній колонтитул
        first = section.first_page_header
        first.is_linked_to_previous = False
        if first.paragraphs:
            first.paragraphs[0].text = ""

    def _insert_page_field(self, paragraph) -> None:
        """Вставити поле PAGE (арабська цифра), без тексту «сторінка»."""
        run = paragraph.add_run()
        fld_begin = run._r.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "begin"})
        instr = run._r.makeelement(qn("w:instrText"), {qn("xml:space"): "preserve"})
        instr.text = "PAGE \\* ARABIC"
        fld_end = run._r.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "end"})
        run._r.append(fld_begin)
        run._r.append(instr)
        run._r.append(fld_end)

    # --- реквізити бланка ---
    def _add_letterhead(self, doc, document: Document, content: DocumentContent) -> None:
        org = doc.add_paragraph()
        org.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = org.add_run(content.org_name)
        run.bold = True

        # 09 назву виду не зазначають на листах (§4.4)
        if not document.is_letter and content.doc_type.strip():
            dt = doc.add_paragraph()
            dt.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = dt.add_run(content.doc_type.upper())
            run.font.size = Pt(document.typography.doc_type_size_pt)
            run.bold = True

        # 10 дата + 11 реєстраційний індекс — рядок реквізитів
        meta = doc.add_paragraph()
        meta.add_run(f"{content.date_text}    № {content.reg_index}")

    def _add_addressees(self, doc, document: Document, content: DocumentContent) -> None:
        if not content.addressees:
            return
        # §7.7: «Адресат» — відступ 90 мм від лівого поля
        for addressee in content.addressees:
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Mm(document.left_indents.addressee_mm)
            p.add_run(addressee)

    def _add_title(self, doc, document: Document, content: DocumentContent) -> None:
        if not content.title.strip():
            return
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.add_run(content.title).bold = True

    def _add_body(self, doc, document: Document, content: DocumentContent) -> None:
        for para_text in content.body:
            p = doc.add_paragraph()
            # §7.7: абзацний відступ 10 мм
            p.paragraph_format.first_line_indent = Mm(document.left_indents.paragraph_mm)
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.add_run(para_text)

    def _add_signature(self, doc, document: Document, content: DocumentContent) -> None:
        doc.add_paragraph()
        p = doc.add_paragraph()
        # посада ліворуч, розшифрування — праворуч (спрощена реалізація через tab)
        p.add_run(content.signature_position)
        p.add_run("\t\t")
        p.add_run(content.signature_name)

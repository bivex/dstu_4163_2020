"""PdfDocumentWriter — адаптер порту DocumentWriter на базі reportlab.

Реалізує ТОЙ САМИЙ порт, що й DocxDocumentWriter (LSP): взаємозамінні без
зміни use-case. Фізично відтворює оформлення згідно з параметрами Document:
поля (§6.2), формат (§6.1), гарнітура та кеглі (§7.2), міжрядковий інтервал
(§7.3), відступи (§7.7), нумерація сторінок (§7.10).

Уся залежність від reportlab ізольована тут (інфраструктура).
"""

from __future__ import annotations

from reportlab.lib.pagesizes import A3, A4, A5
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..domain.model import Document, DocumentContent
from .fonts import FontPaths, resolve_times_new_roman

_FONT_REGULAR = "DSTU-Serif"
_FONT_BOLD = "DSTU-Serif-Bold"

_PAGE_SIZES = {"A4": A4, "A5": A5, "A3": A3}

# §6.7: способи розташування реквізитів бланка
_ALIGN_CENTER = "center"
_ALIGN_FLAG = "flag"  # прапоровий = від лівого поля


class PdfDocumentWriter:
    """Записує доменний документ у файл .pdf за правилами ДСТУ 4163:2020."""

    def __init__(self, fonts: FontPaths | None = None) -> None:
        self._fonts = fonts or resolve_times_new_roman()
        self._fonts_registered = False

    def _ensure_fonts(self) -> None:
        if self._fonts_registered:
            return
        pdfmetrics.registerFont(TTFont(_FONT_REGULAR, self._fonts.regular))
        pdfmetrics.registerFont(TTFont(_FONT_BOLD, self._fonts.bold))
        pdfmetrics.registerFontFamily(
            _FONT_REGULAR, normal=_FONT_REGULAR, bold=_FONT_BOLD
        )
        self._fonts_registered = True

    def write(self, document: Document, content: DocumentContent, destination: str) -> str:
        self._ensure_fonts()
        if not destination.endswith(".pdf"):
            destination = f"{destination}.pdf"

        page_size = _PAGE_SIZES[document.geometry.paper_format.value]
        c = canvas.Canvas(destination, pagesize=page_size)
        layout = _Layout(c, document, content, page_size)
        layout.render()
        c.save()
        return destination


class _Layout:
    """Інкапсулює потік верстки сторінок з урахуванням полів та нумерації."""

    def __init__(self, c, document: Document, content: DocumentContent, page_size) -> None:
        self.c = c
        self.doc = document
        self.content = content
        self.page_w, self.page_h = page_size

        m = document.geometry.margins
        self.left = m.left * mm
        self.right_margin = m.right * mm
        self.top = m.top * mm
        self.bottom = m.bottom * mm
        self.text_width = self.page_w - self.left - self.right_margin

        self.body_pt = document.typography.body_size_pt
        self.doc_type_pt = document.typography.doc_type_size_pt
        # §7.3: міжрядковий інтервал як множник кегля
        self.leading = self.body_pt * document.line_spacing.body_spacing

        self.page_no = 1
        self.y = self.page_h - self.top

    # --- службове ---
    def _new_page(self) -> None:
        self._draw_page_number()
        self.c.showPage()
        self.page_no += 1
        self.y = self.page_h - self.top

    def _ensure_space(self, needed: float) -> None:
        if self.y - needed < self.bottom:
            self._new_page()

    def _draw_page_number(self) -> None:
        # §7.10: перша сторінка не нумерується; 2+ — посередині верхнього поля,
        # арабські, без слова «сторінка» та розділових знаків.
        if self.page_no < 2:
            return
        self.c.setFont(_FONT_REGULAR, self.body_pt)
        text = str(self.page_no)
        x = self.page_w / 2
        y = self.page_h - self.top / 2
        self.c.drawCentredString(x, y, text)

    def _line(self, text: str, *, font=_FONT_REGULAR, size=None, align=_ALIGN_FLAG,
              indent_mm: float = 0.0) -> None:
        size = size or self.body_pt
        self._ensure_space(self.leading)
        self.y -= self.leading
        self.c.setFont(font, size)
        if align == _ALIGN_CENTER:
            self.c.drawCentredString(self.page_w / 2, self.y, text)
        else:
            self.c.drawString(self.left + indent_mm * mm, self.y, text)

    def _wrapped(self, text: str, *, indent_mm: float = 0.0, first_indent_mm: float = 0.0,
                 align=_ALIGN_FLAG) -> None:
        """Перенесення абзацу по ширині тексту з урахуванням відступів (§7.7)."""
        self.c.setFont(_FONT_REGULAR, self.body_pt)
        words = text.split()
        line = ""
        first = True
        avail_first = self.text_width - first_indent_mm * mm
        avail_rest = self.text_width - indent_mm * mm
        for word in words:
            trial = f"{line} {word}".strip()
            avail = avail_first if first else avail_rest
            if pdfmetrics.stringWidth(trial, _FONT_REGULAR, self.body_pt) <= avail:
                line = trial
            else:
                self._line(line, indent_mm=first_indent_mm if first else indent_mm, align=align)
                first = False
                line = word
        if line:
            self._line(line, indent_mm=first_indent_mm if first else indent_mm, align=align)

    def _gap(self, factor: float = 1.0) -> None:
        self.y -= self.leading * factor

    # --- реквізити ---
    def render(self) -> None:
        # 04 найменування юридичної особи — центрований, напівжирний
        self._line(self.content.org_name, font=_FONT_BOLD, align=_ALIGN_CENTER)

        # 09 назва виду — не на листах (§4.4), збільшений кегль (§7.2)
        if not self.doc.is_letter and self.content.doc_type.strip():
            self._gap(0.5)
            self._line(
                self.content.doc_type.upper(),
                font=_FONT_BOLD,
                size=self.doc_type_pt,
                align=_ALIGN_CENTER,
            )

        # 10 дата + 11 реєстраційний індекс
        self._gap()
        self._line(f"{self.content.date_text}    № {self.content.reg_index}")

        # адресати — відступ 90 мм (§7.7)
        if self.content.addressees:
            self._gap()
            for addressee in self.content.addressees:
                for part in addressee.split("\n"):
                    self._line(part, indent_mm=self.doc.left_indents.addressee_mm)

        # 19 заголовок до тексту — центрований, напівжирний
        if self.content.title.strip():
            self._gap()
            self._wrapped(self.content.title, align=_ALIGN_CENTER)

        # 20 текст — абзацний відступ 10 мм (§7.7), вирівнювання за шириною
        self._gap()
        for para in self.content.body:
            self._wrapped(para, first_indent_mm=self.doc.left_indents.paragraph_mm)
            self._gap(0.3)

        # підпис: посада + розшифрування
        self._gap(1.5)
        self._line(
            f"{self.content.signature_position}"
            f"{' ' * 12}{self.content.signature_name}"
        )

        # завершальна сторінка: номер (якщо 2+)
        self._draw_page_number()

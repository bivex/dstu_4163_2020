"""PdfDocumentWriter — адаптер порту DocumentWriter на базі reportlab.

Реалізує ТОЙ САМИЙ порт, що й DocxDocumentWriter (LSP): взаємозамінні без
зміни use-case. Фізично відтворює оформлення згідно з параметрами Document:
поля (§6.2), формат (§6.1), гарнітура та кеглі (§7.2), міжрядковий інтервал
(§7.3), відступи (§7.7), нумерація сторінок (§7.10).

Уся залежність від reportlab ізольована тут (інфраструктура).
"""

from __future__ import annotations

import io

from reportlab.lib.pagesizes import A3, A4, A5
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from ..domain.model import Document, DocumentContent
from ..domain.model.qr_payload import build_signature_qr_payload
from .fonts import FontPaths, resolve_times_new_roman

_FONT_REGULAR = "DSTU-Serif"
_FONT_BOLD = "DSTU-Serif-Bold"
_FONT_HANDWRITTEN = "MarckScript"

_PAGE_SIZES = {"A4": A4, "A5": A5, "A3": A3}

# §5.10: QR-код — рівно 21×21 мм.
_QR_SIDE_MM = 21

# §6.7: способи розташування реквізитів бланка
_ALIGN_CENTER = "center"
_ALIGN_FLAG = "flag"  # прапоровий = від лівого поля


class PdfDocumentWriter:
    """Записує доменний документ у файл .pdf за правилами ДСТУ 4163:2020."""

    def __init__(
        self, fonts: FontPaths | None = None, *, pagination_barcode: bool = False, use_handwritten_date_index: bool = False
    ) -> None:
        self._fonts = fonts or resolve_times_new_roman()
        self._fonts_registered = False
        # Службовий штрихкод машинної пагінації (Code128) — за замовчуванням
        # вимкнено; вмикається явно для документообігу з потоковим скануванням.
        self._pagination_barcode = pagination_barcode
        self._use_handwritten_date_index = use_handwritten_date_index

    def _ensure_fonts(self) -> None:
        if self._fonts_registered:
            return
        pdfmetrics.registerFont(TTFont(_FONT_REGULAR, self._fonts.regular))
        pdfmetrics.registerFont(TTFont(_FONT_BOLD, self._fonts.bold))
        pdfmetrics.registerFontFamily(
            _FONT_REGULAR, normal=_FONT_REGULAR, bold=_FONT_BOLD
        )
        # Реєструємо рукописний шрифт MarckScript
        from pathlib import Path
        marck_path = Path(__file__).parent / "data" / "MarckScript-Regular.ttf"
        if marck_path.is_file():
            pdfmetrics.registerFont(TTFont(_FONT_HANDWRITTEN, str(marck_path)))
        self._fonts_registered = True

    def write(self, document: Document, content: DocumentContent, destination: str) -> str:
        self._ensure_fonts()
        if not destination.endswith(".pdf"):
            destination = f"{destination}.pdf"

        fmt_val = document.geometry.paper_format.value
        if fmt_val not in _PAGE_SIZES:
            raise ValueError(f"Непідтримуваний формат аркуша: '{fmt_val}'. Підтримуються: {list(_PAGE_SIZES.keys())}")
        page_size = _PAGE_SIZES[fmt_val]

        total_pages: int | None = None
        if self._pagination_barcode:
            # Прохід 1 (у пам'ять): порахувати загальну кількість сторінок, щоб
            # штрихкод ніс «<стор.>/<усього>» для звірки комплектності пачки.
            counter = canvas.Canvas(io.BytesIO(), pagesize=page_size,
                                    initialFontName=_FONT_REGULAR)
            probe = _Layout(counter, document, content, page_size, use_handwritten_date_index=self._use_handwritten_date_index)
            probe.render()
            total_pages = probe.page_no

        # Фінальна верстка у файл.
        # initialFontName=_FONT_REGULAR: замінює дефолтний Helvetica (невбудований)
        # на наш TTF, щоб PDF/A-3 §6.2.11.4 не фіксував невбудований шрифт.
        c = canvas.Canvas(destination, pagesize=page_size,
                          initialFontName=_FONT_REGULAR)
        layout = _Layout(
            c,
            document,
            content,
            page_size,
            total_pages=total_pages,
            pagination_barcode=self._pagination_barcode,
            use_handwritten_date_index=self._use_handwritten_date_index,
        )
        layout.render()
        c.save()
        return destination


class _Layout:
    """Інкапсулює потік верстки сторінок з урахуванням полів та нумерації."""

    def __init__(
        self,
        c,
        document: Document,
        content: DocumentContent,
        page_size,
        total_pages: int | None = None,
        *,
        pagination_barcode: bool = False,
        use_handwritten_date_index: bool = False,
    ) -> None:
        self.c = c
        self.doc = document
        self.content = content
        self.page_w, self.page_h = page_size
        # Загальна кількість сторінок (з 1-го проходу); None — ще не відомо.
        self.total_pages = total_pages
        # Чи малювати службовий штрихкод пагінації.
        self.pagination_barcode = pagination_barcode
        self.use_handwritten_date_index = use_handwritten_date_index

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
        if self.page_no == 1:
            if self.content.use_incoming_stamp:
                self._draw_incoming_stamp()
            if self.content.use_archived_stamp:
                self._draw_archived_stamp()
        self._draw_page_number()
        self._draw_page_barcode()
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

    def _draw_page_barcode(self) -> None:
        """Штрихкод машинної пагінації — Code128 у правому верхньому полі.

        Несе маршрутний маркер аркуша (службова машинна позначка, окремо від
        видимого номера за §7.10), тож друкується на КОЖНІЙ сторінці:
            <doc_id>|<стор.>/<усього>|<reg_index>|<E|P>
        напр.  ENAKAZ-2026-032|3/3|032-од|E
        Поля: ідентифікатор документа; позиція аркуша та комплектність пачки;
        реєстраційний індекс (прив'язка до діловодства); тип — E (електронний)
        чи P (паперовий). Дані КЕП у штрихкод НЕ кладемо: для цього є QR (§5.10)
        з верифікованими полями сертифіката; штрихкод лише ідентифікує аркуш.
        """
        if not self.pagination_barcode:
            return
        from reportlab.graphics.barcode import code128

        total = self.total_pages or self.page_no
        kind = "E" if self.doc.is_electronic else "P"
        value = (
            f"{self.doc.doc_id}|{self.page_no}/{total}"
            f"|{self.content.reg_index}|{kind}"
        )
        bar_h = 6 * mm
        # Штрихкод тримаємо у ПРАВІЙ зоні верхнього поля, щоб не накладатися на
        # видимий номер сторінки (§7.10, по центру). Доступна ширина — від
        # центру з запасом до правого поля; модуль ужимаємо, доки влазить.
        right_edge = self.page_w - self.right_margin
        avail_w = right_edge - (self.page_w / 2 + 10 * mm)
        bar_w = 0.30 * mm
        # humanReadable=0: вимикаємо вбудований текст штрихкоду (він використовує
        # Helvetica, яка не вбудовується → порушення PDF/A-3 §6.2.11.4).
        # Людиночитний підпис малюється окремо нижче через drawRightString
        # з зареєстрованим _FONT_REGULAR.
        barcode = code128.Code128(value, barHeight=bar_h, barWidth=bar_w,
                                  humanReadable=0)
        while barcode.width > avail_w and bar_w > 0.16 * mm:
            bar_w -= 0.02 * mm
            barcode = code128.Code128(value, barHeight=bar_h, barWidth=bar_w,
                                      humanReadable=0)
        
        # Перевірка низу сжаття: якщо навіть при 0.16мм ширини недостатньо — короткий payload
        if barcode.width > avail_w:
            short_val = f"{self.doc.doc_id[:12]}|{self.page_no}/{total}|{kind}"
            barcode = code128.Code128(short_val, barHeight=bar_h, barWidth=0.16 * mm, humanReadable=0)

        if barcode.width <= avail_w:
            x = right_edge - barcode.width
            y = self.page_h - self.top / 2 - bar_h / 2
            barcode.drawOn(self.c, x, y)
            
            # Людиночитна підпис під штрихкодом
            kind_label = "ел." if self.doc.is_electronic else "пап."
            caption = f"{self.content.date_text}  {self.page_no}/{total}  {kind_label}".strip()
            caption_w = pdfmetrics.stringWidth(caption, _FONT_REGULAR, 6)
            if caption_w > avail_w:
                caption = f"{self.page_no}/{total} {kind_label}"
            self.c.setFont(_FONT_REGULAR, 6)
            self.c.drawRightString(right_edge, y - 2.5 * mm, caption)

    def _gap(self, factor: float = 1.0) -> None:
        self.y -= self.leading * factor

    def _wrapped_col(self, text: str, x_start: float, col_width: float, font: str = _FONT_REGULAR, size: float | None = None, align: str = _ALIGN_FLAG, y_pos: float | None = None) -> float:
        size = size or self.body_pt
        self.c.setFont(font, size)
        current_y = y_pos if y_pos is not None else self.y
        words = text.split()
        line = ""
        leading = size * 1.2
        for word in words:
            trial = f"{line} {word}".strip()
            if pdfmetrics.stringWidth(trial, font, size) <= col_width:
                line = trial
            else:
                current_y -= leading
                if align == _ALIGN_CENTER:
                    self.c.drawCentredString(x_start + col_width / 2, current_y, line)
                else:
                    self.c.drawString(x_start, current_y, line)
                line = word
        if line:
            current_y -= leading
            if align == _ALIGN_CENTER:
                self.c.drawCentredString(x_start + col_width / 2, current_y, line)
            else:
                self.c.drawString(x_start, current_y, line)
        return current_y

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
                 align=_ALIGN_FLAG, font=_FONT_REGULAR, size=None) -> None:
        """Перенесення абзацу по ширині тексту з урахуванням відступів (§7.7)."""
        size = size or self.body_pt
        self.c.setFont(font, size)
        words = text.split()
        line = ""
        first = True
        avail_first = self.text_width - first_indent_mm * mm
        avail_rest = self.text_width - indent_mm * mm
        for word in words:
            trial = f"{line} {word}".strip()
            avail = avail_first if first else avail_rest
            if pdfmetrics.stringWidth(trial, font, size) <= avail:
                line = trial
            else:
                self._line(
                    line, font=font, size=size,
                    indent_mm=first_indent_mm if first else indent_mm, align=align,
                )
                first = False
                line = word
        if line:
            self._line(
                line, font=font, size=size,
                indent_mm=first_indent_mm if first else indent_mm, align=align,
            )

    # --- реквізити ---
    def render(self) -> None:
        # QR-коди КЕП малюються поряд із кожною відміткою підписувача (внизу),
        # а не стовпчиком у правому полі — так вони масштабуються на багатьох
        # підписантів і природно переносяться між сторінками.
        if self.content.use_control_stamp:
            self._draw_control_stamp()
        if self.content.use_annulled_stamp:
            self._draw_annulled_stamp()
        if self.content.use_copy_mark:
            self._draw_copy_mark_stamp()
        if self.content.use_urgent_stamp:
            self._draw_urgent_stamp()

        # Додаткові довільні корпоративні штампи
        top_right_count = 0
        top_center_count = 0
        left_margin_count = 0
        
        for stamp_text in self.content.extra_stamps:
            loc, color = self._classify_extra_stamp(stamp_text)
            if loc == "top_right":
                y = self.page_h - self.top - 38 * mm - top_right_count * 10 * mm
                self._draw_generic_stamp(stamp_text, y, loc, color)
                top_right_count += 1
            elif loc == "top_center":
                y = self.page_h - self.top - 24 * mm - top_center_count * 11 * mm
                self._draw_generic_stamp(stamp_text, y, loc, color)
                top_center_count += 1
            elif loc == "left_margin":
                y = self.page_h - 70 * mm - left_margin_count * 10 * mm
                self._draw_generic_stamp(stamp_text, y, loc, color)
                left_margin_count += 1

        # Робоча кутова чи поздовжня верстка бланка (§6.7 ДСТУ 4163:2020)
        is_corner_layout = bool(self.content.addressees) or self.doc.is_letter

        if is_corner_layout:
            # --- КУТОВИЙ БЛАНК (§6.7, Додаток А ДСТУ 4163:2020) ---
            start_y = self.y
            left_col_w = min(80 * mm, self.text_width / 2)
            
            # Відступи від лівого поля бланка:
            # 100 мм — для Грифу затвердження та Грифу обмеження доступу
            # 90 мм — для блоку Адресата (§7.6: довжина рядка ≤ 73 мм)
            right_col_x = self.left + 100 * mm
            right_col_w = min(73 * mm, max(30 * mm, (self.left + self.text_width) - right_col_x))

            addressee_x = self.left + 90 * mm
            addressee_w = min(73 * mm, max(30 * mm, (self.left + self.text_width) - addressee_x))

            # 1. Рендеримо ліву колонку
            y_left = start_y
            is_state_org = any(
                word in self.content.org_name.upper()
                for word in ["ДЕРЖАВН", "МІНІСТЕРСТВ", "НАЦІОНАЛЬН", "ПРОКУР", "СЛУЖБ"]
            )
            if is_state_org:
                # Нормативний розмір герба за ДСТУ 4163:2020: 17 мм (висота) × 12 мм (ширина)
                w = 12 * mm
                h = 17 * mm
                if self.doc.symbols and self.doc.symbols.coat_of_arms_height_mm > 0:
                    h = self.doc.symbols.coat_of_arms_height_mm * mm
                if self.doc.symbols and self.doc.symbols.coat_of_arms_width_mm > 0:
                    w = self.doc.symbols.coat_of_arms_width_mm * mm
                
                x = self.left + left_col_w / 2
                self.c.saveState()
                try:
                    self._draw_coat_of_arms(x, y_left - h, w, h)
                finally:
                    self.c.restoreState()
                y_left -= h + 2 * mm

            y_left = self._wrapped_col(self.content.org_name, self.left, left_col_w, font=_FONT_BOLD, size=11, y_pos=y_left)
            y_left -= 4 * mm 
            
            place = self.content.place.strip()
            date_idx_str = f"{self.content.date_text} № {self.content.reg_index}"
            if place:
                y_left = self._wrapped_col(place, self.left, left_col_w, font=_FONT_REGULAR, size=10, y_pos=y_left)
            if self.use_handwritten_date_index:
                self.c.saveState()
                try:
                    self.c.setFillColorRGB(0.08, 0.15, 0.49) # Blue ink
                    y_left = self._wrapped_col(date_idx_str, self.left + 1 * mm, left_col_w, font=_FONT_HANDWRITTEN, size=11, y_pos=y_left)
                finally:
                    self.c.restoreState()
            else:
                y_left = self._wrapped_col(date_idx_str, self.left, left_col_w, font=_FONT_REGULAR, size=10, y_pos=y_left)

            # 2. Рендеримо праву колонку
            y_right = start_y

            if self.content.marking.strip():
                y_right = self._wrapped_col(self.content.marking.upper(), right_col_x, right_col_w, font=_FONT_BOLD, size=11, y_pos=y_right)
                y_right -= 2 * mm

            if self.content.restriction_stamp and self.content.restriction_stamp != "none":
                y_right = self._wrapped_col(self.content.restriction_stamp.upper(), right_col_x, right_col_w, font=_FONT_BOLD, size=11, y_pos=y_right)
                y_right -= 2 * mm
            elif self.content.access_restriction is not None:
                y_right = self._wrapped_col(self.content.access_restriction.heading.upper(), right_col_x, right_col_w, font=_FONT_BOLD, size=11, y_pos=y_right)
                y_right -= 2 * mm

            # Адресат рендериться від 90 мм від лівого поля (Додаток А ДСТУ 4163:2020)
            # §5.15: При наявності понад 4 адресатів зазначаються перші 4 з приміткою "(за списком розсилання)"
            if self.content.addressees:
                target_addressees = list(self.content.addressees)
                is_distribution_list = len(target_addressees) > 4
                if is_distribution_list:
                    target_addressees = target_addressees[:4]

                for idx, addressee in enumerate(target_addressees):
                    text_lines = [p.strip() for p in addressee.split("\n") if p.strip()]
                    if is_distribution_list and idx == len(target_addressees) - 1:
                        text_lines.append("(за списком розсилання)")
                    for part in text_lines:
                        y_right = self._wrapped_col(part, addressee_x, addressee_w, font=_FONT_REGULAR, size=11, y_pos=y_right)
                    y_right -= 3 * mm

            if self.content.sender_contacts.strip():
                sender_name = self.content.org_name.removeprefix("Гр. ").strip()
                y_right = self._wrapped_col(f"від {sender_name},", addressee_x, addressee_w, font=_FONT_REGULAR, size=11, y_pos=y_right)
                for contact_line in self.content.sender_contacts.split("\n"):
                    if contact_line.strip():
                        y_right = self._wrapped_col(contact_line.strip(), addressee_x, addressee_w, font=_FONT_REGULAR, size=10, y_pos=y_right)

            if self.content.approval is not None:
                y_right -= 3 * mm
                grant = self.content.approval
                y_right = self._wrapped_col(grant.heading, right_col_x, right_col_w, font=_FONT_BOLD, size=11, y_pos=y_right)
                if grant.is_by_document:
                    for part in grant.document_reference.split("\n"):
                        if part.strip():
                            y_right = self._wrapped_col(part.strip(), right_col_x, right_col_w, font=_FONT_REGULAR, size=11, y_pos=y_right)
                else:
                    if grant.position:
                        y_right = self._wrapped_col(grant.position, right_col_x, right_col_w, font=_FONT_REGULAR, size=11, y_pos=y_right)
                    if grant.name:
                        y_right = self._wrapped_col(grant.name, right_col_x, right_col_w, font=_FONT_REGULAR, size=11, y_pos=y_right)
                    if grant.date:
                        y_right = self._wrapped_col(grant.date, right_col_x, right_col_w, font=_FONT_REGULAR, size=11, y_pos=y_right)

            self.y = min(y_left, y_right) - 8 * mm

        else:
            # --- ПОЗДОВЖНІЙ БЛАНК ---
            is_state_org = any(
                word in self.content.org_name.upper()
                for word in ["ДЕРЖАВН", "МІНІСТЕРСТВ", "НАЦІОНАЛЬН", "ПРОКУР", "СЛУЖБ"]
            )
            if (
                is_state_org
                and self.doc.symbols
                and self.doc.symbols.coat_of_arms_height_mm > 0
                and self.doc.symbols.coat_of_arms_width_mm > 0
            ):
                w = self.doc.symbols.coat_of_arms_width_mm * mm
                h = self.doc.symbols.coat_of_arms_height_mm * mm
                x = self.page_w / 2
                self.c.saveState()
                try:
                    self._draw_coat_of_arms(x, self.y - h, w, h)
                finally:
                    self.c.restoreState()
                self.y -= h
                self._gap(0.6)

            self._wrapped(self.content.org_name, align=_ALIGN_CENTER, font=_FONT_BOLD)

            if self.content.restriction_stamp and self.content.restriction_stamp != "none":
                self._draw_restriction_stamp(self.content.restriction_stamp)
            elif self.content.access_restriction is not None:
                self._line(
                    self.content.access_restriction.heading,
                    indent_mm=self.doc.left_indents.restriction_mm,
                    font=_FONT_BOLD,
                )

            if not self.doc.is_letter and self.content.doc_type.strip():
                self._gap(0.5)
                self._wrapped(
                    self.content.doc_type.upper(),
                    align=_ALIGN_CENTER,
                    font=_FONT_BOLD,
                    size=self.doc_type_pt,
                )

            self._gap()
            place = self.content.place.strip()
            prefix = f"{place}    " if place else ""
            if self.use_handwritten_date_index:
                if place:
                    self.c.setFont(_FONT_REGULAR, 10)
                    self.c.drawString(self.left, self.y, place)
                self.c.saveState()
                self.c.setFillColorRGB(0.08, 0.15, 0.49) # Blue ink
                self.c.setFont(_FONT_HANDWRITTEN, 11)
                x_offset = self.c.stringWidth(prefix, _FONT_REGULAR, 10) if prefix else 0
                self.c.drawString(self.left + x_offset, self.y, f"{self.content.date_text}    № {self.content.reg_index}")
                self.c.restoreState()
                self.y -= self.body_pt * 1.2
            else:
                self._line(f"{prefix}{self.content.date_text}    № {self.content.reg_index}")



        # 19 заголовок до тексту — центрований, напівжирний
        if self.content.title.strip():
            self._gap()
            self._wrapped(self.content.title, align=_ALIGN_CENTER)

        # 20 текст — абзацний відступ 10 мм (§7.7), вирівнювання за шириною
        self._gap()
        for para in self.content.body:
            self._wrapped(para, first_indent_mm=self.doc.left_indents.paragraph_mm)
            self._gap(0.3)

        # підпис (§4.4 реквізит 22):
        #   е-документ із відміткою КЕП → рамка-відмітка по ключу (Art.18/24);
        #   інакше → рукописний реквізит «посада + розшифрування».
        self._gap(0.6)
        # Атомарне резервування місця під весь блок підпису (Orphan Signature Control)
        self._ensure_space(28 * mm)
        if self.doc.is_electronic and self.content.signatures:
            for i, mark in enumerate(self.content.signatures):
                if i:
                    self._gap(0.3)  # компактний зазор між відмітками підписантів
                self._draw_e_signature_mark(mark)
        else:
            for i, (position, name) in enumerate(self.content.paper_signers):
                if i:
                    self._gap(0.6)  # зазор між підписантами (голова/секретар)
                # посада ліворуч, розшифрування — у фіксованій колонці (§7.7,
                # відступ 125 мм), щоб імена різних підписантів вирівнювались
                self._line(position)
                decode_x = self.left + self.doc.left_indents.signature_decode_mm * mm
                self.c.setFont(_FONT_REGULAR, self.body_pt)
                self.c.drawString(decode_x, self.y, name)
                if self.content.use_stamp or self.content.stamp_type:
                    # Печатка — коло радіусом 20 мм (діаметр 40 мм). Забезпечуємо простір
                    stamp_r = 20 * mm
                    self._ensure_space(stamp_r)
                    self._draw_stamp(self.left + 95 * mm, self.y + 2 * mm)

        # 23 грифи погодження (ПОГОДЖЕНО) — зовнішнє, нижче підпису, від лівого поля
        for agreement in self.content.agreements:
            self._gap(0.8)
            self._draw_agreement(agreement)

        # 24 візи — внутрішнє погодження, нижче погоджень
        for visa in self.content.visas:
            self._gap(0.6)
            self._draw_visa(visa)

        if self.content.use_copy_stamp:
            self._draw_copy_stamp()

        # завершальна сторінка: номер (якщо 2+) + штрихкод пагінації
        if self.page_no == 1:
            if self.content.use_incoming_stamp:
                self._draw_incoming_stamp()
            if self.content.use_archived_stamp:
                self._draw_archived_stamp()
        self._draw_page_number()
        self._draw_page_barcode()

    def _draw_approval_grant(self, grant) -> None:
        """Гриф затвердження (реквізит 21) — праворуч угорі, відступ 100 мм (§7.7).

        ЗАТВЕРДЖУЮ (персональна форма): заголовок, посада, розшифрування, дата.
        ЗАТВЕРДЖЕНО (через документ): заголовок + посилання на документ.
        """
        indent = self.doc.left_indents.approval_mm
        self._line(grant.heading, indent_mm=indent, font=_FONT_BOLD)
        if grant.is_by_document:
            for part in grant.document_reference.split("\n"):
                self._wrapped(part, indent_mm=indent, first_indent_mm=indent)
            return
        if grant.position:
            self._wrapped(grant.position, indent_mm=indent, first_indent_mm=indent)
        if grant.name:
            self._line(grant.name, indent_mm=indent)
        if grant.date:
            self._line(grant.date, indent_mm=indent)

    def _draw_agreement(self, agreement) -> None:
        """Гриф погодження (реквізит 23, ПОГОДЖЕНО) — зовнішнє, від лівого поля."""
        self._line("ПОГОДЖЕНО", font=_FONT_BOLD)
        if agreement.is_by_document:
            for part in agreement.document_reference.split("\n"):
                self._wrapped(part)
            return
        if agreement.position:
            self._wrapped(agreement.position)
        if agreement.name or agreement.date:
            decode = agreement.name
            if agreement.date:
                decode = f"{decode}{' ' * 8}{agreement.date}".strip()
            self._line(decode)

    def _draw_visa(self, visa) -> None:
        """Віза (реквізит 24) — внутрішнє погодження, від лівого поля."""
        self._wrapped(visa.position)
        decode = visa.name
        if visa.date:
            decode = f"{decode}{' ' * 8}{visa.date}".strip()
        self._line(decode)
        if visa.remark:
            self._wrapped(f"Зауваження: {visa.remark}", size=self.body_pt)

    def _draw_e_signature_mark(self, mark) -> None:
        """Відмітка про електронний підпис/печатку за даними сертифіката.

        Стик §4.4(22) ДСТУ ↔ Art.18/24 Закону 2155-VIII. Якщо сертифікат
        нечинний (Art.24) — відмітка позначається як НЕДІЙСНА. Довгі рядки
        (серійник, видавець) переносяться у межах рамки.

        Для mark.kind=='eseal' (електронна печатка юрособи) — інший вигляд:
        замість «Підписувач: ПІБ» друкуємо «Власник печатки: <назва юрособи>»
        та ідентифікатор (ЄДРПОУ/РНОКПП) з сертифіката; посада не виводиться.
        """
        is_seal = getattr(mark, "kind", "esign") == "eseal"
        raw_lines = [(mark.signature_kind, _FONT_BOLD)]
        if is_seal:
            org = getattr(mark, "organization", "") or mark.signer
            raw_lines.append((f"Власник печатки: {org}", _FONT_REGULAR))
            identifier = getattr(mark, "identifier", "")
            if identifier:
                raw_lines.append((f"Ідентифікатор: {identifier}", _FONT_REGULAR))
        else:
            raw_lines.append((f"Підписувач: {mark.signer}", _FONT_REGULAR))
            # посада — лише якщо присутня у сертифікаті (сертифікат працівника)
            if mark.signer_position.strip():
                raw_lines.append((f"Посада: {mark.signer_position}", _FONT_REGULAR))
        raw_lines += [
            (f"Сертифікат: {mark.certificate_serial}", _FONT_REGULAR),
            (f"Видавець: {mark.issuer}", _FONT_REGULAR),
            (f"Чинний: {mark.valid_from} – {mark.valid_to}", _FONT_REGULAR),
            (f"Позначка часу: {mark.timestamp}", _FONT_REGULAR),
        ]
        if mark.certificate_valid:
            raw_lines.append(("Статус сертифіката: ЧИННИЙ", _FONT_BOLD))
        else:
            raw_lines.append(("Статус сертифіката: НЕДІЙСНИЙ (ст.24)", _FONT_BOLD))

        small = 8  # §7.2: довідкові дані 8–12 pt — беремо мінімум для компактності
        pad = 2 * mm
        line_h = small * 1.15
        box_w = min(self.text_width, 95 * mm)  # §7.6: ширина реквізиту ≤73–95 мм
        avail_pt = box_w - 2 * pad  # доступна ширина у пунктах

        # перенесення кожного рядка по ширині рамки (із жорстким розривом токенів)
        wrapped: list[tuple[str, str]] = []
        for text, font in raw_lines:
            for piece in self._wrap_to_width(text, font, small, avail_pt):
                wrapped.append((piece, font))

        box_h = line_h * len(wrapped) + 2 * pad
        side = _QR_SIDE_MM * mm
        required_h = max(box_h, side)
        offset_top = max(0.0, (side - box_h) / 2)

        # Гарантуємо вільне місце під весь блок (рамка КЕП або QR — що вище)
        self._ensure_space(required_h + line_h * 0.4)
        top = self.y - offset_top
        bottom = top - box_h
        self.c.setLineWidth(0.6)
        self.c.rect(self.left, bottom, box_w, box_h, stroke=1, fill=0)

        ty = top - pad - small
        for text, font in wrapped:
            self.c.setFont(font, small)
            self.c.drawString(self.left + pad, ty, text)
            ty -= line_h

        # QR-код підписувача — праворуч від рамки, центрований по її висоті.
        # Подорожує разом із відміткою, тож масштабується на багатьох підписантів.
        self._draw_mark_qr(mark, top, box_h)
        if self.content.use_stamp or self.content.stamp_type:
            # Накладаємо печатку поверх електронного підпису/QR
            self._draw_stamp(self.left + 50 * mm, bottom + box_h / 2)
        self.y = min(bottom, top + box_h / 2 - side / 2) - line_h

    def _wrap_to_width(self, text: str, font: str, size: float, avail_pt: float) -> list[str]:
        """Розбити рядок на частини за доступною шириною (у пунктах).

        Спершу по словах; якщо окреме слово (напр. серійник) ширше за рядок —
        розриваємо його посимвольно.
        """
        out: list[str] = []
        line = ""
        for word in text.split(" "):
            trial = f"{line} {word}".strip()
            if pdfmetrics.stringWidth(trial, font, size) <= avail_pt:
                line = trial
                continue
            if line:
                out.append(line)
                line = ""
            # слово саме по собі може не вміщатися — ріжемо посимвольно
            if pdfmetrics.stringWidth(word, font, size) <= avail_pt:
                line = word
            else:
                chunk = ""
                for ch in word:
                    if pdfmetrics.stringWidth(chunk + ch, font, size) <= avail_pt:
                        chunk += ch
                    else:
                        out.append(chunk)
                        chunk = ch
                line = chunk
        if line:
            out.append(line)
        return out or [""]

    def _draw_mark_qr(self, mark, box_top: float, box_h: float) -> None:
        """QR-код 21×21 мм праворуч від КЕП-відмітки, центрований по вертикалі.

        Кодує дані КЕП/печатки + кваліфіковану позначку часу (§5.10/§5.31).
        Розташований поряд із відміткою свого підписувача, тож при багатьох
        підписантах QR-коди не накопичуються в полі, а йдуть з відмітками.
        """
        import segno  # локальний імпорт: залежність потрібна лише за наявності QR

        payload = build_signature_qr_payload(mark)
        # Адаптивний рівень корекції: при довгому payload беремо "l" (7%),
        # щоб розмір модуля на 21 мм не опускався нижче порогу зчитування (≥0.35 мм)
        err_lvl = "l" if len(payload) > 120 else "m"
        qr = segno.make(payload, error=err_lvl)
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=10, border=0)
        buf.seek(0)

        side = _QR_SIDE_MM * mm
        gap = 4 * mm  # відступ від рамки відмітки (ширина рамки ≤95 мм)
        box_w = min(self.text_width, 95 * mm)
        x = self.left + box_w + gap
        # не виходити за праве поле; якщо тісно — притиснути до правого краю
        x = min(x, self.page_w - self.right_margin - side)
        y = box_top - (box_h + side) / 2
        self.c.setFillColorRGB(1, 1, 1)
        self.c.rect(x - mm, y - mm, side + 2 * mm, side + 2 * mm, stroke=0, fill=1)
        self.c.setFillColorRGB(0, 0, 0)
        self.c.drawImage(
            ImageReader(buf), x, y, width=side, height=side, preserveAspectRatio=True, mask="auto"
        )

    def _draw_coat_of_arms(self, x_center: float, y_bottom: float, w: float, h: float) -> None:
        from svglib.svglib import svg2rlg
        from pathlib import Path

        svg_path = Path(__file__).parent / "data" / "coat_of_arms.svg"
        if not svg_path.is_file():
            return

        drawing = svg2rlg(str(svg_path))
        if drawing is None:
            return

        orig_w = drawing.width
        orig_h = drawing.height

        scale_x = w / orig_w
        scale_y = h / orig_h

        drawing.scale(scale_x, scale_y)
        drawing.width = w
        drawing.height = h

        # Малюємо герб від y_bottom (нижній лівий кут обмежувального боксу)
        x = x_center - w / 2
        drawing.drawOn(self.c, x, y_bottom)

    def _calculate_baseline(self, y: float, h: float, font_name: str, font_size: float, offset: float = 0.3 * mm) -> float:
        """Обчислити вертикальну базову лінію для центрованого тексту у рамці заданої висоти h."""
        font_obj = pdfmetrics.getFont(font_name)
        ascent = font_obj.face.ascent * font_size / 1000.0
        descent = abs(font_obj.face.descent) * font_size / 1000.0
        return y + (h - (ascent - descent)) / 2.0 - descent + offset

    def _draw_double_round_rect(self, x: float, y: float, w: float, h: float, radius: float, offset: float = 0.8 * mm) -> None:
        """Малює преміальну подвійну рамку з округленими кутами."""
        # Зовнішня товща рамка
        self.c.setLineWidth(0.9)
        self.c.roundRect(x, y, w, h, radius)
        # Внутрішня тонка рамка
        self.c.setLineWidth(0.35)
        inner_r = max(0.2 * mm, radius - offset)
        self.c.roundRect(x + offset, y + offset, w - 2 * offset, h - 2 * offset, inner_r)

    def _draw_stamp(self, x: float, y: float) -> None:
        """Малює візуальний синій круглий відбиток печатки компанії у преміум-стилі (Banking Indigo)."""
        stype = self.content.stamp_type.strip().lower()
        if not stype:
            if self.content.use_stamp:
                stype = "documents"
            else:
                return

        import math
        from reportlab.pdfbase import pdfmetrics
        self.c.saveState()
        try:
            # Преміальний банківський синій колір (Banking Indigo)
            self.c.setStrokeColorRGB(0.03, 0.14, 0.42)
            self.c.setFillColorRGB(0.03, 0.14, 0.42)
            self.c.setLineWidth(2.2)
            
            # Зовнішнє товсте коло (діаметр 40 мм = радіус 20 мм)
            r = 20 * mm
            self.c.circle(x, y, r, stroke=1, fill=0)
            
            # Внутрішнє тонке коло (радіус 17.5 мм, відстань 2.5 мм)
            self.c.setLineWidth(0.6)
            self.c.circle(x, y, 17.5 * mm, stroke=1, fill=0)
            
            # Центральний текст
            self.c.setFont(_FONT_BOLD, 7)
            if stype == "contracts":
                self.c.drawCentredString(x, y + 2.3 * mm, "ДЛЯ")
                self.c.drawCentredString(x, y - 1.7 * mm, "ДОГОВОРІВ")
            elif stype == "hr":
                self.c.drawCentredString(x, y + 2.3 * mm, "ВІДДІЛ")
                self.c.drawCentredString(x, y - 1.7 * mm, "КАДРІВ")
            elif stype == "chancellery":
                self.c.setFont(_FONT_BOLD, 8)
                self.c.drawCentredString(x, y + 0.3 * mm, "КАНЦЕЛЯРІЯ")
            elif stype in ["buh", "bookkeeping", "accounting", "бухгалтерія"]:
                self.c.setFont(_FONT_BOLD, 8)
                self.c.drawCentredString(x, y + 0.3 * mm, "БУХГАЛТЕРІЯ")
            elif stype in ["law", "legal", "юридичний"]:
                self.c.drawCentredString(x, y + 2.3 * mm, "ЮРИДИЧНИЙ")
                self.c.drawCentredString(x, y - 1.7 * mm, "ВІДДІЛ")
            elif stype in ["sec", "security", "безпека"]:
                self.c.drawCentredString(x, y + 2.3 * mm, "СЛУЖБА")
                self.c.drawCentredString(x, y - 1.7 * mm, "БЕЗПЕКИ")
            elif stype in ["pur", "purchasing", "procurement", "закупівлі"]:
                self.c.drawCentredString(x, y + 2.3 * mm, "ВІДДІЛ")
                self.c.drawCentredString(x, y - 1.7 * mm, "ЗАКУПІВЕЛЬ")
            elif stype in ["doc", "workflow", "records", "документообіг"]:
                self.c.drawCentredString(x, y + 2.3 * mm, "ВІДДІЛ")
                self.c.drawCentredString(x, y - 1.7 * mm, "ДОКУМЕНТООБІГУ")
            elif stype in ["arc", "archive", "архів"]:
                self.c.setFont(_FONT_BOLD, 8)
                self.c.drawCentredString(x, y + 0.3 * mm, "АРХІВ")
            elif stype in ["fin", "finance", "financial", "фінансовий"]:
                self.c.drawCentredString(x, y + 2.3 * mm, "ФІНАНСОВИЙ")
                self.c.drawCentredString(x, y - 1.7 * mm, "ВІДДІЛ")
            else:  # documents / fallback
                self.c.drawCentredString(x, y + 2.3 * mm, "ДЛЯ")
                self.c.drawCentredString(x, y - 1.7 * mm, "ДОКУМЕНТІВ")
            
            # Текст по верхній дузі (назва організації)
            org_text = self.content.org_name.upper()
            org_text = org_text.removeprefix("ГР. ").removeprefix("АТ ").strip()
            
            # Адаптивно обріжемо за шириною на дузі (доступно 190 градусів на радіусі 14.5 мм)
            r_text = 14.5 * mm
            max_arc_len = r_text * math.radians(190.0)
            
            font_name = _FONT_REGULAR
            font_size = 6.0
            spacing = 1.2
            
            def get_text_width(txt: str, f_size: float, sp: float) -> float:
                if not txt:
                    return 0.0
                return sum(pdfmetrics.stringWidth(c, font_name, f_size) for c in txt) + (len(txt) - 1) * sp

            # Динамічне зменшення розміру шрифту та інтервалу для запобігання обрізанню
            if get_text_width(org_text, font_size, spacing) > max_arc_len:
                for f_sz, sp in [(5.5, 1.0), (5.0, 0.8), (4.5, 0.6), (4.0, 0.5)]:
                    if get_text_width(org_text, f_sz, sp) <= max_arc_len:
                        font_size = f_sz
                        spacing = sp
                        break
                else:
                    font_size = 4.0
                    spacing = 0.5
                    while len(org_text) > 0 and get_text_width(org_text + "...", font_size, spacing) > max_arc_len:
                        org_text = org_text[:-1]
                    org_text += "..."
                    
            self.c.setFont(font_name, font_size)
            
            # Тепер розставимо символи пропорційно їх ширині на дузі
            if org_text:
                widths = [pdfmetrics.stringWidth(c, font_name, font_size) for c in org_text]
                total_w = sum(widths) + (len(org_text) - 1) * spacing
                total_angle = (total_w / r_text) * (180.0 / math.pi)
                
                # Починаємо симетрично від центру (0 градусів)
                start_angle = -total_angle / 2.0
                
                curr_angle = start_angle
                for i, char in enumerate(org_text):
                    char_angle_w = (widths[i] / r_text) * (180.0 / math.pi)
                    char_center_angle = curr_angle + char_angle_w / 2.0
                    
                    angle_rad = math.radians(char_center_angle)
                    char_x = x + r_text * math.sin(angle_rad)
                    char_y = y + r_text * math.cos(angle_rad)
                    
                    self.c.saveState()
                    self.c.translate(char_x, char_y)
                    self.c.rotate(-char_center_angle)
                    self.c.drawCentredString(0, 0, char)
                    self.c.restoreState()
                    
                    curr_angle += char_angle_w + (spacing / r_text) * (180.0 / math.pi)
            
            # Код ЄДРПОУ / ідентифікатор знизу (• замість *)
            code_text = "• УКРАЇНА •"
            if code_text:
                widths_code = [pdfmetrics.stringWidth(c, font_name, font_size) for c in code_text]
                total_w_code = sum(widths_code) + (len(code_text) - 1) * spacing
                total_angle_code = (total_w_code / r_text) * (180.0 / math.pi)
                
                start_angle_code = 180.0 + total_angle_code / 2.0
                
                curr_angle = start_angle_code
                for i, char in enumerate(code_text):
                    char_angle_w = (widths_code[i] / r_text) * (180.0 / math.pi)
                    char_center_angle = curr_angle - char_angle_w / 2.0
                    
                    angle_rad = math.radians(char_center_angle)
                    char_x = x + r_text * math.sin(angle_rad)
                    char_y = y + r_text * math.cos(angle_rad)
                    
                    self.c.saveState()
                    self.c.translate(char_x, char_y)
                    self.c.rotate(180.0 - char_center_angle)
                    self.c.drawCentredString(0, 0, char)
                    self.c.restoreState()
                    
                    curr_angle -= char_angle_w + (spacing / r_text) * (180.0 / math.pi)
        finally:
            self.c.restoreState()

    def _draw_control_stamp(self) -> None:
        """Малює червоний штамп «КОНТРОЛЬ» у лівому полі першої сторінки (подвійна рамка, розрядка)."""
        self.c.saveState()
        try:
            self.c.setStrokeColorRGB(0.62, 0.08, 0.10)
            self.c.setFillColorRGB(0.62, 0.08, 0.10)
            
            w = 26 * mm
            h = 8 * mm
            x = 4 * mm
            y = self.page_h - 60 * mm
            
            self._draw_double_round_rect(x, y, w, h, 1.0 * mm, 0.7 * mm)
            
            font_name = _FONT_BOLD
            font_size = 8.0
            self.c.setFont(font_name, font_size)
            
            from reportlab.pdfbase import pdfmetrics
            font_obj = pdfmetrics.getFont(font_name)
            ascent = font_obj.face.ascent * font_size / 1000.0
            descent = font_obj.face.descent * font_size / 1000.0
            # Оптичне центрування (+0.3 мм)
            y_baseline = y + (h - (ascent - descent)) / 2.0 - descent + 0.3 * mm
            
            self.c.drawCentredString(x + w / 2, y_baseline, "К О Н Т Р О Л Ь")
        finally:
            self.c.restoreState()

    def _draw_incoming_stamp(self) -> None:
        """Малює синій вхідний реєстраційний штамп організації у правому нижньому куті (подвійна рамка)."""
        self.c.saveState()
        try:
            self.c.setStrokeColorRGB(0.03, 0.14, 0.42)
            self.c.setFillColorRGB(0.03, 0.14, 0.42)
            
            w = 72 * mm
            h = 17 * mm
            x = self.page_w - self.right_margin - w
            y = 25 * mm
            
            # Подвійна зовнішня рамка
            self._draw_double_round_rect(x, y, w, h, 1.5 * mm, 0.8 * mm)
            
            # Внутрішня лінія-роздільник посередині (прив'язана до внутрішньої рамки)
            self.c.setLineWidth(0.35)
            self.c.line(x + 0.8 * mm, y + 8.5 * mm, x + w - 0.8 * mm, y + 8.5 * mm)
            
            # Вертикальна лінія-роздільник у нижній частині
            self.c.line(x + 30 * mm, y + 0.8 * mm, x + 30 * mm, y + 8.5 * mm)
            
            # Назва організації (вгорі, центровано)
            font_name_bold = _FONT_BOLD
            font_size_bold = 7.0
            self.c.setFont(font_name_bold, font_size_bold)
            
            from reportlab.pdfbase import pdfmetrics
            font_obj_bold = pdfmetrics.getFont(font_name_bold)
            ascent_bold = font_obj_bold.face.ascent * font_size_bold / 1000.0
            descent_bold = font_obj_bold.face.descent * font_size_bold / 1000.0
            
            # Висота верхнього осередку 7.7 мм (від y + 8.5 до y + 16.2)
            y_baseline_top = (y + 8.5 * mm) + (7.7 * mm - (ascent_bold - descent_bold)) / 2.0 - descent_bold + 0.3 * mm
            
            org = self.content.org_name.removeprefix("Гр. ").removeprefix("АТ ").strip()
            max_org_w = 64 * mm
            if pdfmetrics.stringWidth(org, font_name_bold, font_size_bold) > max_org_w:
                while len(org) > 0 and pdfmetrics.stringWidth(org + "...", font_name_bold, font_size_bold) > max_org_w:
                    org = org[:-1]
                org += "..."
                
            self.c.drawCentredString(x + w / 2, y_baseline_top, org)
            
            # Нижня частина (колонки) - шрифт regular
            font_name_reg = _FONT_REGULAR
            font_size_reg = 6.5
            self.c.setFont(font_name_reg, font_size_reg)
            
            font_obj_reg = pdfmetrics.getFont(font_name_reg)
            ascent_reg = font_obj_reg.face.ascent * font_size_reg / 1000.0
            descent_reg = font_obj_reg.face.descent * font_size_reg / 1000.0
            
            # Висота нижнього осередку 7.7 мм (від y + 0.8 до y + 8.5)
            y_baseline_bot = (y + 0.8 * mm) + (7.7 * mm - (ascent_reg - descent_reg)) / 2.0 - descent_reg + 0.3 * mm
            
            self.c.drawString(x + 3.5 * mm, y_baseline_bot, "Вх. № ________________")
            self.c.drawString(x + 33.5 * mm, y_baseline_bot, "від «___» ____________ 20___ р.")
        finally:
            self.c.restoreState()

    def _draw_copy_stamp(self) -> None:
        """Малює синій штамп засвідчення копії «Згідно з оригіналом» під підписами (подвійна рамка)."""
        self._ensure_space(22 * mm)
        self.c.saveState()
        try:
            self.c.setStrokeColorRGB(0.03, 0.14, 0.42)
            self.c.setFillColorRGB(0.03, 0.14, 0.42)
            
            w = 70 * mm
            h = 19 * mm
            x = self.left
            y = self.y - h - 3 * mm
            
            # Подвійна рамка
            self._draw_double_round_rect(x, y, w, h, 1.5 * mm, 0.8 * mm)
            
            # Лінія-роздільник
            self.c.setLineWidth(0.35)
            self.c.line(x + 0.8 * mm, y + 13 * mm, x + w - 0.8 * mm, y + 13 * mm)
            
            font_name_bold = _FONT_BOLD
            font_size_bold = 7.5
            self.c.setFont(font_name_bold, font_size_bold)
            
            from reportlab.pdfbase import pdfmetrics
            font_obj_bold = pdfmetrics.getFont(font_name_bold)
            ascent_bold = font_obj_bold.face.ascent * font_size_bold / 1000.0
            descent_bold = font_obj_bold.face.descent * font_size_bold / 1000.0
            
            # Висота верхнього осередку 5.2 мм (від y+13 до y+18.2)
            y_baseline_top = (y + 13 * mm) + (5.2 * mm - (ascent_bold - descent_bold)) / 2.0 - descent_bold + 0.2 * mm
            
            self.c.drawCentredString(x + w / 2, y_baseline_top, "З Г І Д Н О   З   О Р И Г І Н А Л О М")
            
            # Нижня частина (два рядки) - шрифт regular
            font_name_reg = _FONT_REGULAR
            font_size_reg = 6.5
            self.c.setFont(font_name_reg, font_size_reg)
            
            font_obj_reg = pdfmetrics.getFont(font_name_reg)
            ascent_reg = font_obj_reg.face.ascent * font_size_reg / 1000.0
            descent_reg = font_obj_reg.face.descent * font_size_reg / 1000.0
            
            # Перший рядок знизу (від y + 6.8 до y + 12.2)
            y_line1 = (y + 6.8 * mm) + (5.4 * mm - (ascent_reg - descent_reg)) / 2.0 - descent_reg + 0.2 * mm
            # Другий рядок знизу (від y + 0.8 до y + 6.8)
            y_line2 = (y + 0.8 * mm) + (6.0 * mm - (ascent_reg - descent_reg)) / 2.0 - descent_reg + 0.2 * mm
            
            pos = self.content.signature_position or "Посадова особа"
            name = self.content.signature_name or "І. Прізвище"
            
            max_text_w = 62 * mm
            if pdfmetrics.stringWidth(pos, font_name_reg, font_size_reg) > max_text_w:
                while len(pos) > 0 and pdfmetrics.stringWidth(pos + "...", font_name_reg, font_size_reg) > max_text_w:
                    pos = pos[:-1]
                pos += "..."
                
            self.c.drawString(x + 3.5 * mm, y_line1, pos)
            self.c.drawString(x + 3.5 * mm, y_line2, f"Підпис _________________  {name}")
            
            self.y = y - 2 * mm
        finally:
            self.c.restoreState()

    def _draw_restriction_stamp(self, label: str) -> None:
        """Малює червоний штамп обмеження доступу у правому верхньому куті (подвійна рамка)."""
        self.c.saveState()
        try:
            self.c.setStrokeColorRGB(0.62, 0.08, 0.10)
            self.c.setFillColorRGB(0.62, 0.08, 0.10)
            
            text = ""
            if label == "dsk":
                text = "ДЛЯ СЛУЖБОВОГО КОРИСТУВАННЯ"
            elif label == "secret":
                text = "Т А Є М Н О"
            elif label == "confidential":
                text = "КОНФІДЕНЦІЙНО"
            else:
                text = label.upper()
                
            font_name = _FONT_BOLD
            font_size = 7.0
            self.c.setFont(font_name, font_size)
            
            from reportlab.pdfbase import pdfmetrics
            w = max(40 * mm, (pdfmetrics.stringWidth(text, font_name, font_size) + 8 * mm))
            h = 8 * mm
            
            x = self.page_w - self.right_margin - w
            y = self.page_h - self.top - 8 * mm
            
            self.c.roundRect(x, y, w, h, 0.8 * mm)
            
            font_obj = pdfmetrics.getFont(font_name)
            ascent = font_obj.face.ascent * font_size / 1000.0
            descent = font_obj.face.descent * font_size / 1000.0
            y_baseline = y + (h - (ascent - descent)) / 2.0 - descent
            
            self.c.drawCentredString(x + w / 2, y_baseline, text)
        finally:
            self.c.restoreState()

    def _draw_copy_mark_stamp(self) -> None:
        """Малює синій прямокутний штамп «КОПІЯ» у правому верхньому куті першої сторінки (подвійна рамка)."""
        self.c.saveState()
        try:
            self.c.setStrokeColorRGB(0.03, 0.14, 0.42)
            self.c.setFillColorRGB(0.03, 0.14, 0.42)
            
            w = 26 * mm
            h = 8 * mm
            x = self.page_w - self.right_margin - w
            y = self.page_h - 19 * mm
            
            # Подвійна рамка
            self._draw_double_round_rect(x, y, w, h, 1.0 * mm, 0.7 * mm)
            
            font_name = _FONT_BOLD
            font_size = 8.0
            self.c.setFont(font_name, font_size)
            
            from reportlab.pdfbase import pdfmetrics
            font_obj = pdfmetrics.getFont(font_name)
            ascent = font_obj.face.ascent * font_size / 1000.0
            descent = font_obj.face.descent * font_size / 1000.0
            y_baseline = y + (h - (ascent - descent)) / 2.0 - descent + 0.3 * mm
            
            self.c.drawCentredString(x + w / 2, y_baseline, "К О П І Я")
        finally:
            self.c.restoreState()

    def _draw_archived_stamp(self) -> None:
        """Малює синій прямокутний штамп «ДО СПРАВИ» у лівому нижньому куті (подвійна рамка)."""
        self.c.saveState()
        try:
            self.c.setStrokeColorRGB(0.03, 0.14, 0.42)
            self.c.setFillColorRGB(0.03, 0.14, 0.42)
            
            w = 56 * mm
            h = 16 * mm
            x = self.left
            y = 25 * mm
            
            # Подвійна зовнішня рамка
            self._draw_double_round_rect(x, y, w, h, 1.5 * mm, 0.8 * mm)
            
            # Лінія-роздільник
            self.c.setLineWidth(0.35)
            self.c.line(x + 0.8 * mm, y + 10.5 * mm, x + w - 0.8 * mm, y + 10.5 * mm)
            
            font_name_bold = _FONT_BOLD
            font_size_bold = 7.0
            self.c.setFont(font_name_bold, font_size_bold)
            
            from reportlab.pdfbase import pdfmetrics
            font_obj_bold = pdfmetrics.getFont(font_name_bold)
            ascent_bold = font_obj_bold.face.ascent * font_size_bold / 1000.0
            descent_bold = font_obj_bold.face.descent * font_size_bold / 1000.0
            
            # Висота верхнього осередку 4.7 мм (від y + 10.5 до y + 15.2)
            y_baseline_top = (y + 10.5 * mm) + (4.7 * mm - (ascent_bold - descent_bold)) / 2.0 - descent_bold + 0.2 * mm
            
            self.c.drawCentredString(x + w / 2, y_baseline_top, "Д О   С П Р А В И")
            
            font_name_reg = _FONT_REGULAR
            font_size_reg = 6.0
            self.c.setFont(font_name_reg, font_size_reg)
            
            font_obj_reg = pdfmetrics.getFont(font_name_reg)
            ascent_reg = font_obj_reg.face.ascent * font_size_reg / 1000.0
            descent_reg = font_obj_reg.face.descent * font_size_reg / 1000.0
            
            # Два нижні рядки
            y_line1 = (y + 5.6 * mm) + (4.9 * mm - (ascent_reg - descent_reg)) / 2.0 - descent_reg + 0.2 * mm
            y_line2 = (y + 0.8 * mm) + (4.8 * mm - (ascent_reg - descent_reg)) / 2.0 - descent_reg + 0.2 * mm
            
            self.c.drawString(x + 3.5 * mm, y_line1, "Справа № ____________________")
            self.c.drawString(x + 3.5 * mm, y_line2, "«___» __________ 20___ р.  Підпис ________")
        finally:
            self.c.restoreState()

    def _draw_annulled_stamp(self) -> None:
        """Малює червоний штамп «АНУЛЬОВАНО» у верхній частині першої сторінки (подвійна рамка, розрядка)."""
        self.c.saveState()
        try:
            self.c.setStrokeColorRGB(0.62, 0.08, 0.10)
            self.c.setFillColorRGB(0.62, 0.08, 0.10)
            
            w = 38 * mm
            h = 9 * mm
            x = (self.page_w - w) / 2
            y = self.page_h - self.top - 12 * mm
            
            # Подвійна рамка
            self._draw_double_round_rect(x, y, w, h, 1.2 * mm, 0.7 * mm)
            
            font_name = _FONT_BOLD
            font_size = 9.0
            self.c.setFont(font_name, font_size)
            
            from reportlab.pdfbase import pdfmetrics
            font_obj = pdfmetrics.getFont(font_name)
            ascent = font_obj.face.ascent * font_size / 1000.0
            descent = font_obj.face.descent * font_size / 1000.0
            y_baseline = y + (h - (ascent - descent)) / 2.0 - descent + 0.3 * mm
            
            self.c.drawCentredString(x + w / 2, y_baseline, "А Н У Л Ь О В А Н О")
        finally:
            self.c.restoreState()

    def _draw_urgent_stamp(self) -> None:
        """Малює червоний штамп «ТЕРМІНОВО» у правому верхньому куті (подвійна рамка, розрядка)."""
        self.c.saveState()
        try:
            self.c.setStrokeColorRGB(0.62, 0.08, 0.10)
            self.c.setFillColorRGB(0.62, 0.08, 0.10)
            
            w = 30 * mm
            h = 8 * mm
            x = self.page_w - self.right_margin - w
            y = self.page_h - 10 * mm
            
            # Подвійна рамка
            self._draw_double_round_rect(x, y, w, h, 1.0 * mm, 0.7 * mm)
            
            font_name = _FONT_BOLD
            font_size = 8.0
            self.c.setFont(font_name, font_size)
            
            from reportlab.pdfbase import pdfmetrics
            font_obj = pdfmetrics.getFont(font_name)
            ascent = font_obj.face.ascent * font_size / 1000.0
            descent = font_obj.face.descent * font_size / 1000.0
            y_baseline = y + (h - (ascent - descent)) / 2.0 - descent + 0.3 * mm
            
            self.c.drawCentredString(x + w / 2, y_baseline, "Т Е Р М І Н О В О")
        finally:
            self.c.restoreState()

    def _classify_extra_stamp(self, text: str) -> tuple[str, tuple[float, float, float]]:
        """Визначає розташування та колір для додаткового штампа."""
        t = text.upper().strip()
        
        # Червоні бордові штампи для контролю, анулювання, небезпеки або відхилення
        red_texts = {
            "ДО ВИКОНАННЯ", "НА КОНТРОЛІ", "ВИКОНАТИ ДО", "ТЕРМІН ПРОДОВЖЕНО", 
            "ПОВЕРНУТО БЕЗ РОЗГЛЯДУ", "НЕДІЙСНО", "ЗНИЩЕНО", "НЕ ОПЛАЧЕНО", "ПОВТОРНО",
            "УВАГА", "ВАЖЛИВО", "ТЕРМІН ЗБЕРІГАННЯ"
        }
        color = (0.62, 0.08, 0.10) if any(x in t for x in red_texts) else (0.03, 0.14, 0.42)
        
        # Визначаємо локацію
        if any(x in t for x in ["НЕДІЙСНО", "ЗНИЩЕНО", "АНУЛЬОВАНО"]):
            loc = "top_center"
        elif any(x in t for x in ["КОНТРОЛ", "ВИКОНАТИ", "ПРОДОВЖЕНО", "ДО ВИКОНАННЯ"]):
            loc = "left_margin"
        else:
            loc = "top_right"
            
        return loc, color

    def _draw_generic_stamp(self, text: str, y: float, loc: str, color: tuple[float, float, float]) -> None:
        """Малює будь-який службовий прямокутний штамп у преміум-стилі."""
        self.c.saveState()
        try:
            self.c.setStrokeColorRGB(*color)
            self.c.setFillColorRGB(*color)
            
            # Підготуємо текст (розрядка літер, якщо текст короткий)
            text_upper = text.upper().strip()
            if len(text_upper) <= 12 and " " not in text_upper:
                display_text = " ".join(list(text_upper))
            else:
                display_text = text_upper
                
            font_name = _FONT_BOLD
            font_size = 7.5
            self.c.setFont(font_name, font_size)
            
            from reportlab.pdfbase import pdfmetrics
            text_w = pdfmetrics.stringWidth(display_text, font_name, font_size)
            w = max(28 * mm, text_w + 6 * mm)
            h = 8 * mm
            
            if loc == "top_right":
                x = self.page_w - self.right_margin - w
            elif loc == "top_center":
                x = (self.page_w - w) / 2
            else:  # left_margin
                x = 4 * mm
                w = max(w, 26 * mm)  # зберігаємо розраховану ширину тексту
                
            self._draw_double_round_rect(x, y, w, h, 1.0 * mm, 0.7 * mm)
            
            font_obj = pdfmetrics.getFont(font_name)
            ascent = font_obj.face.ascent * font_size / 1000.0
            descent = font_obj.face.descent * font_size / 1000.0
            y_baseline = y + (h - (ascent - descent)) / 2.0 - descent + 0.3 * mm
            
            self.c.drawCentredString(x + w / 2, y_baseline, display_text)
        finally:
            self.c.restoreState()



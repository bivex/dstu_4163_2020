"""Пошук TTF-шрифту Times New Roman (для PDF-рендерингу з кирилицею).

Reportlab не має вбудованого Times New Roman із кирилицею, тож реєструємо
системний TTF. Шлях можна задати через env (без хардкоду під одну машину);
інакше шукаємо типові розташування macOS/Linux. Якщо не знайдено — кидаємо
зрозумілу помилку з підказкою.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FontPaths:
    regular: str
    bold: str


class FontNotFoundError(RuntimeError):
    """Шрифт Times New Roman не знайдено — потрібна явна вказівка шляху."""


# Кандидати: (regular, bold). Env-перевизначення має пріоритет.
_CANDIDATES: tuple[tuple[str, str], ...] = (
    (
        "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
        "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    ),
    (
        "/Library/Fonts/Times New Roman.ttf",
        "/Library/Fonts/Times New Roman Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Times_New_Roman_Bold.ttf",
    ),
    # Liberation Serif — метрично сумісна заміна Times New Roman у Linux
    (
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    ),
)


def resolve_times_new_roman(env: dict[str, str] | None = None) -> FontPaths:
    """Повернути шляхи до regular/bold TTF.

    Env:
      DILOVOD4_FONT_REGULAR / DILOVOD4_FONT_BOLD — явні шляхи (bold необовʼязковий).
    """
    e = env if env is not None else os.environ

    reg = e.get("DILOVOD4_FONT_REGULAR")
    if reg:
        if not Path(reg).is_file():
            raise FontNotFoundError(f"DILOVOD4_FONT_REGULAR вказує на неіснуючий файл: {reg}")
        bold = e.get("DILOVOD4_FONT_BOLD") or reg
        return FontPaths(regular=reg, bold=bold if Path(bold).is_file() else reg)

    for regular, bold in _CANDIDATES:
        if Path(regular).is_file():
            bold_path = bold if Path(bold).is_file() else regular
            return FontPaths(regular=regular, bold=bold_path)

    raise FontNotFoundError(
        "Не знайдено TTF Times New Roman. Вкажіть шлях через DILOVOD4_FONT_REGULAR "
        "(і за потреби DILOVOD4_FONT_BOLD)."
    )

"""Оцифрування паперових документів: нормалізація завантаженого скану в PDF.

Робочий процес (відповідає Закону № 851-IV про електронні документи):
- користувач завантажує скан паперового документа — PDF або фото (JPEG/PNG/TIFF);
- скан стає ЕЛЕКТРОННИМ оригіналом (rendered) — документ не генерується з полів;
- далі він підписується КЕП через звичайний пайплайн (submit → manifest →
  sign → ASiC-E), тож електронна копія набуває юридичної сили (ст.7 ↔ ст.12).

Зображення конвертуються в PDF через Pillow (вже в залежностях reportlab→PIL).
Багатосторінкові TIFF розгортаються у багатосторінковий PDF. PDF приймається
як є (лише перевірка, що це справді PDF за сигнатурою %PDF).
"""

from __future__ import annotations

import io

# Підтримувані вхідні типи сканів
_IMAGE_CONTENT_TYPES = {
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "image/tiff": "TIFF",
    "image/tif": "TIFF",
    "image/bmp": "BMP",
    "image/webp": "WEBP",
}
_PDF_CONTENT_TYPES = {"application/pdf"}

# Ліміт розміру скану (захист від надвеликих завантажень) — 50 МБ
MAX_SCAN_BYTES = 50 * 1024 * 1024


class ScanError(ValueError):
    """Помилка обробки завантаженого скану (непідтримуваний тип/пошкоджений файл)."""


def is_supported(content_type: str, filename: str = "") -> bool:
    """Чи підтримується тип файлу для оцифрування."""
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct in _PDF_CONTENT_TYPES or ct in _IMAGE_CONTENT_TYPES:
        return True
    # запасний варіант — за розширенням, якщо content-type відсутній/octet-stream
    name = (filename or "").lower()
    return name.endswith((".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"))


def normalize_to_pdf(data: bytes, content_type: str, filename: str = "") -> bytes:
    """Перетворити завантажений скан у PDF-байти (електронний оригінал).

    - PDF → повертається як є (після перевірки сигнатури);
    - зображення → конвертується в PDF (багатосторінковий TIFF → багато сторінок).

    Кидає ScanError для непідтримуваних/пошкоджених файлів.
    """
    if not data:
        raise ScanError("порожній файл скану")
    if len(data) > MAX_SCAN_BYTES:
        raise ScanError(f"скан завеликий (> {MAX_SCAN_BYTES // (1024 * 1024)} МБ)")

    ct = (content_type or "").lower().split(";")[0].strip()
    name = (filename or "").lower()
    is_pdf = ct in _PDF_CONTENT_TYPES or name.endswith(".pdf")

    if is_pdf:
        if data[:5] != b"%PDF-":
            raise ScanError("файл не є коректним PDF (відсутня сигнатура %PDF)")
        return data

    # зображення → PDF через Pillow
    try:
        from PIL import Image, ImageSequence
    except ImportError as exc:  # pragma: no cover
        raise ScanError("Pillow недоступний для конвертації зображення") from exc

    try:
        img = Image.open(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ScanError(f"не вдалося прочитати зображення: {exc}") from exc

    # зібрати всі кадри (для багатосторінкових TIFF), привести до RGB
    frames = []
    for frame in ImageSequence.Iterator(img):
        rgb = frame.convert("RGB")
        frames.append(rgb)
    if not frames:
        raise ScanError("зображення не містить сторінок")

    out = io.BytesIO()
    first, rest = frames[0], frames[1:]
    first.save(out, format="PDF", save_all=bool(rest), append_images=rest, resolution=200.0)
    return out.getvalue()

"""Формування корисного навантаження QR-коду за §5.10 ДСТУ 4163:2020.

Крос-лінк (заголовок dstu-файлу): QR (§5.10) несе дані про КЕП/печатку +
кваліфіковані позначки часу. Тобто QR кодує дані сертифіката з
ElectronicSignatureMark. Це чиста доменна логіка (без IO, без рендерингу).

Формат — компактний рядок «ключ=значення», розділений ';' — детермінований і
легко парситься будь-яким верифікатором. Сам растровий QR малює адаптер.
"""

from __future__ import annotations

from .signature import ElectronicSignatureMark

# Версія схеми навантаження — для зворотної сумісності верифікаторів.
QR_PAYLOAD_VERSION = "1"


def build_signature_qr_payload(mark: ElectronicSignatureMark) -> str:
    """Зібрати рядок навантаження QR з даних електронного підпису.

    Поля (§5.10: дані про КЕП/печатку + позначка часу):
      v   — версія схеми
      typ — тип підпису (QES — кваліфікований, AES — удосконалений)
      sn  — серійний номер сертифіката
      sub — підписувач (ПІБ або псевдонім, Art.4-1)
      iss — видавець (надавач/АЦСК)
      vf  — чинний від
      vt  — чинний до
      ts  — кваліфікована позначка часу
      st  — статус сертифіката за Art.24 (VALID/INVALID)
    """
    typ = "QES" if mark.is_qualified else "AES"
    status = "VALID" if mark.certificate_valid else "INVALID"
    fields = [
        ("v", QR_PAYLOAD_VERSION),
        ("typ", typ),
        ("sn", mark.certificate_serial),
        ("sub", mark.signer),
        ("iss", mark.issuer),
        ("vf", mark.valid_from),
        ("vt", mark.valid_to),
        ("ts", mark.timestamp),
        ("st", status),
    ]
    # екрануємо роздільники у значеннях, щоб не зламати парсинг
    parts = [f"{k}={_escape(v)}" for k, v in fields]
    return ";".join(parts)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace("=", "\\=")

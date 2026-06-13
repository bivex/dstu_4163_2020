"""Тести формування навантаження QR-коду (§5.10) — чиста доменна логіка.

Формат версії 2 — позиційний ASCII:
    DSTU4163;<v>;<typ>;<sn>;<vf>;<vt>;<ts>;<st>
Підписувач/видавець НЕ кодуються (вони у видимій відмітці) — це тримає QR
компактним, щоб модуль за фіксованих 21 мм лишався читабельним телефоном.
"""

from __future__ import annotations

from dilovod4.domain.model import CertificateStatus, ElectronicSignatureMark
from dilovod4.domain.model.qr_payload import (
    QR_PAYLOAD_PREFIX,
    QR_PAYLOAD_VERSION,
    build_signature_qr_payload,
)


def _mark(**overrides) -> ElectronicSignatureMark:
    kw = dict(
        signer="ПЕТРЕНКО Олександр Іванович",
        certificate_serial="58E2D9C1F0A4B7E3",
        issuer="КН ЕДП «Дія»",
        valid_from="01.01.2026",
        valid_to="01.01.2028",
        timestamp="13.06.2026 16:42:05 EET",
    )
    kw.update(overrides)
    return ElectronicSignatureMark(**kw)


def test_payload_positional_fields():
    parts = build_signature_qr_payload(_mark()).split(";")
    assert parts[0] == QR_PAYLOAD_PREFIX
    assert parts[1] == QR_PAYLOAD_VERSION
    assert parts[2] == "QES"
    assert parts[3] == "58E2D9C1F0A4B7E3"
    assert parts[4] == "01.01.2026"
    assert parts[5] == "01.01.2028"
    assert parts[6] == "13.06.2026 16:42:05 EET"
    assert parts[7] == "V"


def test_payload_marks_invalid_certificate():
    parts = build_signature_qr_payload(_mark(status=CertificateStatus.CANCELLED)).split(";")
    assert parts[7] == "X"


def test_payload_advanced_signature_type():
    parts = build_signature_qr_payload(_mark(is_qualified=False)).split(";")
    assert parts[2] == "AES"


def test_payload_is_ascii():
    # кирилиця роздула б QR; навантаження має лишатися ASCII
    payload = build_signature_qr_payload(_mark())
    assert payload.isascii()


def test_payload_excludes_cyrillic_identity():
    # підписувач/видавець (кирилиця) навмисно НЕ в QR — лише у видимій відмітці
    payload = build_signature_qr_payload(_mark())
    assert "ПЕТРЕНКО" not in payload
    assert "Дія" not in payload


def test_payload_stays_compact_for_scannable_module():
    # за 21 мм версія QR має лишатися малою (≤ v6) для модуля > 0.5 мм
    import segno

    payload = build_signature_qr_payload(_mark())
    qr = segno.make(payload, error="m")
    assert qr.version <= 6


def test_payload_sanitizes_separator_in_value():
    # роздільник у значенні замінюється, щоб не зламати позиційний парсинг
    parts = build_signature_qr_payload(_mark(certificate_serial="AB;CD")).split(";")
    assert len(parts) == 8
    assert parts[3] == "AB CD"

"""Тести ElectronicSignatureMark для eSeal (електронна печатка) + QR-пейлоад.

Перевіряє, що нові поля kind/organization/identifier коректно впливають на
``signature_kind`` та ``build_signature_qr_payload``, і що існуючі КЕП-відмітки
(без нових полів) зберігають зворотну сумісність.
"""

from __future__ import annotations

import pytest

from dilovod4.domain.model import ElectronicSignatureMark
from dilovod4.domain.model.qr_payload import (
    QR_PAYLOAD_PREFIX,
    QR_PAYLOAD_VERSION,
    build_signature_qr_payload,
)


def _mark(**kw) -> ElectronicSignatureMark:
    base = dict(
        signer="Тестовий Підписувач",
        certificate_serial="ABC123",
        issuer="КНЕДП Тест",
        valid_from="01.01.2026",
        valid_to="01.01.2028",
        timestamp="2026-06-27T12:00:00Z",
    )
    base.update(kw)
    return ElectronicSignatureMark(**base)


# --- signature_kind ---------------------------------------------------------

def test_esign_mark_signature_kind_default():
    m = _mark()
    assert m.kind == "esign"
    assert m.signature_kind == "Кваліфікований електронний підпис"


def test_esign_mark_signature_kind_advanced():
    m = _mark(is_qualified=False)
    assert m.signature_kind == "Удосконалений електронний підпис"


def test_eseal_mark_signature_kind_qualified():
    m = _mark(kind="eseal", organization="ТОВ Рога і Копита", identifier="NTRUA-43213421")
    assert m.signature_kind == "Кваліфікована електронна печатка"


def test_eseal_mark_signature_kind_advanced():
    m = _mark(kind="eseal", is_qualified=False)
    assert m.signature_kind == "Удосконалена електронна печатка"


# --- нові поля --------------------------------------------------------------

def test_eseal_mark_carries_organization_and_identifier():
    m = _mark(kind="eseal", organization="ТОВ Тест", identifier="NTRUA-11111111")
    assert m.organization == "ТОВ Тест"
    assert m.identifier == "NTRUA-11111111"


def test_esign_mark_defaults_organization_empty():
    m = _mark()
    assert m.organization == ""
    assert m.identifier == ""


# --- зворотна сумісність (без нових полів) ---------------------------------

def test_legacy_mark_without_kind_is_esign():
    """Конструктор лише з обовʼязковими полями → esign (зворотна сумісність)."""
    m = ElectronicSignatureMark(
        signer="Легат",
        certificate_serial="S1",
        issuer="I",
        valid_from="01.01.2026",
        valid_to="01.01.2028",
        timestamp="t",
    )
    assert m.kind == "esign"
    assert m.organization == ""
    assert "підпис" in m.signature_kind.lower()


# --- QR payload -------------------------------------------------------------

def test_qr_payload_esign_uses_QES():
    m = _mark()
    payload = build_signature_qr_payload(m)
    parts = payload.split(";")
    assert parts[0] == QR_PAYLOAD_PREFIX
    assert parts[1] == QR_PAYLOAD_VERSION
    assert parts[2] == "QES"


def test_qr_payload_eseal_uses_QESL():
    m = _mark(kind="eseal")
    payload = build_signature_qr_payload(m)
    assert payload.split(";")[2] == "QESL"


def test_qr_payload_advanced_eseal_uses_AESL():
    m = _mark(kind="eseal", is_qualified=False)
    payload = build_signature_qr_payload(m)
    assert payload.split(";")[2] == "AESL"


def test_qr_payload_includes_cert_serial_regardless_of_kind():
    m = _mark(kind="eseal", certificate_serial="DEADBEEF")
    payload = build_signature_qr_payload(m)
    assert "DEADBEEF" in payload


def test_qr_payload_status_reflects_validity():
    m_valid = _mark(kind="eseal")
    m_invalid = _mark(kind="eseal", validity_period_expired=True)
    assert build_signature_qr_payload(m_valid).split(";")[7] == "V"
    assert build_signature_qr_payload(m_invalid).split(";")[7] == "X"


# --- інваріанти -------------------------------------------------------------

def test_seal_mark_requires_signer():
    """signer обовʼязковий і для печатки (назва юрособи)."""
    with pytest.raises(Exception):
        _mark(kind="eseal", signer="")

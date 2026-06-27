"""Тести парсера сертифікатів cert_info_from_cms (eSeal/eSign розрізнення).

Використовує тестовий генератор сертифікатів (ECDSA CMS), щоб перевірити, що
``cert_info_from_cms`` коректно витягує cert_type, organization, identifier з
QC statements. Не потребує нативної UAPKI чи мережі.
"""

from __future__ import annotations

import sys
from pathlib import Path

# domain_bridge живе в portal/, тестуємо як окремий модуль — додаємо portal у path
_PORTAL = Path(__file__).resolve().parent.parent / "portal"
if str(_PORTAL) not in sys.path:
    sys.path.insert(0, str(_PORTAL))

from dilovod4.infrastructure.test_cert_factory import (  # noqa: E402
    generate_test_ca,
    issue_esign_cert,
    issue_eseal_cert,
    sign_data_with_leaf,
)
from portal import domain_bridge as bridge  # noqa: E402


def _esign_cms() -> bytes:
    ca = generate_test_ca()
    leaf = issue_esign_cert(ca, "Петренко Петро Петрович", "1234512345")
    return sign_data_with_leaf(leaf, b"signed by person\n")


def _eseal_cms() -> bytes:
    ca = generate_test_ca()
    leaf = issue_eseal_cert(ca, "ТОВ Рога і Копита", "43213421")
    return sign_data_with_leaf(leaf, b"sealed by org\n")


# --- eSign ------------------------------------------------------------------

def test_parses_esign_cert_type():
    info = bridge.cert_info_from_cms(_esign_cms())
    assert info.get("cert_type") == "esign"


def test_parses_esign_signer_cn_and_rnopp():
    info = bridge.cert_info_from_cms(_esign_cms())
    assert info.get("signer") == "Петренко Петро Петрович"
    assert info.get("serialNumber") == "1234512345"  # РНОКПП
    assert info.get("identifier") == "1234512345"


def test_parses_esign_no_organization():
    info = bridge.cert_info_from_cms(_esign_cms())
    # КЕП особи не несе O
    assert info.get("organization") == ""


# --- eSeal ------------------------------------------------------------------

def test_parses_eseal_cert_type():
    info = bridge.cert_info_from_cms(_eseal_cms())
    assert info.get("cert_type") == "eseal"


def test_parses_eseal_organization_and_edrpou():
    info = bridge.cert_info_from_cms(_eseal_cms())
    assert info.get("organization") == "ТОВ Рога і Копита"
    # identifier для печатки — organizationIdentifier (NTRUA-ЄДРПОУ)
    assert info.get("organizationIdentifier") == "NTRUA-43213421"
    assert info.get("identifier") == "NTRUA-43213421"


def test_parses_eseal_signer_is_org_name():
    """Для печатки signer (CN) = назва юрособи (не ПІБ особи)."""
    info = bridge.cert_info_from_cms(_eseal_cms())
    assert info.get("signer") == "ТОВ Рога і Копита"


# --- спільні поля -----------------------------------------------------------

def test_parses_certificate_serial_and_validity():
    info = bridge.cert_info_from_cms(_esign_cms())
    assert info.get("certificate_serial")  # непорожній hex
    assert info.get("valid_from")  # DD.MM.YYYY
    assert info.get("valid_to")
    assert "." in info["valid_from"]  # формат DD.MM.YYYY


def test_parses_issuer_from_ca():
    info = bridge.cert_info_from_cms(_esign_cms())
    assert "Тестовий КНЕДП" in info.get("issuer", "")


def test_parses_subject_dn_for_audit():
    info = bridge.cert_info_from_cms(_eseal_cms())
    dn = info.get("subject_dn", "")
    assert "CN=ТОВ Рога і Копита" in dn
    assert "2.5.4.97=NTRUA-43213421" in dn


def test_returns_empty_on_garbage():
    """best-effort: невалідний вхід → {} (підпис лишиться без даних)."""
    info = bridge.cert_info_from_cms(b"not a real signature")
    assert info == {}


def test_returns_empty_on_detached_no_cert():
    """CMS без сертифіката → openssl print_certs порожній → {}."""
    info = bridge.cert_info_from_cms(b"\x30\x02\x00\x00")  # невалідний DER
    assert info == {}

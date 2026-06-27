"""Тести генератора тестових сертифікатів (X.509 eSign/eSeal).

Не потребують нативної UAPKI чи мережі — лише ``cryptography``. Перевіряють,
що фабрика будує криптографічно валідні сертифікати з правильними українськими
QC-розширеннями, які парсяться ``cryptography``/openssl.
"""

from __future__ import annotations

import datetime as _dt
import subprocess
import warnings

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.serialization import pkcs12, pkcs7
from cryptography.x509.oid import NameOID

from dilovod4.infrastructure import test_cert_factory as f
from dilovod4.infrastructure.test_cert_factory import (
    OID_QC_STATEMENTS_EXT,
    OID_QC_TYPE_ESEAL,
    OID_QC_TYPE_ESIGN,
    generate_test_ca,
    issue_esign_cert,
    issue_eseal_cert,
    sign_data_with_leaf,
    to_pkcs12,
    to_pkcs12_chain,
    write_bundle,
)

# cryptography не парсить QC statements у типізований вигляд — беремо сирі байти
# extension.value (UnrecognizedExtension) і шукаємо OID послідовністю байт.
_QC_ESIGN_BYTES = f._enc_oid(OID_QC_TYPE_ESIGN)
_QC_ESEAL_BYTES = f._enc_oid(OID_QC_TYPE_ESEAL)


# --- CA ---------------------------------------------------------------------

def test_test_ca_is_self_signed_with_ca_constraints():
    ca = generate_test_ca()
    assert ca.cert.issuer == ca.cert.subject  # self-signed
    bc = ca.cert.extensions.get_extension_for_class(x509.BasicConstraints)
    assert bc.value.ca is True
    ku = ca.cert.extensions.get_extension_for_class(x509.KeyUsage)
    assert ku.value.key_cert_sign is True
    assert ku.value.crl_sign is True


def test_test_ca_has_organization_identifier():
    ca = generate_test_ca()
    org_ids = ca.cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_IDENTIFIER)
    assert org_ids, "CA має мати organizationIdentifier (2.5.4.97)"
    assert org_ids[0].value.startswith("NTRUA-")


# --- eSign leaf -------------------------------------------------------------

def test_esign_cert_has_rnopp_and_esign_qc():
    ca = generate_test_ca()
    leaf = issue_esign_cert(ca, "Петренко Петро Петрович", "1234512345")
    assert leaf.cert_type == "esign"

    cn = leaf.cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    assert cn[0].value == "Петренко Петро Петрович"
    sn = leaf.cert.subject.get_attributes_for_oid(NameOID.SERIAL_NUMBER)
    assert sn[0].value == "1234512345"  # РНОКПП

    ku = leaf.cert.extensions.get_extension_for_class(x509.KeyUsage)
    assert ku.value.content_commitment is True  # nonRepudiation

    qc = _qc_extension_bytes(leaf.cert)
    assert _QC_ESIGN_BYTES in qc, "eSign-сертифікат має нести QC type eSign"
    assert _QC_ESEAL_BYTES not in qc


def test_esign_cert_issued_by_ca():
    ca = generate_test_ca()
    leaf = issue_esign_cert(ca, "Іваненко Іван", "3000000000")
    assert leaf.cert.issuer == ca.cert.subject


def test_esign_cert_validity_window():
    ca = generate_test_ca()
    leaf = issue_esign_cert(ca, "Тестовий", "1111111111", valid_days=2)
    now = _dt.datetime.now(_dt.timezone.utc)
    nb = leaf.cert.not_valid_before_utc
    na = leaf.cert.not_valid_after_utc
    assert nb <= now <= na
    assert (na - nb).days == 2


# --- eSeal leaf -------------------------------------------------------------

def test_eseal_cert_has_organization_and_eseal_qc():
    ca = generate_test_ca()
    leaf = issue_eseal_cert(ca, "ТОВ Рога і Копита", "43213421")
    assert leaf.cert_type == "eseal"

    orgs = leaf.cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
    assert orgs and orgs[0].value == "ТОВ Рога і Копита"
    cn = leaf.cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    assert cn[0].value == "ТОВ Рога і Копита"
    org_ids = leaf.cert.subject.get_attributes_for_oid(NameOID.ORGANIZATION_IDENTIFIER)
    assert org_ids and org_ids[0].value == "NTRUA-43213421"

    ku = leaf.cert.extensions.get_extension_for_class(x509.KeyUsage)
    assert ku.value.content_commitment is True  # nonRepudiation

    qc = _qc_extension_bytes(leaf.cert)
    assert _QC_ESEAL_BYTES in qc, "eSeal-сертифікат має нести QC type eSeal"
    assert _QC_ESIGN_BYTES not in qc


def test_eseal_cert_basic_constraints_not_ca():
    ca = generate_test_ca()
    leaf = issue_eseal_cert(ca, "ФОП Тест", "11111111")
    bc = leaf.cert.extensions.get_extension_for_class(x509.BasicConstraints)
    assert bc.value.ca is False


# --- PKCS12 / CMS -----------------------------------------------------------

def test_pkcs12_roundtrip_loads_with_password():
    ca = generate_test_ca()
    leaf = issue_esign_cert(ca, "Тест Тестовий", "1234512345")
    blob = to_pkcs12_chain(leaf, ca, "s3cret", "test-label")
    key, cert, cas = pkcs12.load_key_and_certificates(blob, b"s3cret")
    assert cert == leaf.cert
    assert ca.cert in cas


def test_pkcs12_single_cert_no_chain():
    ca = generate_test_ca()
    blob = to_pkcs12(ca.cert, ca.key, "pw", "ca-only")
    key, cert, cas = pkcs12.load_key_and_certificates(blob, b"pw")
    assert cert == ca.cert
    assert cas == []


def test_sign_data_with_leaf_yields_cms_with_cert():
    ca = generate_test_ca()
    leaf = issue_esign_cert(ca, "Підписувач", "1234512345")
    data = b"document content to sign\n"
    sig = sign_data_with_leaf(leaf, data)
    # cryptography розбирає PKCS7
    sigs = pkcs7.load_der_pkcs7_certificates(sig)
    assert sigs, "CMS має містити сертифікат підписувача"
    assert sigs[0] == leaf.cert


def test_sign_data_with_leaf_openssl_parseable():
    """openssl має розібрати згенерований CMS (сумісність з EUSign/UAPKI verify)."""
    ca = generate_test_ca()
    leaf = issue_esign_cert(ca, "Тест Підписувач", "1234512345")
    sig = sign_data_with_leaf(leaf, b"hello\n")
    r = subprocess.run(
        ["openssl", "pkcs7", "-inform", "DER", "-print_certs", "-noout"],
        input=sig, capture_output=True,
    )
    assert r.returncode == 0


# --- bundle -----------------------------------------------------------------

def test_write_bundle_creates_all_files(tmp_path):
    paths = write_bundle(
        str(tmp_path),
        person_cn="Особа Тест",
        org_name="ТОВ Юрособа",
    )
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [
        "ca.cer", "ca.p12",
        "org_eseal.cer", "org_eseal.p12",
        "person_esign.cer", "person_esign.p12",
    ]
    assert set(paths) == {"ca", "esign", "eseal"}


def test_write_bundle_p12_files_open(tmp_path):
    write_bundle(str(tmp_path))
    for name in ("ca.p12", "person_esign.p12", "org_eseal.p12"):
        blob = (tmp_path / name).read_bytes()
        key, cert, cas = pkcs12.load_key_and_certificates(blob, b"testpassword")
        assert cert is not None


def test_bundle_esign_and_eseal_certs_distinguishable(tmp_path):
    write_bundle(str(tmp_path))
    esign_cert = x509.load_pem_x509_certificate(
        (tmp_path / "person_esign.cer").read_bytes()
    )
    eseal_cert = x509.load_pem_x509_certificate(
        (tmp_path / "org_eseal.cer").read_bytes()
    )
    assert _QC_ESIGN_BYTES in _qc_extension_bytes(esign_cert)
    assert _QC_ESEAL_BYTES not in _qc_extension_bytes(esign_cert)
    assert _QC_ESEAL_BYTES in _qc_extension_bytes(eseal_cert)
    assert _QC_ESIGN_BYTES not in _qc_extension_bytes(eseal_cert)


# --- negative ---------------------------------------------------------------

def test_invalid_cert_type_rejected():
    ca = generate_test_ca()
    with pytest.raises(ValueError):
        f._issue_leaf(
            ca, common_name="x", kind="bogus", organization="",
            identifier="1", valid_days=1, dstu=False,
        )


# --- helpers ----------------------------------------------------------------

def _qc_extension_bytes(cert: x509.Certificate) -> bytes:
    """Сирі байти qcStatements extension (UnrecognizedExtension.value)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ext = cert.extensions.get_extension_for_oid(OID_QC_STATEMENTS_EXT)
    return ext.value.value  # type: ignore[union-attr]

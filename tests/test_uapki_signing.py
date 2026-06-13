"""Тести Python-порту UAPKI (реальне підписання через нативну libuapki).

Тести самопропускаються, якщо бібліотека не зібрана (UapkiLibraryNotFound) —
щоб suite лишався зеленим без нативної залежності. Збірка:
    cd external/UAPKI/library && bash build-uapki.sh macos-arm64
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from dilovod4.domain.model import CertificateStatus
from dilovod4.infrastructure.uapki import (
    UapkiClient,
    UapkiError,
    UapkiLibraryNotFound,
    check_cert_status_online,
    sign_file_pkcs12,
    verify_signature,
)

_UAPKI_ROOT = (
    Path(__file__).resolve().parents[1]
    / "external" / "UAPKI" / "library"
)
_DATA = _UAPKI_ROOT / "test" / "data"
_P12 = _DATA / "test-diia.p12"


def _client_or_skip() -> UapkiClient:
    try:
        return UapkiClient()
    except UapkiLibraryNotFound:
        pytest.skip("libuapki не зібрана (build-uapki.sh)")


def _require_testdata() -> None:
    if not _P12.is_file():
        pytest.skip("тестовий PKCS#12 контейнер недоступний")


def test_version():
    client = _client_or_skip()
    v = client.version()
    assert v.get("name") == "UAPKI"
    assert "version" in v


def test_list_keys_and_select():
    client = _client_or_skip()
    _require_testdata()
    client.init(str(_DATA / "certs"), str(_DATA / "crls"))
    client.open_pkcs12(str(_P12), "testpassword")
    keys = client.list_keys()
    assert keys, "контейнер має містити ключі"
    assert "id" in keys[0]
    sel = client.select_key(keys[0]["id"])
    assert "certId" in sel
    client.close()


def test_sign_raw_and_cms():
    client = _client_or_skip()
    _require_testdata()
    client.init(str(_DATA / "certs"), str(_DATA / "crls"))
    client.open_pkcs12(str(_P12), "testpassword")
    client.select_key(client.list_keys()[0]["id"])

    raw = client.sign_bytes(b"test data", signature_format="RAW")
    assert len(base64.b64decode(raw["bytes"])) > 0

    cms = client.sign_bytes(b"test data", signature_format="CMS")
    container = base64.b64decode(cms["bytes"])
    assert len(container) > len(base64.b64decode(raw["bytes"]))  # CMS обгортає підпис
    client.close()


def test_sign_file_pkcs12_high_level():
    _client_or_skip()
    _require_testdata()
    result = sign_file_pkcs12(
        file_path=str(_DATA / "test-fox.txt"),
        pkcs12_path=str(_P12),
        password="testpassword",
        cert_cache_dir=str(_DATA / "certs"),
        crl_cache_dir=str(_DATA / "crls"),
        signature_format="CMS",
    )
    assert len(result.container) > 0
    assert result.key_id
    assert result.cert_serial


def test_sign_result_to_signature_mark():
    _client_or_skip()
    _require_testdata()
    result = sign_file_pkcs12(
        file_path=str(_DATA / "test-fox.txt"),
        pkcs12_path=str(_P12),
        password="testpassword",
        cert_cache_dir=str(_DATA / "certs"),
        crl_cache_dir=str(_DATA / "crls"),
        signature_format="CMS",
    )
    mark = result.to_signature_mark(
        signer="ТЕСТ Підписувач",
        issuer="КН ЕДП «Дія»",
        valid_from="01.01.2026",
        valid_to="01.01.2028",
        status=CertificateStatus.ACTIVE,
    )
    assert mark.certificate_serial == result.cert_serial
    assert mark.certificate_valid
    assert mark.is_qualified


def test_cert_info_extraction():
    """GET_CERT + CERT_INFO витягують реальні поля X.509 підписувача."""
    _client_or_skip()
    _require_testdata()
    result = sign_file_pkcs12(
        file_path=str(_DATA / "test-fox.txt"),
        pkcs12_path=str(_P12),
        password="testpassword",
        cert_cache_dir=str(_DATA / "certs"),
        crl_cache_dir=str(_DATA / "crls"),
        signature_format="CMS",
        parse_cert=True,
    )
    assert result.cert is not None, "сертифікат підписувача має розібратися"
    c = result.cert
    assert c.serial_number
    assert c.subject_cn  # напр. 'ДП ДІЯ (Тестування)'
    assert c.issuer_cn  # надавач (АЦСК)
    assert c.not_before and c.not_after


def test_signature_mark_auto_from_real_cert():
    """to_signature_mark_auto заповнює відмітку повністю з X.509, без хардкоду."""
    _client_or_skip()
    _require_testdata()
    result = sign_file_pkcs12(
        file_path=str(_DATA / "test-fox.txt"),
        pkcs12_path=str(_P12),
        password="testpassword",
        cert_cache_dir=str(_DATA / "certs"),
        crl_cache_dir=str(_DATA / "crls"),
        signature_format="CMS",
    )
    mark = result.to_signature_mark_auto()
    # поля взяті з реального сертифіката
    assert mark.signer == result.cert.subject_cn or mark.signer == result.cert.subject_o
    assert mark.certificate_serial == result.cert.serial_number
    assert mark.issuer
    # тестовий сертифікат Дія прострочений (дійсний до 2024) -> Art.24 НЕДІЙСНИЙ
    assert result.cert.is_expired
    assert not mark.certificate_valid
    assert mark.status == CertificateStatus.CANCELLED


def _sign_detached(data: bytes) -> bytes:
    """Підписати дані detached-CMS і повернути контейнер (для verify-тестів)."""
    client = _client_or_skip()
    _require_testdata()
    client.init(str(_DATA / "certs"), str(_DATA / "crls"))
    client.open_pkcs12(str(_P12), "testpassword")
    client.select_key(client.list_keys()[0]["id"])
    sig = client.sign_bytes(data, signature_format="CMS", detached=True)
    client.close()
    return base64.b64decode(sig["bytes"])


def test_verify_valid_signature():
    data = b"The quick brown fox jumps over the lazy dog\n"
    container = _sign_detached(data)
    res = verify_signature(
        container,
        cert_cache_dir=str(_DATA / "certs"),
        crl_cache_dir=str(_DATA / "crls"),
        content=data,
    )
    assert res.is_valid
    assert res.status == "TOTAL-VALID"
    assert res.valid_signatures
    assert res.valid_digests
    assert res.status_signature == "VALID"
    assert res.status_message_digest == "VALID"


def test_verify_detects_tampered_content():
    data = b"The quick brown fox jumps over the lazy dog\n"
    container = _sign_detached(data)
    res = verify_signature(
        container,
        cert_cache_dir=str(_DATA / "certs"),
        crl_cache_dir=str(_DATA / "crls"),
        content=b"tampered payload",
    )
    # криптопідпис коректний, але дайджест даних не збігається -> провал
    assert not res.is_valid
    assert res.status == "TOTAL-FAILED"
    assert res.status_message_digest == "INVALID"


_OCSP_URL = "http://ca.informjust.ua/services/ocsp/"


def test_online_ocsp_status():
    """Онлайн-перевірка статусу сертифіката за OCSP (повна Art.24).

    Потребує мережі; самопропускається, якщо відповідач недоступний.
    Тестовий сертифікат Дія відкликано (CESSATION_OF_OPERATION) -> REVOKED.
    """
    import glob

    _client_or_skip()
    _require_testdata()
    matches = glob.glob(str(_DATA / "certs" / "BED50831-5BC6C06E*.cer"))
    if not matches:
        pytest.skip("сертифікат підписувача недоступний у кеші")
    cert_der = Path(matches[0]).read_bytes()
    try:
        st = check_cert_status_online(
            cert_der,
            cert_cache_dir=str(_DATA / "certs"),
            crl_cache_dir=str(_DATA / "crls"),
            ocsp_url=_OCSP_URL,
        )
    except UapkiError as exc:
        pytest.skip(f"OCSP-відповідач недоступний: {exc}")

    assert st.response_status == "SUCCESSFUL"
    assert st.cert_status in ("GOOD", "REVOKED", "UNKNOWN")
    # цей тестовий сертифікат відкликано
    if st.is_revoked:
        assert st.revocation_time
        assert st.revocation_reason

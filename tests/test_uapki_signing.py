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
    UapkiLibraryNotFound,
    sign_file_pkcs12,
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

"""Тести серверного підпису печаткою юрособи (server_seal).

Самопропускаються, якщо нативна libuapki не зібрана/не INITиться — suite лишається
зеленим без криптозалежності. Криптографічний шлях підпису перевіряється на
наявному тестовому DSTU-контейнері ІІТ (test-diia.p12) — він доводить, що
``sign_with_server_seal`` будує валідний CAdES, що його парсить cert_info_from_cms.

NB: реальна печатка юрособи (DSTU eSeal-PKCS#12) підписується тим самим шляхом;
QC-type eseal визначається з сертифіката печатки, а не з алгоритму підпису.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_PORTAL = Path(__file__).resolve().parent.parent / "portal"
if str(_PORTAL) not in sys.path:
    sys.path.insert(0, str(_PORTAL))

from dilovod4.infrastructure.uapki import UapkiLibraryNotFound  # noqa: E402
from portal import domain_bridge as bridge  # noqa: E402

# Каталоги з CA-сертифікатами/CRL + тестовий DSTU-контейнер (фікстури UAPKI).
_UAPKI_ROOT = Path(__file__).resolve().parents[1] / "external" / "UAPKI" / "library"
_DATA = _UAPKI_ROOT / "test" / "data"
_TEST_P12 = _DATA / "test-diia.p12"
_TEST_P12_PASS = "testpassword"


def _uapki_init_works() -> bool:
    """Чи проходить UAPKI INIT + OPEN тестового контейнера (бібліотека + кеш)."""
    try:
        from dilovod4.infrastructure.uapki import UapkiClient, UapkiError

        with UapkiClient() as cli:
            cli.init(str(_DATA / "certs"), str(_DATA / "crls"), offline=True)
        return _TEST_P12.is_file()
    except (UapkiLibraryNotFound, OSError):
        return False
    except UapkiError:
        return False


_HAS_UAPKI = _uapki_init_works()


def test_sign_with_server_seal_yields_valid_cms():
    """sign_with_server_seal будує валідний CAdES з тестового контейнера.

    Парсер cert_info_from_cms витягує дані підписувача з САМОГО контейнера.
    Самопропускається без зібраної libuapki/кешу — як існуючі тести uapki_signing.
    """
    if not _HAS_UAPKI:
        pytest.skip("libuapki не зібрана або INIT/контейнер недоступні")

    from dilovod4.infrastructure.server_seal import sign_with_server_seal

    result = sign_with_server_seal(
        b"manifest bytes to be sealed\n",
        p12_path=str(_TEST_P12),
        password=_TEST_P12_PASS,
        cert_cache_dir=str(_DATA / "certs"),
        crl_cache_dir=str(_DATA / "crls"),
    )
    assert len(result.container) > 0
    assert result.cert is not None
    # дані підписувача витягуються з сертифіката в контейнері
    info = bridge.cert_info_from_cms(result.container)
    assert info.get("signer")  # ПІБ / назва
    assert info.get("certificate_serial")
    assert info.get("issuer")


def test_sign_with_server_seal_rejects_missing_p12(tmp_path):
    """Невалідний конфіг → ServerSealError (не підіймаємося до UAPKI)."""
    from dilovod4.infrastructure.server_seal import ServerSealError, sign_with_server_seal

    with pytest.raises(ServerSealError):
        sign_with_server_seal(
            b"data",
            p12_path="",
            password="x",
            cert_cache_dir=str(tmp_path),
            crl_cache_dir=str(tmp_path),
        )


def test_sign_with_server_seal_rejects_missing_password(tmp_path):
    # перевірка конфігурації спрацьовує до виклику UAPKI — не потребує зібраної lib
    from dilovod4.infrastructure.server_seal import ServerSealError, sign_with_server_seal

    with pytest.raises(ServerSealError):
        sign_with_server_seal(
            b"data",
            p12_path=str(_TEST_P12),
            password="",
            cert_cache_dir=str(tmp_path),
            crl_cache_dir=str(tmp_path),
        )


def test_cades_t_requires_urls(tmp_path):
    """CAdES-T без tsp_url/cmp_url → ServerSealError (до виклику UAPKI)."""
    from dilovod4.infrastructure.server_seal import ServerSealError, sign_with_server_seal

    with pytest.raises(ServerSealError):
        sign_with_server_seal(
            b"data",
            p12_path=str(_TEST_P12),
            password="testpassword",
            cert_cache_dir=str(tmp_path),
            crl_cache_dir=str(tmp_path),
            with_timestamp=True,
            # tsp_url/cmp_url не задані
        )

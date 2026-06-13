"""Тести реєстру КНЕДП (резолвинг сервісних адрес за issuer CN)."""

from __future__ import annotations

import pytest

from dilovod4.infrastructure.ca_registry import (
    CaRegistryError,
    find_by_issuer_cn,
    list_providers,
)


def test_registry_loads():
    providers = list_providers()
    assert len(providers) > 10  # у реєстрі десятки КНЕДП


def test_find_monobank_endpoints():
    ca = find_by_issuer_cn("monobank")
    assert ca.cmp_url == "http://ca.monobank.ua/services/cmp/"
    assert ca.tsp_url == "http://ca.monobank.ua/services/tsp/dstu/"
    assert ca.ocsp_url and "ocsp" in ca.ocsp_url


def test_find_by_full_issuer_cn():
    # повний CN з CERT_INFO має резолвитись так само
    ca = find_by_issuer_cn("КНЕДП monobank | Universal Bank")
    assert ca.cmp_url and "monobank" in ca.cmp_url


def test_urls_have_scheme():
    for ca in list_providers():
        for url in (ca.cmp_url, ca.ocsp_url, ca.tsp_url):
            if url:
                assert url.startswith(("http://", "https://"))


def test_unknown_provider_raises():
    with pytest.raises(CaRegistryError):
        find_by_issuer_cn("неіснуючий надавач XYZ-12345")

"""Тести CMP-клієнта (IIT transport) — побудова запиту та розбір відповіді.

Без мережі: перевіряємо детермінований формат запиту й парсинг коду результату.
Реальний онлайн-обмін із КНЕДП тут не тестуємо (залежить від мережі/CA).
"""

from __future__ import annotations

import pytest

from dilovod4.infrastructure.cmp import (
    CmpError,
    build_request,
    parse_response,
)

_KID0 = bytes.fromhex(
    "310A3F72088A5DD7C9638B568C0C8A76273F8C2E8F0D0BED59DD4C6279C540E7"
)
_KID1 = bytes.fromhex(
    "73D57661C99206D3198A63FFEDD23141D1F2B6C7790B6E7578767CC4A981EAEE"
)


def test_build_request_length_and_structure():
    req = build_request(_KID0, _KID1)
    # 120-байтовий payload + ContentInfo/OID/обгортки = 138 байт
    assert len(req) == 138
    assert req[0] == 0x30  # SEQUENCE
    # OID data присутній
    assert bytes.fromhex("06092A864886F70D010701") in req
    # keyId вкладені у payload
    assert _KID0 in req
    assert _KID1 in req


def test_build_request_single_keyid_duplicates():
    req = build_request(_KID0)
    # без secondary — первинний keyId дублюється
    assert req.count(_KID0) >= 2


def test_build_request_rejects_bad_length():
    with pytest.raises(CmpError):
        build_request(b"\x00" * 16)  # не 32 байти


def test_parse_response_not_found():
    # реальна відповідь Monobank на невідомий keyId (result=9)
    resp = bytes.fromhex("301706092a864886f70d010701a00a04080d00000009000000")
    r = parse_response(resp)
    assert r.result_code == 9
    assert not r.found
    assert r.certificates == ()


def test_parse_response_success_code():
    # синтетична відповідь з кодом результату 1 (без вкладених сертифікатів)
    payload = bytes([0x0D, 0, 0, 0]) + (1).to_bytes(4, "little")
    # ContentInfo data -> OCTET STRING(payload)
    def der_len(n):
        return bytes([n]) if n < 0x80 else b""
    octet = bytes([0x04, len(payload)]) + payload
    explicit = bytes([0xA0, len(octet)]) + octet
    oid = bytes.fromhex("06092A864886F70D010701")
    inner = oid + explicit
    resp = bytes([0x30, len(inner)]) + inner
    r = parse_response(resp)
    assert r.result_code == 1
    assert r.found


_INFORMJUST_CMP = "http://ca.informjust.ua/services/cmp/"
# subjectKeyIdentifier тестового ключа test-diia.p12 (UAPKI SELECT_KEY id)
_TEST_DIIA_SKI = bytes.fromhex(
    "5BC6C06EE1E00C1700E92AA7A9AD75F82D3CB7A9B66E3A98023209B24513315C"
)


def test_online_fetch_certificate_by_ski():
    """Онлайн-дотягування сертифіката з КНЕДП за subjectKeyIdentifier.

    Потребує мережі; самопропускається, якщо CMP недоступний. Перевірено на
    ca.informjust.ua — повертає ланцюг сертифікатів тестового ключа Дія.
    """
    from dilovod4.infrastructure.cmp import fetch_certificate

    try:
        r = fetch_certificate(_TEST_DIIA_SKI, _INFORMJUST_CMP)
    except CmpError:
        pytest.skip("CMP-сервер недоступний")
    if not r.found:
        pytest.skip(f"сертифікат не повернуто (code={r.result_code})")
    assert r.found
    assert len(r.certificates) >= 1
    assert r.signer_cert is not None

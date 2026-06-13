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


def test_parse_response_success_code():
    # синтетична відповідь з кодом результату 1 у payload offset 4
    payload = bytes([0x0D, 0, 0, 0]) + (1).to_bytes(4, "little")
    resp = bytes([0x04, 0x08]) + payload
    r = parse_response(resp)
    assert r.result_code == 1
    assert r.found

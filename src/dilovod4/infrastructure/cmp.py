"""CMP-клієнт КНЕДП (IIT-сумісний) — онлайн-дотягування сертифіката за keyId.

Контейнери з лише приватними ключами (без вбудованого сертифіката) потребують
дотягування сертифіката підписувача з КНЕДП за public-key-id. UAPKI вбудованого
CMP-клієнта не має, тож реалізуємо проприетарний IIT-«transport» формат
(перевірено реверсом jkurwa, https://github.com/muromec/jkurwa).

Формат запиту (НЕ RFC 4210): 120-байтовий payload з public-key-id на фіксованих
зміщеннях, загорнутий у ContentInfo type=data:
    offset 0x00 = 0x0d  (маркер)
    offset 0x08 = 0x02  (кількість keyId)
    offset 0x0c = keyId[0]  (32 байти ГОСТ 34.311 від стиснутої точки)
    offset 0x2c = keyId[1]  (другий keyId або повтор першого)
    offset 0x6c = 0x01
    offset 0x70 = 0x01

public-key-id = ГОСТ 34.311 (блок замін №1, нульовий IV) від octet string зі
стиснутою точкою відкритого ключа. UAPKI віддає його як `keyId2` у SELECT_KEY.

Відповідь: ContentInfo type=data з payload, де перші байти — код результату
(readInt32LE(4) == 1 -> успіх; інакше сертифікат не знайдено). За успіху payload
містить вкладений ContentInfo із сертифікатами.

ОБМЕЖЕННЯ: якщо до ключів не випущено (або знято) сертифікат, сервер повертає
ненульовий код — це не помилка клієнта, а відсутність сертифіката на CA.
"""

from __future__ import annotations

import struct
import urllib.request
from dataclasses import dataclass

# ContentInfo data: OID 1.2.840.113549.1.7.1
_OID_DATA = bytes.fromhex("06092A864886F70D010701")
_PAYLOAD_LEN = 120
_OFF_MARKER = 0x00
_OFF_COUNT = 0x08
_OFF_KEYID0 = 0x0C
_OFF_KEYID1 = 0x2C
_OFF_FLAG1 = 0x6C
_OFF_FLAG2 = 0x70


class CmpError(RuntimeError):
    """Помилка CMP-обміну (мережа або ненульовий код результату)."""


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(value)) + value


def build_request(key_id_primary: bytes, key_id_secondary: bytes | None = None) -> bytes:
    """Зібрати CMP-запит (IIT transport) для дотягування сертифіката за keyId.

    key_id_* — 32 байти public-key-id (ГОСТ 34.311), напр. UAPKI keyId2 (hex->bytes).
    """
    if len(key_id_primary) != 32:
        raise CmpError(f"key_id_primary має бути 32 байти, отримано {len(key_id_primary)}")
    secondary = key_id_secondary or key_id_primary
    if len(secondary) != 32:
        raise CmpError(f"key_id_secondary має бути 32 байти, отримано {len(secondary)}")

    ct = bytearray(_PAYLOAD_LEN)
    ct[_OFF_MARKER] = 0x0D
    ct[_OFF_COUNT] = 0x02
    ct[_OFF_KEYID0 : _OFF_KEYID0 + 32] = key_id_primary
    ct[_OFF_KEYID1 : _OFF_KEYID1 + 32] = secondary
    ct[_OFF_FLAG1] = 0x01
    ct[_OFF_FLAG2] = 0x01

    octet = _tlv(0x04, bytes(ct))
    explicit = _tlv(0xA0, octet)
    return _tlv(0x30, _OID_DATA + explicit)


@dataclass(frozen=True)
class CmpResponse:
    """Розібрана відповідь CMP."""

    result_code: int  # 1 = успіх; інакше сертифікат не знайдено
    raw: bytes

    @property
    def found(self) -> bool:
        return self.result_code == 1


def parse_response(resp: bytes) -> CmpResponse:
    """Витягти код результату з відповіді CMP (readInt32LE на payload offset 4)."""
    # payload — у вкладеному OCTET STRING; для коду достатньо останніх/перших байт
    # IIT кладе [marker(0x0d) | 0x000000 | resultLE(4) | ...]. Беремо int32 LE з offset 4
    # всередині OCTET STRING. Знаходимо OCTET STRING (тег 0x04) у структурі.
    code = -1
    idx = resp.find(b"\x04\x08")  # OCTET STRING довжиною 8 у короткій відповіді
    if idx >= 0 and idx + 2 + 8 <= len(resp):
        payload = resp[idx + 2 : idx + 2 + 8]
        code = struct.unpack("<I", payload[4:8])[0]
    elif len(resp) >= 4:
        code = struct.unpack("<I", resp[-4:])[0]
    return CmpResponse(result_code=code, raw=resp)


def fetch_certificate(
    key_id_primary: bytes,
    cmp_url: str,
    *,
    key_id_secondary: bytes | None = None,
    timeout: int = 30,
) -> CmpResponse:
    """Дотягнути сертифікат за keyId з CMP-сервера КНЕДП.

    cmp_url — напр. 'http://ca.monobank.ua/services/cmp/' (з реєстру CAs.json).
    Повертає CmpResponse; .found == True означає, що сертифікат знайдено
    (повний розбір вкладених сертифікатів — наступний крок за потреби).
    """
    payload = build_request(key_id_primary, key_id_secondary)
    req = urllib.request.Request(
        cmp_url,
        data=payload,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(payload)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            resp = r.read()
    except OSError as exc:
        raise CmpError(f"CMP-запит не вдався: {exc}") from exc
    return parse_response(resp)

"""CMP-клієнт КНЕДП (IIT-сумісний) — онлайн-дотягування сертифіката за keyId.

Контейнери з лише приватними ключами (без вбудованого сертифіката) потребують
дотягування сертифіката підписувача з КНЕДП. UAPKI вбудованого CMP-клієнта не
має, тож реалізуємо проприетарний IIT-«transport» формат (сумісний із
реалізацією jkurwa, https://github.com/muromec/jkurwa).

ВАЖЛИВО про ідентифікатор: CMP-сервер індексує сертифікати за
**subjectKeyIdentifier** ключа (його UAPKI віддає як `id` у SELECT_KEY/KEYS —
це SKI, напр. '5BC6C06E…'), а НЕ за keyId2 (ГОСТ-хеш стиснутої точки).
Перевірено на ca.informjust.ua: із SKI сервер повертає повний ланцюг, із keyId2
— код 9 (не знайдено).

Формат запиту (НЕ RFC 4210): 120-байтовий payload з id на фіксованих зміщеннях,
загорнутий у ContentInfo type=data:
    offset 0x00 = 0x0d  (маркер)
    offset 0x08 = 0x02  (кількість id)
    offset 0x0c = id[0]  (32 байти subjectKeyIdentifier)
    offset 0x2c = id[1]  (другий id або повтор першого)
    offset 0x6c = 0x01
    offset 0x70 = 0x01

Відповідь: ContentInfo type=data, OCTET STRING якого містить
    [marker 0x0d | 0x000000 | resultLE(4) | вкладений CMS SignedData з сертифікатами]
result == 1 -> успіх; інакше (напр. 9) сертифікат не знайдено.
"""

from __future__ import annotations

import struct
import urllib.request
from dataclasses import dataclass, field

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


# --- мінімальний DER-парсер (tag, length, value) ---
def _read_tlv(buf: bytes, pos: int) -> tuple[int, int, int, int]:
    """Повернути (tag, content_start, content_len, next_pos) для TLV на позиції pos."""
    tag = buf[pos]
    p = pos + 1
    first = buf[p]
    p += 1
    if first < 0x80:
        length = first
    else:
        nbytes = first & 0x7F
        length = int.from_bytes(buf[p : p + nbytes], "big")
        p += nbytes
    return tag, p, length, p + length


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(value)) + value


def build_request(key_id_primary: bytes, key_id_secondary: bytes | None = None) -> bytes:
    """Зібрати CMP-запит (IIT transport) для дотягування сертифіката за id.

    key_id_* — 32 байти subjectKeyIdentifier ключа (UAPKI `id` із SELECT_KEY).
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


def _extract_octet_payload(resp: bytes) -> bytes | None:
    """ContentInfo data -> вміст внутрішнього OCTET STRING."""
    try:
        tag, cs, cl, _ = _read_tlv(resp, 0)  # SEQUENCE
        if tag != 0x30:
            return None
        pos = cs
        # OID
        t, s, l, nxt = _read_tlv(resp, pos)
        pos = nxt
        # [0] explicit
        t, s, l, nxt = _read_tlv(resp, pos)
        if t != 0xA0:
            return None
        # OCTET STRING всередині
        t, s, l, nxt = _read_tlv(resp, s)
        if t != 0x04:
            return None
        return resp[s : s + l]
    except (IndexError, ValueError):
        return None


def _extract_certificates(inner_cms: bytes) -> list[bytes]:
    """Витягти DER-сертифікати з вкладеного CMS SignedData (поле certificates [0])."""
    certs: list[bytes] = []
    try:
        # ContentInfo SEQUENCE
        t, cs, cl, _ = _read_tlv(inner_cms, 0)
        if t != 0x30:
            return certs
        pos = cs
        t, s, l, nxt = _read_tlv(inner_cms, pos)  # OID signedData
        pos = nxt
        t, s, l, nxt = _read_tlv(inner_cms, pos)  # [0]
        if t != 0xA0:
            return certs
        # SignedData SEQUENCE
        t, sd_s, sd_l, _ = _read_tlv(inner_cms, s)
        if t != 0x30:
            return certs
        p = sd_s
        end = sd_s + sd_l
        # version INTEGER
        _, _, _, p = _read_tlv(inner_cms, p)
        # digestAlgorithms SET
        _, _, _, p = _read_tlv(inner_cms, p)
        # encapContentInfo SEQUENCE
        _, _, _, p = _read_tlv(inner_cms, p)
        # certificates [0] (IMPLICIT)
        if p < end:
            t, cert_s, cert_l, _ = _read_tlv(inner_cms, p)
            if t == 0xA0:
                cp = cert_s
                cend = cert_s + cert_l
                while cp < cend:
                    ct_tag, _, _, cnext = _read_tlv(inner_cms, cp)
                    if ct_tag == 0x30:  # Certificate SEQUENCE
                        certs.append(inner_cms[cp:cnext])
                    cp = cnext
    except (IndexError, ValueError):
        pass
    return certs


@dataclass(frozen=True)
class CmpResponse:
    """Розібрана відповідь CMP."""

    result_code: int  # 1 = успіх; інакше сертифікат не знайдено
    raw: bytes
    certificates: tuple[bytes, ...] = field(default_factory=tuple)

    @property
    def found(self) -> bool:
        return self.result_code == 1

    @property
    def signer_cert(self) -> bytes | None:
        """Перший сертифікат у ланцюгу — зазвичай сертифікат підписувача."""
        return self.certificates[0] if self.certificates else None


def parse_response(resp: bytes) -> CmpResponse:
    """Розібрати відповідь CMP: код результату + вкладені сертифікати."""
    payload = _extract_octet_payload(resp)
    if payload is None or len(payload) < 8:
        # коротка відповідь без обгортки — спроба прочитати хвіст
        code = struct.unpack("<I", resp[-4:])[0] if len(resp) >= 4 else -1
        return CmpResponse(result_code=code, raw=resp)
    # [marker(0x0d) 0x000000 | resultLE(4) | inner CMS]
    code = struct.unpack("<I", payload[4:8])[0]
    certs = tuple(_extract_certificates(payload[8:])) if code == 1 else ()
    return CmpResponse(result_code=code, raw=resp, certificates=certs)


def fetch_certificate(
    key_id_primary: bytes,
    cmp_url: str,
    *,
    key_id_secondary: bytes | None = None,
    timeout: int = 30,
) -> CmpResponse:
    """Дотягнути сертифікат за subjectKeyIdentifier з CMP-сервера КНЕДП.

    cmp_url — напр. 'http://ca.informjust.ua/services/cmp/' (з реєстру CAs.json).
    .found == True та .signer_cert містить DER сертифіката підписувача за успіху.
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

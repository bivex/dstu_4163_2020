"""Тести формування навантаження QR-коду (§5.10) — чиста доменна логіка."""

from __future__ import annotations

from dilovod4.domain.model import CertificateStatus, ElectronicSignatureMark
from dilovod4.domain.model.qr_payload import (
    QR_PAYLOAD_VERSION,
    build_signature_qr_payload,
)


def _mark(**overrides) -> ElectronicSignatureMark:
    kw = dict(
        signer="ПЕТРЕНКО Олександр Іванович",
        certificate_serial="58E2D9C1F0A4B7E3",
        issuer="КН ЕДП «Дія»",
        valid_from="01.01.2026",
        valid_to="01.01.2028",
        timestamp="13.06.2026 16:42:05 EET",
    )
    kw.update(overrides)
    return ElectronicSignatureMark(**kw)


def _parse(payload: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in _split_escaped(payload, ";"):
        k, v = _split_escaped(token, "=", maxsplit=1)
        out[k] = v.replace("\\;", ";").replace("\\=", "=").replace("\\\\", "\\")
    return out


def _split_escaped(s: str, sep: str, maxsplit: int = -1) -> list[str]:
    parts, buf, i = [], [], 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            buf.append(s[i : i + 2])
            i += 2
            continue
        if ch == sep and (maxsplit < 0 or len(parts) < maxsplit):
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return parts


def test_payload_contains_certificate_fields():
    payload = build_signature_qr_payload(_mark())
    d = _parse(payload)
    assert d["v"] == QR_PAYLOAD_VERSION
    assert d["typ"] == "QES"
    assert d["sn"] == "58E2D9C1F0A4B7E3"
    assert d["sub"] == "ПЕТРЕНКО Олександр Іванович"
    assert d["iss"] == "КН ЕДП «Дія»"
    assert d["ts"] == "13.06.2026 16:42:05 EET"
    assert d["st"] == "VALID"


def test_payload_marks_invalid_certificate():
    payload = build_signature_qr_payload(_mark(status=CertificateStatus.CANCELLED))
    assert _parse(payload)["st"] == "INVALID"


def test_payload_advanced_signature_type():
    payload = build_signature_qr_payload(_mark(is_qualified=False))
    assert _parse(payload)["typ"] == "AES"


def test_payload_escapes_separators_in_values():
    payload = build_signature_qr_payload(_mark(issuer="A;B=C"))
    # роздільники в значенні не ламають парсинг
    assert _parse(payload)["iss"] == "A;B=C"

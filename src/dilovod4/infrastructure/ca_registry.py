"""Реєстр КНЕДП — резолвинг CMP/OCSP/TSP-адрес за emitentom (issuer CN).

Завантажує CAs.json (реєстр кваліфікованих надавачів, напр. iit.com.ua) і за
issuer CN сертифіката повертає його сервісні адреси. Це знімає потребу вручну
вказувати cmp_url/tsp_url — їх визначаємо за самим сертифікатом.

Снапшот реєстру лежить у data/CAs.json; оновити — завантажити свіжий
з https://iit.com.ua/download/productfiles/CAs.json. Можна також передати
шлях/URL до власної копії.
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_BUNDLED = Path(__file__).resolve().parent / "data" / "CAs.json"
_REGISTRY_URL = "https://iit.com.ua/download/productfiles/CAs.json"


class CaRegistryError(RuntimeError):
    """Помилка реєстру КНЕДП (не знайдено надавача або реєстр недоступний)."""


@dataclass(frozen=True)
class CaEndpoints:
    """Сервісні адреси одного КНЕДП."""

    issuer_cns: tuple[str, ...]
    cmp_url: str | None
    ocsp_url: str | None
    tsp_url: str | None
    edrpou: str | None

    @staticmethod
    def from_entry(entry: dict) -> "CaEndpoints":
        return CaEndpoints(
            issuer_cns=tuple(entry.get("issuerCNs", [])),
            cmp_url=_full_url(entry.get("cmpAddress")),
            ocsp_url=_full_url(entry.get("ocspAccessPointAddress")),
            tsp_url=_full_url(entry.get("tspAddress")),
            edrpou=entry.get("codeEDRPOU"),
        )


def _full_url(addr: str | None) -> str | None:
    """Додати схему http:// до адреси з реєстру (там без схеми)."""
    if not addr:
        return None
    if addr.startswith(("http://", "https://")):
        return addr
    return f"http://{addr}"


@lru_cache(maxsize=4)
def _load(source: str | None = None) -> tuple[CaEndpoints, ...]:
    """Завантажити реєстр (з bundled-снапшоту, файла або URL)."""
    if source and source.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(source, timeout=30) as r:
                raw = r.read()
        except OSError as exc:
            raise CaRegistryError(f"не вдалося завантажити реєстр: {exc}") from exc
        data = json.loads(raw)
    else:
        path = Path(source) if source else _BUNDLED
        if not path.is_file():
            raise CaRegistryError(f"реєстр не знайдено: {path}")
        data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(CaEndpoints.from_entry(e) for e in data)


def list_providers(source: str | None = None) -> tuple[CaEndpoints, ...]:
    """Усі КНЕДП із реєстру."""
    return _load(source)


def find_by_issuer_cn(issuer_cn: str, *, source: str | None = None) -> CaEndpoints:
    """Знайти КНЕДП за issuer CN сертифіката (повний або частковий збіг).

    issuer_cn — CN видавця з CERT_INFO (напр. 'КНЕДП monobank | Universal Bank').
    """
    providers = _load(source)
    # точний збіг
    for ca in providers:
        if issuer_cn in ca.issuer_cns:
            return ca
    # частковий (CN може трохи відрізнятись регістром/пробілами)
    norm = issuer_cn.strip().lower()
    for ca in providers:
        for cn in ca.issuer_cns:
            if norm in cn.strip().lower() or cn.strip().lower() in norm:
                return ca
    raise CaRegistryError(f"КНЕДП не знайдено в реєстрі за issuer CN: {issuer_cn!r}")

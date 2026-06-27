"""Серверний підпис електронною печаткою юрособи (eSeal) — ключ у PKCS#12 на сервері.

На відміну від клієнтського підпису КЕП особи (ключ у браузері, ЗУ 2155-VIII),
ключ печатки юрособи належить організації, тож сервер як її представник може
підписувати нею. Це дозволяє масовий/автоматизований підпис без участі браузера
директора (пакет наказів, розрахункових документів тощо).

Реалізація — тонка обгортка над ``sign_file_pkcs12`` (нативна UAPKI): приймає
дані (байти маніфесту ASiC-E), шлях до PKCS#12 печатки та пароль, повертає
detached-CAdES-контейнер (p7s) + розібрані дані сертифіката.

ВАЖЛИВО про безпеку:
  * пароль PKCS#12 береться лише з оточення, ніколи не логується;
  * файл ключа має бути захищений на рівні ОС (0600, окремий користувач-сервіс);
  * для продакшну з високими вимогами — HSM/PKCS#11 (окрема інтеграція).

Потребує зібраної нативної libuapki (див. ``uapki.UapkiClient``). Без неї
``UapkiLibraryNotFound`` піднімається на першому виклику — портал має віддавати
503 для ендпоїнту серверного підпису.
"""

from __future__ import annotations

from dataclasses import dataclass

from .uapki import (
    CertInfo,
    sign_file_pkcs12,
    sign_file_with_remote_cert,
)


class ServerSealError(RuntimeError):
    """Помилка серверного підпису печаткою (конфігурація/підпис)."""


@dataclass(frozen=True)
class SealSignResult:
    """Результат серверного підпису печаткою: контейнер + дані сертифіката."""

    container: bytes  # detached CAdES-контейнер (p7s, DER)
    cert: CertInfo  # розібраний сертифікат печатки (org name, ЄДРПОУ, строки)


def sign_with_server_seal(
    data: bytes,
    *,
    p12_path: str,
    password: str,
    cert_cache_dir: str,
    crl_cache_dir: str,
    with_timestamp: bool = False,
    tsp_url: str | None = None,
    cmp_url: str | None = None,
    ignore_cert_status: bool = True,
) -> SealSignResult:
    """Підписати ``data`` печаткою юрособи з PKCS#12-контейнера на сервері.

    ``data`` — байти, що підписуються (напр. ASiC-E маніфест). Повертає
    detached-CAdES контейнер. ``with_timestamp=True`` → CAdES-T з кваліфікованою
    позначкою часу (Art.26.4), потребує ``tsp_url`` і ``cmp_url`` (дотягнення
    сертифіката онлайн). Інакше — CAdES-BES (MVP), сумісний із перевірятниками.

    ``ignore_cert_status=True`` — типово, щоб тестові/прострочені сертифікати
    печатки підписувалися (для бойового чинного сертифіката можна вимкнути).

    Піднімає ``UapkiLibraryNotFound`` (libuapki не зібрана), ``UapkiError``
    (помилка підпису), ``ServerSealError`` (невалідний конфіг/результат).
    """
    if not p12_path:
        raise ServerSealError("шлях до PKCS#12 печатки не задано")
    if not password:
        raise ServerSealError("пароль PKCS#12 печатки не задано")

    # sign_file_* приймає шлях до файлу даних, тож пишемо маніфест у тимчасовий
    # файл і прибираємо його після підпису.
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".bin")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)

        if with_timestamp:
            # CAdES-T: потрібен онлайн-режим + TSP/CMP-адреси КНЕДП
            if not tsp_url or not cmp_url:
                raise ServerSealError("CAdES-T потребує tsp_url і cmp_url")
            sig = sign_file_with_remote_cert(
                file_path=path,
                pkcs12_path=p12_path,
                password=password,
                cmp_url=cmp_url,
                cert_cache_dir=cert_cache_dir,
                crl_cache_dir=crl_cache_dir,
                signature_format="CAdES-T",
                detached=True,
                ignore_cert_status=ignore_cert_status,
                tsp_url=tsp_url,
            )
        else:
            sig = sign_file_pkcs12(
                file_path=path,
                pkcs12_path=p12_path,
                password=password,
                cert_cache_dir=cert_cache_dir,
                crl_cache_dir=crl_cache_dir,
                signature_format="CAdES-BES",
                detached=True,
                ignore_cert_status=ignore_cert_status,
                parse_cert=True,
            )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass

    if sig.cert is None:
        raise ServerSealError("сертифікат печатки не розібрано")

    return SealSignResult(container=sig.container, cert=sig.cert)


__all__ = [
    "SealSignResult",
    "ServerSealError",
    "sign_with_server_seal",
]

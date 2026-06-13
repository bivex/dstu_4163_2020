"""Відмітка про електронний підпис (КЕП) — value object.

Стик двох норм: §4.4 реквізит 22 ДСТУ 4163:2020 (для е-документів підпис =
електронний підпис/печатка) ↔ Закон 2155-VIII Art.18 (КЕП) та Art.24
(чинність кваліфікованого сертифіката).

ElectronicSignatureMark несе дані сертифіката, з яких будується візуальна
відмітка у документі. Чинність визначається за Art.24 (CertificateValidity):
строк не закінчився, статус не скасований/заблокований, сертифікат видавця чинний.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import InvariantViolation
from .enums import CertificateStatus


@dataclass(frozen=True)
class ElectronicSignatureMark:
    signer: str  # ПІБ або псевдонім (Art.4-1)
    certificate_serial: str  # серійний номер кваліфікованого сертифіката
    issuer: str  # надавач/АЦСК, що видав сертифікат
    valid_from: str  # початок строку дії (оформлений за §5.10)
    valid_to: str  # кінець строку дії
    timestamp: str  # кваліфікована позначка часу підпису
    is_qualified: bool = True  # КЕП (Art.18) чи удосконалений
    status: CertificateStatus = CertificateStatus.ACTIVE  # Art.25
    validity_period_expired: bool = False  # Art.24
    issuer_certificate_valid: bool = True  # Art.24

    def __post_init__(self) -> None:
        if not self.signer.strip():
            raise InvariantViolation("підписувач не може бути порожнім")
        if not self.certificate_serial.strip():
            raise InvariantViolation("серійний номер сертифіката не може бути порожнім")

    @property
    def certificate_valid(self) -> bool:
        """Art.24: кваліфікований сертифікат чинний на момент перевірки."""
        return (
            not self.validity_period_expired
            and self.status not in (CertificateStatus.CANCELLED, CertificateStatus.BLOCKED)
            and self.issuer_certificate_valid
        )

    @property
    def signature_kind(self) -> str:
        return (
            "Кваліфікований електронний підпис"
            if self.is_qualified
            else "Удосконалений електронний підпис"
        )

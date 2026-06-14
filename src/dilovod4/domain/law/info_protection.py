"""Обчислювані норми Закону № 80/94-ВР «Про захист інформації в інформаційно-
комунікаційних системах» — перенесені з info_protection_80_94.catala_en.

Чисті функції/перевірки над доменними даними, БЕЗ IO. Кожна функція відповідає
одному Catala-scope; статті закону збережено у docstring.

Стик: режим «захисту інформації в ІКС», на який посилається ст.12 Закону 851-IV
(перевірка цілісності іншими засобами), доповнює режим обмеженого доступу
законів 2657-XII (ст.21) та 2939-VI (ст.6). «Інформація з обмеженим доступом»
тут — той самий обʼєкт, що захищає гриф обмеження доступу (реквізит 15 ДСТУ).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class InfoCategory(Enum):
    """Категорія інформації в системі для режиму доступу/обробки/захисту."""

    STATE_RESOURCE = "StateResource"  # державні інформаційні ресурси
    RESTRICTED_BY_LAW = "RestrictedByLaw"  # обмежений доступ (вимога захисту за законом)
    ORDINARY = "Ordinary"  # звичайна інформація


class SystemOwnerType(Enum):
    """Тип власника/розпорядника системи."""

    PUBLIC_SECTOR = "PublicSector"  # органи влади, держ/комун. підприємства, ОМС
    PRIVATE = "Private"  # приватний власник


class AccessSource(Enum):
    """Ст.4. Ким визначається порядок доступу."""

    DEFINED_BY_OWNER = "DefinedByOwner"  # володільцем інформації
    DEFINED_BY_LEGISLATION = "DefinedByLegislation"  # законодавством


@dataclass(frozen=True)
class ProcessingSetup:
    """Ст.8. Умови обробки у системі."""

    category: InfoCategory
    owner_type: SystemOwnerType
    security_authorized: bool  # авторизована з безпеки система
    has_conformity_certificate: bool  # сертифікат відповідності стандарту ІБ


@dataclass(frozen=True)
class ProtectionSetup:
    """Ст.9. Забезпечення захисту у системі."""

    category: InfoCategory
    owner_type: SystemOwnerType
    cyber_defence_unit_established: bool  # підрозділ із кіберзахисту / відповідальні особи


# --- Ст.4. Доступ до інформації в системі ---
def access_defined_by(category: InfoCategory) -> AccessSource:
    """Ст.4(1,2). Порядок доступу визначає володілець; для державних ресурсів
    або інформації з обмеженим доступом — законодавство."""
    if category in (InfoCategory.STATE_RESOURCE, InfoCategory.RESTRICTED_BY_LAW):
        return AccessSource.DEFINED_BY_LEGISLATION
    return AccessSource.DEFINED_BY_OWNER


# --- Ст.8. Умови обробки інформації в системі ---
def processing_compliant(setup: ProcessingSetup) -> bool:
    """Ст.8. Державні ресурси або інформація з обмеженим доступом у системах
    публічного сектору мають оброблятися в авторизованих з безпеки системах або
    за наявності сертифіката відповідності стандарту ІБ. Для звичайної інформації
    чи приватних систем норма не застосовується."""
    if setup.category is InfoCategory.ORDINARY or setup.owner_type is SystemOwnerType.PRIVATE:
        return True
    return setup.security_authorized or setup.has_conformity_certificate


# --- Ст.9. Забезпечення захисту інформації в системі ---
def cyber_defence_required(setup: ProtectionSetup) -> bool:
    """Ст.9(2). Підрозділ із кіберзахисту обовʼязковий для державних ресурсів
    або інформації з обмеженим доступом у системах публічного сектору."""
    return (
        setup.owner_type is SystemOwnerType.PUBLIC_SECTOR
        and setup.category is not InfoCategory.ORDINARY
    )


def protection_compliant(setup: ProtectionSetup) -> bool:
    """Ст.9. Якщо підрозділ із кіберзахисту обовʼязковий — він має бути утворений;
    інакше норма не застосовується."""
    if cyber_defence_required(setup):
        return setup.cyber_defence_unit_established
    return True

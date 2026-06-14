"""Тести обчислюваних норм Закону № 80/94-ВР «Про захист інформації в
інформаційно-комунікаційних системах» (domain/law/info_protection).
Дзеркалять scope'и info_protection_80_94.catala_en.
"""

from __future__ import annotations

import pytest

from dilovod4.domain.law import (
    AccessSource,
    InfoCategory,
    ProcessingSetup,
    ProtectionSetup,
    SystemOwnerType,
    access_defined_by,
    cyber_defence_required,
    protection_compliant,
    system_processing_compliant,
)


# --- Ст.4: джерело порядку доступу ---
@pytest.mark.parametrize(
    "category",
    [InfoCategory.STATE_RESOURCE, InfoCategory.RESTRICTED_BY_LAW],
)
def test_state_and_restricted_access_by_legislation(category):
    assert access_defined_by(category) is AccessSource.DEFINED_BY_LEGISLATION


def test_ordinary_access_by_owner():
    assert access_defined_by(InfoCategory.ORDINARY) is AccessSource.DEFINED_BY_OWNER


# --- Ст.8: умови обробки ---
def _proc(**over) -> ProcessingSetup:
    base = dict(
        category=InfoCategory.STATE_RESOURCE,
        owner_type=SystemOwnerType.PUBLIC_SECTOR,
        security_authorized=False,
        has_conformity_certificate=False,
    )
    base.update(over)
    return ProcessingSetup(**base)


def test_public_state_info_needs_authorization_or_certificate():
    assert system_processing_compliant(_proc()) is False
    assert system_processing_compliant(_proc(security_authorized=True)) is True
    assert system_processing_compliant(_proc(has_conformity_certificate=True)) is True


def test_ordinary_info_always_compliant():
    assert system_processing_compliant(_proc(category=InfoCategory.ORDINARY)) is True


def test_private_system_outside_norm():
    assert system_processing_compliant(_proc(owner_type=SystemOwnerType.PRIVATE)) is True


# --- Ст.9: захист та кіберзахист ---
def _prot(**over) -> ProtectionSetup:
    base = dict(
        category=InfoCategory.RESTRICTED_BY_LAW,
        owner_type=SystemOwnerType.PUBLIC_SECTOR,
        cyber_defence_unit_established=False,
    )
    base.update(over)
    return ProtectionSetup(**base)


def test_cyber_defence_required_for_public_restricted():
    assert cyber_defence_required(_prot()) is True


def test_cyber_defence_not_required_for_ordinary_or_private():
    assert cyber_defence_required(_prot(category=InfoCategory.ORDINARY)) is False
    assert cyber_defence_required(_prot(owner_type=SystemOwnerType.PRIVATE)) is False


def test_protection_compliant_requires_unit_when_mandatory():
    assert protection_compliant(_prot()) is False
    assert protection_compliant(_prot(cyber_defence_unit_established=True)) is True


def test_protection_compliant_when_unit_not_required():
    # звичайна інформація — підрозділ не обовʼязковий, відповідність є
    assert protection_compliant(_prot(category=InfoCategory.ORDINARY)) is True
    assert protection_compliant(_prot(owner_type=SystemOwnerType.PRIVATE)) is True

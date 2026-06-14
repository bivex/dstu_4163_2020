"""Тести обчислюваних норм Закону № 2297-VI «Про захист персональних даних»
(domain/law/personal_data). Дзеркалять scope'и personal_data_2297.catala_en.
"""

from __future__ import annotations

import pytest

from dilovod4.domain.law import (
    AccessRequestor,
    GeneralRequirements,
    ProcessingBasis,
    ProcessingContext,
    PurposeChange,
    SpecialCategoryException,
    TransferGround,
    access_deferral_allowed,
    access_free,
    access_fulfilment_within_limit,
    access_study_within_limit,
    collection_notice_deadline_working_days,
    collection_notice_timely,
    cross_border_transfer_permitted,
    further_processing_allowed,
    law_applies,
    processing_compliant,
    processing_lawful,
    special_category_processing_permitted,
)


# --- Ст.6 ---
def _req(**over) -> GeneralRequirements:
    base = dict(
        purpose_defined_in_law=True,
        data_adequate_not_excessive=True,
        accurate_and_updated=True,
        retained_no_longer_than_needed=True,
    )
    base.update(over)
    return GeneralRequirements(**base)


def test_processing_compliant_all_met():
    assert processing_compliant(_req()) is True


@pytest.mark.parametrize(
    "field",
    [
        "purpose_defined_in_law",
        "data_adequate_not_excessive",
        "accurate_and_updated",
        "retained_no_longer_than_needed",
    ],
)
def test_processing_noncompliant_when_one_fails(field):
    assert processing_compliant(_req(**{field: False})) is False


def test_purpose_unchanged_allows_processing():
    change = PurposeChange(False, False, False, False)
    assert further_processing_allowed(change) is True


def test_compatible_new_purpose_allows_processing():
    change = PurposeChange(purpose_changed=True, new_purpose_incompatible=False,
                           new_consent_obtained=False, law_allows_without_consent=False)
    assert further_processing_allowed(change) is True


def test_incompatible_purpose_needs_consent_or_law():
    bad = PurposeChange(True, True, False, False)
    assert further_processing_allowed(bad) is False
    assert further_processing_allowed(PurposeChange(True, True, True, False)) is True
    assert further_processing_allowed(PurposeChange(True, True, False, True)) is True


# --- Ст.7 ---
def test_special_category_forbidden_without_exception():
    assert special_category_processing_permitted(SpecialCategoryException.NO_EXCEPTION) is False


@pytest.mark.parametrize(
    "exc",
    [
        SpecialCategoryException.EXPLICIT_CONSENT,
        SpecialCategoryException.HEALTHCARE_PURPOSES,
        SpecialCategoryException.MANIFESTLY_PUBLIC,
        SpecialCategoryException.COURT_OPERATIVE_SECURITY,
    ],
)
def test_special_category_permitted_with_exception(exc):
    assert special_category_processing_permitted(exc) is True


# --- Ст.11 ---
@pytest.mark.parametrize(
    "basis",
    [
        ProcessingBasis.CONSENT,
        ProcessingBasis.CONTRACT_WITH_SUBJECT,
        ProcessingBasis.VITAL_INTERESTS,
        ProcessingBasis.LEGAL_OBLIGATION_OF_CONTROLLER,
        ProcessingBasis.LEGAL_PERMISSION_FOR_POWERS,
    ],
)
def test_processing_lawful_for_standard_bases(basis):
    assert processing_lawful(basis) is True


def test_legitimate_interests_blocked_when_overridden():
    assert processing_lawful(ProcessingBasis.LEGITIMATE_INTERESTS,
                             legitimate_interests_override_subject=True) is False
    assert processing_lawful(ProcessingBasis.LEGITIMATE_INTERESTS,
                             legitimate_interests_override_subject=False) is True


# --- Ст.12 ---
def test_collection_notice_deadline():
    assert collection_notice_deadline_working_days(collected_from_subject=True) == 0
    assert collection_notice_deadline_working_days(collected_from_subject=False) == 30


def test_collection_notice_timely():
    assert collection_notice_timely(True, 999) is True  # збір у субʼєкта — момент збору
    assert collection_notice_timely(False, 30) is True
    assert collection_notice_timely(False, 31) is False


# --- Ст.16 ---
def test_access_study_limit():
    assert access_study_within_limit(10) is True
    assert access_study_within_limit(11) is False


def test_access_fulfilment_limit():
    assert access_fulfilment_within_limit(30) is True
    assert access_fulfilment_within_limit(31) is False


# --- Ст.17 ---
def test_subject_own_data_no_deferral():
    assert access_deferral_allowed(AccessRequestor.DATA_SUBJECT_OWN_DATA, 0, 0) is False


def test_third_party_deferral_within_limits():
    assert access_deferral_allowed(AccessRequestor.THIRD_PARTY, 30, 45) is True
    assert access_deferral_allowed(AccessRequestor.THIRD_PARTY, 31, 45) is False
    assert access_deferral_allowed(AccessRequestor.THIRD_PARTY, 30, 46) is False


# --- Ст.19 ---
def test_subject_access_free_third_party_paid():
    assert access_free(AccessRequestor.DATA_SUBJECT_OWN_DATA) is True
    assert access_free(AccessRequestor.THIRD_PARTY) is False


# --- Ст.25 ---
def test_personal_household_exempt():
    assert law_applies(ProcessingContext.PERSONAL_HOUSEHOLD) is False


def test_journalistic_exempt_only_with_balance():
    assert law_applies(ProcessingContext.JOURNALISTIC_CREATIVE,
                       balance_of_rights_ensured=True) is False
    assert law_applies(ProcessingContext.JOURNALISTIC_CREATIVE,
                       balance_of_rights_ensured=False) is True


def test_general_processing_law_applies():
    assert law_applies(ProcessingContext.GENERAL) is True


# --- Ст.29 ---
def test_transfer_to_adequate_state():
    assert cross_border_transfer_permitted(adequate_protection_state=True) is True


def test_transfer_without_adequacy_needs_ground():
    assert cross_border_transfer_permitted(False, TransferGround.NO_TRANSFER_GROUND) is False
    assert cross_border_transfer_permitted(False, TransferGround.UNAMBIGUOUS_CONSENT) is True

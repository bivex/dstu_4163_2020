"""Тести обчислюваних норм Закону № 2939-VI «Про доступ до публічної інформації»
(domain/law/public_information). Дзеркалять scope'и public_information_2939.catala_en.
"""

from __future__ import annotations

import pytest

from dilovod4.domain.law import (
    NonRestrictableTopic,
    PublicAccessRegime,
    RefusalGround,
    RequestUrgency,
    Requestor,
    ThreePartTest,
    public_info_regime,
    public_restriction_lawful,
    public_topic_may_be_restricted,
    publication_timely,
    refusal_lawful,
    reimbursement_required,
    response_deadline_hours,
    response_deadline_working_days,
)


# --- Ст.1 ---
def test_open_by_default():
    assert public_info_regime(restricted_by_law=False) is PublicAccessRegime.OPEN


def test_restricted_by_law():
    assert public_info_regime(restricted_by_law=True) is PublicAccessRegime.RESTRICTED


# --- Ст.6(5,6,7): теми, що не підлягають обмеженню ---
@pytest.mark.parametrize(
    "topic",
    [
        NonRestrictableTopic.BUDGET_USE_PROCUREMENT,
        NonRestrictableTopic.TAX_DEBT,
        NonRestrictableTopic.OFFICIAL_DECLARATION,
        NonRestrictableTopic.PUBLIC_OFFICIAL_REMUNERATION,
    ],
)
def test_protected_topics_cannot_be_restricted(topic):
    assert public_topic_may_be_restricted(topic) is False


def test_other_topic_may_be_restricted():
    assert public_topic_may_be_restricted(NonRestrictableTopic.OTHER_TOPIC) is True


# --- Ст.6(2): трискладовий тест ---
def _full() -> ThreePartTest:
    return ThreePartTest(
        legitimate_interest=True,
        substantial_harm=True,
        harm_outweighs_public_interest=True,
    )


def test_restriction_lawful_all_met():
    assert public_restriction_lawful(NonRestrictableTopic.OTHER_TOPIC, _full()) is True


def test_restriction_unlawful_for_protected_topic():
    assert public_restriction_lawful(NonRestrictableTopic.BUDGET_USE_PROCUREMENT, _full()) is False


@pytest.mark.parametrize(
    "field", ["legitimate_interest", "substantial_harm", "harm_outweighs_public_interest"]
)
def test_restriction_unlawful_when_test_part_fails(field):
    kwargs = dict(
        legitimate_interest=True,
        substantial_harm=True,
        harm_outweighs_public_interest=True,
    )
    kwargs[field] = False
    assert public_restriction_lawful(NonRestrictableTopic.OTHER_TOPIC, ThreePartTest(**kwargs)) is False


# --- Ст.15: строки оприлюднення ---
def test_approved_document_timely():
    assert publication_timely(is_draft_act=False, working_days_since_approval=5) is True
    assert publication_timely(is_draft_act=False, working_days_since_approval=6) is False


def test_draft_act_timely():
    assert publication_timely(is_draft_act=True, working_days_before_review=10) is True
    assert publication_timely(is_draft_act=True, working_days_before_review=9) is False


# --- Ст.20: строки розгляду запиту ---
def test_life_safety_deadline_hours():
    assert response_deadline_hours(RequestUrgency.LIFE_SAFETY_ENVIRONMENT) == 48
    assert response_deadline_hours(RequestUrgency.ORDINARY) == 0


def test_ordinary_deadline_days():
    assert response_deadline_working_days(RequestUrgency.ORDINARY) == 5
    assert response_deadline_working_days(RequestUrgency.ORDINARY, extended_for_volume=True) == 20
    assert response_deadline_working_days(RequestUrgency.LIFE_SAFETY_ENVIRONMENT) == 0


# --- Ст.21: плата ---
def test_own_data_no_reimbursement():
    assert reimbursement_required(Requestor.OWN_DATA_OR_PUBLIC_INTEREST, pages=100) is False


def test_general_reimbursement_over_10_pages():
    assert reimbursement_required(Requestor.GENERAL, pages=10) is False
    assert reimbursement_required(Requestor.GENERAL, pages=11) is True


# --- Ст.22: відмова ---
@pytest.mark.parametrize(
    "ground",
    [
        RefusalGround.NOT_HELD_NOT_OBLIGED,
        RefusalGround.RESTRICTED_INFORMATION,
        RefusalGround.COPYING_COST_NOT_PAID,
        RefusalGround.REQUEST_REQUIREMENTS_NOT_MET,
    ],
)
def test_refusal_lawful_with_ground(ground):
    assert refusal_lawful(ground) is True


def test_refusal_unlawful_without_ground():
    assert refusal_lawful(RefusalGround.NO_GROUND) is False

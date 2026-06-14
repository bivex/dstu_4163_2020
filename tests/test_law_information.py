"""Тести обчислюваних норм Закону № 2657-XII «Про інформацію»
(domain/law/information). Дзеркалять scope'и information_law_2657.catala_en.
"""

from __future__ import annotations

import pytest

from dilovod4.domain.law import (
    AccessRegime,
    PublicInterestTest,
    RestrictionTest,
    StatementKind,
    UndisclosableTopic,
    access_regime,
    disclosure_permitted,
    liable_for_statement,
    restriction_lawful,
    statement_subject_to_refutation,
    topic_may_be_restricted,
)


# --- Ст.20 ---
def test_open_by_default():
    assert access_regime(restricted_by_law=False) is AccessRegime.OPEN


def test_restricted_only_by_law():
    assert access_regime(restricted_by_law=True) is AccessRegime.RESTRICTED


# --- Ст.21(4): перелік тем, що не підлягають обмеженню ---
@pytest.mark.parametrize(
    "topic",
    [
        UndisclosableTopic.ENVIRONMENT_FOOD_QUALITY,
        UndisclosableTopic.EMERGENCIES_DISASTERS,
        UndisclosableTopic.PUBLIC_HEALTH_LIVING,
        UndisclosableTopic.HUMAN_RIGHTS_VIOLATIONS,
    ],
)
def test_protected_topics_cannot_be_restricted(topic):
    assert topic_may_be_restricted(topic) is False


def test_other_topic_may_be_restricted():
    assert topic_may_be_restricted(UndisclosableTopic.OTHER_TOPIC) is True


# --- Ст.21(2) ↔ ст.6(2): трискладовий тест ---
def _full_test() -> RestrictionTest:
    return RestrictionTest(
        restriction_provided_by_law=True,
        legitimate_aim=True,
        harm_outweighs_public_interest=True,
    )


def test_restriction_lawful_when_all_conditions_met():
    assert restriction_lawful(UndisclosableTopic.OTHER_TOPIC, _full_test()) is True


def test_restriction_unlawful_for_protected_topic():
    # навіть з повним тестом захищена тема не підлягає обмеженню
    assert restriction_lawful(UndisclosableTopic.HUMAN_RIGHTS_VIOLATIONS, _full_test()) is False


@pytest.mark.parametrize(
    "field",
    ["restriction_provided_by_law", "legitimate_aim", "harm_outweighs_public_interest"],
)
def test_restriction_unlawful_when_test_part_fails(field):
    kwargs = dict(
        restriction_provided_by_law=True,
        legitimate_aim=True,
        harm_outweighs_public_interest=True,
    )
    kwargs[field] = False
    assert restriction_lawful(UndisclosableTopic.OTHER_TOPIC, RestrictionTest(**kwargs)) is False


# --- Ст.29: суспільно необхідна інформація ---
def test_disclosure_permitted_when_public_interest_overrides():
    test = PublicInterestTest(
        is_subject_of_public_interest=True, public_right_to_know_outweighs_harm=True
    )
    assert disclosure_permitted(test) is True


@pytest.mark.parametrize(
    "subj,overrides",
    [(False, True), (True, False), (False, False)],
)
def test_disclosure_denied_when_test_incomplete(subj, overrides):
    test = PublicInterestTest(
        is_subject_of_public_interest=subj, public_right_to_know_outweighs_harm=overrides
    )
    assert disclosure_permitted(test) is False


# --- Ст.30: оціночні судження ---
def test_value_judgment_no_liability_no_refutation():
    assert liable_for_statement(StatementKind.VALUE_JUDGMENT) is False
    assert statement_subject_to_refutation(StatementKind.VALUE_JUDGMENT) is False


def test_defamation_is_liable():
    assert liable_for_statement(StatementKind.DEFAMATION) is True
    assert statement_subject_to_refutation(StatementKind.DEFAMATION) is True


def test_factual_statement_liable_and_refutable():
    assert liable_for_statement(StatementKind.FACTUAL_STATEMENT) is True
    assert statement_subject_to_refutation(StatementKind.FACTUAL_STATEMENT) is True

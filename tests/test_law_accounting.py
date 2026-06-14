"""Тести обчислюваних норм Закону № 996-XIV «Про бухгалтерський облік та
фінансову звітність в Україні» (domain/law/accounting).
Дзеркалять scope'и accounting_996.catala_en.
"""

from __future__ import annotations

import pytest

from dilovod4.domain.law import (
    EnterpriseSize,
    GroupSize,
    IfrsObligation,
    PrimaryDocRequisites,
    PublisherKind,
    SizeMetrics,
    enterprise_size,
    group_size,
    ifrs_mandatory,
    primary_doc_valid,
    publication_deadline_day,
    published_in_time,
    reporting_period_valid,
    retention_sufficient,
    web_retention_sufficient,
)


# --- Ст.2(2): категорія підприємства (2-з-3) ---
def test_micro_enterprise():
    # активи 300k, дохід 600k, 8 осіб — усі три < мікро-порогів
    assert enterprise_size(SizeMetrics(300_000, 600_000, 8)) is EnterpriseSize.MICRO


def test_small_enterprise():
    # перевищує мікро за всіма, але ≤ малих порогів
    assert enterprise_size(SizeMetrics(3_000_000, 7_000_000, 40)) is EnterpriseSize.SMALL


def test_medium_enterprise():
    assert enterprise_size(SizeMetrics(15_000_000, 35_000_000, 200)) is EnterpriseSize.MEDIUM


def test_large_enterprise():
    assert enterprise_size(SizeMetrics(50_000_000, 100_000_000, 500)) is EnterpriseSize.LARGE


def test_two_of_three_rule_micro():
    # активи високі, але дохід і працівники в межах мікро → 2 з 3 → мікро
    assert enterprise_size(SizeMetrics(10_000_000, 700_000, 10)) is EnterpriseSize.MICRO


def test_only_one_criterion_not_enough():
    # лише 1 критерій мікро (активи), решта — рівень середнього → не мікро, не мале
    assert enterprise_size(SizeMetrics(350_000, 35_000_000, 200)) is EnterpriseSize.MEDIUM


# --- Ст.12(1): категорія групи ---
def test_small_group():
    assert group_size(SizeMetrics(3_000_000, 7_000_000, 40)) is GroupSize.SMALL_GROUP


def test_medium_group():
    assert group_size(SizeMetrics(15_000_000, 35_000_000, 200)) is GroupSize.MEDIUM_GROUP


def test_large_group():
    assert group_size(SizeMetrics(50_000_000, 100_000_000, 500)) is GroupSize.LARGE_GROUP


# --- Ст.8(3): строк зберігання ---
def test_retention():
    assert retention_sufficient(3) is True
    assert retention_sufficient(2) is False


# --- Ст.9(2): обовʼязкові реквізити первинного документа ---
def _req(**over) -> PrimaryDocRequisites:
    base = dict(
        has_title=True,
        has_date=True,
        has_enterprise_name=True,
        has_operation_content=True,
        has_responsible_persons=True,
        has_signature=True,
    )
    base.update(over)
    return PrimaryDocRequisites(**base)


def test_primary_doc_valid_all_requisites():
    assert primary_doc_valid(_req()) is True


@pytest.mark.parametrize(
    "field",
    [
        "has_title",
        "has_date",
        "has_enterprise_name",
        "has_operation_content",
        "has_responsible_persons",
        "has_signature",
    ],
)
def test_primary_doc_invalid_missing_requisite(field):
    assert primary_doc_valid(_req(**{field: False})) is False


# --- Ст.12-1(2): обовʼязковість МСФЗ ---
def _ifrs(**over) -> IfrsObligation:
    base = dict(
        public_interest_entity=False,
        public_joint_stock=False,
        extractive_industry=False,
        large_group_parent=False,
        government_listed_activity=False,
    )
    base.update(over)
    return IfrsObligation(**base)


def test_ifrs_not_mandatory_for_ordinary():
    assert ifrs_mandatory(_ifrs()) is False


@pytest.mark.parametrize(
    "field",
    [
        "public_interest_entity",
        "public_joint_stock",
        "extractive_industry",
        "large_group_parent",
        "government_listed_activity",
    ],
)
def test_ifrs_mandatory_when_any_flag(field):
    assert ifrs_mandatory(_ifrs(**{field: True})) is True


# --- Ст.13: звітний період ---
def test_standard_period_calendar_year():
    assert reporting_period_valid(is_newly_created=False, period_months=12) is True
    assert reporting_period_valid(is_newly_created=False, period_months=13) is False


def test_newly_created_period_12_to_15():
    assert reporting_period_valid(is_newly_created=True, period_months=12) is True
    assert reporting_period_valid(is_newly_created=True, period_months=15) is True
    assert reporting_period_valid(is_newly_created=True, period_months=11) is False
    assert reporting_period_valid(is_newly_created=True, period_months=16) is False


# --- Ст.14: строки оприлюднення ---
def test_publication_deadlines():
    assert publication_deadline_day(PublisherKind.PUBLIC_INTEREST_NON_LARGE_ISSUER) == 120
    assert publication_deadline_day(PublisherKind.LARGE_NON_ISSUER_OR_MEDIUM) == 152


def test_published_in_time():
    pi = PublisherKind.PUBLIC_INTEREST_NON_LARGE_ISSUER
    assert published_in_time(pi, 120) is True
    assert published_in_time(pi, 121) is False
    lm = PublisherKind.LARGE_NON_ISSUER_OR_MEDIUM
    assert published_in_time(lm, 152) is True
    assert published_in_time(lm, 153) is False


def test_web_retention():
    assert web_retention_sufficient(6) is True
    assert web_retention_sufficient(5) is False

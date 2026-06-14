"""Обчислювані норми Закону № 996-XIV «Про бухгалтерський облік та фінансову
звітність в Україні» — перенесені з accounting_996.catala_en.

Чисті функції/перевірки над доменними даними, БЕЗ IO. Кожна функція відповідає
одному Catala-scope; статті закону збережено у docstring.

Стик: обовʼязкові реквізити первинного документа (ст.9(2)) — паралель до §4.4
ДСТУ 4163:2020 (MandatoryRequisitesRule); електронний первинний документ
потребує підпису за Законом 851-IV; фінансова звітність НЕ є інформацією з
обмеженим доступом (ст.14(2)) — стик із законами 2657-XII / 2939-VI.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class EnterpriseSize(Enum):
    """Ст.2(2). Категорія підприємства."""

    MICRO = "Micro"
    SMALL = "Small"
    MEDIUM = "Medium"
    LARGE = "Large"


class GroupSize(Enum):
    """Ст.12(1). Категорія групи."""

    SMALL_GROUP = "SmallGroup"
    MEDIUM_GROUP = "MediumGroup"
    LARGE_GROUP = "LargeGroup"


@dataclass(frozen=True)
class SizeMetrics:
    """Ст.2(2)/12(1). Показники річної фінзвітності (євро / особи)."""

    balance_assets_eur: float  # балансова вартість активів
    net_revenue_eur: float  # чистий дохід від реалізації
    avg_employees: int  # середня кількість працівників


@dataclass(frozen=True)
class PrimaryDocRequisites:
    """Ст.9(2). Обовʼязкові реквізити первинного документа."""

    has_title: bool  # назва документа (форми)
    has_date: bool  # дата складання
    has_enterprise_name: bool  # назва підприємства
    has_operation_content: bool  # зміст та обсяг госп. операції
    has_responsible_persons: bool  # посади і прізвища відповідальних
    has_signature: bool  # особистий підпис / ідентифікація


@dataclass(frozen=True)
class IfrsObligation:
    """Ст.12-1(2). Хто зобовʼязаний звітувати за МСФЗ."""

    public_interest_entity: bool  # підприємство, що становить суспільний інтерес
    public_joint_stock: bool  # публічне акціонерне товариство
    extractive_industry: bool  # видобувні галузі
    large_group_parent: bool  # материнське підприємство великої групи
    government_listed_activity: bool  # вид діяльності з переліку КМУ


class PublisherKind(Enum):
    """Ст.14(3). Категорія оприлюднювача за строком."""

    PUBLIC_INTEREST_NON_LARGE_ISSUER = "PublicInterestNonLargeIssuer"  # до 30 квітня
    LARGE_NON_ISSUER_OR_MEDIUM = "LargeNonIssuerOrMedium"  # до 1 червня


def _meets_at_least_two(
    metrics: SizeMetrics, assets_cap: float, revenue_cap: float, employees_cap: int
) -> bool:
    """Чи відповідають показники щонайменше двом із трьох порогів (включно)."""
    count = (
        (1 if metrics.balance_assets_eur <= assets_cap else 0)
        + (1 if metrics.net_revenue_eur <= revenue_cap else 0)
        + (1 if metrics.avg_employees <= employees_cap else 0)
    )
    return count >= 2


# --- Ст.2(2). Категорія підприємства ---
def enterprise_size(metrics: SizeMetrics) -> EnterpriseSize:
    """Ст.2(2). Належність за 2-з-3 критеріїв: мікро 350k/700k/10; мале 4M/8M/50;
    середнє 20M/40M/250; інакше велике."""
    if _meets_at_least_two(metrics, 350_000.0, 700_000.0, 10):
        return EnterpriseSize.MICRO
    if _meets_at_least_two(metrics, 4_000_000.0, 8_000_000.0, 50):
        return EnterpriseSize.SMALL
    if _meets_at_least_two(metrics, 20_000_000.0, 40_000_000.0, 250):
        return EnterpriseSize.MEDIUM
    return EnterpriseSize.LARGE


# --- Ст.12(1). Категорія групи ---
def group_size(metrics: SizeMetrics) -> GroupSize:
    """Ст.12(1). Належність за 2-з-3 критеріїв: мала 4M/8M/50; середня
    20M/40M/250; інакше велика."""
    if _meets_at_least_two(metrics, 4_000_000.0, 8_000_000.0, 50):
        return GroupSize.SMALL_GROUP
    if _meets_at_least_two(metrics, 20_000_000.0, 40_000_000.0, 250):
        return GroupSize.MEDIUM_GROUP
    return GroupSize.LARGE_GROUP


# --- Ст.8(3). Строк зберігання ---
def retention_sufficient(retention_years: int) -> bool:
    """Ст.8(3). Збереження документів/регістрів/звітності не менше трьох років."""
    return retention_years >= 3


# --- Ст.9(2). Обовʼязкові реквізити первинного документа ---
def primary_doc_valid(req: PrimaryDocRequisites) -> bool:
    """Ст.9(2). Первинний документ дійсний за наявності всіх обовʼязкових
    реквізитів (паралель до §4.4 ДСТУ 4163:2020)."""
    return (
        req.has_title
        and req.has_date
        and req.has_enterprise_name
        and req.has_operation_content
        and req.has_responsible_persons
        and req.has_signature
    )


# --- Ст.12-1(2). Обовʼязковість МСФЗ ---
def ifrs_mandatory(obligation: IfrsObligation) -> bool:
    """Ст.12-1(2,3). МСФЗ обовʼязкові для ПСІ, ПАТ, видобувних, материнських
    підприємств великих груп та видів діяльності з переліку КМУ; інші —
    визначають доцільність самостійно."""
    return (
        obligation.public_interest_entity
        or obligation.public_joint_stock
        or obligation.extractive_industry
        or obligation.large_group_parent
        or obligation.government_listed_activity
    )


# --- Ст.13. Звітний період ---
def reporting_period_valid(is_newly_created: bool, period_months: int) -> bool:
    """Ст.13(1,2). Звітний період — календарний рік; перший період
    новоствореного підприємства — від 12 до 15 місяців."""
    if is_newly_created:
        return 12 <= period_months <= 15
    return period_months == 12


# --- Ст.14. Строки оприлюднення ---
def publication_deadline_day(publisher: PublisherKind) -> int:
    """Ст.14(3). Граничний день оприлюднення: ПСІ/ПАТ/монополії/видобувні —
    30 квітня (≈120-й день); великі не-емітенти та середні — 1 червня (≈152-й)."""
    return 120 if publisher is PublisherKind.PUBLIC_INTEREST_NON_LARGE_ISSUER else 152


def published_in_time(publisher: PublisherKind, publication_day_of_year: int) -> bool:
    """Ст.14(3). Оприлюднення не пізніше граничного дня."""
    return publication_day_of_year <= publication_deadline_day(publisher)


def web_retention_sufficient(web_retention_years: int) -> bool:
    """Ст.14(7). Оприлюднена річна звітність зберігається на вебсайті не менше
    шести років."""
    return web_retention_years >= 6

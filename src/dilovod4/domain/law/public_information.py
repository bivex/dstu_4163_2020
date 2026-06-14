"""Обчислювані норми Закону № 2939-VI «Про доступ до публічної інформації» —
перенесені з public_information_2939.catala_en.

Чисті функції/перевірки над доменними даними, БЕЗ IO. Кожна функція відповідає
одному Catala-scope; статті закону збережено у docstring.

Стик: трискладовий тест ст.6(2) — канонічна форма тесту обмеження, на який
посилається ст.21 Закону 2657-XII (information.py), та гриф «для службового
користування» (ст.9 ↔ реквізит 15 ДСТУ 4163:2020). Доступ до персональних
даних стикується із Законом 2297-VI (personal_data.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AccessRegime(Enum):
    """Ст.1(2). Режим доступу до публічної інформації."""

    OPEN = "Open"
    RESTRICTED = "Restricted"


class RestrictedKind(Enum):
    """Ст.6(1). Види інформації з обмеженим доступом."""

    CONFIDENTIAL = "Confidential"  # ст.7 — конфіденційна
    SECRET = "Secret"  # ст.8 — таємна
    OFFICIAL = "Official"  # ст.9 — службова
    NOT_RESTRICTED = "NotRestricted"


class NonRestrictableTopic(Enum):
    """Ст.6(5,6,7). Відомості, доступ до яких НЕ може бути обмежено."""

    BUDGET_USE_PROCUREMENT = "BudgetUseProcurement"  # ч.5 — бюджет, закупівлі, майно
    TAX_DEBT = "TaxDebt"  # ч.5 — податковий борг фізосіб
    OFFICIAL_DECLARATION = "OfficialDeclaration"  # ч.6 — декларації
    PUBLIC_OFFICIAL_REMUNERATION = "PublicOfficialRemuneration"  # ч.7 — оплата праці
    OTHER_TOPIC = "OtherTopic"  # інші теми (можуть обмежуватися за тестом ч.2)


class RequestUrgency(Enum):
    """Ст.20. Характер запиту, що визначає строк відповіді."""

    LIFE_SAFETY_ENVIRONMENT = "LifeSafetyEnvironment"  # 48 годин
    ORDINARY = "Ordinary"  # 5 робочих днів


class Requestor(Enum):
    """Ст.21. Хто отримує інформацію (для визначення плати)."""

    OWN_DATA_OR_PUBLIC_INTEREST = "OwnDataOrPublicInterest"  # безоплатно
    GENERAL = "General"  # звичайний запитувач


class RefusalGround(Enum):
    """Ст.22(1). Вичерпні підстави відмови у задоволенні запиту."""

    NOT_HELD_NOT_OBLIGED = "NotHeldNotObliged"  # 1) не володіє і не зобовʼязаний
    RESTRICTED_INFORMATION = "RestrictedInformation"  # 2) обмежений доступ (ч.2 ст.6)
    COPYING_COST_NOT_PAID = "CopyingCostNotPaid"  # 3) не оплачено копіювання
    REQUEST_REQUIREMENTS_NOT_MET = "RequestRequirementsNotMet"  # 4) вимоги до запиту
    NO_GROUND = "NoGround"  # підстав для відмови немає


@dataclass(frozen=True)
class ThreePartTest:
    """Ст.6(2). Сукупність вимог для правомірного обмеження доступу."""

    legitimate_interest: bool  # п.1 — нацбезпека/порядок/права тощо
    substantial_harm: bool  # п.2 — істотна шкода цим інтересам
    harm_outweighs_public_interest: bool  # п.3 — шкода > суспільний інтерес


# --- Ст.1. Режим публічної інформації ---
def public_info_regime(restricted_by_law: bool) -> AccessRegime:
    """Ст.1(2). Публічна інформація відкрита, крім випадків, встановлених законом."""
    return AccessRegime.RESTRICTED if restricted_by_law else AccessRegime.OPEN


# --- Ст.6(5,6,7). Перелік відомостей, що не підлягають обмеженню ---
def topic_may_be_restricted(topic: NonRestrictableTopic) -> bool:
    """Ст.6(5,6,7). Перелічені теми (бюджет, податковий борг, декларації, оплата
    праці керівників) не можуть обмежуватися за жодних умов."""
    return topic is NonRestrictableTopic.OTHER_TOPIC


# --- Ст.6(2). Трискладовий тест правомірності обмеження ---
def restriction_lawful(topic: NonRestrictableTopic, test: ThreePartTest) -> bool:
    """Ст.6(2). Обмеження правомірне, якщо тема дозволяє обмеження І витримано
    сукупність трьох вимог: легітимний інтерес, істотна шкода, перевага шкоди
    над суспільним інтересом."""
    return (
        topic_may_be_restricted(topic)
        and test.legitimate_interest
        and test.substantial_harm
        and test.harm_outweighs_public_interest
    )


# --- Ст.15. Строки оприлюднення ---
def publication_timely(
    is_draft_act: bool,
    working_days_since_approval: int = 0,
    working_days_before_review: int = 0,
) -> bool:
    """Ст.15(2,4). Затверджений документ оприлюднюється ≤5 робочих днів після
    затвердження; проект акта — не менш як за 10 робочих днів до розгляду."""
    if is_draft_act:
        return working_days_before_review >= 10
    return working_days_since_approval <= 5


# --- Ст.20. Строки розгляду запиту ---
def response_deadline_hours(urgency: RequestUrgency) -> int:
    """Ст.20(2). Для запитів щодо життя/свободи/довкілля/НС — 48 годин; для
    звичайних строк вимірюється у робочих днях (повертає 0)."""
    return 48 if urgency is RequestUrgency.LIFE_SAFETY_ENVIRONMENT else 0


def response_deadline_working_days(
    urgency: RequestUrgency, extended_for_volume: bool = False
) -> int:
    """Ст.20(1,4). Звичайний запит — 5 робочих днів, за великого обсягу — до 20;
    для термінових строк вимірюється у годинах (повертає 0)."""
    if urgency is RequestUrgency.LIFE_SAFETY_ENVIRONMENT:
        return 0
    return 20 if extended_for_volume else 5


# --- Ст.21. Плата за надання інформації ---
def reimbursement_required(requestor: Requestor, pages: int) -> bool:
    """Ст.21(1,2,4). Інформація безкоштовна; за копіювання понад 10 сторінок —
    відшкодування фактичних витрат; інформація про себе/суспільно необхідна —
    без плати за копіювання."""
    if requestor is Requestor.OWN_DATA_OR_PUBLIC_INTEREST:
        return False
    return pages > 10


# --- Ст.22. Відмова в задоволенні запиту ---
def refusal_lawful(ground: RefusalGround) -> bool:
    """Ст.22(1,2). Відмова правомірна лише з однієї з чотирьох вичерпних підстав;
    NO_GROUND означає неправомірну відмову."""
    return ground is not RefusalGround.NO_GROUND

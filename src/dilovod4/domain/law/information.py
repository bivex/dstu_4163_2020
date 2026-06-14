"""Обчислювані норми Закону № 2657-XII «Про інформацію» — перенесені з
information_law_2657.catala_en.

Чисті функції/перевірки над доменними даними, БЕЗ IO. Кожна функція відповідає
одному Catala-scope; статті закону збережено у docstring.

Стик: режим інформації з обмеженим доступом (ст.21) живить обіг е-документів з
такою інформацією (ст.15 Закону 851-IV) та гриф обмеження доступу (реквізит 15
ДСТУ 4163:2020). Тут — лише класифікація доступу та тести правомірності.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AccessRegime(Enum):
    """Ст.20. Режим доступу до інформації."""

    OPEN = "Open"  # відкрита
    RESTRICTED = "Restricted"  # з обмеженим доступом


class RestrictedKind(Enum):
    """Ст.21(1). Види інформації з обмеженим доступом."""

    CONFIDENTIAL = "Confidential"  # конфіденційна (ч.2)
    SECRET = "Secret"  # таємна (ч.3)
    OFFICIAL = "Official"  # службова (ч.3)
    NOT_RESTRICTED = "NotRestricted"  # не належить до обмеженого доступу


class UndisclosableTopic(Enum):
    """Ст.21(4). Відомості, що НЕ можуть бути віднесені до обмеженого доступу."""

    ENVIRONMENT_FOOD_QUALITY = "EnvironmentFoodQuality"  # 1) довкілля, якість продуктів
    EMERGENCIES_DISASTERS = "EmergenciesDisasters"  # 2) аварії, катастрофи, НС
    PUBLIC_HEALTH_LIVING = "PublicHealthLiving"  # 3) здоровʼя, правопорядок, освіта
    HUMAN_RIGHTS_VIOLATIONS = "HumanRightsViolations"  # 4) порушення прав людини
    OTHER_TOPIC = "OtherTopic"  # інші теми (можуть обмежуватися за законом)


class StatementKind(Enum):
    """Ст.30. Характер висловлювання."""

    VALUE_JUDGMENT = "ValueJudgment"  # оціночне судження
    DEFAMATION = "Defamation"  # наклеп (виняток ч.2)
    FACTUAL_STATEMENT = "FactualStatement"  # фактичні дані


@dataclass(frozen=True)
class RestrictionTest:
    """Ст.6(2) ↔ ст.21(2). Трискладовий тест правомірності обмеження доступу."""

    restriction_provided_by_law: bool  # обмежено в інтересах, визначених законом
    legitimate_aim: bool  # заради легітимної мети
    harm_outweighs_public_interest: bool  # шкода переважає суспільний інтерес


@dataclass(frozen=True)
class PublicInterestTest:
    """Ст.29. Тест суспільної необхідності інформації."""

    is_subject_of_public_interest: bool
    public_right_to_know_outweighs_harm: bool


# --- Ст.20. Доступ до інформації ---
def access_regime(restricted_by_law: bool) -> AccessRegime:
    """Ст.20(2). Будь-яка інформація відкрита, крім віднесеної законом до
    інформації з обмеженим доступом."""
    return AccessRegime.RESTRICTED if restricted_by_law else AccessRegime.OPEN


# --- Ст.21(4). Перелік відомостей, що не підлягають обмеженню ---
def topic_may_be_restricted(topic: UndisclosableTopic) -> bool:
    """Ст.21(4). Вичерпний перелік тем, що НЕ можуть обмежуватися за жодних умов."""
    return topic is UndisclosableTopic.OTHER_TOPIC


# --- Ст.21(2) ↔ ст.6(2). Правомірність обмеження доступу ---
def restriction_lawful(topic: UndisclosableTopic, test: RestrictionTest) -> bool:
    """Обмеження правомірне, якщо тема дозволяє обмеження І витримано трискладовий
    тест: обмежено законом, заради легітимної мети, шкода переважає суспільний
    інтерес (ст.6(2))."""
    return (
        topic_may_be_restricted(topic)
        and test.restriction_provided_by_law
        and test.legitimate_aim
        and test.harm_outweighs_public_interest
    )


# --- Ст.29. Поширення суспільно необхідної інформації ---
def disclosure_permitted(test: PublicInterestTest) -> bool:
    """Ст.29(1). Інформація з обмеженим доступом може бути поширена, якщо вона
    суспільно необхідна: предмет суспільного інтересу і право громадськості знати
    переважає потенційну шкоду."""
    return test.is_subject_of_public_interest and test.public_right_to_know_outweighs_harm


# --- Ст.30. Звільнення від відповідальності ---
def liable_for_statement(statement: StatementKind) -> bool:
    """Ст.30(1,2). Оціночні судження не тягнуть відповідальності (крім наклепу);
    фактичні дані — підлягають доведенню."""
    return statement in (StatementKind.DEFAMATION, StatementKind.FACTUAL_STATEMENT)


def statement_subject_to_refutation(statement: StatementKind) -> bool:
    """Ст.30(2). Оціночні судження не підлягають спростуванню та доведенню
    правдивості; фактичні дані та наклеп — підлягають."""
    return statement is not StatementKind.VALUE_JUDGMENT

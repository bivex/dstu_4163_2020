"""Гриф обмеження доступу (реквізит 15 ДСТУ 4163:2020) — value object.

Стик: реквізит 15 ДСТУ ↔ ст.21 Закону № 2657-XII «Про інформацію». Гриф несе
вид інформації з обмеженим доступом (конфіденційна/таємна/службова), тему
відомостей (для перевірки переліку ч.4 ст.21, що не підлягає обмеженню) та
трискладовий тест правомірності обмеження (ст.6(2) ↔ ст.21(2)).

Чистий value object без IO. Перелічення дублюють domain/law/information, але
імпортуються звідти — єдине джерело істини для норм закону.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import InvariantViolation
from ..law.information import RestrictedKind, RestrictionTest, UndisclosableTopic


@dataclass(frozen=True)
class AccessRestriction:
    """Реквізит 15 — гриф обмеження доступу до документа (ст.21 З-ну 2657-XII).

    kind — вид обмеженого доступу; topic — тема відомостей (для ч.4 ст.21);
    test — трискладовий тест правомірності обмеження. Гриф проставляється лише
    для документів з інформацією з обмеженим доступом; для відкритих — None у
    DocumentContent.access_restriction.
    """

    kind: RestrictedKind
    topic: UndisclosableTopic
    test: RestrictionTest
    marking: str = ""  # текст грифа, напр. «Для службового користування»

    def __post_init__(self) -> None:
        if self.kind is RestrictedKind.NOT_RESTRICTED:
            raise InvariantViolation(
                "гриф обмеження доступу не може мати вид NOT_RESTRICTED"
            )

    @property
    def heading(self) -> str:
        """Текст грифа: явний marking або типовий за видом."""
        if self.marking.strip():
            return self.marking
        return {
            RestrictedKind.CONFIDENTIAL: "Конфіденційно",
            RestrictedKind.SECRET: "Таємно",
            RestrictedKind.OFFICIAL: "Для службового користування",
        }[self.kind]

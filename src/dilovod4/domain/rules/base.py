"""Контракт правила відповідності та типи результатів.

ConformanceRule — порт усередині домену (ISP: вузький інтерфейс, один метод).
Кожне правило відповідає одному параграфу ДСТУ / одному Catala-scope (SRP).
Правила чисті: документ -> RuleResult, без IO та без стану.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from ..model import Document, DocumentContent


class Severity(Enum):
    ERROR = "error"  # порушення норми
    WARNING = "warning"  # зауваження/рекомендація


@dataclass(frozen=True)
class Finding:
    """Конкретна знахідка під час перевірки правила."""

    rule_id: str
    clause: str  # параграф ДСТУ, напр. "§4.4"
    message: str
    severity: Severity = Severity.ERROR


@dataclass(frozen=True)
class RuleResult:
    """Підсумок застосування одного правила."""

    rule_id: str
    clause: str
    conforms: bool
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @staticmethod
    def ok(rule_id: str, clause: str) -> "RuleResult":
        return RuleResult(rule_id=rule_id, clause=clause, conforms=True, findings=())

    @staticmethod
    def fail(rule_id: str, clause: str, findings: list[Finding]) -> "RuleResult":
        return RuleResult(
            rule_id=rule_id, clause=clause, conforms=False, findings=tuple(findings)
        )


@runtime_checkable
class ConformanceRule(Protocol):
    """Порт правила. Нові правила розширюють систему без зміни ядра (OCP).

    Більшість правил перевіряють лише оформлення (Document) і реалізують
    evaluate(document). Правило, якому потрібен ще й вміст (DocumentContent з
    КЕП-відмітками), оголошує атрибут класу `requires_content = True` і має
    сигнатуру evaluate(document, content) — рушій ConformanceChecker передасть
    вміст за цим прапором.
    """

    rule_id: str
    clause: str

    def evaluate(self, document: Document) -> RuleResult:
        """Застосувати правило до документа. Чиста функція, без побічних ефектів."""
        ...


@runtime_checkable
class ContentAwareRule(Protocol):
    """Порт правила, що потребує вмісту документа (DocumentContent).

    Маркерний прапор `requires_content` вмикає диспетчеризацію у
    ConformanceChecker: таким правилам передається ще й DocumentContent.
    """

    rule_id: str
    clause: str
    requires_content: bool

    def evaluate(self, document: Document, content: "DocumentContent") -> RuleResult:
        ...

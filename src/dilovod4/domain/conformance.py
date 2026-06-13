"""Звіт відповідності та доменна служба перевірки.

ConformanceReport — агрегований результат усіх правил (value object).
ConformanceChecker — доменна служба: чиста, застосовує набір правил до документа.
Жодного IO: завантаження правил — обовʼязок use-case через порт RuleSetProvider.
"""

from __future__ import annotations

from dataclasses import dataclass

from .model import Document
from .rules import ConformanceRule, Finding, RuleResult


@dataclass(frozen=True)
class ConformanceReport:
    doc_id: str
    results: tuple[RuleResult, ...]

    @property
    def conforms(self) -> bool:
        return all(r.conforms for r in self.results)

    @property
    def findings(self) -> tuple[Finding, ...]:
        return tuple(f for r in self.results for f in r.findings)

    @property
    def findings_count(self) -> int:
        return len(self.findings)

    def failed_rules(self) -> tuple[RuleResult, ...]:
        return tuple(r for r in self.results if not r.conforms)


class ConformanceChecker:
    """Доменна служба: застосовує правила до документа й збирає звіт."""

    def check(
        self, document: Document, rules: tuple[ConformanceRule, ...]
    ) -> ConformanceReport:
        results = tuple(rule.evaluate(document) for rule in rules)
        return ConformanceReport(doc_id=document.doc_id, results=results)

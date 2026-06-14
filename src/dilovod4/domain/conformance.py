"""Звіт відповідності та доменна служба перевірки.

ConformanceReport — агрегований результат усіх правил (value object).
ConformanceChecker — доменна служба: чиста, застосовує набір правил до документа.
Жодного IO: завантаження правил — обовʼязок use-case через порт RuleSetProvider.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from .model import Document, DocumentContent
from .rules import ConformanceRule, ContentAwareRule, Finding, RuleResult


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
        self,
        document: Document,
        rules: tuple[ConformanceRule | ContentAwareRule, ...],
        content: DocumentContent | None = None,
    ) -> ConformanceReport:
        # Більшість правил перевіряють лише оформлення (Document). Правила, що
        # позначені requires_content=True (напр. ст.7 Закону 851-IV про
        # оригінал е-документа), потребують ще й вмісту з КЕП-відмітками —
        # їм передаємо DocumentContent. Якщо вмісту немає, такі правила
        # пропускаємо (відсутній предмет перевірки).
        results: list[RuleResult] = []
        for rule in rules:
            if getattr(rule, "requires_content", False):
                if content is None:
                    continue
                results.append(cast(ContentAwareRule, rule).evaluate(document, content))
            else:
                results.append(cast(ConformanceRule, rule).evaluate(document))
        return ConformanceReport(doc_id=document.doc_id, results=tuple(results))

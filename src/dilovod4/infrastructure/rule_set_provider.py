"""Адаптер набору правил — реалізація порту RuleSetProvider.

Будує канонічний набір з ALL_RULE_CLASSES, дозволяючи вимкнути окремі правила
за профілем (rule_id). Розширення новим правилом не змінює use-case (OCP).
"""

from __future__ import annotations

from collections.abc import Iterable

from ..domain.rules import ALL_RULE_CLASSES, ConformanceRule


class DefaultRuleSetProvider:
    """Типовий профіль: усі правила ДСТУ 4163:2020 + ст.7 Закону 851-IV, мінус вимкнені."""

    def __init__(self, disabled_rules: Iterable[str] = ()) -> None:
        self._disabled = frozenset(disabled_rules)
        self._rules: tuple[ConformanceRule, ...] = tuple(
            cls() for cls in ALL_RULE_CLASSES if cls.rule_id not in self._disabled
        )

    def rules(self) -> tuple[ConformanceRule, ...]:
        return self._rules

"""§6.8/6.9 — бланки, §5.10 — дата, §5.1/5.10/5.31 — розміри символів.

Catala scopes: BlankRequisites, DateRule, SymbolDimensions.
"""

from __future__ import annotations

from ..model import BlankType, DateStyle, Document
from .base import ConformanceRule, Finding, RuleResult

_PERMITTED_CODES: dict[BlankType, frozenset[int]] = {
    BlankType.GENERAL: frozenset({1, 2, 3, 4, 5, 13}),
    BlankType.LETTER: frozenset({1, 2, 3, 4, 5, 6, 8}),
    BlankType.SPECIFIC_VIEW: frozenset({1, 2, 3, 4, 5, 9, 13}),
}
_SPECIFIC_VIEW_THRESHOLD = 2000

_VALID_DATE_STYLES = (
    DateStyle.DIGITAL,
    DateStyle.REVERSE_DIGITAL,
    DateStyle.VERBAL_NUMERIC,
)


def permitted_codes(blank_type: BlankType) -> frozenset[int]:
    return _PERMITTED_CODES[blank_type]


class BlankRequisitesRule(ConformanceRule):
    rule_id = "BLANK_REQUISITES"
    clause = "§6.8/6.9"

    def evaluate(self, document: Document) -> RuleResult:
        b = document.blank
        findings: list[Finding] = []

        allowed = _PERMITTED_CODES[b.blank_type]
        if b.requisite_code not in allowed:
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"реквізит {b.requisite_code} не дозволено для бланка "
                    f"«{b.blank_type.value}» (дозволені: {sorted(allowed)})",
                )
            )

        # §6.8: бланк конкретного виду виправданий лише за тиражу > 2000/рік.
        if b.blank_type is BlankType.SPECIFIC_VIEW and b.annual_units <= _SPECIFIC_VIEW_THRESHOLD:
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"бланк конкретного виду невиправданий: тираж {b.annual_units} ≤ "
                    f"{_SPECIFIC_VIEW_THRESHOLD}/рік",
                )
            )

        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )


class DateRule(ConformanceRule):
    rule_id = "DATE"
    clause = "§5.10"

    def evaluate(self, document: Document) -> RuleResult:
        d = document.date
        if d.style not in _VALID_DATE_STYLES:
            return RuleResult.fail(
                self.rule_id,
                self.clause,
                [Finding(self.rule_id, self.clause, f"неприпустимий спосіб дати: {d.style.value}")],
            )
        return RuleResult.ok(self.rule_id, self.clause)


class SymbolDimensionsRule(ConformanceRule):
    rule_id = "SYMBOL_DIMENSIONS"
    clause = "§5.1/5.10/5.31"

    def evaluate(self, document: Document) -> RuleResult:
        s = document.symbols
        findings: list[Finding] = []

        if not (s.coat_of_arms_height_mm == 17 and s.coat_of_arms_width_mm == 12):
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"Герб {s.coat_of_arms_height_mm}×{s.coat_of_arms_width_mm} мм, очікувано 17×12",
                )
            )
        if s.emblem_height_mm > 17:
            findings.append(
                Finding(self.rule_id, self.clause, f"емблема {s.emblem_height_mm} мм > 17 мм")
            )
        if s.qr_side_mm != 21:
            findings.append(
                Finding(self.rule_id, self.clause, f"QR-код {s.qr_side_mm} мм, очікувано 21×21")
            )
        if not (s.registration_zone_height_mm == 60 and s.registration_zone_width_mm == 100):
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"зона держреєстрації {s.registration_zone_height_mm}×"
                    f"{s.registration_zone_width_mm} мм, очікувано 60×100",
                )
            )

        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )

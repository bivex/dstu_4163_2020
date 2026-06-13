"""§6.1/6.2/6.5 — формат, поля, допуск розташування (Catala scope DocumentGeometry)."""

from __future__ import annotations

from ..model import Document, PaperFormat
from .base import ConformanceRule, Finding, RuleResult

_STANDARD_FORMATS = (PaperFormat.A4, PaperFormat.A5, PaperFormat.A3)
_MARGINS = {"left": 30, "right": 10, "top": 20, "bottom": 20}
_OFFSET_TOLERANCE_MM = 2


class DocumentGeometryRule(ConformanceRule):
    rule_id = "DOCUMENT_GEOMETRY"
    clause = "§6.1/6.2/6.5"

    def evaluate(self, document: Document) -> RuleResult:
        g = document.geometry
        findings: list[Finding] = []

        if g.paper_format not in _STANDARD_FORMATS:
            findings.append(
                Finding(self.rule_id, self.clause, f"нестандартний формат: {g.paper_format.value}")
            )

        m = g.margins
        for name, expected in _MARGINS.items():
            actual = getattr(m, name)
            if actual != expected:
                findings.append(
                    Finding(
                        self.rule_id,
                        self.clause,
                        f"поле '{name}' = {actual} мм, очікувано {expected} мм",
                    )
                )

        if g.requisite_offset_mm > _OFFSET_TOLERANCE_MM:
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"відхилення розташування {g.requisite_offset_mm} мм > допуск "
                    f"±{_OFFSET_TOLERANCE_MM} мм",
                )
            )

        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )

"""§6.7 — оформлення реквізитів та §7.2/7.6 — типографіка.

Catala scopes: RequisiteFormatting, Typography.
"""

from __future__ import annotations

from ..model import Document, RequisiteAlignment
from .base import ConformanceRule, Finding, RuleResult

_VALID_ALIGNMENTS = (RequisiteAlignment.CENTERED, RequisiteAlignment.FLAG)


class RequisiteFormattingRule(ConformanceRule):
    rule_id = "REQUISITE_FORMATTING"
    clause = "§6.7"

    def evaluate(self, document: Document) -> RuleResult:
        f = document.formatting
        findings: list[Finding] = []

        if f.alignment not in _VALID_ALIGNMENTS:
            findings.append(
                Finding(self.rule_id, self.clause, f"неприпустиме вирівнювання: {f.alignment.value}")
            )
        if f.underlined_or_separated:
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    "не дозволено підкреслювати або відокремлювати реквізити бланка рискою",
                )
            )

        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )


class TypographyRule(ConformanceRule):
    rule_id = "TYPOGRAPHY"
    clause = "§7.2/7.6"

    def evaluate(self, document: Document) -> RuleResult:
        t = document.typography
        findings: list[Finding] = []

        if not t.is_times_new_roman:
            findings.append(Finding(self.rule_id, self.clause, "гарнітура має бути Times New Roman"))
        if not (12 <= t.body_size_pt <= 14):
            findings.append(
                Finding(self.rule_id, self.clause, f"кегль тексту {t.body_size_pt} pt поза 12–14 pt")
            )
        if not (8 <= t.small_size_pt <= 12):
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"кегль довідкових даних {t.small_size_pt} pt поза 8–12 pt",
                )
            )
        if not (14 <= t.doc_type_size_pt <= 16):
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"кегль назви виду {t.doc_type_size_pt} pt поза 14–16 pt",
                )
            )
        if t.multiline_row_chars > 28:
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"довжина рядка реквізиту {t.multiline_row_chars} знаків > 28 (73 мм)",
                )
            )

        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )

"""§7.3 — міжрядковий інтервал, §7.7 — відступи, §7.10 — нумерація сторінок.

Catala scopes: LineSpacing, LeftIndentation, PageNumbering.
"""

from __future__ import annotations

from ..model import Document, PaperFormat
from .base import ConformanceRule, Finding, RuleResult


class LineSpacingRule(ConformanceRule):
    rule_id = "LINE_SPACING"
    clause = "§7.3"

    def evaluate(self, document: Document) -> RuleResult:
        fmt = document.geometry.paper_format
        s = document.line_spacing.body_spacing

        if fmt is PaperFormat.A5:
            conforms = s == 1.0
            expected = "1,0"
        else:  # A4, A3
            conforms = 1.0 <= s <= 1.5
            expected = "1,0–1,5"

        if conforms:
            return RuleResult.ok(self.rule_id, self.clause)
        return RuleResult.fail(
            self.rule_id,
            self.clause,
            [
                Finding(
                    self.rule_id,
                    self.clause,
                    f"інтервал {s} для {fmt.value} поза діапазоном {expected}",
                )
            ],
        )


class LeftIndentationRule(ConformanceRule):
    rule_id = "LEFT_INDENTATION"
    clause = "§7.7"

    _EXPECTED = {
        "paragraph_mm": 10,
        "addressee_mm": 90,
        "approval_mm": 100,
        "restriction_mm": 100,
        "signature_decode_mm": 125,
    }
    _LABELS = {
        "paragraph_mm": "абзац",
        "addressee_mm": "адресат",
        "approval_mm": "гриф затвердження",
        "restriction_mm": "гриф обмеження доступу",
        "signature_decode_mm": "розшифрування підпису",
    }

    def evaluate(self, document: Document) -> RuleResult:
        ind = document.left_indents
        findings: list[Finding] = []
        for field_name, expected in self._EXPECTED.items():
            actual = getattr(ind, field_name)
            if actual != expected:
                findings.append(
                    Finding(
                        self.rule_id,
                        self.clause,
                        f"відступ «{self._LABELS[field_name]}» = {actual} мм, очікувано {expected} мм",
                    )
                )
        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )


class PageNumberingRule(ConformanceRule):
    rule_id = "PAGE_NUMBERING"
    clause = "§7.10"

    def evaluate(self, document: Document) -> RuleResult:
        p = document.page_numbering
        requires_numbering = p.page_count >= 2
        findings: list[Finding] = []

        if p.first_page_numbered:
            findings.append(
                Finding(self.rule_id, self.clause, "першу сторінку не нумерують")
            )
        if requires_numbering and not p.second_page_numbered:
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    "друга та наступні сторінки мають бути пронумеровані",
                )
            )
        if p.uses_word_or_punctuation:
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    "номер без слова «сторінка» та розділових знаків",
                )
            )

        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )

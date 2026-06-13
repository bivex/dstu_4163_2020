"""§7.11 — бік друку за строком зберігання, §5.15 — адресати, §5.21 — додатки.

Catala scopes: PrintSideByRetention, AddresseeRule, AppendixRule.
"""

from __future__ import annotations

from ..model import Document, PrintSide, StorageTerm
from .base import ConformanceRule, Finding, RuleResult

_MAX_ADDRESSEES = 4
_MAX_APPENDICES = 10


def prescribed_print_side(term: StorageTerm) -> PrintSide:
    """§7.11. Приписаний бік друку за строком зберігання."""
    if term is StorageTerm.TEMPORARY:
        return PrintSide.BOTH_SIDES
    return PrintSide.ONE_SIDE  # Permanent, LongTerm


class PrintSideRule(ConformanceRule):
    rule_id = "PRINT_SIDE"
    clause = "§7.11"

    def evaluate(self, document: Document) -> RuleResult:
        term = document.storage_term
        both_allowed = term is StorageTerm.TEMPORARY
        # Перевіряємо лише факт: для постійного/тривалого — обидва боки заборонені.
        # Двигун повертає приписане значення; порушення фіксується, лише якщо
        # документ позначено тегом друку на обох боках за непридатного строку.
        findings: list[Finding] = []
        if "printed_both_sides" in document.tags and not both_allowed:
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"для строку «{term.value}» друк лише на одному боці аркуша",
                )
            )
        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )


class AddresseeRule(ConformanceRule):
    rule_id = "ADDRESSEE"
    clause = "§5.15"

    def evaluate(self, document: Document) -> RuleResult:
        if document.addressee_count > _MAX_ADDRESSEES:
            return RuleResult.fail(
                self.rule_id,
                self.clause,
                [
                    Finding(
                        self.rule_id,
                        self.clause,
                        f"{document.addressee_count} адресатів > {_MAX_ADDRESSEES}: "
                        "потрібен список розсилання, на документі — один адресат",
                    )
                ],
            )
        return RuleResult.ok(self.rule_id, self.clause)


class AppendixRule(ConformanceRule):
    rule_id = "APPENDIX"
    clause = "§5.21"

    def evaluate(self, document: Document) -> RuleResult:
        if document.appendix_count > _MAX_APPENDICES:
            return RuleResult.fail(
                self.rule_id,
                self.clause,
                [
                    Finding(
                        self.rule_id,
                        self.clause,
                        f"{document.appendix_count} додатків > {_MAX_APPENDICES}: потрібен опис",
                    )
                ],
            )
        return RuleResult.ok(self.rule_id, self.clause)

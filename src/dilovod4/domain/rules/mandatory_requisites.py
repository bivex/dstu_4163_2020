"""§4.4 — обовʼязкові реквізити документа (Catala scope MandatoryRequisites)."""

from __future__ import annotations

from ..model import Document
from .base import ConformanceRule, Finding, RuleResult


class MandatoryRequisitesRule(ConformanceRule):
    rule_id = "MANDATORY_REQUISITES"
    clause = "§4.4"

    def evaluate(self, document: Document) -> RuleResult:
        r = document.requisites

        # signature_satisfied: електронний підпис/печатка або паперовий підпис
        signature_satisfied = (
            (r.electronic_signature or r.electronic_seal)
            if document.is_electronic
            else r.paper_signature
        )

        findings: list[Finding] = []

        def miss(present: bool, code: str, label: str) -> None:
            if not present:
                findings.append(
                    Finding(self.rule_id, self.clause, f"відсутній реквізит {code} — {label}")
                )

        miss(r.org_name, "04", "найменування юридичної особи")
        # 09 — назву виду документа не зазначають на листах
        if not document.is_letter:
            miss(r.doc_type, "09", "назва виду документа")
        miss(r.date, "10", "дата документа")
        miss(r.reg_index, "11", "реєстраційний індекс")
        miss(r.title, "19", "заголовок до тексту")
        miss(r.text, "20", "текст документа")
        if not signature_satisfied:
            kind = (
                "електронний підпис або електронна печатка"
                if document.is_electronic
                else "підпис"
            )
            findings.append(
                Finding(self.rule_id, self.clause, f"відсутній реквізит 22 — {kind}")
            )

        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )

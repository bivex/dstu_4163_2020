"""Ст.7 Закону № 851-IV — оригінал електронного документа (ContentAware-правило).

На відміну від решти правил (що перевіряють лише оформлення за Document), це
правило потребує DocumentContent — бо ознака оригіналу спирається на КЕП-відмітки
(реквізит 22, §4.4 ДСТУ ↔ ст.7 Закону 851-IV). Тому має прапор
requires_content=True; рушій ConformanceChecker передасть йому вміст.

Логіка делегується чистій нормі domain/law (is_original): оригінал =
обовʼязкові реквізити + підпис автора + доказувана цілісність. Для е-документа
доказуваність цілісності забезпечує чинний КЕП (ст.12 ↔ Art.24 Закону 2155-VIII).
"""

from __future__ import annotations

from ..law import is_original
from ..model import Document, DocumentContent
from .base import Finding, RuleResult


class ElectronicOriginalRule:
    """Ст.7 Закону 851-IV: чи є електронний документ оригіналом.

    Застосовується лише до е-документів (is_electronic). Паперові документи
    норма ст.7 щодо е-оригіналу не стосується — повертаємо ok без зауважень.
    """

    rule_id = "ELECTRONIC_ORIGINAL"
    clause = "ст.7 З-ну 851-IV"
    requires_content = True

    def evaluate(self, document: Document, content: DocumentContent) -> RuleResult:
        if not document.is_electronic:
            return RuleResult.ok(self.rule_id, self.clause)

        findings: list[Finding] = []

        # обовʼязкові реквізити (§4.4) — наявність підтверджує MandatoryRequisitesRule;
        # тут перевіряємо стик саме е-оригіналу за ст.7.
        has_requisites = (
            document.requisites.org_name
            and document.requisites.date
            and document.requisites.reg_index
            and document.requisites.text
        )

        marks = content.signatures
        has_author_signature = len(marks) >= 1
        # доказувана цілісність: хоча б одна КЕП-відмітка з чинним сертифікатом
        # (ст.12 ↔ Art.24 Закону 2155-VIII)
        integrity_provable = any(m.certificate_valid for m in marks)

        original = is_original(
            has_mandatory_requisites=bool(has_requisites),
            has_author_signature=has_author_signature,
            integrity_provable=integrity_provable,
        )

        if not original:
            if not has_author_signature:
                findings.append(
                    Finding(
                        self.rule_id,
                        self.clause,
                        "е-документ не є оригіналом: відсутній підпис автора (КЕП-відмітка)",
                    )
                )
            elif not integrity_provable:
                findings.append(
                    Finding(
                        self.rule_id,
                        self.clause,
                        "е-документ не є оригіналом: жодна КЕП-відмітка не має чинного "
                        "сертифіката (цілісність недоказувана, ст.12 ↔ Art.24)",
                    )
                )
            if not has_requisites:
                findings.append(
                    Finding(
                        self.rule_id,
                        self.clause,
                        "е-документ не є оригіналом: відсутні обовʼязкові реквізити (§4.4)",
                    )
                )

        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )

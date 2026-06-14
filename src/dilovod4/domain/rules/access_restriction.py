"""Ст.21 Закону № 2657-XII — правомірність грифа обмеження доступу
(ContentAware-правило).

Потребує DocumentContent, бо предмет перевірки — гриф обмеження доступу
(реквізит 15), що живе у вмісті, а не в параметрах оформлення Document. Прапор
requires_content=True вмикає диспетчеризацію вмісту у ConformanceChecker.

Логіка делегується чистим нормам domain/law/information:
  • тема грифа не має належати до переліку ч.4 ст.21 (відомості, що НЕ можуть
    бути обмежені — довкілля, НС, стан здоровʼя, порушення прав людини);
  • має бути витриманий трискладовий тест правомірності (ст.6(2) ↔ ст.21(2)).
"""

from __future__ import annotations

from ..law.information import restriction_lawful, topic_may_be_restricted
from ..model import Document, DocumentContent
from .base import Finding, RuleResult


class AccessRestrictionRule:
    """Ст.21 Закону 2657-XII: правомірність обмеження доступу до документа.

    Застосовується лише за наявності грифа обмеження доступу (реквізит 15).
    Для відкритих документів (гриф відсутній) — ok без зауважень.
    """

    rule_id = "ACCESS_RESTRICTION"
    clause = "ст.21 З-ну 2657-XII"
    requires_content = True

    def evaluate(self, document: Document, content: DocumentContent) -> RuleResult:
        restriction = content.access_restriction
        if restriction is None:
            # відкритий документ — ст.21 щодо обмеження не застосовується
            return RuleResult.ok(self.rule_id, self.clause)

        findings: list[Finding] = []

        # ч.4 ст.21: тема не повинна належати до переліку, що не підлягає обмеженню
        if not topic_may_be_restricted(restriction.topic):
            findings.append(
                Finding(
                    self.rule_id,
                    self.clause,
                    f"тема «{restriction.topic.value}» не може бути віднесена до "
                    "інформації з обмеженим доступом (ч.4 ст.21)",
                )
            )

        # ст.6(2) ↔ ст.21(2): трискладовий тест правомірності
        if not restriction_lawful(restriction.topic, restriction.test):
            t = restriction.test
            if topic_may_be_restricted(restriction.topic):
                # тема дозволяє, отже причина — провал тесту; вкажемо конкретику
                if not t.restriction_provided_by_law:
                    findings.append(
                        Finding(
                            self.rule_id,
                            self.clause,
                            "обмеження не передбачене законом (трискладовий тест, ст.6(2))",
                        )
                    )
                if not t.legitimate_aim:
                    findings.append(
                        Finding(
                            self.rule_id,
                            self.clause,
                            "відсутня легітимна мета обмеження (трискладовий тест, ст.6(2))",
                        )
                    )
                if not t.harm_outweighs_public_interest:
                    findings.append(
                        Finding(
                            self.rule_id,
                            self.clause,
                            "шкода від поширення не переважає суспільний інтерес "
                            "(трискладовий тест, ст.6(2))",
                        )
                    )

        return (
            RuleResult.ok(self.rule_id, self.clause)
            if not findings
            else RuleResult.fail(self.rule_id, self.clause, findings)
        )

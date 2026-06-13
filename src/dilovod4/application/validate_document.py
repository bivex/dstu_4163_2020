"""Use-case: перевірка документа на відповідність ДСТУ 4163:2020.

Оркеструє домен: бере правила з порту RuleSetProvider, застосовує доменну
службу ConformanceChecker, мапить доменний звіт у DTO. Залежності — через
конструктор (DIP). Жодного прямого IO, БД чи мережі тут немає.
"""

from __future__ import annotations

import logging
from typing import Callable

from ..domain.conformance import ConformanceChecker, ConformanceReport
from ..domain.events import DocumentValidated
from ..domain.model import Document
from ..domain.ports import RuleSetProvider
from .dto import ConformanceReportDTO, FindingDTO, RuleResultDTO

logger = logging.getLogger("dilovod4.application")


def _to_dto(report: ConformanceReport) -> ConformanceReportDTO:
    results = tuple(
        RuleResultDTO(
            rule_id=r.rule_id,
            clause=r.clause,
            conforms=r.conforms,
            findings=tuple(
                FindingDTO(f.rule_id, f.clause, f.message, f.severity.value) for f in r.findings
            ),
        )
        for r in report.results
    )
    return ConformanceReportDTO(
        doc_id=report.doc_id,
        conforms=report.conforms,
        findings_count=report.findings_count,
        results=results,
    )


class ValidateDocument:
    """Застосунковий сервіс перевірки документа."""

    def __init__(
        self,
        rule_set: RuleSetProvider,
        checker: ConformanceChecker | None = None,
        event_publisher: Callable[[DocumentValidated], None] | None = None,
    ) -> None:
        self._rule_set = rule_set
        self._checker = checker or ConformanceChecker()
        self._publish = event_publisher

    def execute(self, document: Document) -> ConformanceReportDTO:
        rules = self._rule_set.rules()
        logger.info(
            "validate_document.start", extra={"doc_id": document.doc_id, "rule_count": len(rules)}
        )
        report = self._checker.check(document, rules)
        logger.info(
            "validate_document.done",
            extra={
                "doc_id": document.doc_id,
                "conforms": report.conforms,
                "findings": report.findings_count,
            },
        )
        if self._publish is not None:
            self._publish(
                DocumentValidated(
                    doc_id=document.doc_id,
                    conforms=report.conforms,
                    findings_count=report.findings_count,
                )
            )
        return _to_dto(report)

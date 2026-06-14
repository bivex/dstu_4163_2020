"""Use-case: згенерувати документ у файл за параметрами оформлення ДСТУ 4163:2020.

Оркеструє: (опційно) перевірити оформлення, потім делегувати запис порту
DocumentWriter. Залежності — через конструктор (DIP). Жодного прямого IO тут:
фактичний запис робить адаптер.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..domain.conformance import ConformanceChecker
from ..domain.model import Document, DocumentContent
from ..domain.ports import DocumentWriter, RuleSetProvider
from .dto import ConformanceReportDTO
from .validate_document import _to_dto

logger = logging.getLogger("dilovod4.application")


@dataclass(frozen=True)
class GenerationResult:
    path: str
    report: ConformanceReportDTO | None


class GenerateDocument:
    """Застосунковий сервіс генерації документа."""

    def __init__(
        self,
        writer: DocumentWriter,
        rule_set: RuleSetProvider | None = None,
        checker: ConformanceChecker | None = None,
    ) -> None:
        self._writer = writer
        self._rule_set = rule_set
        self._checker = checker or ConformanceChecker()

    def execute(
        self, document: Document, content: DocumentContent, destination: str, *, validate: bool = True
    ) -> GenerationResult:
        report_dto: ConformanceReportDTO | None = None
        if validate and self._rule_set is not None:
            report = self._checker.check(document, self._rule_set.rules(), content)
            report_dto = _to_dto(report)
            logger.info(
                "generate_document.validated",
                extra={"doc_id": document.doc_id, "conforms": report.conforms},
            )

        path = self._writer.write(document, content, destination)
        logger.info("generate_document.written", extra={"doc_id": document.doc_id, "path": path})
        return GenerationResult(path=path, report=report_dto)

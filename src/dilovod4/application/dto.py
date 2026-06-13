"""DTO застосунку.

Прості структури для передачі даних через межу застосунку. Доменні сутності
НЕ протікають у presentation/infrastructure — назовні віддаємо лише DTO.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FindingDTO:
    rule_id: str
    clause: str
    message: str
    severity: str


@dataclass(frozen=True)
class RuleResultDTO:
    rule_id: str
    clause: str
    conforms: bool
    findings: tuple[FindingDTO, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ConformanceReportDTO:
    """Вихідний DTO use-case ValidateDocument."""

    doc_id: str
    conforms: bool
    findings_count: int
    results: tuple[RuleResultDTO, ...]

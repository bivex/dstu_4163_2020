"""Доменні події."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class DomainEvent:
    occurred_at: datetime = field(default_factory=_now)


@dataclass(frozen=True)
class DocumentValidated(DomainEvent):
    """Документ перевірено на відповідність ДСТУ 4163:2020."""

    doc_id: str = ""
    conforms: bool = False
    findings_count: int = 0

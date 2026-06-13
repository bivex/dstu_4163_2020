"""Доменний шар ДСТУ 4163:2020 — чистий, без зовнішніх залежностей."""

from .errors import DomainError, InvariantViolation
from .events import DocumentValidated, DomainEvent
from .ports import DocumentRepository, DocumentWriter, RuleSetProvider

__all__ = [
    "DomainError",
    "InvariantViolation",
    "DocumentValidated",
    "DomainEvent",
    "DocumentRepository",
    "DocumentWriter",
    "RuleSetProvider",
]

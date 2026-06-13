"""Інфраструктурний шар: адаптери, що реалізують доменні порти."""

from .config import AppConfig
from .document_mapper import MappingError, document_from_dict
from .docx_writer import DocxDocumentWriter
from .repository import InMemoryDocumentRepository
from .rule_set_provider import DefaultRuleSetProvider

__all__ = [
    "AppConfig",
    "MappingError",
    "document_from_dict",
    "DocxDocumentWriter",
    "InMemoryDocumentRepository",
    "DefaultRuleSetProvider",
]

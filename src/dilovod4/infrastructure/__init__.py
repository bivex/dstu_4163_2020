"""Інфраструктурний шар: адаптери, що реалізують доменні порти."""

from .config import AppConfig
from .document_mapper import MappingError, document_from_dict
from .docx_writer import DocxDocumentWriter
from .fonts import FontNotFoundError, FontPaths, resolve_times_new_roman
from .pdf_writer import PdfDocumentWriter
from .repository import InMemoryDocumentRepository
from .rule_set_provider import DefaultRuleSetProvider
from .uapki import (
    SignResult,
    UapkiClient,
    UapkiError,
    UapkiLibraryNotFound,
    sign_file_pkcs12,
)

__all__ = [
    "AppConfig",
    "MappingError",
    "document_from_dict",
    "DocxDocumentWriter",
    "PdfDocumentWriter",
    "FontPaths",
    "FontNotFoundError",
    "resolve_times_new_roman",
    "InMemoryDocumentRepository",
    "DefaultRuleSetProvider",
    "UapkiClient",
    "UapkiError",
    "UapkiLibraryNotFound",
    "SignResult",
    "sign_file_pkcs12",
]

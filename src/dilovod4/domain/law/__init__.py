"""Обчислювані норми Закону № 851-IV «Про електронні документи та електронний
документообіг» (перенесені з electronic_documents_851.catala_en)."""

from .electronic_documents import (
    DocumentClass,
    SignatureKind,
    StorageState,
    creation_completed,
    electronic_original_permitted,
    integrity_verifiable,
    is_original,
    storage_admissible,
    storage_term_sufficient,
)

__all__ = [
    "DocumentClass",
    "SignatureKind",
    "StorageState",
    "creation_completed",
    "electronic_original_permitted",
    "integrity_verifiable",
    "is_original",
    "storage_admissible",
    "storage_term_sufficient",
]

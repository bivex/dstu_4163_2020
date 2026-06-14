"""Обчислювані норми законів України (перенесені з .catala_en специфікацій):
  • № 851-IV «Про електронні документи та електронний документообіг»;
  • № 2657-XII «Про інформацію».
"""

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
from .information import (
    AccessRegime,
    PublicInterestTest,
    RestrictedKind,
    RestrictionTest,
    StatementKind,
    UndisclosableTopic,
    access_regime,
    disclosure_permitted,
    liable_for_statement,
    restriction_lawful,
    statement_subject_to_refutation,
    topic_may_be_restricted,
)

__all__ = [
    # Закон 851-IV
    "DocumentClass",
    "SignatureKind",
    "StorageState",
    "creation_completed",
    "electronic_original_permitted",
    "integrity_verifiable",
    "is_original",
    "storage_admissible",
    "storage_term_sufficient",
    # Закон 2657-XII
    "AccessRegime",
    "PublicInterestTest",
    "RestrictedKind",
    "RestrictionTest",
    "StatementKind",
    "UndisclosableTopic",
    "access_regime",
    "disclosure_permitted",
    "liable_for_statement",
    "restriction_lawful",
    "statement_subject_to_refutation",
    "topic_may_be_restricted",
]

"""Тести обчислюваних норм Закону № 851-IV (domain/law/electronic_documents).

Дзеркалять scope'и electronic_documents_851.catala_en: кожен тест відповідає
статті закону.
"""

from __future__ import annotations

import pytest

from dilovod4.domain.errors import InvariantViolation
from dilovod4.domain.law import (
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


# --- Ст.6 ---
def test_creation_completed_single_signature():
    assert creation_completed(signatures_applied=1, seals_applied=0) is True


def test_creation_completed_seal_only():
    assert creation_completed(signatures_applied=0, seals_applied=1) is True


def test_creation_not_completed_without_any():
    assert creation_completed(signatures_applied=0, seals_applied=0) is False


def test_creation_requires_all_signers():
    assert creation_completed(signatures_applied=1, seals_applied=0, required_signers=2) is False
    assert creation_completed(signatures_applied=2, seals_applied=0, required_signers=2) is True


def test_creation_negative_signers_rejected():
    with pytest.raises(InvariantViolation):
        creation_completed(1, 0, required_signers=-1)


# --- Ст.7 ---
def test_is_original_all_present():
    assert is_original(True, True, True) is True


@pytest.mark.parametrize(
    "req,sig,integ",
    [(False, True, True), (True, False, True), (True, True, False)],
)
def test_is_original_missing_component(req, sig, integ):
    assert is_original(req, sig, integ) is False


# --- Ст.8 ---
def test_ordinary_document_permitted_as_e_original():
    assert electronic_original_permitted(DocumentClass.ORDINARY) is True


def test_inheritance_certificate_forbidden():
    assert electronic_original_permitted(DocumentClass.INHERITANCE_CERTIFICATE) is False


def test_single_original_needs_centralized_repository():
    assert electronic_original_permitted(DocumentClass.SINGLE_ORIGINAL_ONLY) is False
    assert (
        electronic_original_permitted(
            DocumentClass.SINGLE_ORIGINAL_ONLY, centralized_repository_exists=True
        )
        is True
    )


def test_other_law_forbidden():
    assert electronic_original_permitted(DocumentClass.OTHER_LAW_FORBIDDEN) is False


# --- Ст.12 ---
@pytest.mark.parametrize("kind", [SignatureKind.QUALIFIED, SignatureKind.ADVANCED])
def test_integrity_verifiable_qualified_or_advanced(kind):
    assert integrity_verifiable(kind) is True


def test_integrity_other_kind_needs_protection_means():
    assert integrity_verifiable(SignatureKind.OTHER) is False
    assert integrity_verifiable(SignatureKind.OTHER, other_protection_means_applied=True) is True


# --- Ст.13 ---
def _state(**over) -> StorageState:
    base = dict(
        e_storage_term_days=3650,
        paper_term_days=3650,
        information_accessible=True,
        format_restorable=True,
        origin_metadata_kept=True,
    )
    base.update(over)
    return StorageState(**base)


def test_storage_term_sufficient():
    assert storage_term_sufficient(_state()) is True
    assert storage_term_sufficient(_state(e_storage_term_days=100)) is False


def test_storage_admissible_all_conditions():
    assert storage_admissible(_state()) is True


@pytest.mark.parametrize(
    "field", ["information_accessible", "format_restorable", "origin_metadata_kept"]
)
def test_storage_inadmissible_when_condition_missing(field):
    assert storage_admissible(_state(**{field: False})) is False


def test_storage_inadmissible_when_term_too_short():
    assert storage_admissible(_state(e_storage_term_days=1)) is False

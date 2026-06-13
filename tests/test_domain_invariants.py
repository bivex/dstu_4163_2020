"""Тести інваріантів домену (структурна валідність, не відповідність нормі)."""

from __future__ import annotations

import pytest

from dilovod4.domain.errors import InvariantViolation
from dilovod4.domain.model import PageMargins

from .builders import conformant_document


def test_empty_doc_id_violates_invariant():
    with pytest.raises(InvariantViolation):
        conformant_document(doc_id="  ")


def test_negative_addressee_violates_invariant():
    with pytest.raises(InvariantViolation):
        conformant_document(addressee_count=-1)


def test_negative_margin_violates_invariant():
    with pytest.raises(InvariantViolation):
        PageMargins(left=-5, right=10, top=20, bottom=20)

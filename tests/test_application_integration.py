"""Інтеграційні тести застосунку та адаптерів (межі системи)."""

from __future__ import annotations

import json
from pathlib import Path

from dilovod4.application.validate_document import ValidateDocument
from dilovod4.domain.events import DocumentValidated
from dilovod4.infrastructure.document_mapper import MappingError, document_from_dict
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider

from .builders import conformant_document

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def test_default_rule_set_has_all_rules():
    # 13 правил ДСТУ 4163:2020 + ст.7 Закону 851-IV + ст.21 Закону 2657-XII
    provider = DefaultRuleSetProvider()
    assert len(provider.rules()) == 15


def test_disabled_rule_excluded():
    provider = DefaultRuleSetProvider(disabled_rules={"LINE_SPACING"})
    ids = {r.rule_id for r in provider.rules()}
    assert "LINE_SPACING" not in ids
    assert len(ids) == 14


def test_validate_conformant_document():
    use_case = ValidateDocument(rule_set=DefaultRuleSetProvider())
    report = use_case.execute(conformant_document())
    assert report.conforms
    assert report.findings_count == 0


def test_use_case_publishes_event():
    events: list[DocumentValidated] = []
    use_case = ValidateDocument(
        rule_set=DefaultRuleSetProvider(), event_publisher=events.append
    )
    use_case.execute(conformant_document())
    assert len(events) == 1
    assert events[0].conforms is True


def test_validate_conformant_sample_file():
    data = json.loads((SAMPLES / "conformant.json").read_text(encoding="utf-8"))
    doc = document_from_dict(data)
    report = ValidateDocument(rule_set=DefaultRuleSetProvider()).execute(doc)
    assert report.conforms, [f.message for f in
                             (fnd for r in report.results for fnd in r.findings)]


def test_validate_non_conformant_sample_file():
    data = json.loads((SAMPLES / "non_conformant.json").read_text(encoding="utf-8"))
    doc = document_from_dict(data)
    report = ValidateDocument(rule_set=DefaultRuleSetProvider()).execute(doc)
    assert not report.conforms
    failed_ids = {r.rule_id for r in report.results if not r.conforms}
    # очікувані порушення з підготовленого файла
    for expected in {
        "MANDATORY_REQUISITES",
        "DOCUMENT_GEOMETRY",
        "REQUISITE_FORMATTING",
        "TYPOGRAPHY",
        "LINE_SPACING",
        "LEFT_INDENTATION",
        "PAGE_NUMBERING",
        "PRINT_SIDE",
        "ADDRESSEE",
        "APPENDIX",
        "BLANK_REQUISITES",
        "SYMBOL_DIMENSIONS",
    }:
        assert expected in failed_ids, expected


def test_mapper_rejects_unknown_enum():
    data = json.loads((SAMPLES / "conformant.json").read_text(encoding="utf-8"))
    data["geometry"]["paper_format"] = "A2"
    try:
        document_from_dict(data)
        assert False, "очікувалась MappingError"
    except MappingError as exc:
        assert "paper_format" in str(exc)


def test_mapper_reports_missing_field():
    try:
        document_from_dict({"doc_id": "X"})
        assert False, "очікувалась MappingError"
    except MappingError as exc:
        assert "requisites" in str(exc)

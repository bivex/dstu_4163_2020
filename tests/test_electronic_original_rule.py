"""Тести правила ст.7 Закону 851-IV (ElectronicOriginalRule) та диспетчеризації
ContentAware-правил у ConformanceChecker.
"""

from __future__ import annotations

from dilovod4.domain.conformance import ConformanceChecker
from dilovod4.domain.model import DocumentContent
from dilovod4.domain.model.enums import CertificateStatus
from dilovod4.domain.model.signature import ElectronicSignatureMark
from dilovod4.domain.rules import ElectronicOriginalRule

from .builders import conformant_document


def _mark(valid: bool = True) -> ElectronicSignatureMark:
    return ElectronicSignatureMark(
        signer="ПЕТРЕНКО Олександр",
        certificate_serial="58E2D9C1",
        issuer="КН ЕДП «Дія»",
        valid_from="01.01.2026",
        valid_to="01.01.2028",
        timestamp="14.06.2026 10:00:00",
        is_qualified=True,
        status=CertificateStatus.ACTIVE if valid else CertificateStatus.CANCELLED,
    )


def _content(**over) -> DocumentContent:
    base = dict(
        org_name="ТОВ «ТЕСТ»",
        doc_type="Наказ",
        date_text="14.06.2026",
        reg_index="01",
        title="Заголовок",
        body=("Текст.",),
        signature_position="Директор",
        signature_name="І. ТЕСТ",
    )
    base.update(over)
    return DocumentContent(**base)


def test_electronic_original_valid_mark_conforms():
    rule = ElectronicOriginalRule()
    doc = conformant_document(is_electronic=True)
    content = _content(e_signature=_mark(valid=True))
    result = rule.evaluate(doc, content)
    assert result.conforms


def test_electronic_original_no_signature_fails():
    rule = ElectronicOriginalRule()
    doc = conformant_document(is_electronic=True)
    content = _content()  # без КЕП-відмітки
    result = rule.evaluate(doc, content)
    assert not result.conforms
    assert any("підпис автора" in f.message for f in result.findings)


def test_electronic_original_invalid_certificate_fails():
    rule = ElectronicOriginalRule()
    doc = conformant_document(is_electronic=True)
    content = _content(e_signature=_mark(valid=False))
    result = rule.evaluate(doc, content)
    assert not result.conforms
    assert any("цілісність" in f.message for f in result.findings)


def test_paper_document_not_subject_to_rule():
    rule = ElectronicOriginalRule()
    doc = conformant_document(is_electronic=False)
    content = _content()
    result = rule.evaluate(doc, content)
    assert result.conforms  # ст.7 щодо е-оригіналу не стосується паперового


def test_rule_marked_requires_content():
    assert ElectronicOriginalRule.requires_content is True


# --- диспетчеризація у рушії ---
def test_checker_skips_content_rule_without_content():
    """Без DocumentContent ContentAware-правило пропускається (немає предмета)."""
    checker = ConformanceChecker()
    doc = conformant_document(is_electronic=True)
    report = checker.check(doc, (ElectronicOriginalRule(),))
    # правило пропущено → у звіті немає його результату
    assert all(r.rule_id != "ELECTRONIC_ORIGINAL" for r in report.results)
    assert report.conforms  # порожній звіт конформний


def test_checker_runs_content_rule_with_content():
    checker = ConformanceChecker()
    doc = conformant_document(is_electronic=True)
    content = _content(e_signature=_mark(valid=True))
    report = checker.check(doc, (ElectronicOriginalRule(),), content)
    assert any(r.rule_id == "ELECTRONIC_ORIGINAL" for r in report.results)
    assert report.conforms


def test_checker_mixed_rules_dispatch():
    """Звичайні та ContentAware-правила працюють разом."""
    from dilovod4.domain.rules import MandatoryRequisitesRule

    checker = ConformanceChecker()
    doc = conformant_document(is_electronic=True)
    content = _content(e_signature=_mark(valid=True))
    report = checker.check(
        doc, (MandatoryRequisitesRule(), ElectronicOriginalRule()), content
    )
    ids = {r.rule_id for r in report.results}
    assert "MANDATORY_REQUISITES" in ids
    assert "ELECTRONIC_ORIGINAL" in ids

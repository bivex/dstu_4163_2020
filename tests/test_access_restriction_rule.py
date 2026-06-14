"""Тести правила ст.21 Закону 2657-XII (AccessRestrictionRule).

Перевіряють правомірність грифа обмеження доступу (реквізит 15): перелік ч.4
та трискладовий тест. Дзеркалять norму domain/law/information.
"""

from __future__ import annotations

from dilovod4.domain.conformance import ConformanceChecker
from dilovod4.domain.law import RestrictedKind, RestrictionTest, UndisclosableTopic
from dilovod4.domain.model import AccessRestriction, DocumentContent
from dilovod4.domain.rules import AccessRestrictionRule

from .builders import conformant_document


def _content(restriction: AccessRestriction | None = None) -> DocumentContent:
    return DocumentContent(
        org_name="ТОВ «ТЕСТ»",
        doc_type="Наказ",
        date_text="14.06.2026",
        reg_index="01",
        title="Заголовок",
        body=("Текст.",),
        signature_position="Директор",
        signature_name="І. ТЕСТ",
        access_restriction=restriction,
    )


def _full_test() -> RestrictionTest:
    return RestrictionTest(
        restriction_provided_by_law=True,
        legitimate_aim=True,
        harm_outweighs_public_interest=True,
    )


def test_open_document_conforms():
    rule = AccessRestrictionRule()
    result = rule.evaluate(conformant_document(), _content(restriction=None))
    assert result.conforms


def test_lawful_restriction_conforms():
    rule = AccessRestrictionRule()
    restriction = AccessRestriction(
        kind=RestrictedKind.OFFICIAL,
        topic=UndisclosableTopic.OTHER_TOPIC,
        test=_full_test(),
    )
    result = rule.evaluate(conformant_document(), _content(restriction))
    assert result.conforms


def test_protected_topic_cannot_be_restricted():
    rule = AccessRestrictionRule()
    restriction = AccessRestriction(
        kind=RestrictedKind.OFFICIAL,
        topic=UndisclosableTopic.HUMAN_RIGHTS_VIOLATIONS,
        test=_full_test(),
    )
    result = rule.evaluate(conformant_document(), _content(restriction))
    assert not result.conforms
    assert any("ч.4 ст.21" in f.message for f in result.findings)


def test_failed_three_part_test_reported():
    rule = AccessRestrictionRule()
    restriction = AccessRestriction(
        kind=RestrictedKind.CONFIDENTIAL,
        topic=UndisclosableTopic.OTHER_TOPIC,
        test=RestrictionTest(
            restriction_provided_by_law=False,
            legitimate_aim=True,
            harm_outweighs_public_interest=False,
        ),
    )
    result = rule.evaluate(conformant_document(), _content(restriction))
    assert not result.conforms
    msgs = " ".join(f.message for f in result.findings)
    assert "не передбачене законом" in msgs
    assert "суспільний інтерес" in msgs


def test_rule_marked_requires_content():
    assert AccessRestrictionRule.requires_content is True


def test_checker_dispatches_with_content():
    checker = ConformanceChecker()
    restriction = AccessRestriction(
        kind=RestrictedKind.OFFICIAL,
        topic=UndisclosableTopic.OTHER_TOPIC,
        test=_full_test(),
    )
    report = checker.check(
        conformant_document(), (AccessRestrictionRule(),), _content(restriction)
    )
    assert any(r.rule_id == "ACCESS_RESTRICTION" for r in report.results)
    assert report.conforms


def test_checker_skips_without_content():
    checker = ConformanceChecker()
    report = checker.check(conformant_document(), (AccessRestrictionRule(),))
    assert all(r.rule_id != "ACCESS_RESTRICTION" for r in report.results)

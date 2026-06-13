"""CLI Dilovod4 — точка входу та композиційний корінь (composition root).

Тут і тільки тут збираються залежності та інʼєктуються в use-case (DIP).
Presentation залежить від application, не від домену напряму для логіки;
доменні типи використовуються лише через мапер на межі.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import Sequence

from ..application.validate_document import ValidateDocument
from ..domain.errors import DomainError
from ..infrastructure.config import AppConfig
from ..infrastructure.document_mapper import MappingError, document_from_dict
from ..infrastructure.rule_set_provider import DefaultRuleSetProvider
from .renderers import render_json, render_text


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format='{"level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
        stream=sys.stderr,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dilovod4",
        description="Перевірка оформлення документа на відповідність ДСТУ 4163:2020.",
    )
    p.add_argument(
        "input",
        nargs="?",
        default="-",
        help="Шлях до JSON-опису документа ('-' або відсутній = stdin).",
    )
    p.add_argument(
        "--format",
        choices=("text", "json"),
        default=None,
        help="Формат виводу (типово з env DILOVOD4_OUTPUT_FORMAT або 'text').",
    )
    return p


def _read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def main(argv: Sequence[str] | None = None) -> int:
    config = AppConfig.from_env()
    _configure_logging(config.log_level)
    args = _build_parser().parse_args(argv)
    output_format = args.format or config.output_format

    try:
        raw = _read_input(args.input)
    except OSError as exc:
        print(f"Помилка читання вводу: {exc}", file=sys.stderr)
        return 2

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"Некоректний JSON: {exc}", file=sys.stderr)
        return 2

    # Композиційний корінь: збираємо граф залежностей.
    rule_set = DefaultRuleSetProvider(disabled_rules=config.disabled_rules)
    use_case = ValidateDocument(rule_set=rule_set)

    try:
        document = document_from_dict(data)
    except MappingError as exc:
        print(f"Помилка вхідних даних: {exc}", file=sys.stderr)
        return 2
    except DomainError as exc:
        print(f"Порушено інваріант документа: {exc}", file=sys.stderr)
        return 2

    report = use_case.execute(document)

    if output_format == "json":
        print(render_json(report))
    else:
        print(render_text(report))

    # Код повернення: 0 — відповідає, 1 — є порушення норми.
    return 0 if report.conforms else 1


if __name__ == "__main__":
    raise SystemExit(main())

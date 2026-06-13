"""Рендеринг звіту відповідності у текст або JSON (presentation)."""

from __future__ import annotations

import json
from dataclasses import asdict

from ..application.dto import ConformanceReportDTO


def render_text(report: ConformanceReportDTO) -> str:
    lines: list[str] = []
    status = "ВІДПОВІДАЄ" if report.conforms else "НЕ ВІДПОВІДАЄ"
    lines.append(f"Документ: {report.doc_id}")
    lines.append(f"Підсумок: {status} ДСТУ 4163:2020")
    lines.append(f"Знахідок: {report.findings_count}")
    lines.append("")
    for r in report.results:
        mark = "OK " if r.conforms else "FAIL"
        lines.append(f"  [{mark}] {r.clause:<14} {r.rule_id}")
        for f in r.findings:
            lines.append(f"         - {f.message}")
    return "\n".join(lines)


def render_json(report: ConformanceReportDTO) -> str:
    return json.dumps(asdict(report), ensure_ascii=False, indent=2)

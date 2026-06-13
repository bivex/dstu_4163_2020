"""Конфігурація застосунку.

Усі налаштування — з оточення (env) із безпечними типовими значеннями.
Жодних секретів чи URL у коді. Домен про конфіг не знає.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppConfig:
    output_format: str = "text"  # text | json
    log_level: str = "INFO"
    # Профіль перевірки: CSV вимкнених rule_id, напр. "LINE_SPACING,SYMBOL_DIMENSIONS"
    disabled_rules: frozenset[str] = frozenset()

    @staticmethod
    def from_env(env: dict[str, str] | None = None) -> "AppConfig":
        e = env if env is not None else dict(os.environ)
        disabled = e.get("DILOVOD4_DISABLED_RULES", "")
        return AppConfig(
            output_format=e.get("DILOVOD4_OUTPUT_FORMAT", "text").lower(),
            log_level=e.get("DILOVOD4_LOG_LEVEL", "INFO").upper(),
            disabled_rules=frozenset(x.strip() for x in disabled.split(",") if x.strip()),
        )

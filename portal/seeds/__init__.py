"""Системні сідери для ініціалізації та оновлення бази даних порталу."""

from __future__ import annotations

from typing import Callable
from sqlalchemy.orm import Session

from portal.seeds.initial_data import (
    seed_default_admin,
    seed_default_counterparties,
    seed_default_journals,
)
from portal.seeds.processes import seed_default_processes
from portal.seeds.templates import seed_default_templates


def run_all_seeds(session_factory: Callable[[], Session]) -> None:
    """Виконати всі вбудовані сідери (ідемпотентно)."""
    seed_default_admin(session_factory)
    seed_default_counterparties(session_factory)
    seed_default_journals(session_factory)
    seed_default_processes(session_factory)
    seed_default_templates(session_factory)

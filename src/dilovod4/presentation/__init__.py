"""Presentation шар: CLI та рендерери."""

from .cli import main
from .renderers import render_json, render_text

__all__ = ["main", "render_json", "render_text"]

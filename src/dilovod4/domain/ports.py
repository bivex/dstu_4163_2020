"""Порти домену (інтерфейси зовнішніх залежностей).

Домен оголошує контракти; інфраструктура їх реалізує (Dependency Inversion).
Жодних імпортів з infrastructure/application тут бути не може.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .model import Document, DocumentContent
from .rules import ConformanceRule


@runtime_checkable
class RuleSetProvider(Protocol):
    """Порт: джерело набору правил для перевірки (профіль)."""

    def rules(self) -> tuple[ConformanceRule, ...]:
        ...


@runtime_checkable
class DocumentRepository(Protocol):
    """Порт: сховище документів. Реалізація — в інфраструктурі."""

    def get(self, doc_id: str) -> Document | None:
        ...

    def save(self, document: Document) -> None:
        ...


@runtime_checkable
class DocumentWriter(Protocol):
    """Порт: відтворення документа у конкретному форматі (.docx, .pdf, ...).

    Адаптер фізично реалізує оформлення згідно з параметрами Document
    (поля, гарнітура, кеглі, інтервал, нумерація) та наповнює його текстом
    з DocumentContent. Домен не знає, у який саме формат і як саме.
    """

    def write(self, document: Document, content: DocumentContent, destination: str) -> str:
        """Записати документ у destination. Повертає фактичний шлях."""
        ...

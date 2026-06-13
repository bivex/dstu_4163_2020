"""In-memory репозиторій документів — реалізація порту DocumentRepository.

Адаптер для тестів і CLI. Реальне сховище (БД/файл) реалізується тим самим
портом без зміни домену чи застосунку.
"""

from __future__ import annotations

from ..domain.model import Document


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._store: dict[str, Document] = {}

    def get(self, doc_id: str) -> Document | None:
        return self._store.get(doc_id)

    def save(self, document: Document) -> None:
        self._store[document.doc_id] = document

"""Текстовий вміст документа (value object).

Document описує ПАРАМЕТРИ оформлення (кеглі, поля, наявність реквізитів).
DocumentContent несе фактичний ТЕКСТ реквізитів для відтворення у .docx.
Розділення дозволяє перевіряти оформлення окремо від наповнення.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import InvariantViolation


@dataclass(frozen=True)
class DocumentContent:
    org_name: str  # 04 — найменування юридичної особи
    doc_type: str  # 09 — назва виду документа (порожньо для листа)
    date_text: str  # 10 — дата документа (оформлена за §5.10)
    reg_index: str  # 11 — реєстраційний індекс
    title: str  # 19 — заголовок до тексту
    body: tuple[str, ...]  # 20 — абзаци тексту документа
    signature_position: str  # посада підписанта
    signature_name: str  # розшифрування підпису (І. ПРІЗВИЩЕ)
    addressees: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.org_name.strip():
            raise InvariantViolation("найменування юридичної особи не може бути порожнім")
        if not self.body:
            raise InvariantViolation("текст документа не може бути порожнім")

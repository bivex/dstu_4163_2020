"""Текстовий вміст документа (value object).

Document описує ПАРАМЕТРИ оформлення (кеглі, поля, наявність реквізитів).
DocumentContent несе фактичний ТЕКСТ реквізитів для відтворення у .docx.
Розділення дозволяє перевіряти оформлення окремо від наповнення.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import InvariantViolation
from .access_restriction import AccessRestriction
from .approval import Agreement, ApprovalGrant, Visa
from .signature import ElectronicSignatureMark


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
    # Контактні дані відправника (для фізосіб/громадян): адреса, телефон, email.
    # Виводяться дрібнішим шрифтом під рядком з org_name (§5.4 ДСТУ 4163).
    sender_contacts: str = ""
    # Робоча позначка документа (напр. «ПРОЕКТ») — праворуч угорі, над реквізитами.
    # Не є реквізитом ДСТУ; службова відмітка стадії підготовки документа.
    marking: str = ""
    # §4.4 реквізит 22 для е-документів: відмітка про КЕП/печатку (Art.18/24).
    # Якщо задано — підпис відтворюється як відмітка по ключу, а не рукописний.
    e_signature: ElectronicSignatureMark | None = None
    # Кілька підписантів (директор + головний бухгалтер тощо): кожен має власну
    # КЕП-відмітку з QR. Якщо порожньо — береться один e_signature (сумісність).
    e_signatures: tuple[ElectronicSignatureMark, ...] = field(default_factory=tuple)
    # §4.4 реквізит 21 — гриф затвердження (ЗАТВЕРДЖУЮ/ЗАТВЕРДЖЕНО), праворуч угорі.
    approval: ApprovalGrant | None = None
    # §4.4 реквізит 23 — грифи погодження (ПОГОДЖЕНО), зовнішнє, нижче підпису.
    agreements: tuple[Agreement, ...] = field(default_factory=tuple)
    # §4.4 реквізит 24 — візи (внутрішнє погодження), нижче підпису/погоджень.
    visas: tuple[Visa, ...] = field(default_factory=tuple)
    # Кілька рукописних підписантів (напр. голова + секретар протоколу). Кожен —
    # пара «посада, розшифрування». Якщо порожньо — береться базова пара
    # signature_position/signature_name (сумісність).
    paper_signatures: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    # Реквізит 15 — гриф обмеження доступу (ст.21 З-ну 2657-XII). None для
    # відкритих документів; задається лише для інформації з обмеженим доступом.
    access_restriction: AccessRestriction | None = None
    # Чи накладати графічну синю печатку організації поверх підпису.
    use_stamp: bool = False
    # Тип графічної печатки ("" - немає, "documents", "contracts", "hr", "chancellery").
    stamp_type: str = ""
    # Службові прямокутні штампи
    use_incoming_stamp: bool = False
    use_copy_stamp: bool = False
    use_control_stamp: bool = False
    restriction_stamp: str = ""


    def __post_init__(self) -> None:
        if not self.org_name.strip():
            raise InvariantViolation("найменування юридичної особи не може бути порожнім")
        if not self.body:
            raise InvariantViolation("текст документа не може бути порожнім")

    @property
    def signatures(self) -> tuple[ElectronicSignatureMark, ...]:
        """Усі КЕП-відмітки: явний перелік e_signatures або один e_signature."""
        if self.e_signatures:
            return self.e_signatures
        if self.e_signature is not None:
            return (self.e_signature,)
        return ()

    @property
    def paper_signers(self) -> tuple[tuple[str, str], ...]:
        """Усі рукописні підписанти: явний перелік або базова пара (сумісність)."""
        if self.paper_signatures:
            return self.paper_signatures
        return ((self.signature_position, self.signature_name),)

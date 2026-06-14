"""Обчислювані норми Закону № 851-IV «Про електронні документи та електронний
документообіг» — перенесені з electronic_documents_851.catala_en.

Чисті функції/перевірки над доменними даними, БЕЗ IO та без залежності від
агрегату Document (це норми про е-документ як такий, не про оформлення ДСТУ).
Кожна функція відповідає одному Catala-scope; назви статей збережено у docstring.

Стик: чинність сертифіката (Art.24/25 Закону 2155-VIII) тут НЕ переобчислюється —
використовується ElectronicSignatureMark.certificate_valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import InvariantViolation


class SignatureKind(Enum):
    """Ст.12. Вид підпису/печатки, що визначає спосіб перевірки цілісності."""

    QUALIFIED = "Qualified"  # кваліфікований
    ADVANCED = "Advanced"  # удосконалений
    OTHER = "Other"  # інший вид


class DocumentClass(Enum):
    """Ст.8(3). Клас документа щодо припустимості електронного оригіналу."""

    INHERITANCE_CERTIFICATE = "InheritanceCertificate"  # п.1 свідоцтво про спадщину
    SINGLE_ORIGINAL_ONLY = "SingleOriginalOnly"  # п.2 лише один примірник
    OTHER_LAW_FORBIDDEN = "OtherLawForbidden"  # п.3 інші випадки за законом
    ORDINARY = "Ordinary"  # звичайний документ


# --- Ст.6. Завершення створення електронного документа ---
def creation_completed(
    signatures_applied: int, seals_applied: int, required_signers: int = 0
) -> bool:
    """Ст.6(3,4). Накладанням підпису/печатки завершується створення; за кількох
    підписантів — накладанням останнім. Якщо кількість підписантів задано
    (required_signers>0) — потрібно зібрати всі; інакше досить одного підпису/печатки.
    """
    if required_signers < 0:
        raise InvariantViolation("кількість підписантів не може бути відʼємною")
    if required_signers > 0:
        return signatures_applied >= required_signers
    return signatures_applied + seals_applied >= 1


# --- Ст.7. Оригінал електронного документа ---
def is_original(
    has_mandatory_requisites: bool,
    has_author_signature: bool,
    integrity_provable: bool,
) -> bool:
    """Ст.7(1,4). Оригінал = обовʼязкові реквізити + підпис автора + доказувана
    цілісність і справжність."""
    return has_mandatory_requisites and has_author_signature and integrity_provable


# --- Ст.8. Припустимість електронного оригіналу ---
def electronic_original_permitted(
    document_class: DocumentClass, centralized_repository_exists: bool = False
) -> bool:
    """Ст.8(3). Вичерпний перелік документів, що НЕ можуть бути е-оригіналом.
    Виняток для «єдиного примірника» — за наявності централізованого сховища.
    """
    if document_class is DocumentClass.ORDINARY:
        return True
    if document_class is DocumentClass.SINGLE_ORIGINAL_ONLY:
        return centralized_repository_exists
    # InheritanceCertificate, OtherLawForbidden
    return False


# --- Ст.12. Перевірка цілісності електронного документа ---
def integrity_verifiable(
    signature_kind: SignatureKind, other_protection_means_applied: bool = False
) -> bool:
    """Ст.12. Кваліфікований/удосконалений підпис підтверджує цілісність прямо;
    для іншого виду — лише за застосування інших засобів захисту інформації."""
    if signature_kind in (SignatureKind.QUALIFIED, SignatureKind.ADVANCED):
        return True
    return other_protection_means_applied


# --- Ст.13. Зберігання електронних документів ---
@dataclass(frozen=True)
class StorageState:
    """Ст.13. Стан зберігання для перевірки строку та припустимості."""

    e_storage_term_days: int  # строк зберігання е-документа
    paper_term_days: int  # строк для паперового відповідника
    information_accessible: bool  # ч.4 п.1
    format_restorable: bool  # ч.4 п.2
    origin_metadata_kept: bool  # ч.4 п.3 (за наявності)


def storage_term_sufficient(state: StorageState) -> bool:
    """Ст.13(2). Строк зберігання е-документа не менший від паперового."""
    return state.e_storage_term_days >= state.paper_term_days


def storage_admissible(state: StorageState) -> bool:
    """Ст.13(2,4). Строк достатній і виконано всі умови припустимого зберігання."""
    return (
        storage_term_sufficient(state)
        and state.information_accessible
        and state.format_restorable
        and state.origin_metadata_kept
    )

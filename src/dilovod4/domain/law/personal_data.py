"""Обчислювані норми Закону № 2297-VI «Про захист персональних даних» —
перенесені з personal_data_2297.catala_en.

Чисті функції/перевірки над доменними даними, БЕЗ IO. Кожна функція відповідає
одному Catala-scope; статті закону збережено у docstring.

Стик: «конфіденційна інформація про особу» (ст.5) — персонально-даний бік
режиму обмеженого доступу (ст.21 Закону 2657-XII) та грифа обмеження доступу
(реквізит 15 ДСТУ 4163:2020). Персональні дані в е-документах також взаємодіють
зі зберіганням/обігом за ст.15 Закону 851-IV.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProcessingBasis(Enum):
    """Ст.11. Підстави для обробки персональних даних."""

    CONSENT = "Consent"  # 1) згода субʼєкта
    LEGAL_PERMISSION_FOR_POWERS = "LegalPermissionForPowers"  # 2) дозвіл за законом
    CONTRACT_WITH_SUBJECT = "ContractWithSubject"  # 3) правочин із субʼєктом
    VITAL_INTERESTS = "VitalInterests"  # 4) життєво важливі інтереси
    LEGAL_OBLIGATION_OF_CONTROLLER = "LegalObligationOfController"  # 5) обовʼязок за законом
    LEGITIMATE_INTERESTS = "LegitimateInterests"  # 6) законні інтереси (з балансом)


class SpecialCategoryException(Enum):
    """Ст.7(2). Винятки із заборони обробки особливих категорій (ч.1)."""

    EXPLICIT_CONSENT = "ExplicitConsent"  # 1) однозначна згода
    EMPLOYMENT_LAW_OBLIGATIONS = "EmploymentLawObligations"  # 2) трудові правовідносини
    VITAL_INTERESTS_INCAPACITATED = "VitalInterestsIncapacitated"  # 3) недієздатність
    NONPROFIT_ASSOCIATION_MEMBERS = "NonprofitAssociationMembers"  # 4) обʼєднання — члени
    LEGAL_CLAIM = "LegalClaim"  # 5) правова вимога
    HEALTHCARE_PURPOSES = "HealthcarePurposes"  # 6) охорона здоровʼя
    COURT_OPERATIVE_SECURITY = "CourtOperativeSecurity"  # 7) суд/ОРД/контррозвідка
    MANIFESTLY_PUBLIC = "ManifestlyPublic"  # 8) явно оприлюднені субʼєктом
    NO_EXCEPTION = "NoException"  # виняток відсутній


class TransferGround(Enum):
    """Ст.29(4). Підстави передачі за кордон (поза адекватним захистом)."""

    UNAMBIGUOUS_CONSENT = "UnambiguousConsent"  # 1) однозначна згода
    CONTRACT_IN_SUBJECT_FAVOUR = "ContractInSubjectFavour"  # 2) правочин на користь субʼєкта
    VITAL_INTERESTS_TRANSFER = "VitalInterestsTransfer"  # 3) життєво важливі інтереси
    PUBLIC_INTEREST_LEGAL_CLAIM = "PublicInterestLegalClaim"  # 4) суспільний інтерес/вимога
    CONTROLLER_PRIVACY_GUARANTEES = "ControllerPrivacyGuarantees"  # 5) гарантії невтручання
    NO_TRANSFER_GROUND = "NoTransferGround"  # підстава відсутня


class AccessRequestor(Enum):
    """Ст.16/17/19. Хто подає запит на доступ."""

    DATA_SUBJECT_OWN_DATA = "DataSubjectOwnData"  # субʼєкт щодо власних даних
    THIRD_PARTY = "ThirdParty"  # третя особа


class ProcessingContext(Enum):
    """Ст.25(2). Контекст обробки для звільнення від дії Закону."""

    PERSONAL_HOUSEHOLD = "PersonalHousehold"  # п.1 — особисті/побутові потреби
    JOURNALISTIC_CREATIVE = "JournalisticCreative"  # п.2 — журналістські/творчі цілі
    GENERAL = "General"  # звичайна обробка


@dataclass(frozen=True)
class GeneralRequirements:
    """Ст.6. Загальні вимоги до обробки."""

    purpose_defined_in_law: bool  # ч.1 — мета сформульована в актах
    data_adequate_not_excessive: bool  # ч.3 — відповідні, адекватні, ненадмірні
    accurate_and_updated: bool  # ч.2 — точні, достовірні, оновлювані
    retained_no_longer_than_needed: bool  # ч.8 — не довше, ніж потрібно


@dataclass(frozen=True)
class PurposeChange:
    """Ст.6(1) абз.3. Зміна мети на несумісну потребує нової згоди."""

    purpose_changed: bool
    new_purpose_incompatible: bool
    new_consent_obtained: bool
    law_allows_without_consent: bool


# --- Ст.6. Загальні вимоги ---
def processing_compliant(req: GeneralRequirements) -> bool:
    """Ст.6(1,2,3,8). Обробка відповідає загальним вимогам: визначена мета,
    адекватність, точність/оновлюваність, обмежений строк зберігання."""
    return (
        req.purpose_defined_in_law
        and req.data_adequate_not_excessive
        and req.accurate_and_updated
        and req.retained_no_longer_than_needed
    )


def further_processing_allowed(change: PurposeChange) -> bool:
    """Ст.6(1) абз.3. За зміни мети на несумісну потрібна нова згода або дозвіл
    закону; якщо мету не змінено чи нова мета сумісна — обробка триває."""
    if not change.purpose_changed or not change.new_purpose_incompatible:
        return True
    return change.new_consent_obtained or change.law_allows_without_consent


# --- Ст.7. Особливі категорії ---
def special_category_processing_permitted(exception: SpecialCategoryException) -> bool:
    """Ст.7(1,2). Обробка особливих категорій заборонена, крім наявності одного
    з винятків ч.2."""
    return exception is not SpecialCategoryException.NO_EXCEPTION


# --- Ст.11. Підстави обробки ---
def processing_lawful(
    basis: ProcessingBasis, legitimate_interests_override_subject: bool = False
) -> bool:
    """Ст.11(1). Обробка правомірна за наявності підстави. Для законних інтересів
    (п.6) — лише якщо вони не переважені правами субʼєкта."""
    if basis is ProcessingBasis.LEGITIMATE_INTERESTS:
        return not legitimate_interests_override_subject
    return True


# --- Ст.12. Повідомлення при збиранні ---
def collection_notice_deadline_working_days(collected_from_subject: bool) -> int:
    """Ст.12(2). Дедлайн повідомлення: у момент збору (0) або 30 робочих днів."""
    return 0 if collected_from_subject else 30


def collection_notice_timely(collected_from_subject: bool, working_days_since: int) -> bool:
    """Ст.12(2). Повідомлення вчасне, якщо збір у субʼєкта або ≤30 робочих днів."""
    return collected_from_subject or working_days_since <= 30


# --- Ст.16. Строки доступу ---
def access_study_within_limit(study_working_days: int) -> bool:
    """Ст.16(5). Вивчення запиту — не більше 10 робочих днів."""
    return study_working_days <= 10


def access_fulfilment_within_limit(fulfilment_calendar_days: int) -> bool:
    """Ст.16(5). Запит задовольняється протягом 30 календарних днів."""
    return fulfilment_calendar_days <= 30


# --- Ст.17. Відстрочення доступу ---
def access_deferral_allowed(
    requestor: AccessRequestor,
    deferral_calendar_days: int = 0,
    total_calendar_days: int = 0,
) -> bool:
    """Ст.17(1,2). Субʼєкту відстрочення доступу до власних даних заборонено;
    для третіх осіб — ≤30 кал.днів і загалом ≤45."""
    if requestor is AccessRequestor.DATA_SUBJECT_OWN_DATA:
        return False
    return deferral_calendar_days <= 30 and total_calendar_days <= 45


# --- Ст.19. Оплата доступу ---
def access_free(requestor: AccessRequestor) -> bool:
    """Ст.19(1,2). Доступ субʼєкта до власних даних безоплатний; третім особам
    може бути платним."""
    return requestor is AccessRequestor.DATA_SUBJECT_OWN_DATA


# --- Ст.25. Обмеження дії Закону ---
def law_applies(context: ProcessingContext, balance_of_rights_ensured: bool = False) -> bool:
    """Ст.25(2). Закон не застосовується до обробки для особистих/побутових
    потреб; для журналістських/творчих цілей — лише за забезпечення балансу прав."""
    if context is ProcessingContext.PERSONAL_HOUSEHOLD:
        return False
    if context is ProcessingContext.JOURNALISTIC_CREATIVE:
        return not balance_of_rights_ensured
    return True


# --- Ст.29. Транскордонна передача ---
def cross_border_transfer_permitted(
    adequate_protection_state: bool, ground: TransferGround = TransferGround.NO_TRANSFER_GROUND
) -> bool:
    """Ст.29(3,4). Передача за кордон допускається за належного захисту державою
    АБО за наявності однієї з підстав ч.4."""
    return adequate_protection_state or ground is not TransferGround.NO_TRANSFER_GROUND

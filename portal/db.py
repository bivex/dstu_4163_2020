"""Шар бази даних порталу підписання — SQLAlchemy 2.0 ORM.

Модель багатопідписання: Document (метадані + згенерований файл) →
черга Signer (порядок, статус) → AuditEvent (трасування для ст.13 Закону
851-IV: цілісність, походження, дата/час подій).

Зберігання за ст.13 Закону 851-IV: документи та події тримаються не менше
строку, встановленого для паперових відповідників (retention_until).
"""

from __future__ import annotations

import datetime as dt
import enum
import os
import sys
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

def _default_db_path() -> str:
    """Дефолтний шлях SQLite-БД за платформою.

    macOS (packaged-app): ~/Library/Application Support/dms-dir/portal.db —
    переживає видалення .app. Docker/інші: /data/portal.db (том контейнера).
    Явний PORTAL_DATABASE_URL завжди має пріоритет (див. нижче)."""
    if sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "dms-dir"
        d.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{d / 'portal.db'}"
    return "sqlite:////data/portal.db"


DATABASE_URL = os.environ.get("PORTAL_DATABASE_URL") or _default_db_path()

# SQLite потребує check_same_thread=False для багатопотокового FastAPI.
_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, echo=False, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class DocStatus(str, enum.Enum):
    DRAFT = "draft"  # редагується
    PENDING_APPROVAL = "pending_approval"  # погодження
    PENDING_SIGNATURES = "pending_signatures"  # очікує підписів у черзі
    SIGNED = "signed"  # усі підписали
    PUBLISHED = "published"  # оприлюднено (ст.14 996-XIV / ст.15 2939-VI)


class UserRole(str, enum.Enum):
    """Глобальна роль користувача. Окремо від position (вільний текст для
    PDF/листів погодження) — саме role використовується для прийняття рішень
    про доступ на бекенді та блокування UI на фронті."""

    ADMIN = "admin"        # повний доступ, керування користувачами/ролями
    DIRECTOR = "director"  # створює/підписує/публікує документи вищого рівня
    ACCOUNTANT = "accountant"  # фінансові документи, погодження, підпис
    CLERK = "clerk"        # створює чернетки, перегляд — мінімум прав


class ApprovalType(str, enum.Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


class ApproverStatus(str, enum.Enum):
    WAITING = "waiting"
    INVITED = "invited"
    APPROVED = "approved"
    REJECTED = "rejected"


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    OVERDUE = "overdue"


class SignerStatus(str, enum.Enum):
    WAITING = "waiting"  # ще не його черга
    INVITED = "invited"  # його черга, очікує дії
    SIGNED = "signed"  # підписав
    REJECTED = "rejected"  # відмовив


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(512))
    status: Mapped[DocStatus] = mapped_column(
        Enum(DocStatus, native_enum=False), default=DocStatus.DRAFT
    )
    fmt: Mapped[str] = mapped_column(String(8), default="pdf")  # pdf | docx
    # папка-категорія (організаційне групування, незалежне від статусу/архіву).
    # NULL — документ поза папками («Без папки»).
    folder_id: Mapped[int | None] = mapped_column(
        ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # JSON DocumentContent + Document params, з яких будується документ
    content_json: Mapped[str] = mapped_column(Text)
    # згенерований документ (PDF/DOCX) та контейнер з підписами (ASiC-E)
    rendered: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # версія документа з відмітками про КЕП + QR, побудована ПІСЛЯ реального
    # підпису з даних сертифікатів (для завантаження людиною). Чистий rendered
    # лишається недоторканим — саме над його digest накладено КЕП (ASiC-E).
    rendered_marked: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    asice: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # звіт відповідності ДСТУ/НПА (JSON) на момент генерації
    conformance_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # реєстраційні дані (присвоюються автоматично при поданні у чергу /submit):
    # наскрізний індекс за типом документа в межах року + дата реєстрації.
    doc_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reg_number: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1,2,3…
    reg_index: Mapped[str | None] = mapped_column(String(64), nullable=True)  # «125»
    reg_date: Mapped[str | None] = mapped_column(String(64), nullable=True)  # «14 червня 2026 р.»
    registered_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # оцифрування паперового документа: заливка скану (PDF/фото) як оригіналу.
    # Для is_scanned=True документ НЕ генерується з полів форми — оригіналом є
    # сам скан (rendered), який підписується КЕП через звичайний пайплайн.
    is_scanned: Mapped[bool] = mapped_column(default=False)

    # архівування: організаційна позначка (незалежна від workflow-статусу).
    # Архівований документ ховається зі звичайного списку, але не видаляється —
    # лишається доступним у розділі «Архів» та для відновлення.
    archived_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    # ст.13 Закону 851-IV: строк зберігання (≥ паперового відповідника)
    retention_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    approval_type: Mapped[str] = mapped_column(String(32), default="sequential")
    journal_id: Mapped[int | None] = mapped_column(
        ForeignKey("journals.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # === Трекінг розгляду вихідного документа (відповідь від адресата) ===
    # review_status: 'pending' - відправлено, чекаємо | 'responded' - відповідь отримана | 'overdue' - строк минув | 'not_applicable' - трекінг не потрібен
    review_status: Mapped[str | None] = mapped_column(String(32), nullable=True, default=None)
    # дата очікуваної відповіді (за замовчуванням = registered_at + 30 днів)
    expected_response_date: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # дата фактичного отримання відповіді
    response_received_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # нотатка до трекінгу (наприклад, опис отриманої відповіді)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    signers: Mapped[list["Signer"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Signer.order_index"
    )
    approvers: Mapped[list["Approver"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Approver.order_index"
    )
    resolutions: Mapped[list["Resolution"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    tasks: Mapped[list["Task"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="AuditEvent.created_at"
    )
    # додатки (скани/PDF/зображення/офісні) — пакуються у спільний ASiC-E контейнер
    # і підписуються єдиним КЕП разом з основним документом. Порядок order_index
    # детермінує послідовність <asic:DataObjectReference> у маніфесті (частина
    # підписаного digest) — перенумерація/переorder після підпису ламає підпис.
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Attachment.order_index"
    )
    folder: Mapped["Folder | None"] = relationship(back_populates="documents")

    @property
    def next_signer(self) -> "Signer | None":
        """Наступний у черзі підписант (INVITED або перший WAITING)."""
        for s in self.signers:
            if s.status in (SignerStatus.INVITED, SignerStatus.WAITING):
                return s
        return None

    @property
    def next_approver(self) -> "Approver | None":
        """Наступний у черзі погоджувач (INVITED або перший WAITING)."""
        for a in self.approvers:
            if a.status in (ApproverStatus.INVITED, ApproverStatus.WAITING):
                return a
        return None


class Attachment(Base):
    """Додаток до документа (скан/PDF/зображення/офісний файл).

    Server-owned blob (inline LargeBinary, як Document.rendered/.asice). Входить
    у спільний ASiC-E контейнер підпису. ``stored_filename`` — точне імʼя всередині
    ZIP, заморожене при завантаженні; унікальне в межах документа (вкл. основний
    файл ``{doc_id}.{fmt}``). ``order_index`` задає порядок у маніфесті ASiC.
    """
    __tablename__ = "attachments"
    __table_args__ = (
        UniqueConstraint("document_id", "stored_filename", name="uq_attachment_doc_filename"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    original_filename: Mapped[str] = mapped_column(String(256), default="")
    stored_filename: Mapped[str] = mapped_column(String(256))
    mime: Mapped[str] = mapped_column(String(128), default="application/octet-stream")
    size: Mapped[int] = mapped_column(Integer, default=0)
    blob: Mapped[bytes] = mapped_column(LargeBinary)
    use_incoming_stamp: Mapped[bool] = mapped_column(Boolean, default=False)
    use_copy_stamp: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    document: Mapped["Document"] = relationship(back_populates="attachments")


class Folder(Base):
    """Папка-категорія для організаційного групування документів.

    Незалежна від workflow-статусу та архіву — суто зручність користувача
    для розкладання документів по теках. Видалення папки не чіпає документи
    (folder_id → NULL завдяки ondelete=SET NULL).
    """

    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    color: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )  # напр. «primary», «#aabbcc»
    position: Mapped[int] = mapped_column(Integer, default=0)  # порядок у списку
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    documents: Mapped[list["Document"]] = relationship(back_populates="folder")


class Signer(Base):
    __tablename__ = "signers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)  # порядок у черзі (0,1,2…)
    full_name: Mapped[str] = mapped_column(String(256))  # ПІБ підписувача
    position: Mapped[str] = mapped_column(String(256), default="")  # посада (необовʼязково)
    status: Mapped[SignerStatus] = mapped_column(
        Enum(SignerStatus, native_enum=False), default=SignerStatus.WAITING
    )
    # дані КЕП-відмітки, видобуті із CMS-підпису після підпису
    certificate_serial: Mapped[str | None] = mapped_column(String(128), nullable=True)
    issuer: Mapped[str | None] = mapped_column(String(256), nullable=True)
    valid_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(64), nullable=True)
    signed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # підпис CMS/p7s цього підписувача (для збирання ASiC-E)
    signature: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    # тип підписанта: "person" (КЕП особи) або "seal" (електронна печатка
    # юрособи/ФОП). Дефолт "person" — зворотна сумісність; "seal" виставляється
    # автоматично, коли прийнятий CMS несе eSeal-сертифікат (QC type eseal).
    signer_type: Mapped[str] = mapped_column(String(16), default="person")
    # дані печатки (eSeal): організація та ідентифікатор (ЄДРПОУ/РНОКПП) з
    # сертифіката. Для person-підписанта лишається порожнім.
    organization: Mapped[str | None] = mapped_column(String(256), nullable=True)
    identifier: Mapped[str | None] = mapped_column(String(128), nullable=True)

    document: Mapped[Document] = relationship(back_populates="signers")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(64))  # created|edited|signed|rejected|published
    actor: Mapped[str] = mapped_column(String(256), default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    document: Mapped[Document] = relationship(back_populates="events")


class Approver(Base):
    __tablename__ = "approvers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    order_index: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(256))
    position: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[ApproverStatus] = mapped_column(
        Enum(ApproverStatus, native_enum=False), default=ApproverStatus.WAITING
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    document: Mapped[Document] = relationship(back_populates="approvers")


class Journal(Base):
    __tablename__ = "journals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    prefix: Mapped[str] = mapped_column(String(32))
    number_template: Mapped[str] = mapped_column(String(128))  # напр. "№ {number}-{prefix}"
    next_number: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Resolution(Base):
    __tablename__ = "resolutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    author: Mapped[str] = mapped_column(String(256))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    document: Mapped[Document] = relationship(back_populates="resolutions")
    tasks: Mapped[list[Task]] = relationship(
        back_populates="resolution", cascade="all, delete-orphan"
    )


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    resolution_id: Mapped[int | None] = mapped_column(
        ForeignKey("resolutions.id", ondelete="SET NULL"), nullable=True
    )
    executor: Mapped[str] = mapped_column(String(256))
    executor_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text)
    due_date: Mapped[str] = mapped_column(String(64))  # напр. "2026-06-25"
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False), default=TaskStatus.PENDING
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    document: Mapped[Document] = relationship(back_populates="tasks")
    resolution: Mapped[Resolution | None] = relationship(back_populates="tasks")


import hashlib
import secrets


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256), default="")
    position: Mapped[str] = mapped_column(String(256), default="")
    # роль для контролю доступу (див. UserRole). Окремо від position: position —
    # вільний текст для відображення (PDF, листи погодження); role — enum для gate-ів.
    # values_callable — критично: код (auth, bootstrap) присвоює .value ('admin',
    # 'clerk'), а SQLAlchemy Enum за замов. зберігає/читає NAME ('ADMIN'). Без
    # values_callable запуск з наявної БД (де role='clerk') дає LookupError.
    role: Mapped[str] = mapped_column(
        Enum(UserRole, native_enum=False,
             values_callable=lambda x: [e.value for e in x]),
        default=UserRole.CLERK.value, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(128))
    kep_serial_number: Mapped[str | None] = mapped_column(String(256), unique=True, index=True, nullable=True)
    kep_certificate_serial: Mapped[str | None] = mapped_column(String(256), index=True, nullable=True)
    kep_subject_cn: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # CN сертифіката ЕЛЕКТРОННОЇ ПЕЧАТКИ юрособи, прив'язаного в кабінеті (окремо
    # від kep_* — КЕП особи). Використовується _is_active_signer: печатку може
    # накласти лише користувач, чия organization_cert_cn збігається з CN печатки.
    organization_cert_cn: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # контакти фізособи-заявника: підставляються у блок «від кого» заяви/скарги
    # (Закон «Про звернення громадян» №393/96-ВР, ст. 5). Окремо від email — email
    # це логін, phone/address — публічні реквізити у документах.
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Факсимиле (дигітальне зображення рукописного підпису/печатки) — PNG/JPG блоб.
    # Накладається на PDF при генерації merged-pdf з ?visa=true.
    # Не є електронним підписом — виключно візуальний елемент.
    facsimile_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    facsimile_mime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    @staticmethod
    def hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return f"{salt}:{h}"

    def verify_password(self, password: str) -> bool:
        try:
            salt, h = self.password_hash.split(":", 1)
            return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest() == h
        except ValueError:
            return False


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    code: Mapped[str] = mapped_column(String(64), index=True)
    subject_type: Mapped[str] = mapped_column(String(32))  # legal | fop | person
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Process(Base):
    """Бізнес-процес документообігу — BPMN-lite граф (вузли + зв'язки) у JSON.

    graph_json: {"nodes": [{"id","type","label","x","y"}], "edges": [{"from","to","label"}]}
    type вузла: start | task | gateway | end.
    """
    __tablename__ = "processes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    graph_json: Mapped[str] = mapped_column(Text, default="{}")
    is_builtin: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class DocTemplate(Base):
    """Шаблон процесуального/службового документа.

    Зберігає типовий вид, категорію, заголовок та текст документа.
    is_builtin=True — системний шаблон (сіється автоматично), не підлягає
    видаленню. Користувацькі (is_builtin=False) можна повністю редагувати.

    Поля відповідають полям форми документа (DocForm у фронтенді).
    """
    __tablename__ = "doc_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Класифікація
    category: Mapped[str] = mapped_column(String(64), index=True)  # розпорядчі, довідкові, …
    doc_type: Mapped[str] = mapped_column(String(128))              # «Наказ», «Лист», …
    subject_type: Mapped[str] = mapped_column(String(16), default="legal")  # legal|fop|person
    # Відображення
    title: Mapped[str] = mapped_column(String(512))        # назва шаблону (для картки)
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(64), default="i-lucide-file-text")
    # Контент документа
    title_tpl: Mapped[str] = mapped_column(Text, default="")    # типовий заголовок документа
    body: Mapped[str] = mapped_column(Text, default="")         # текст документа
    addressees: Mapped[str | None] = mapped_column(Text, nullable=True)
    sender_contacts: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Мета
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


def init_db() -> None:
    """Створити таблиці (ідемпотентно) + легка міграція нових колонок."""
    # переконатися, що каталог для SQLite існує
    if DATABASE_URL.startswith("sqlite:///"):
        path = DATABASE_URL.replace("sqlite:///", "", 1)
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    Base.metadata.create_all(engine)
    from portal.migrations import run_migrations
    from portal.seeds import run_all_seeds

    run_migrations(engine)
    run_all_seeds(SessionLocal)



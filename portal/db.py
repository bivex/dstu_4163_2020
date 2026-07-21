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
    # міграція: додати колонки, яких немає у наявній таблиці на томі
    # (create_all не змінює вже створені таблиці)
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    if "users" in insp.get_table_names():
        u_cols = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            if "kep_serial_number" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN kep_serial_number VARCHAR(256)"))
            if "kep_certificate_serial" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN kep_certificate_serial VARCHAR(256)"))
            if "kep_subject_cn" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN kep_subject_cn VARCHAR(256)"))
            # роль для контролю доступу; всім наявним — clerk (мінімум прав),
            # адміна піднімаємо окремо через PORTAL_BOOTSTRAP_ADMIN_EMAIL.
            if "role" not in u_cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'clerk'")
                )
            # CN сертифіката електронної печатки юрособи (окремо від КЕП особи)
            if "organization_cert_cn" not in u_cols:
                conn.execute(
                    text("ALTER TABLE users ADD COLUMN organization_cert_cn VARCHAR(256)")
                )
            # контакти фізособи-заявника для блоку «від кого» у заявах/скаргах
            if "phone" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN phone VARCHAR(64)"))
            if "address" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN address TEXT"))
            # факсимиле (дигітальне зображення підпису)
            if "facsimile_blob" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN facsimile_blob BLOB"))
            if "facsimile_mime" not in u_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN facsimile_mime VARCHAR(32)"))

    if "signers" in insp.get_table_names():
        s_cols = {c["name"] for c in insp.get_columns("signers")}
        with engine.begin() as conn:
            # тип підписанта: person (КЕП) | seal (електронна печатка юрособи)
            if "signer_type" not in s_cols:
                conn.execute(
                    text(
                        "ALTER TABLE signers ADD COLUMN signer_type VARCHAR(16) DEFAULT 'person'"
                    )
                )
            # дані печатки (eSeal): організація та ідентифікатор
            if "organization" not in s_cols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN organization VARCHAR(256)"))
            if "identifier" not in s_cols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN identifier VARCHAR(128)"))

    if "documents" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("documents")}
        if "rendered_marked" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE documents ADD COLUMN rendered_marked BLOB"))
        # реєстраційні колонки (авто-нумерація + автодата)
        with engine.begin() as conn:
            if "doc_type" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN doc_type VARCHAR(64)"))
            if "reg_number" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN reg_number INTEGER"))
            if "reg_index" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN reg_index VARCHAR(64)"))
            if "reg_date" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN reg_date VARCHAR(64)"))
            if "registered_at" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN registered_at DATETIME"))
            if "archived_at" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN archived_at DATETIME"))
            if "is_scanned" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN is_scanned BOOLEAN DEFAULT 0"))
            if "folder_id" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN folder_id INTEGER"))
            if "approval_type" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE documents ADD COLUMN approval_type VARCHAR(32) DEFAULT 'sequential'"
                    )
                )
            if "journal_id" not in cols:
                conn.execute(text("ALTER TABLE documents ADD COLUMN journal_id INTEGER"))
        # clean up old reg_index values that have the № prefix baked in
        # (templates were fixed to not include №, so existing values need stripping)
        with engine.begin() as conn:
            rows = conn.execute(
                text("SELECT id, reg_index FROM documents WHERE reg_index LIKE :pat"), {"pat": "№%"}
            ).fetchall()
            for row in rows:
                new_val = row[1].lstrip("№ ").lstrip("№")
                if new_val != row[1]:
                    conn.execute(
                        text("UPDATE documents SET reg_index = :v WHERE id = :id"),
                        {"v": new_val, "id": row[0]},
                    )
    # clean up journal templates that have the № prefix baked in (рендер додає № сам,
    # тож шаблон з «№» давав подвійний номер «№ № 3-ВИХ»)
    if "journals" in insp.get_table_names():
        with engine.begin() as conn:
            jrows = conn.execute(
                text("SELECT id, number_template FROM journals WHERE number_template LIKE :pat"),
                {"pat": "№%"},
            ).fetchall()
            for jr in jrows:
                new_tpl = jr[1].lstrip("№ ").lstrip("№").strip()
                if new_tpl != jr[1]:
                    conn.execute(
                        text("UPDATE journals SET number_template = :v WHERE id = :id"),
                        {"v": new_tpl, "id": jr[0]},
                    )
    if "signers" in insp.get_table_names():
        scols = {c["name"] for c in insp.get_columns("signers")}
        with engine.begin() as conn:
            if "valid_from" not in scols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN valid_from VARCHAR(64)"))
            if "valid_to" not in scols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN valid_to VARCHAR(64)"))
    # users: посаду користувача (для вибору погоджувачів із реальних юзерів системи)
    if "users" in insp.get_table_names():
        ucols = {c["name"] for c in insp.get_columns("users")}
        with engine.begin() as conn:
            if "position" not in ucols:
                conn.execute(text("ALTER TABLE users ADD COLUMN position VARCHAR(256) DEFAULT ''"))
    # approvers: зв'язок погоджувача з користувачем системи (user_id)
    if "approvers" in insp.get_table_names():
        acols = {c["name"] for c in insp.get_columns("approvers")}
        with engine.begin() as conn:
            if "user_id" not in acols:
                conn.execute(text("ALTER TABLE approvers ADD COLUMN user_id INTEGER"))
    # tasks: зв'язок виконавця з користувачем системи (executor_user_id)
    if "tasks" in insp.get_table_names():
        tcols = {c["name"] for c in insp.get_columns("tasks")}
        with engine.begin() as conn:
            if "executor_user_id" not in tcols:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN executor_user_id INTEGER"))
    # сіємо дефолтного адміна якщо таблиця users порожня
    _seed_default_admin()
    # сіємо дефолтних контрагентів
    _seed_default_counterparties()
    # сіємо дефолтні реєстраційні журнали
    _seed_default_journals()
    # сіємо вбудовані бізнес-процеси документообігу
    _seed_default_processes()
    # сіємо вбудовані шаблони процесуальних документів
    _seed_default_templates()


def _seed_default_journals() -> None:
    """Створити дефолтні реєстраційні журнали якщо таблиця порожня."""
    with SessionLocal() as session:
        if session.query(Journal).first():
            return
        j1 = Journal(
            name="Накази з основної діяльності",
            prefix="ОД",
            number_template="{number}-{prefix}",
            next_number=1,
        )
        j2 = Journal(
            name="Вхідне листування",
            prefix="ВХ",
            number_template="{number}/{prefix}",
            next_number=1,
        )
        j3 = Journal(
            name="Вихідне листування",
            prefix="ВИХ",
            number_template="{number}-{prefix}/01-12",
            next_number=1,
        )
        session.add_all([j1, j2, j3])
        session.commit()


def _seed_default_admin() -> None:
    """Створити дефолтного адміна admin@dilovod.local / admin якщо немає жодного user."""
    default_email = os.environ.get("PORTAL_ADMIN_EMAIL", "admin@dilovod.local")
    default_pass = os.environ.get("PORTAL_ADMIN_PASSWORD", "admin")
    with SessionLocal() as session:
        if session.query(User).first():
            # таблиця не порожня — спробуємо підняти адміна через bootstrap-email
            _bootstrap_admin(session, default_email)
            return
        user = User(
            email=default_email,
            name="Адміністратор",
            position="Адміністратор",
            role=UserRole.ADMIN.value,
            password_hash=User.hash_password(default_pass),
            phone="+38 050 123 45 67",
            address="вул. Садова, 5, кв. 12, м. Київ, 01001",
        )
        session.add(user)
        session.commit()


def _bootstrap_admin(session, email: str | None) -> None:
    """Підняти роль вказаного користувача до admin при старті.

    Використовується для існуючих баз, де міграція проставила всім role='clerk':
    задайте PORTAL_BOOTSTRAP_ADMIN_EMAIL=email@org — і цей користувач стане адміном.
    Це разова дія при старті; якщо роль вже admin — нічого не робимо."""
    bootstrap_email = os.environ.get("PORTAL_BOOTSTRAP_ADMIN_EMAIL") or email
    if not bootstrap_email:
        return
    # якщо вже є хоча б один admin — не втручаємося (адмін призначений вручну)
    if session.query(User).filter_by(role=UserRole.ADMIN.value).first():
        return
    user = session.query(User).filter_by(email=bootstrap_email).first()
    if user and user.role != UserRole.ADMIN.value:
        user.role = UserRole.ADMIN.value
        session.commit()


def _seed_default_counterparties() -> None:
    """Створити дефолтних контрагентів якщо таблиця порожня."""
    with SessionLocal() as session:
        existing_names = {c.name for c in session.query(Counterparty.name).all()}
        
        to_add = []
        defaults = [
            ('ТОВ "Дія Консалтинг"', "12345678", "legal", "info@diaconsulting.com.ua", "+380441112233", "м. Київ, вул. Хрещатик, 1"),
            ('АТ "Укрпошта"', "21560043", "legal", "ukrposhta@ukrposhta.ua", "+380442223344", "м. Київ, вул. Хрещатик, 22"),
            ("ФОП Шевченко Тарас Григорович", "3012345678", "fop", "shevchenko@gmail.com", "+380998887766", "м. Канів, вул. Шевченка, 10"),
            ("Національна поліція України", "40108578", "legal", "info@police.gov.ua", "+380442560333", "Голові Національної поліції України\nвул. Академіка Богомольця, 10\nм. Київ, 01601"),
            ("Офіс Генерального прокурора", "00034051", "legal", "zvern@gp.gov.ua", "+380442007624", "Генеральному прокурору\nвул. Різницька, 13/15\nм. Київ, 01011"),
            ("Антимонопольний комітет України", "00032744", "legal", "post@amcu.gov.ua", "+380442516223", "Голові Антимонопольного комітету України\nвул. Митрополита Василя Липківського, 45\nм. Київ, 03035")
        ]

        for name, code, subject_type, email, phone, address in defaults:
            if name not in existing_names:
                to_add.append(Counterparty(
                    name=name,
                    code=code,
                    subject_type=subject_type,
                    email=email,
                    phone=phone,
                    address=address
                ))
        
        if to_add:
            session.add_all(to_add)
            session.commit()


def _seed_default_processes() -> None:
    """Створити вбудовані бізнес-процеси документообігу якщо таблиця порожня.

    Кожен процес — BPMN-lite граф: вузли (start/task/gateway/end) з координатами
    для розкладки зліва-направо та зв'язки між ними. Слугують шаблонами й
    прикладами для конструктора процесів.
    """
    import json as _json

    with SessionLocal() as session:
        existing_names = {p.name for p in session.query(Process.name).all()}

        def graph(nodes, edges):
            return _json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)

        def add_if_new(items):
            """Додати лише процеси, яких ще немає (за назвою) — ідемпотентно."""
            fresh = [p for p in items if p.name not in existing_names]
            if fresh:
                session.add_all(fresh)
                existing_names.update(p.name for p in fresh)
            return fresh

        # 1) Погодження та підписання вихідного документа
        p1_nodes = [
            {"id": "n1", "type": "start", "label": "Створення проєкту", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Погодження (візування)", "x": 220, "y": 120},
            {"id": "n3", "type": "gateway", "label": "Погоджено?", "x": 430, "y": 120},
            {"id": "n4", "type": "task", "label": "Доопрацювання", "x": 430, "y": 250},
            {"id": "n5", "type": "task", "label": "Підписання КЕП", "x": 620, "y": 120},
            {"id": "n6", "type": "task", "label": "Реєстрація", "x": 810, "y": 120},
            {"id": "n7", "type": "end", "label": "Відправлення", "x": 1000, "y": 120},
        ]
        p1_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n5", "label": "так"},
            {"from": "n3", "to": "n4", "label": "ні"},
            {"from": "n4", "to": "n2", "label": "повторно"},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 2) Реєстрація та виконання вхідного документа
        p2_nodes = [
            {"id": "n1", "type": "start", "label": "Надходження", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Реєстрація вхідного", "x": 220, "y": 120},
            {"id": "n3", "type": "task", "label": "Розгляд керівником", "x": 420, "y": 120},
            {"id": "n4", "type": "task", "label": "Накладення резолюції", "x": 620, "y": 120},
            {"id": "n5", "type": "task", "label": "Виконання доручення", "x": 820, "y": 120},
            {"id": "n6", "type": "gateway", "label": "Виконано?", "x": 1020, "y": 120},
            {"id": "n7", "type": "end", "label": "Списання у справу", "x": 1210, "y": 120},
        ]
        p2_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": "так"},
            {"from": "n6", "to": "n5", "label": "ні"},
        ]

        # 3) Видання наказу з основної діяльності
        p3_nodes = [
            {"id": "n1", "type": "start", "label": "Ініціювання наказу", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Підготовка проєкту", "x": 230, "y": 120},
            {"id": "n3", "type": "task", "label": "Візування (юрист, бухгалтер)", "x": 440, "y": 120},
            {"id": "n4", "type": "task", "label": "Підписання керівником", "x": 670, "y": 120},
            {"id": "n5", "type": "task", "label": "Реєстрація (наскрізний №)", "x": 880, "y": 120},
            {"id": "n6", "type": "task", "label": "Ознайомлення працівників", "x": 1100, "y": 120},
            {"id": "n7", "type": "end", "label": "Зберігання у справі", "x": 1320, "y": 120},
        ]
        p3_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        add_if_new([
            Process(
                name="Погодження та підписання вихідного документа",
                description="Типовий маршрут вихідного документа: візування → підписання КЕП → реєстрація → відправлення.",
                graph_json=graph(p1_nodes, p1_edges),
                is_builtin=True,
            ),
            Process(
                name="Реєстрація та виконання вхідного документа",
                description="Обробка вхідного: реєстрація → розгляд → резолюція → виконання → списання у справу.",
                graph_json=graph(p2_nodes, p2_edges),
                is_builtin=True,
            ),
            Process(
                name="Видання наказу з основної діяльності",
                description="Життєвий цикл наказу: підготовка → візування → підписання → реєстрація → ознайомлення.",
                graph_json=graph(p3_nodes, p3_edges),
                is_builtin=True,
            ),
        ])

        # --- Професійні процеси для ФОП (фізична особа — підприємець) ---

        # 4) Укладення договору з контрагентом
        f1_nodes = [
            {"id": "n1", "type": "start", "label": "Запит від клієнта", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Підготовка договору", "x": 230, "y": 120},
            {"id": "n3", "type": "task", "label": "Узгодження умов", "x": 440, "y": 120},
            {"id": "n4", "type": "gateway", "label": "Умови узгоджено?", "x": 650, "y": 120},
            {"id": "n5", "type": "task", "label": "Коригування", "x": 650, "y": 250},
            {"id": "n6", "type": "task", "label": "Підписання КЕП обома", "x": 860, "y": 120},
            {"id": "n7", "type": "end", "label": "Договір у силі", "x": 1070, "y": 120},
        ]
        f1_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n6", "label": "так"},
            {"from": "n4", "to": "n5", "label": "ні"},
            {"from": "n5", "to": "n3", "label": "повторно"},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 5) Виставлення рахунку та облік оплати
        f2_nodes = [
            {"id": "n1", "type": "start", "label": "Надання послуги/товару", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Виставлення рахунку", "x": 250, "y": 120},
            {"id": "n3", "type": "task", "label": "Надсилання клієнту", "x": 460, "y": 120},
            {"id": "n4", "type": "gateway", "label": "Оплачено?", "x": 670, "y": 120},
            {"id": "n5", "type": "task", "label": "Нагадування про оплату", "x": 670, "y": 250},
            {"id": "n6", "type": "task", "label": "Акт виконаних робіт", "x": 880, "y": 120},
            {"id": "n7", "type": "end", "label": "Облік доходу (Книга ОД)", "x": 1090, "y": 120},
        ]
        f2_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n6", "label": "так"},
            {"from": "n4", "to": "n5", "label": "ні"},
            {"from": "n5", "to": "n4", "label": "очікування"},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 6) Подання податкової звітності ФОП (єдиний податок + ЄСВ)
        f3_nodes = [
            {"id": "n1", "type": "start", "label": "Кінець звітного періоду", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Звірка доходів", "x": 240, "y": 120},
            {"id": "n3", "type": "task", "label": "Формування декларації", "x": 450, "y": 120},
            {"id": "n4", "type": "task", "label": "Підписання КЕП", "x": 660, "y": 120},
            {"id": "n5", "type": "task", "label": "Подання до ДПС", "x": 850, "y": 120},
            {"id": "n6", "type": "task", "label": "Сплата ЄП та ЄСВ", "x": 1050, "y": 120},
            {"id": "n7", "type": "end", "label": "Квитанція №2 отримана", "x": 1270, "y": 120},
        ]
        f3_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 7) Прийняття найманого працівника
        f4_nodes = [
            {"id": "n1", "type": "start", "label": "Потреба у працівникові", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Отримання документів від кандидата", "x": 230, "y": 120},
            {"id": "n3", "type": "task", "label": "Укладення трудового договору", "x": 450, "y": 120},
            {"id": "n4", "type": "task", "label": "Оформлення наказу про прийняття", "x": 670, "y": 120},
            {"id": "n5", "type": "task", "label": "Повідомлення ДПС про прийняття", "x": 890, "y": 120},
            {"id": "n6", "type": "task", "label": "Інструктаж та допуск до роботи", "x": 1110, "y": 120},
            {"id": "n7", "type": "end", "label": "Оформлено найм", "x": 1330, "y": 120},
        ]
        f4_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 8) Отримання первинних документів від постачальника
        f5_nodes = [
            {"id": "n1", "type": "start", "label": "Надходження послуг/товарів", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Отримання первинних документів", "x": 250, "y": 120},
            {"id": "n3", "type": "gateway", "label": "Перевірка ДСТУ та реквізитів", "x": 470, "y": 120},
            {"id": "n4", "type": "task", "label": "Запит на виправлення", "x": 470, "y": 250},
            {"id": "n5", "type": "task", "label": "Підписання КЕП (Вчасно/Дія)", "x": 690, "y": 120},
            {"id": "n6", "type": "task", "label": "Оплата рахунку постачальника", "x": 900, "y": 120},
            {"id": "n7", "type": "end", "label": "Первинні документи підписано", "x": 1110, "y": 120},
        ]
        f5_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n5", "label": "так"},
            {"from": "n3", "to": "n4", "label": "ні"},
            {"from": "n4", "to": "n2", "label": "повторно"},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 9) Реєстрація та робота з ПРРО
        f6_nodes = [
            {"id": "n1", "type": "start", "label": "Необхідність фіскалізації", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Подання форми 20-ОПП", "x": 230, "y": 120},
            {"id": "n3", "type": "task", "label": "Подання форми 1-ПРРО", "x": 440, "y": 120},
            {"id": "n4", "type": "task", "label": "Подання форми 5-ПРРО (касир)", "x": 650, "y": 120},
            {"id": "n5", "type": "task", "label": "Відкриття зміни та продажі", "x": 860, "y": 120},
            {"id": "n6", "type": "task", "label": "Створення Z-звіту та закриття", "x": 1070, "y": 120},
            {"id": "n7", "type": "end", "label": "Зміна успішно закрита", "x": 1280, "y": 120},
        ]
        f6_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 10) Припинення (закриття) діяльності ФОП
        f7_nodes = [
            {"id": "n1", "type": "start", "label": "Рішення припинити діяльність", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Подання заяви в Дію (держреєстратор)", "x": 250, "y": 120},
            {"id": "n3", "type": "task", "label": "Подання ліквідаційної звітності", "x": 470, "y": 120},
            {"id": "n4", "type": "task", "label": "Остаточна сплата податків", "x": 680, "y": 120},
            {"id": "n5", "type": "task", "label": "Закриття рахунків у банках", "x": 890, "y": 120},
            {"id": "n6", "type": "task", "label": "Пройдення податкової звірки", "x": 1100, "y": 120},
            {"id": "n7", "type": "end", "label": "ФОП офіційно знято з обліку", "x": 1310, "y": 120},
        ]
        f7_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        add_if_new([
            Process(
                name="ФОП: Укладення договору з контрагентом",
                description="Договірна робота ФОП: запит → підготовка → узгодження → підписання КЕП обома сторонами.",
                graph_json=graph(f1_nodes, f1_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Виставлення рахунку та облік оплати",
                description="Розрахунки ФОП: рахунок → надсилання → контроль оплати → акт → запис у Книгу обліку доходів.",
                graph_json=graph(f2_nodes, f2_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Подання податкової звітності (ЄП + ЄСВ)",
                description="Звітність єдинника: звірка доходів → декларація → КЕП → подання до ДПС → сплата ЄП/ЄСВ.",
                graph_json=graph(f3_nodes, f3_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Прийняття найманого працівника",
                description="Оформлення найму: пакет документів → трудовий договір → наказ про прийняття → повідомлення ДПС → інструктаж.",
                graph_json=graph(f4_nodes, f4_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Отримання первинних документів від постачальника",
                description="Контроль вхідної первинки: рахунок/накладна → перевірка реквізитів та відповідності ДСТУ → підписання КЕП → оплата.",
                graph_json=graph(f5_nodes, f5_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Реєстрація та робота з ПРРО",
                description="Робота з програмною касою: подання 20-ОПП → реєстрація каси 1-ПРРО → реєстрація касира 5-ПРРО → Z-звіти.",
                graph_json=graph(f6_nodes, f6_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Припинення (закриття) діяльності",
                description="Процедура закриття ФОП: заява держреєстратору → ліквідаційна звітність → закриття рахунків → податкова звірка.",
                graph_json=graph(f7_nodes, f7_edges),
                is_builtin=True,
            ),
        ])
        session.commit()


def _seed_default_templates() -> None:
    """Сіяти вбудовані шаблони процесуальних документів (ідемпотентно).

    Виконується при кожному старті: пропускає шаблони, що вже є (за title).
    is_builtin=True — системні шаблони не можна видалити через API.
    """
    TEMPLATES = [
        # ── Розпорядчі ──────────────────────────────────────────────────────
        dict(
            category="rozporyadchi", doc_type="Наказ про відпустку",
            subject_type="legal", title="Наказ про надання відпустки",
            description="Щорічна основна або додаткова відпустка працівника",
            icon="i-lucide-umbrella", sort_order=10,
            title_tpl="Про надання щорічної відпустки",
            body=(
                "НАКАЗУЮ:\n"
                "1. Надати [ПІБ] щорічну основну відпустку тривалістю 14 календарних днів "
                "з [Дата] по [Дата] за робочий період з [Дата] по [Дата].\n"
                "2. Головному бухгалтеру провести розрахунок та виплату відпускних."
            ),
        ),
        dict(
            category="rozporyadchi", doc_type="Наказ про прийняття на роботу",
            subject_type="legal", title="Наказ про прийняття на роботу",
            description="Оформлення нового працівника на посаду",
            icon="i-lucide-user-plus", sort_order=11,
            title_tpl="Про прийняття на роботу",
            body=(
                "НАКАЗУЮ:\n"
                "1. Прийняти [ПІБ] на роботу з [Дата] на посаду [Посада].\n"
                "2. Встановити посадовий оклад згідно зі штатним розкладом."
            ),
        ),
        dict(
            category="rozporyadchi", doc_type="Наказ",
            subject_type="legal", title="Наказ про звільнення",
            description="Розірвання трудового договору з працівником",
            icon="i-lucide-user-minus", sort_order=12,
            title_tpl="Про звільнення",
            body=(
                "НАКАЗУЮ:\n"
                "1. Звільнити [ПІБ], [Посада], з [Дата] у зв'язку з "
                "[підстава відповідно до ст. КЗпП України].\n"
                "2. Виплатити належні компенсації відповідно до законодавства."
            ),
        ),
        dict(
            category="rozporyadchi", doc_type="Наказ",
            subject_type="legal", title="Наказ про відрядження",
            description="Направлення працівника у службове відрядження",
            icon="i-lucide-plane", sort_order=13,
            title_tpl="Про направлення у службове відрядження",
            body=(
                "НАКАЗУЮ:\n"
                "1. Направити [ПІБ], [Посада], у службове відрядження до [Місто/Організація] "
                "з [Дата] по [Дата] з метою [мета відрядження].\n"
                "2. Витрати на відрядження відшкодувати відповідно до чинного законодавства.\n"
                "3. Контроль за виконанням покласти на [ПІБ відповідального]."
            ),
        ),
        dict(
            category="rozporyadchi", doc_type="Наказ",
            subject_type="legal", title="Наказ про заохочення",
            description="Преміювання або нагородження працівника за результатами роботи",
            icon="i-lucide-award", sort_order=14,
            title_tpl="Про заохочення",
            body=(
                "У зв'язку з [підстава заохочення]\n"
                "НАКАЗУЮ:\n"
                "1. Оголосити подяку (нагородити грамотою / виплатити премію у розмірі [сума] грн) "
                "[ПІБ], [Посада].\n"
                "2. Головному бухгалтеру провести відповідні нарахування."
            ),
        ),
        dict(
            category="rozporyadchi", doc_type="Розпорядження",
            subject_type="legal", title="Розпорядження",
            description="Оперативне розпорядження керівника або структурного підрозділу",
            icon="i-lucide-file-badge", sort_order=20,
            title_tpl="Про [предмет розпорядження]",
            body=(
                "З метою [мета] ЗОБОВ'ЯЗУЮ:\n"
                "1. [ПІБ відповідального] забезпечити [дія] до [Дата].\n"
                "2. Контроль за виконанням залишаю за собою."
            ),
        ),
        dict(
            category="rozporyadchi", doc_type="Постанова",
            subject_type="legal", title="Постанова",
            description="Рішення колегіального органу управління",
            icon="i-lucide-gavel", sort_order=30,
            title_tpl="Про [предмет постанови]",
            body=(
                "Розглянувши [предмет], колегія ПОСТАНОВЛЯЄ:\n"
                "1. [Рішення пункт 1].\n"
                "2. [Рішення пункт 2].\n"
                "3. Контроль за виконанням покласти на [ПІБ]."
            ),
        ),
        dict(
            category="rozporyadchi", doc_type="Рішення",
            subject_type="legal", title="Рішення",
            description="Рішення органу місцевого самоврядування або колегіального органу",
            icon="i-lucide-circle-check-big", sort_order=40,
            title_tpl="Про [предмет рішення]",
            body=(
                "Відповідно до [норма права/повноважень],\n"
                "ВИРІШИТИ:\n"
                "1. [Рішення пункт 1].\n"
                "2. [Рішення пункт 2].\n"
                "3. Рішення набирає чинності з дня прийняття."
            ),
        ),
        # ── Довідково-інформаційні ──────────────────────────────────────────
        dict(
            category="dovidkovi", doc_type="Протокол",
            subject_type="legal", title="Протокол засідання",
            description="Протокол зборів, нарад, засідань колегіальних органів",
            icon="i-lucide-clipboard-list", sort_order=100,
            title_tpl="Протокол засідання [назва органу]",
            body=(
                "ПРИСУТНІ: [перелік учасників]\n\n"
                "ПОРЯДОК ДЕННИЙ:\n1. [Питання 1]\n2. [Питання 2]\n\n"
                "СЛУХАЛИ:\n[ПІБ] — [короткий зміст виступу]\n\n"
                "ВИРІШИЛИ:\n1. [Рішення 1]\n2. [Рішення 2]"
            ),
        ),
        dict(
            category="dovidkovi", doc_type="Витяг з протоколу",
            subject_type="legal", title="Витяг з протоколу",
            description="Витяг окремого питання або рішення з протоколу засідання",
            icon="i-lucide-file-minus", sort_order=101,
            title_tpl="Витяг з протоколу № [номер] від [дата]",
            body=(
                "З протоколу засідання [назва органу] № [номер] від [дата].\n\n"
                "Питання [порядковий номер] порядку денного:\n[зміст питання]\n\n"
                "ВИРІШИЛИ:\n[зміст рішення]"
            ),
        ),
        dict(
            category="dovidkovi", doc_type="Акт",
            subject_type="legal", title="Акт",
            description="Акт перевірки, прийому-передачі або інвентаризації",
            icon="i-lucide-file-check", sort_order=102,
            title_tpl="Акт [предмет акта]",
            body=(
                "Комісія у складі:\n"
                "Голова: [ПІБ, посада]\n"
                "Члени комісії: [ПІБ, посада]\n\n"
                "СКЛАЛА цей акт про наступне:\n[Зміст акта]\n\n"
                "ВИСНОВОК: [висновок комісії]\n\n"
                "Підписи членів комісії:"
            ),
        ),
        dict(
            category="dovidkovi", doc_type="Акт",
            subject_type="legal", title="Акт прийому-передачі",
            description="Фіксація передачі майна, документів або справ",
            icon="i-lucide-arrow-left-right", sort_order=103,
            title_tpl="Акт прийому-передачі [майно/документи]",
            body=(
                "Ми, що нижче підписалися:\n"
                "Передав: [ПІБ, посада]\n"
                "Прийняв: [ПІБ, посада]\n\n"
                "Склали цей акт про те, що [Передав] передав, а [Прийняв] прийняв наступне:\n"
                "[перелік майна/документів із зазначенням кількості та стану]\n\n"
                "Претензій сторони не мають."
            ),
        ),
        dict(
            category="dovidkovi", doc_type="Довідка",
            subject_type="legal", title="Довідка",
            description="Офіційна довідка про підтвердження фактів або даних",
            icon="i-lucide-badge-info", sort_order=104,
            title_tpl="Довідка про [предмет]",
            body=(
                "Видана [ПІБ], [посада], у тому, що [зміст довідки].\n\n"
                "Довідка видана для пред'явлення [куди/кому]."
            ),
        ),
        # ── Листування ──────────────────────────────────────────────────────
        dict(
            category="lystuvannya", doc_type="Лист",
            subject_type="legal", title="Офіційний лист",
            description="Ділове листування між організаціями або органами",
            icon="i-lucide-mail", sort_order=200,
            title_tpl="Щодо [предмет листа]",
            body=(
                "Шановні колеги!\n\n"
                "Звертаємося до вас з приводу [суть питання].\n\n"
                "[Основний зміст листа]\n\n"
                "Просимо розглянути та надати відповідь у встановлений законом строк."
            ),
            addressees="[Посада керівника]\n[Найменування організації]\n[Адреса]",
        ),
        dict(
            category="lystuvannya", doc_type="Лист",
            subject_type="legal", title="Лист-відповідь",
            description="Відповідь на вхідне звернення або запит організації",
            icon="i-lucide-reply", sort_order=201,
            title_tpl="Відповідь на лист від [дата] № [номер]",
            body=(
                "У відповідь на Ваш лист від [дата] № [номер] щодо [предмет] "
                "повідомляємо наступне:\n\n[Зміст відповіді]\n\n"
                "Сподіваємося на плідну співпрацю."
            ),
            addressees="[Посада керівника]\n[Найменування організації]",
        ),
        dict(
            category="lystuvannya", doc_type="Службова записка",
            subject_type="legal", title="Службова записка",
            description="Внутрішня службова записка між підрозділами",
            icon="i-lucide-sticky-note", sort_order=202,
            title_tpl="Службова записка щодо [предмет]",
            body=(
                "Доводжу до Вашого відома, що [суть питання].\n\n"
                "Враховуючи зазначені обставини, прошу [суть прохання]."
            ),
            addressees="[Посада керівника підрозділу]",
        ),
        dict(
            category="lystuvannya", doc_type="Доповідна записка",
            subject_type="legal", title="Доповідна записка",
            description="Доповідна записка керівнику з викладенням фактів і пропозицій",
            icon="i-lucide-file-pen-line", sort_order=203,
            title_tpl="Доповідна записка щодо [предмет]",
            body=(
                "Доповідаю Вам про наступне:\n"
                "[Виклад фактів та обставин]\n\n"
                "Вважаю за необхідне [пропозиція або прохання]."
            ),
            addressees="[Посада керівника]",
        ),
        dict(
            category="lystuvannya", doc_type="Пояснювальна записка",
            subject_type="legal", title="Пояснювальна записка",
            description="Пояснення обставин або причин певних дій чи подій",
            icon="i-lucide-message-circle-question", sort_order=204,
            title_tpl="Пояснювальна записка щодо [предмет]",
            body=(
                "Пояснюю, що [виклад обставин та причин].\n\n"
                "[Додаткові пояснення та аргументи]."
            ),
            addressees="[Посада керівника]",
        ),
        # ── Звернення громадян ──────────────────────────────────────────────
        dict(
            category="zvernennya", doc_type="Заява",
            subject_type="person", title="Заява",
            description="Загальна заява фізичної особи до органу або установи",
            icon="i-lucide-user-pen", sort_order=300,
            title_tpl="Заява про [предмет звернення]",
            body=(
                "Звертаюся до Вас із заявою з приводу [коротко опишіть обставини справи та "
                "підставу звернення].\n\n"
                "Відповідно до [норма закону, що підтверджує ваше право],\n\n"
                "ПРОШУ:\n"
                "1. [суть прохання або вимоги];\n"
                "2. повідомити мене про результати розгляду цієї заяви у встановлений законом строк."
            ),
            addressees=(
                "[Посада, ПІБ посадової особи]\n"
                "[Найменування органу]\n"
                "[Адреса органу]"
            ),
            sender_contacts=(
                "[Вулиця, будинок, квартира]\n"
                "[Місто, індекс]\n"
                "тел.: [+38 0XX XXX XX XX]\n"
                "email: [your@email.com]"
            ),
        ),
        dict(
            category="zvernennya", doc_type="Заява про надання матеріальної допомоги",
            subject_type="person", title="Заява про матеріальну допомогу",
            description="Звернення про надання матеріальної допомоги",
            icon="i-lucide-hand-heart", sort_order=301,
            title_tpl="Заява про надання матеріальної допомоги",
            body=(
                "Прошу надати мені матеріальну допомогу у зв'язку зі скрутним матеріальним "
                "становищем (на лікування / за сімейними обставинами)."
            ),
            addressees="Директору ДП «ДІЛОВОД»",
            sender_contacts=(
                "[Вулиця, будинок, квартира]\n"
                "[Місто, індекс]\n"
                "тел.: [+38 0XX XXX XX XX]\n"
                "email: [your@email.com]"
            ),
        ),
        dict(
            category="zvernennya", doc_type="Скарга на дії правоохоронців",
            subject_type="person", title="Скарга на дії правоохоронців",
            description="Процесуальна скарга на неправомірні дії службових осіб",
            icon="i-lucide-shield-alert", sort_order=302,
            title_tpl="Скарга на неправомірні дії (бездіяльність) службових осіб правоохоронних органів",
            body=(
                "Звертаюся до Вас із скаргою на неправомірні дії та бездіяльність "
                "працівників правоохоронних органів.\n"
                "Під час проведення процесуальних дій [Дата/Місце] було допущено істотні "
                "порушення моїх законних прав, що виявилося у [Опис неправомірних дій].\n"
                "Прошу провести службове розслідування за вказаними фактами, вжити заходів "
                "дисциплінарного реагування та повідомити мене про результати розгляду."
            ),
            addressees="Генеральному прокурору\nвул. Різницька, 13/15\nм. Київ, 01011",
            sender_contacts=(
                "[Вулиця, будинок, квартира]\n"
                "[Місто, індекс]\n"
                "тел.: [+38 0XX XXX XX XX]\n"
                "email: [your@email.com]"
            ),
        ),
        dict(
            category="zvernennya", doc_type="Заява",
            subject_type="person", title="Адміністративна скарга",
            description="Оскарження рішення органу виконавчої влади у вищий орган",
            icon="i-lucide-scale", sort_order=303,
            title_tpl="Скарга на рішення [назва органу] від [дата] № [номер]",
            body=(
                "Мені стало відомо про прийняте рішення [назва органу] від [дата] № [номер] "
                "щодо [предмет рішення].\n\n"
                "Вважаю зазначене рішення неправомірним з огляду на наступне:\n"
                "1. [Аргумент 1];\n"
                "2. [Аргумент 2].\n\n"
                "Відповідно до ст. 55 Конституції України та Закону України «Про звернення громадян»,\n"
                "ПРОШУ:\n"
                "1. Скасувати зазначене рішення як протиправне;\n"
                "2. Прийняти рішення, що відповідає вимогам закону."
            ),
            addressees="[Назва вищого органу]\n[Адреса]",
            sender_contacts=(
                "[Вулиця, будинок, квартира]\n"
                "[Місто, індекс]\n"
                "тел.: [+38 0XX XXX XX XX]\n"
                "email: [your@email.com]"
            ),
        ),
        dict(
            category="zvernennya", doc_type="Заява",
            subject_type="person", title="Інформаційний запит",
            description="Запит на отримання публічної інформації відповідно до Закону України",
            icon="i-lucide-search", sort_order=304,
            title_tpl="Запит на отримання публічної інформації",
            body=(
                "Відповідно до Закону України «Про доступ до публічної інформації» прошу надати "
                "наступну публічну інформацію:\n"
                "[Конкретний опис запитуваної інформації]\n\n"
                "Прошу надати відповідь у строк, передбачений законодавством (5 робочих днів).\n"
                "Спосіб отримання: [особисто / поштою / електронною поштою]."
            ),
            addressees="[Розпорядник інформації]\n[Адреса]",
            sender_contacts=(
                "[Вулиця, будинок, квартира]\n"
                "[Місто, індекс]\n"
                "тел.: [+38 0XX XXX XX XX]\n"
                "email: [your@email.com]"
            ),
        ),
        # ── Договірні ───────────────────────────────────────────────────────
        dict(
            category="dohovirni", doc_type="Договір",
            subject_type="legal", title="Договір",
            description="Типовий господарський або цивільно-правовий договір",
            icon="i-lucide-file-signature", sort_order=400,
            title_tpl="Договір [предмет] № [номер]",
            body=(
                "1. ПРЕДМЕТ ДОГОВОРУ\n"
                "1.1. [Сторона 1] зобов'язується [дія], а [Сторона 2] — прийняти та оплатити.\n\n"
                "2. ЦІНА ДОГОВОРУ\n"
                "2.1. Загальна вартість становить [сума] грн, у т.ч. ПДВ 20%.\n\n"
                "3. СТРОКИ ВИКОНАННЯ\n"
                "3.1. Строк виконання: з [дата] по [дата].\n\n"
                "4. ВІДПОВІДАЛЬНІСТЬ СТОРІН\n"
                "4.1. У разі порушення умов договору винна сторона сплачує пеню у розмірі "
                "[відсоток]% від суми заборгованості.\n\n"
                "5. ФОРС-МАЖОР\n"
                "5.1. Сторони звільняються від відповідальності за невиконання зобов'язань "
                "у разі обставин непереборної сили.\n\n"
                "6. РЕКВІЗИТИ СТОРІН\n"
                "Сторона 1: [реквізити]\n"
                "Сторона 2: [реквізити]"
            ),
        ),
        dict(
            category="dohovirni", doc_type="Угода",
            subject_type="legal", title="Угода",
            description="Угода між сторонами про врегулювання відносин",
            icon="i-lucide-handshake", sort_order=401,
            title_tpl="Угода про [предмет] № [номер]",
            body=(
                "Сторони, що підписали цю угоду:\n"
                "[Сторона 1] в особі [ПІБ],\n"
                "[Сторона 2] в особі [ПІБ],\n\n"
                "ДОМОВИЛИСЯ про наступне:\n"
                "1. [Умова 1];\n"
                "2. [Умова 2];\n"
                "3. Угода набирає чинності з моменту підписання обома сторонами."
            ),
        ),
        dict(
            category="dohovirni", doc_type="Додаткова угода",
            subject_type="legal", title="Додаткова угода",
            description="Внесення змін або доповнень до чинного договору",
            icon="i-lucide-file-plus", sort_order=402,
            title_tpl="Додаткова угода № [номер] до договору № [номер] від [дата]",
            body=(
                "Сторони домовились внести до договору № [номер] від [дата] такі зміни:\n"
                "1. Пункт [X.X] договору викласти в новій редакції:\n"
                "«[нова редакція пункту]».\n"
                "2. Доповнити договір пунктом [X.X] такого змісту:\n"
                "«[зміст нового пункту]».\n\n"
                "У решті умови договору залишаються без змін.\n"
                "Дана угода є невід'ємною частиною договору."
            ),
        ),
        # ── Нормативні ──────────────────────────────────────────────────────
        dict(
            category="normatyvni", doc_type="Положення",
            subject_type="legal", title="Положення про підрозділ",
            description="Положення про підрозділ, комісію або порядок роботи",
            icon="i-lucide-book-marked", sort_order=500,
            title_tpl="Положення про [назва підрозділу/органу]",
            body=(
                "РОЗДІЛ I. ЗАГАЛЬНІ ПОЛОЖЕННЯ\n"
                "1.1. [Назва] є [правовий статус].\n"
                "1.2. У своїй діяльності керується [нормативна база].\n\n"
                "РОЗДІЛ II. ЗАВДАННЯ ТА ФУНКЦІЇ\n"
                "2.1. Основними завданнями є:\n[перелік завдань].\n\n"
                "РОЗДІЛ III. ПРАВА ТА ОБОВ'ЯЗКИ\n"
                "3.1. [Назва] має право:\n[перелік прав].\n"
                "3.2. [Назва] зобов'язана:\n[перелік обов'язків].\n\n"
                "РОЗДІЛ IV. ВІДПОВІДАЛЬНІСТЬ\n"
                "4.1. [Умови відповідальності]."
            ),
        ),
        dict(
            category="normatyvni", doc_type="Інструкція",
            subject_type="legal", title="Інструкція",
            description="Нормативна інструкція з порядку виконання роботи або процесу",
            icon="i-lucide-list-checks", sort_order=501,
            title_tpl="Інструкція з [предмет]",
            body=(
                "1. ЗАГАЛЬНІ ПОЛОЖЕННЯ\n"
                "1.1. Ця інструкція визначає порядок [предмет].\n"
                "1.2. Дія інструкції поширюється на [коло осіб або підрозділів].\n\n"
                "2. ПОРЯДОК ВИКОНАННЯ\n"
                "2.1. [Крок 1].\n"
                "2.2. [Крок 2].\n"
                "2.3. [Крок 3].\n\n"
                "3. ВІДПОВІДАЛЬНІСТЬ\n"
                "3.1. Відповідальність за дотримання інструкції покладається на [посада]."
            ),
        ),
        dict(
            category="normatyvni", doc_type="Посадова інструкція",
            subject_type="legal", title="Посадова інструкція",
            description="Посадова інструкція працівника з правами, обов'язками та вимогами",
            icon="i-lucide-user-cog", sort_order=502,
            title_tpl="Посадова інструкція [назва посади]",
            body=(
                "1. ЗАГАЛЬНІ ПОЛОЖЕННЯ\n"
                "1.1. [Посада] відноситься до категорії [категорія].\n"
                "1.2. Призначається та звільняється наказом [посада керівника].\n"
                "1.3. Підпорядковується безпосередньо [посада].\n\n"
                "2. ПОСАДОВІ ОБОВ'ЯЗКИ\n"
                "2.1. [Обов'язок 1].\n"
                "2.2. [Обов'язок 2].\n\n"
                "3. ПРАВА\n"
                "3.1. [Право 1].\n"
                "3.2. [Право 2].\n\n"
                "4. ВІДПОВІДАЛЬНІСТЬ\n"
                "4.1. [Посада] несе відповідальність за [перелік].\n\n"
                "5. КВАЛІФІКАЦІЙНІ ВИМОГИ\n"
                "5.1. Освіта: [вимоги].\n"
                "5.2. Досвід роботи: [вимоги]."
            ),
        ),
        # ── Стилі та підказки ────────────────────────────────────────────────
        dict(
            category="stylevi", doc_type="Підказка",
            subject_type="legal", title="Юридичний стиль написання",
            description="Правила юридичного стилю для офіційних документів",
            icon="i-lucide-scale", sort_order=600,
            title_tpl="[Назва документа]",
            body=(
                "ЮРИДИЧНИЙ СТИЛЬ — ОСНОВНІ ПРАВИЛА\n\n"
                "1. ТОЧНІСТЬ ТА ОДНОЗНАЧНІСТЬ\n"
                "   • Уникайте слів з подвійним тлумаченням.\n"
                "   • Використовуйте терміни у значенні, закріпленому законом.\n"
                "   • Числа та дати пишіть цифрами і літерами: «5 (п'ять)».\n"
                "   • Уникайте займенників — замінюйте їх на повну назву сторони.\n\n"
                "2. ОФІЦІЙНО-ДІЛОВИЙ РЕГІСТР\n"
                "   • Не вживайте розмовних слів, жаргону, скорочень без розшифрування.\n"
                "   • Дієслова — переважно у наказовому або зобов'язувальному способі:\n"
                "     «зобов'язується», «має право», «несе відповідальність».\n"
                "   • Речення — повні, без еліпсів.\n\n"
                "3. СТРУКТУРА ДОКУМЕНТА\n"
                "   • Преамбула → Права → Обов'язки → Відповідальність → Підписи.\n"
                "   • Кожен пункт — одна думка. Підпункти нумеруйте: 1.1, 1.2…\n"
                "   • Посилання на закон: «відповідно до ст. 15 Закону України від 16.07.1999 № 996-XIV».\n\n"
                "4. ЗАБОРОНИ\n"
                "   • Не вживайте: «і т.д.», «тощо» — перераховуйте повністю або\n"
                "     пишіть «у тому числі, але не виключно».\n"
                "   • Не скорочуйте назви органів без попереднього розкриття абревіатури.\n"
                "   • Не вживайте оцінних прикметників («хороший», «великий»).\n\n"
                "5. МОВА\n"
                "   • Документ — виключно державною мовою (Закон № 2704-VIII).\n"
                "   • Іноземні терміни — лише за відсутності українського відповідника,\n"
                "     з поясненням у дужках при першому вживанні."
            ),
        ),
        dict(
            category="stylevi", doc_type="Підказка",
            subject_type="legal", title="Офіційно-діловий стиль",
            description="Загальні правила офіційно-ділового стилю листування та документів",
            icon="i-lucide-briefcase", sort_order=601,
            title_tpl="[Назва документа]",
            body=(
                "ОФІЦІЙНО-ДІЛОВИЙ СТИЛЬ — ПРАВИЛА\n\n"
                "1. ЗОВНІШНІЙ ВИГЛЯД\n"
                "   • Шрифт: Times New Roman або Arial, 12–14 pt.\n"
                "   • Міжрядковий інтервал: 1,5 для основного тексту.\n"
                "   • Абзацний відступ: 1,25 см.\n"
                "   • Поля: ліве 30 мм, праве 10 мм, верхнє і нижнє 20 мм (ДСТУ 4163).\n\n"
                "2. ЗВЕРТАННЯ\n"
                "   • Офіційне: «Шановний(а) [Ім'я по батькові]!»\n"
                "   • До органу: «Шановні колеги!» або без звертання.\n"
                "   • Закінчення: «З повагою,» або «Залишаємось із повагою,».\n\n"
                "3. ПОБУДОВА АБЗАЦІВ\n"
                "   • Перший абзац — суть звернення (хто, до кого, з якого приводу).\n"
                "   • Основна частина — факти, аргументи, хронологія.\n"
                "   • Заключний абзац — конкретне прохання або очікувані дії.\n\n"
                "4. ЧИСЛА І ДАТИ\n"
                "   • Дата: «19 липня 2026 р.» або «19.07.2026».\n"
                "   • Час: «14:30» (24-годинний формат).\n"
                "   • Суми: «25 000,00 грн (двадцять п'ять тисяч гривень 00 коп.)».\n\n"
                "5. ТИПОВІ КЛІШЕ\n"
                "   Початок: «Звертаємося до Вас з приводу…», «На виконання…»\n"
                "   Посилання: «Відповідно до…», «Згідно з…», «На підставі…»\n"
                "   Прохання: «Просимо розглянути…», «Прошу надати…»\n"
                "   Відповідь: «У відповідь на Ваш лист від… № …»"
            ),
        ),
        dict(
            category="stylevi", doc_type="Підказка",
            subject_type="legal", title="Правила написання наказу",
            description="Структура та обов'язкові реквізити наказу відповідно до ДСТУ 4163",
            icon="i-lucide-file-badge", sort_order=602,
            title_tpl="Наказ",
            body=(
                "СТРУКТУРА НАКАЗУ (ДСТУ 4163:2020)\n\n"
                "ОБОВ'ЯЗКОВІ РЕКВІЗИТИ:\n"
                "01 — Найменування організації\n"
                "04 — Назва виду документа: НАКАЗ\n"
                "11 — Дата документа: 19 липня 2026 р.\n"
                "12 — Реєстраційний індекс: № 25-ОД\n"
                "25 — Заголовок: «Про надання відпустки» (без крапки)\n"
                "28 — Текст\n"
                "22 — Підпис\n\n"
                "СТРУКТУРА ТЕКСТУ:\n"
                "• Констатуюча частина (може бути відсутня для наказів\n"
                "  з кадрових питань): «У зв'язку з…», «На підставі…»\n"
                "• Розпорядча частина починається словом НАКАЗУЮ: (двокрапка,\n"
                "  далі з нового рядка нумеровані пункти)\n"
                "• Останній пункт — контроль: «Контроль за виконанням наказу\n"
                "  залишаю за собою» або «покласти на [ПІБ, посада]».\n\n"
                "ВАЖЛИВО:\n"
                "   • Заголовок відповідає на питання «про що?».\n"
                "   • Виконавці у пунктах — у давальному відмінку: «зобов'язати\n"
                "     Петренка І.В.» або «доручити відділу кадрів».\n"
                "   • Строки — конкретні дати, не «у найкоротший термін».\n"
                "   • Якщо наказ скасовує інший — вказати: «Наказ № … від … вважати\n"
                "     таким, що втратив чинність»."
            ),
        ),
        dict(
            category="stylevi", doc_type="Підказка",
            subject_type="legal", title="Правила написання листа",
            description="Реквізити та структура службового листа за ДСТУ 4163",
            icon="i-lucide-mail-open", sort_order=603,
            title_tpl="Лист",
            body=(
                "СЛУЖБОВИЙ ЛИСТ — СТРУКТУРА (ДСТУ 4163:2020)\n\n"
                "РЕКВІЗИТИ (порядок зліва направо, зверху вниз):\n"
                "01 — Зображення герба / логотипу\n"
                "07 — Найменування організації\n"
                "11 — Дата: 19.07.2026\n"
                "12 — Реєстраційний індекс: № 01-14/256\n"
                "13 — Посилання на вхідний лист (якщо відповідь)\n"
                "16 — Адресат (у правому верхньому кутку)\n"
                "25 — Заголовок\n"
                "28 — Текст\n"
                "33 — Відмітка про наявність додатків\n"
                "22 — Підпис\n\n"
                "АДРЕСАТ — ФОРМАТ:\n"
                "   Директору\n"
                "   ТОВ «Назва»\n"
                "   Пану/Пані [Ім'я по батькові]\n"
                "(якщо відомий конкретний отримувач — у давальному відмінку)\n\n"
                "СТРУКТУРА ТЕКСТУ:\n"
                "   1. Вступ: мета звернення\n"
                "   2. Основна частина: факти, обґрунтування\n"
                "   3. Висновок: конкретне прохання / очікувана дія\n\n"
                "ВИХІДНИЙ ІНДЕКС: складається з кодів структурного підрозділу,\n"
                "виду листування та порядкового номера: «01-12/87».\n\n"
                "МОВА ЗВЕРТАННЯ:\n"
                "   «Шановний Іване Петровичу!» — якщо особисте.\n"
                "   «Шановні колеги!» — якщо колективне.\n"
                "   «Просимо…» — у множині від організації.\n"
                "   «Прошу…» — від конкретної посадової особи."
            ),
        ),
        dict(
            category="stylevi", doc_type="Підказка",
            subject_type="person", title="Правила написання заяви громадянина",
            description="Структура заяви до органу влади відповідно до Закону про звернення громадян",
            icon="i-lucide-user-pen", sort_order=604,
            title_tpl="Заява",
            body=(
                "ЗАЯВА ГРОМАДЯНИНА — ПРАВИЛА (Закон України «Про звернення громадян»)\n\n"
                "ОБОВ'ЯЗКОВІ РЕКВІЗИТИ (ст. 5):\n"
                "   1. ПІБ автора (Прізвище, Ім'я, По батькові).\n"
                "   2. Місце проживання (адреса).\n"
                "   3. Суть питання (конкретні зауваження, пропозиції, заяви, скарги чи вимоги).\n"
                "   4. Письмове звернення: повинно бути підписано заявником із зазначенням дати.\n"
                "   5. Електронне звернення: обов'язково зазначається електронна адреса (email) "
                "або інші контакти для відповіді. Накладання КЕП (електронного підпису) НЕ є обов'язковим.\n\n"
                "РЕКВІЗИТИ «ШАПКИ» (верхній правий кут):\n"
                "   [Посада та ПІБ керівника органу, куди звертаєтесь]\n"
                "   [Повна назва органу]\n"
                "   [Адреса органу]\n"
                "   від [ПІБ заявника у родовому відмінку]\n"
                "   який(яка) мешкає: [адреса]\n"
                "   тел.: [номер]\n"
                "   email: [адреса]\n\n"
                "НАЗВА ДОКУМЕНТА:\n"
                "   ЗАЯВА\n"
                "   (по центру, великими літерами, без крапки)\n\n"
                "ПОРЯДОК РОЗГЛЯДУ ТА ПЕРЕАДРЕСАЦІЇ (ст. 5, ст. 7):\n"
                "   • Недотримання вимог: Звернення, оформлене з порушенням ст. 5, повертається заявнику "
                "з роз'ясненнями не пізніш як через 10 днів від дня надходження.\n"
                "   • Відсутність повноважень: Якщо питання не входять до компетенції органу, звернення "
                "протягом 5 днів пересилається компетентному органу, про що повідомляється заявник.\n"
                "   • Заборона пересилання скарги: Категорично заборонено направляти скаргу на розгляд тим "
                "органам або посадовим особам, дії чи рішення яких оскаржуються.\n\n"
                "СТРОКИ РОЗГЛЯДУ (ст. 20):\n"
                "   • Загальний строк — не більше 30 днів від дня надходження.\n"
                "   • Звернення, які не потребують додаткового вивчення — невідкладно, але не пізніше 15 днів.\n\n"
                "ЗАБОРОНЕНІ ФОРМУЛЮВАННЯ:\n"
                "   • Образи, лайка, заклики до ворожнечі (такі звернення залишаються без розгляду).\n"
                "   • Анонімні звернення (без зазначення ПІБ чи адреси) розгляду не підлягають."
            ),
        ),
        dict(
            category="stylevi", doc_type="Підказка",
            subject_type="legal", title="Правила написання протоколу",
            description="Реквізити та структура протоколу засідання за ДСТУ 4163",
            icon="i-lucide-clipboard-list", sort_order=605,
            title_tpl="Протокол",
            body=(
                "ПРОТОКОЛ ЗАСІДАННЯ — СТРУКТУРА\n\n"
                "РЕКВІЗИТИ:\n"
                "   Назва органу або організації\n"
                "   ПРОТОКОЛ\n"
                "   [дата]                  № [номер]\n"
                "   [місце проведення]\n\n"
                "   Голова: [ПІБ]\n"
                "   Секретар: [ПІБ]\n"
                "   Присутні: [ПІБ у називному відмінку, через кому]\n"
                "   (якщо > 15 осіб — «N осіб, список додається»)\n\n"
                "ПОРЯДОК ДЕННИЙ:\n"
                "   1. [Питання 1]     Доповідач: [ПІБ]\n"
                "   2. [Питання 2]     Доповідач: [ПІБ]\n\n"
                "ОСНОВНА ЧАСТИНА (повторюється для кожного питання):\n"
                "   1. СЛУХАЛИ:\n"
                "   [ПІБ] — [короткий виклад від 3-ї особи]\n\n"
                "   ВИСТУПИЛИ:\n"
                "   [ПІБ] — [зміст виступу]\n\n"
                "   ВИРІШИЛИ:\n"
                "   1.1. [Рішення від інфінітива: «Затвердити…», «Доручити…»]\n"
                "   Результати голосування: «за» — X, «проти» — 0, «утримались» — 0.\n\n"
                "ПІДПИСИ:\n"
                "   Голова        ________  [ПІБ]\n"
                "   Секретар      ________  [ПІБ]\n\n"
                "ВАЖЛИВО:\n"
                "   • Дієслова рішень — у формі інфінітива: «затвердити», «зобов'язати».\n"
                "   • Виступи — від третьої особи: «[ПІБ] зазначив(ла), що…»\n"
                "   • Протокол підписується у день засідання або наступного дня."
            ),
        ),
        dict(
            category="stylevi", doc_type="Підказка",
            subject_type="legal", title="Правила написання договору",
            description="Обов'язкова структура та юридичні вимоги до договору",
            icon="i-lucide-file-signature", sort_order=606,
            title_tpl="Договір",
            body=(
                "ДОГОВІР — ЮРИДИЧНІ ВИМОГИ\n\n"
                "ОБОВ'ЯЗКОВІ РОЗДІЛИ:\n"
                "1. ПРЕАМБУЛА\n"
                "   «[Назва Сторони 1], в особі [посада, ПІБ], який(яка) діє на підставі\n"
                "   [Статуту/довіреності № від], далі — «Замовник», з одного боку, та\n"
                "   [Назва Сторони 2]…, далі — «Виконавець», з іншого боку,\n"
                "   уклали цей Договір про наступне:»\n\n"
                "2. ПРЕДМЕТ ДОГОВОРУ\n"
                "   Чітко, що саме, в якому обсязі, до якого строку.\n\n"
                "3. ЦІНА ТА ПОРЯДОК РОЗРАХУНКІВ\n"
                "   Сума, валюта, ПДВ, строки оплати, реквізити.\n\n"
                "4. ПРАВА ТА ОБОВ'ЯЗКИ СТОРІН\n"
                "   Для кожної сторони окремим підрозділом.\n\n"
                "5. ВІДПОВІДАЛЬНІСТЬ СТОРІН\n"
                "   Пеня (% від суми за день), штраф (фіксована сума), обмеження.\n\n"
                "6. ФОРС-МАЖОР\n"
                "   Перелік обставин + порядок сповіщення (строк 3–7 днів).\n\n"
                "7. СТРОК ДІЇ ТА ПОРЯДОК РОЗІРВАННЯ\n"
                "   Дата набрання чинності, строк, умови дострокового розірвання.\n\n"
                "8. РЕКВІЗИТИ ТА ПІДПИСИ СТОРІН\n"
                "   Юридична адреса, ЄДРПОУ, IBAN, тел., email, підписи + печатки.\n\n"
                "ВАЖЛИВО:\n"
                "   • Назви сторін у тексті — скорочено («Замовник», «Виконавець»),\n"
                "     але ОДНАКОВО по всьому тексту.\n"
                "   • Після підписання — кожній стороні по 1 примірнику.\n"
                "   • Зміни — лише письмовою Додатковою угодою."
            ),
        ),
        dict(
            category="stylevi", doc_type="Підказка",
            subject_type="legal", title="Оформлення реквізитів за ДСТУ 4163",
            description="Обов'язкові реквізити службових документів за чинним ДСТУ",
            icon="i-lucide-ruler", sort_order=607,
            title_tpl="[Назва документа]",
            body=(
                "ОФОРМЛЕННЯ РЕКВІЗИТІВ ЗА ДСТУ 4163:2020\n\n"
                "1. ОБОВ'ЯЗКОВІ РЕКВІЗИТИ (для юридичної сили):\n"
                "   • Найменування організації (04).\n"
                "   • Назва виду документа (09) — УВАГА: не зазначається на листах!\n"
                "   • Дата документа (10) та реєстраційний індекс (11).\n"
                "   • Заголовок до тексту (19) та сам текст документа (20).\n"
                "   • Підпис (22). Для електронних документів — електронний підпис або печатка.\n\n"
                "2. ГЕОМЕТРІЯ ТА ПОЛЯ СТОРІНКИ (§6.1, §6.2):\n"
                "   • Формати паперу: А4 (210×297), А5 (210×148), допустимо А3 (297×420) для таблиць.\n"
                "   • Поля: Ліве — 30 мм, Праве — 10 мм, Верхнє та Нижнє — по 20 мм.\n"
                "   • Точність: Допуск розташування реквізитів становить ±2 мм (§6.5).\n\n"
                "3. ТИПОГРАФІКА ТА СПРАЙТИНГ (§7.2, §7.3, §7.6):\n"
                "   • Гарнітура: Times New Roman, колір чорний. Підкреслення реквізитів бланка рискою ЗАБОРОНЕНО.\n"
                "   • Розміри шрифту (pt):\n"
                "     - Основний текст: 12–14 pt.\n"
                "     - Довідкові дані, виноски, виконавець: 8–12 pt.\n"
                "     - Назва виду документа: 14–16 pt (великими розрідженими літерами).\n"
                "   • Міжрядковий інтервал: для А4 — 1.0–1.5 інтервали; для А5 — строго 1.0.\n"
                "   • Рядки реквізитів: максимум 28 знаків (довжина рядка до 73 мм) для багаторядкових реквізитів.\n\n"
                "4. ВІДСТУПИ ВІД ЛІВОГО ПОЛЯ (§7.7):\n"
                "   • Абзацний відступ тексту — 10 мм.\n"
                "   • Реквізит «Адресат» — 90 мм.\n"
                "   • Гриф затвердження та обмеження доступу — 100 мм.\n"
                "   • Розшифрування підпису (ПІБ) — 125 мм.\n\n"
                "5. НУМЕРАЦІЯ СТОРІНОК (§7.10):\n"
                "   • Починаючи з 2-ї сторінки, номери проставляються посередині верхнього поля арабськими цифрами.\n"
                "   • Номер пишеться БЕЗ слова «сторінка»/«стор.» та крапок. Перша сторінка не нумерується.\n\n"
                "6. СТОРОНА ДРУКУ ТА ЗБЕРІГАННЯ (§7.11):\n"
                "   • Постійне та тривале зберігання (>10 років): Тільки односторонній друк.\n"
                "   • Тимчасове зберігання (до 10 років включно): Дозволено двосторонній друк.\n\n"
                "7. ОБМЕЖЕННЯ АДРЕСАТІВ ТА ДОДАТКІВ (§5.15, §5.21):\n"
                "   • Адресати: не більше 4 отримувачів. Якщо більше — складається список розсилання.\n"
                "   • Додатки: якщо кількість додатків перевищує 10, обов'язково складається опис додатків.\n\n"
                "8. ГЕРБИ, QR-КОДИ ТА ЗОНИ (§5.1, §5.10, §5.31):\n"
                "   • Державний герб: 17×12 мм. Емблема: висота ≤17 мм.\n"
                "   • QR-код: розмір 21×21 мм.\n"
                "   • Зона держреєстрації (верхній правий кут): вільне місце розміром 60×100 мм."
            ),
        ),
        dict(
            category="stylevi", doc_type="Підказка",
            subject_type="legal", title="Типові мовні звороти та кліше",
            description="Готові формулювання для різних частин офіційних документів",
            icon="i-lucide-quote", sort_order=608,
            title_tpl="[Назва документа]",
            body=(
                "МОВНІ КЛІШЕ ОФІЦІЙНИХ ДОКУМЕНТІВ\n\n"
                "ПОЧАТОК / ПОСИЛАННЯ:\n"
                "   • «Відповідно до статті [X] Закону України «[Назва]»…»\n"
                "   • «Згідно з наказом [органу] від [дата] № [номер]…»\n"
                "   • «На виконання доручення [посада] від [дата]…»\n"
                "   • «Керуючись [норма], [орган] вирішує:»\n"
                "   • «З метою [мета], на підставі [підстава]…»\n\n"
                "ПРОХАННЯ / ВИМОГА:\n"
                "   • «Просимо розглянути та надати відповідь у встановлений строк.»\n"
                "   • «Прошу вжити заходів щодо [дія].»\n"
                "   • «Пропонуємо укласти договір на таких умовах:»\n"
                "   • «Зобов'язуємо [ПІБ/підрозділ] забезпечити [дія] до [дата].»\n\n"
                "ВІДМОВА / РОЗ'ЯСНЕННЯ:\n"
                "   • «Повідомляємо, що у задоволенні Вашого прохання відмовлено у\n"
                "     зв'язку з [підстава].»\n"
                "   • «Роз'яснюємо, що відповідно до [норма]…»\n"
                "   • «Зазначене прохання виходить за межі повноважень [орган].»\n\n"
                "ЗАВЕРШЕННЯ:\n"
                "   • «З повагою,» / «З щирою повагою,»\n"
                "   • «Сподіваємося на плідну співпрацю.»\n"
                "   • «Залишаємося у Вашому розпорядженні.»\n"
                "   • «Додатки: на [X] арк. у [Y] прим.»\n\n"
                "ПОСИЛАННЯ НА ДОДАТКИ В ТЕКСТІ:\n"
                "   «…(додаток 1)» або «…(див. додаток)»\n"
                "   Окремий реквізит «Додаток:» оформлюється після тексту:\n"
                "   «Додаток: Копія свідоцтва на 2 арк. в 1 прим.»"
            ),
        ),
    ]

    with SessionLocal() as session:
        existing_titles = {t.title for t in session.query(DocTemplate.title).all()}
        to_add = [
            DocTemplate(
                category=d["category"],
                doc_type=d["doc_type"],
                subject_type=d.get("subject_type", "legal"),
                title=d["title"],
                description=d.get("description", ""),
                icon=d.get("icon", "i-lucide-file-text"),
                title_tpl=d.get("title_tpl", ""),
                body=d.get("body", ""),
                addressees=d.get("addressees"),
                sender_contacts=d.get("sender_contacts"),
                is_builtin=True,
                sort_order=d.get("sort_order", 0),
            )
            for d in TEMPLATES
            if d["title"] not in existing_titles
        ]
        if to_add:
            session.add_all(to_add)
            session.commit()

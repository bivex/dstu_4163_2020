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

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

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
    sessionmaker,
)

DATABASE_URL = os.environ.get("PORTAL_DATABASE_URL", "sqlite:////data/portal.db")

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
    password_hash: Mapped[str] = mapped_column(String(128))
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
    if "signers" in insp.get_table_names():
        scols = {c["name"] for c in insp.get_columns("signers")}
        with engine.begin() as conn:
            if "valid_from" not in scols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN valid_from VARCHAR(64)"))
            if "valid_to" not in scols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN valid_to VARCHAR(64)"))
    # сіємо дефолтного адміна якщо таблиця users порожня
    _seed_default_admin()
    # сіємо дефолтних контрагентів
    _seed_default_counterparties()
    # сіємо дефолтні реєстраційні журнали
    _seed_default_journals()


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
            return
        user = User(
            email=default_email,
            name="Адміністратор",
            password_hash=User.hash_password(default_pass),
        )
        session.add(user)
        session.commit()


def _seed_default_counterparties() -> None:
    """Створити дефолтних контрагентів якщо таблиця порожня."""
    with SessionLocal() as session:
        if session.query(Counterparty).first():
            return
        c1 = Counterparty(
            name='ТОВ "Дія Консалтинг"',
            code="12345678",
            subject_type="legal",
            email="info@diaconsulting.com.ua",
            phone="+380441112233",
            address="м. Київ, вул. Хрещатик, 1",
        )
        c2 = Counterparty(
            name='АТ "Укрпошта"',
            code="21560043",
            subject_type="legal",
            email="ukrposhta@ukrposhta.ua",
            phone="+380442223344",
            address="м. Київ, вул. Хрещатик, 22",
        )
        c3 = Counterparty(
            name="ФОП Шевченко Тарас Григорович",
            code="3012345678",
            subject_type="fop",
            email="shevchenko@gmail.com",
            phone="+380998887766",
            address="м. Канів, вул. Шевченка, 10",
        )
        session.add_all([c1, c2, c3])
        session.commit()

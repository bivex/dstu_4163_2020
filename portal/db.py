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
    PENDING_SIGNATURES = "pending_signatures"  # очікує підписів у черзі
    SIGNED = "signed"  # усі підписали
    PUBLISHED = "published"  # оприлюднено (ст.14 996-XIV / ст.15 2939-VI)


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
    status: Mapped[DocStatus] = mapped_column(Enum(DocStatus), default=DocStatus.DRAFT)
    fmt: Mapped[str] = mapped_column(String(8), default="pdf")  # pdf | docx
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

    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
    # ст.13 Закону 851-IV: строк зберігання (≥ паперового відповідника)
    retention_until: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    signers: Mapped[list["Signer"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Signer.order_index"
    )
    events: Mapped[list["AuditEvent"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="AuditEvent.created_at"
    )

    @property
    def next_signer(self) -> "Signer | None":
        """Наступний у черзі підписант (INVITED або перший WAITING)."""
        for s in self.signers:
            if s.status in (SignerStatus.INVITED, SignerStatus.WAITING):
                return s
        return None


class Signer(Base):
    __tablename__ = "signers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)  # порядок у черзі (0,1,2…)
    full_name: Mapped[str] = mapped_column(String(256))  # ПІБ підписувача
    position: Mapped[str] = mapped_column(String(256), default="")  # посада (необовʼязково)
    status: Mapped[SignerStatus] = mapped_column(
        Enum(SignerStatus), default=SignerStatus.WAITING
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
    if "signers" in insp.get_table_names():
        scols = {c["name"] for c in insp.get_columns("signers")}
        with engine.begin() as conn:
            if "valid_from" not in scols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN valid_from VARCHAR(64)"))
            if "valid_to" not in scols:
                conn.execute(text("ALTER TABLE signers ADD COLUMN valid_to VARCHAR(64)"))
    # сіємо дефолтного адміна якщо таблиця users порожня
    _seed_default_admin()


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

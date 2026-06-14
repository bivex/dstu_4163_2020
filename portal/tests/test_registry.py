"""Unit-тести модуля реєстрації (portal.registry).

Покривають логіку авто-індексів на рівні функцій (без HTTP), з ізольованою
in-memory БД на кожен тест:
- літерний суфікс індексу за кожним типом документа (ПКМУ № 55/2018);
- наскрізна нумерація в межах типу (накази 1-од, 2-од…);
- незалежність послідовностей різних типів;
- щорічне скидання лічильника (новий діловодний рік → з 1);
- ідемпотентність assign_registration (повторний виклик не змінює номер);
- невідомий тип документа → чистий номер без суфікса;
- словесно-цифровий формат дати ДСТУ для всіх 12 місяців.
"""

from __future__ import annotations

import datetime as dt
import importlib
import sys
from pathlib import Path

import pytest

_PORTAL = Path(__file__).resolve().parents[1]  # каталог portal/
if str(_PORTAL.parent) not in sys.path:
    sys.path.insert(0, str(_PORTAL.parent))


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """Свіжа ізольована БД + перезавантажені модулі portal.db / portal.registry."""
    db_file = tmp_path / "registry_test.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")
    for mod in ("portal.db", "portal.registry"):
        if mod in sys.modules:
            del sys.modules[mod]
    db_mod = importlib.import_module("portal.db")
    db_mod.init_db()
    return db_mod


def _make_doc(db_mod, doc_id: str, doc_type: str = "Наказ"):
    """Створити мінімальний Document у БД (без рендеру), повернути його."""
    with db_mod.SessionLocal() as session:
        doc = db_mod.Document(
            doc_id=doc_id,
            title=f"Тест {doc_id}",
            fmt="pdf",
            status=db_mod.DocStatus.DRAFT,
            content_json="{}",
        )
        session.add(doc)
        session.commit()
        return doc.id


def _register(db_mod, registry, internal_id: int, doc_type: str,
              when: dt.datetime | None = None) -> dict:
    """Зареєструвати документ за внутрішнім id; повернути присвоєні поля."""
    with db_mod.SessionLocal() as session:
        doc = session.get(db_mod.Document, internal_id)
        registry.assign_registration(session, doc, doc_type, when=when)
        session.commit()
        return {
            "reg_index": doc.reg_index,
            "reg_number": doc.reg_number,
            "reg_date": doc.reg_date,
            "doc_type": doc.doc_type,
            "registered_at": doc.registered_at,
        }


# --- суфікс за типом документа ---------------------------------------------

@pytest.mark.parametrize(
    "doc_type,expected_index",
    [
        ("Наказ", "1-од"),
        ("Розпорядження", "1-р"),
        ("Доповідна записка", "1-дз"),
        ("Службова записка", "1-сз"),
        ("Протокол", "1"),
        ("Акт", "1"),
        ("Лист", "1"),
    ],
)
def test_index_suffix_per_type(db, doc_type, expected_index):
    """Кожен тип отримує свій літерний суфікс (або чистий номер)."""
    from portal import registry

    internal_id = _make_doc(db, "D-1", doc_type)
    res = _register(db, registry, internal_id, doc_type)
    assert res["reg_index"] == expected_index
    assert res["reg_number"] == 1
    assert res["doc_type"] == doc_type


def test_unknown_type_gets_plain_number(db):
    """Невідомий тип документа → чистий порядковий номер без суфікса."""
    from portal import registry

    internal_id = _make_doc(db, "D-X", "Розпорядчий лист щастя")
    res = _register(db, registry, internal_id, "Розпорядчий лист щастя")
    assert res["reg_index"] == "1"


# --- наскрізна нумерація в межах типу --------------------------------------

def test_sequential_numbering_same_type(db):
    """Накази нумеруються наскрізно: 1-од, 2-од, 3-од."""
    from portal import registry

    indices = []
    for i in range(1, 4):
        iid = _make_doc(db, f"N-{i}", "Наказ")
        indices.append(_register(db, registry, iid, "Наказ")["reg_index"])
    assert indices == ["1-од", "2-од", "3-од"]


def test_independent_sequences_per_type(db):
    """Різні типи мають незалежні лічильники (наказ і лист — кожен з 1)."""
    from portal import registry

    n1 = _register(db, registry, _make_doc(db, "N-1", "Наказ"), "Наказ")
    l1 = _register(db, registry, _make_doc(db, "L-1", "Лист"), "Лист")
    n2 = _register(db, registry, _make_doc(db, "N-2", "Наказ"), "Наказ")
    l2 = _register(db, registry, _make_doc(db, "L-2", "Лист"), "Лист")
    r1 = _register(db, registry, _make_doc(db, "R-1", "Розпорядження"), "Розпорядження")
    assert n1["reg_index"] == "1-од"
    assert n2["reg_index"] == "2-од"
    assert l1["reg_index"] == "1"
    assert l2["reg_index"] == "2"
    assert r1["reg_index"] == "1-р"


def test_next_reg_number_helper(db):
    """next_reg_number повертає MAX+1 у межах типу й року."""
    from portal import registry

    year = dt.datetime.now(dt.timezone.utc).year
    with db.SessionLocal() as session:
        assert registry.next_reg_number(session, "Наказ", year) == 1
    _register(db, registry, _make_doc(db, "N-1", "Наказ"), "Наказ")
    _register(db, registry, _make_doc(db, "N-2", "Наказ"), "Наказ")
    with db.SessionLocal() as session:
        assert registry.next_reg_number(session, "Наказ", year) == 3
        # інший тип — окремий лічильник
        assert registry.next_reg_number(session, "Лист", year) == 1


# --- щорічне скидання лічильника -------------------------------------------

def test_yearly_counter_reset(db):
    """Новий діловодний рік → лічильник стартує з 1 (наскрізна нумерація річна)."""
    from portal import registry

    y2025 = dt.datetime(2025, 12, 30, tzinfo=dt.timezone.utc)
    y2026 = dt.datetime(2026, 1, 5, tzinfo=dt.timezone.utc)
    a = _register(db, registry, _make_doc(db, "N-25a", "Наказ"), "Наказ", when=y2025)
    b = _register(db, registry, _make_doc(db, "N-25b", "Наказ"), "Наказ", when=y2025)
    c = _register(db, registry, _make_doc(db, "N-26a", "Наказ"), "Наказ", when=y2026)
    assert a["reg_index"] == "1-од"
    assert b["reg_index"] == "2-од"
    assert c["reg_index"] == "1-од"  # 2026 рік — лічильник з 1


def test_year_isolation_in_next_number(db):
    """next_reg_number фільтрує за роком: документи 2025 не впливають на 2026."""
    from portal import registry

    y2025 = dt.datetime(2025, 6, 1, tzinfo=dt.timezone.utc)
    _register(db, registry, _make_doc(db, "N-25", "Наказ"), "Наказ", when=y2025)
    with db.SessionLocal() as session:
        assert registry.next_reg_number(session, "Наказ", 2025) == 2
        assert registry.next_reg_number(session, "Наказ", 2026) == 1


# --- ідемпотентність -------------------------------------------------------

def test_assign_idempotent(db):
    """Повторний assign_registration не змінює вже присвоєний номер/дату."""
    from portal import registry

    iid = _make_doc(db, "N-1", "Наказ")
    first = _register(db, registry, iid, "Наказ")
    # повторний виклик з іншим типом/датою — нічого не змінює
    second = _register(db, registry, iid, "Лист",
                       when=dt.datetime(2030, 1, 1, tzinfo=dt.timezone.utc))
    assert second["reg_index"] == first["reg_index"] == "1-од"
    assert second["reg_number"] == first["reg_number"] == 1
    assert second["doc_type"] == "Наказ"  # тип не перезаписано


def test_idempotent_does_not_consume_number(db):
    """Повторна реєстрація не «з'їдає» наступний номер для нових документів."""
    from portal import registry

    iid = _make_doc(db, "N-1", "Наказ")
    _register(db, registry, iid, "Наказ")
    _register(db, registry, iid, "Наказ")  # повтор — no-op
    nxt = _register(db, registry, _make_doc(db, "N-2", "Наказ"), "Наказ")
    assert nxt["reg_index"] == "2-од"  # не 3-од


# --- формат дати -----------------------------------------------------------

@pytest.mark.parametrize(
    "date,expected",
    [
        (dt.date(2026, 1, 1), "1 січня 2026 р."),
        (dt.date(2026, 2, 14), "14 лютого 2026 р."),
        (dt.date(2026, 3, 8), "8 березня 2026 р."),
        (dt.date(2026, 4, 30), "30 квітня 2026 р."),
        (dt.date(2026, 5, 9), "9 травня 2026 р."),
        (dt.date(2026, 6, 14), "14 червня 2026 р."),
        (dt.date(2026, 7, 1), "1 липня 2026 р."),
        (dt.date(2026, 8, 24), "24 серпня 2026 р."),
        (dt.date(2026, 9, 15), "15 вересня 2026 р."),
        (dt.date(2026, 10, 14), "14 жовтня 2026 р."),
        (dt.date(2026, 11, 21), "21 листопада 2026 р."),
        (dt.date(2026, 12, 31), "31 грудня 2026 р."),
    ],
)
def test_ua_date_format_all_months(db, date, expected):
    """Словесно-цифровий формат дати ДСТУ для кожного місяця року."""
    from portal import registry

    assert registry.format_ua_date(date) == expected


def test_assign_sets_date_from_when(db):
    """reg_date формується з переданого моменту реєстрації (when)."""
    from portal import registry

    when = dt.datetime(2026, 6, 14, 9, 30, tzinfo=dt.timezone.utc)
    res = _register(db, registry, _make_doc(db, "N-1", "Наказ"), "Наказ", when=when)
    assert res["reg_date"] == "14 червня 2026 р."
    assert res["registered_at"] is not None

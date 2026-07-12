"""Тести контактних даних заявника (phone/address) у моделі User.

Регресійний сценрій: phone/address раніше були у моделі Counterparty, а не User —
через це /auth/login падав із 500 ('User' object has no attribute 'phone'), а
PUT /users не персистив контакти. Тут покривається весь ланцюжок: модель →
міграція → /auth/login → /auth/me → POST/PUT/GET /users.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_PORTAL = Path(__file__).resolve().parents[1]  # каталог portal/
if str(_PORTAL.parent) not in sys.path:
    sys.path.insert(0, str(_PORTAL.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient зі свіжою ізольованою БД на кожен тест (реальна авторизація,
    без dependency override) — щоб перевірити саме /auth/login та /auth/me."""
    db_file = tmp_path / "portal_test.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")

    for mod in list(sys.modules.keys()):
        if mod == "portal" or mod.startswith("portal."):
            del sys.modules[mod]
    db = importlib.import_module("portal.db")
    main = importlib.import_module("portal.main")
    db.init_db()

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


def _create_and_login(client, email: str, password: str = "pass12345",
                      phone: str | None = None, address: str | None = None):
    """Створити користувача безпосередньо в БД і увійти через /auth/login.

    Повертає (user_id, token, headers). Створення через БД (а не POST /users)
    дозволяє задати phone/address наперед для тестів читання /auth/me."""
    from portal.db import SessionLocal, User
    with SessionLocal() as session:
        user = User(
            email=email,
            name="Тестовий Користувач",
            password_hash=User.hash_password(password),
            phone=phone,
            address=address,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        uid = user.id

    r = client.post("/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    return uid, token, {"Authorization": f"Bearer {token}"}


# --- модель: phone/address є саме у User, не лише у Counterparty (регресія) ---
def test_user_model_has_contact_columns():
    """phone/address мають бути mapped-колонками класу User.

    Регресія: колонки випадково додавали лише до Counterparty — User їх не мав,
    і user.phone падав з AttributeError."""
    from portal.db import User
    col_keys = {c.key for c in User.__mapper__.columns}
    assert "phone" in col_keys, "у User немає колонки phone"
    assert "address" in col_keys, "у User немає колонки address"
    # і атрибути доступні як Python-дескриптори (не raise AttributeError)
    u = User(email="x@y.z", name="n", password_hash="h")
    assert u.phone is None
    assert u.address is None


def test_init_db_migrates_contact_columns_on_legacy_db(client):
    """init_db має додавати phone/address до наявної таблиці users (ALTER TABLE),
    бо create_all не змінює вже створені таблиці. Симулюємо стару БД: дропаємо
    колонки, повторно проганяємо init_db — колонки мають повернутись."""
    from sqlalchemy import inspect, text
    import portal.db as db

    def _has(col: str) -> bool:
        return col in {c["name"] for c in inspect(db.engine).get_columns("users")}

    assert _has("phone") and _has("address")  # після початкового init_db

    # симулюємо стару схему без контактних колонок
    with db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE users DROP COLUMN phone"))
        conn.execute(text("ALTER TABLE users DROP COLUMN address"))
    assert not _has("phone") and not _has("address")

    # повторний init_db має дотягнути колонки міграцією
    db.init_db()
    assert _has("phone"), "міграція не додала phone"
    assert _has("address"), "міграція не додала address"


# --- /auth/login: головна регресія (раніше 500) ---
def test_login_returns_phone_address(client):
    """/auth/login повертає 200 і phone/address у user — раніше падало 500,
    бо _user_public читав неіснуючий атрибут User.phone."""
    _, _, _ = _create_and_login(
        client, email="contacts@example.com",
        phone="+38 050 111 22 33",
        address="вул. Садова, 5, кв. 12\nм. Харків, 61000",
    )
    r = client.post("/auth/login", json={"email": "contacts@example.com", "password": "pass12345"})
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["phone"] == "+38 050 111 22 33"
    assert user["address"] == "вул. Садова, 5, кв. 12\nм. Харків, 61000"


def test_login_returns_nulls_when_contacts_absent(client):
    """/auth/login не падає і повертає None для контактів, якщо їх не задано."""
    _create_and_login(client, email="bare@example.com")
    r = client.post("/auth/login", json={"email": "bare@example.com", "password": "pass12345"})
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert user["phone"] is None
    assert user["address"] is None


# --- /auth/me ---
def test_auth_me_returns_phone_address(client):
    """/auth/me віддає ті ж контакти, що й login — фронтенд carrier currentUser."""
    _, _, headers = _create_and_login(
        client, email="me@example.com",
        phone="+38 044 555 66 77",
        address="м. Київ, вул. Хрещатик, 1",
    )
    r = client.get("/auth/me", headers=headers)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["phone"] == "+38 044 555 66 77"
    assert me["address"] == "м. Київ, вул. Хрещатик, 1"


# --- POST /users ---
def test_post_user_persists_phone_address(client):
    """Створення користувача через API зберігає phone/address у БД."""
    _, admin_token, admin_h = _create_and_login(client, email="admin2@example.com")
    r = client.post("/users", json={
        "name": "Нова Людина",
        "email": "newbie@example.com",
        "password": "secret12345",
        "phone": "+38 097 000 00 00",
        "address": "м. Львів, пл. Ринок, 1",
    }, headers=admin_h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phone"] == "+38 097 000 00 00"
    assert body["address"] == "м. Львів, пл. Ринок, 1"

    from portal.db import SessionLocal, User
    with SessionLocal() as session:
        db_user = session.query(User).filter_by(email="newbie@example.com").first()
        assert db_user is not None
        assert db_user.phone == "+38 097 000 00 00"
        assert db_user.address == "м. Львів, пл. Ринок, 1"


# --- PUT /users: головна регресія (раніше не персистило) ---
def test_put_user_persists_phone_address(client):
    """PUT /users/{id} зберігає phone/address у колонку (раніше ставив
    транзієнтний атрибут, що не зберігався — контакти губились)."""
    uid, _, headers = _create_and_login(client, email="put@example.com")
    r = client.put(f"/users/{uid}", json={
        "phone": "+38 050 123 45 67",
        "address": "вул. Садова, 5, кв. 12\nм. Харків, 61000",
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "+38 050 123 45 67"
    assert r.json()["address"] == "вул. Садова, 5, кв. 12\nм. Харків, 61000"

    # повторне /auth/me має бачити оновлені контакти (свіжий read з БД)
    r_me = client.get("/auth/me", headers=headers)
    assert r_me.status_code == 200, r_me.text
    assert r_me.json()["phone"] == "+38 050 123 45 67"
    assert r_me.json()["address"] == "вул. Садова, 5, кв. 12\nм. Харків, 61000"

    from portal.db import SessionLocal, User
    with SessionLocal() as session:
        db_user = session.get(User, uid)
        assert db_user.phone == "+38 050 123 45 67"
        assert db_user.address == "вул. Садова, 5, кв. 12\nм. Харків, 61000"


def test_put_user_empty_phone_becomes_none(client):
    """Порожній рядок phone/address нормалізується до None (`or None`), а не
    зберігається як '' — інакше блок «від кого» отримував би порожній рядок."""
    uid, _, headers = _create_and_login(
        client, email="empty@example.com", phone="+38 000", address="стара адреса")
    r = client.put(f"/users/{uid}", json={"phone": "   ", "address": ""}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["phone"] is None
    assert r.json()["address"] is None


def test_put_user_partial_update_keeps_other_contact(client):
    """Оновлення лише phone не затирає address і навпаки."""
    uid, _, headers = _create_and_login(
        client, email="partial@example.com",
        phone="+38 050 1", address="м. Одеса, вул. Дерибасівська, 1")
    r = client.put(f"/users/{uid}", json={"phone": "+38 099 222 33 44"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phone"] == "+38 099 222 33 44"
    assert body["address"] == "м. Одеса, вул. Дерибасівська, 1"  # не зачепили


# --- GET /users ---
def test_get_users_returns_contacts(client):
    """GET /users віддає phone/address кожного користувача (для адмін-форми)."""
    _, _, headers = _create_and_login(
        client, email="list@example.com",
        phone="+38 067 888 99 00", address="м. Полтава, вул. Соборності, 10")
    r = client.get("/users", headers=headers)
    assert r.status_code == 200, r.text
    found = [u for u in r.json() if u["email"] == "list@example.com"]
    assert found, "користувача немає у списку"
    assert found[0]["phone"] == "+38 067 888 99 00"
    assert found[0]["address"] == "м. Полтава, вул. Соборності, 10"

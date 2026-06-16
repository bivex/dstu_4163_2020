"""Тести для авторизації та прив'язки КЕП.

Використовується фікстура TestClient зі свіжою тестовою БД на кожен тест.
Криптографічні перевірки openssl cms мокаються за допомогою pytest monkeypatch.
"""

from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path
import pytest

_PORTAL = Path(__file__).resolve().parents[1]  # каталог portal/
if str(_PORTAL.parent) not in sys.path:
    sys.path.insert(0, str(_PORTAL.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient зі свіжою ізольованою БД на кожен тест."""
    db_file = tmp_path / "portal_test.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")

    # Перезавантажити модулі portal для свіжої конфігурації
    for mod in list(sys.modules.keys()):
        if mod == "portal" or mod.startswith("portal."):
            del sys.modules[mod]
            
    db = importlib.import_module("portal.db")
    main = importlib.import_module("portal.main")
    db.init_db()

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def mock_kep(monkeypatch):
    """Мокає функції криптографічної перевірки КЕП."""
    # Імпортуємо модуль bridge, який буде використовуватися в роутерах
    import portal.domain_bridge as bridge
    
    # Мок успішної перевірки підпису
    monkeypatch.setattr(bridge, "verify_signature", lambda d, s: True)
    
    # Мок вилучення сертифіката
    monkeypatch.setattr(bridge, "cert_info_from_cms", lambda s: {
        "serialNumber": "3123456789",
        "certificate_serial": "ABCDEF123456",
        "signer": "ПЕТРЕНКО Олександр"
    })


def test_challenge_generation(client):
    """Тест генерації одноразових челенджів."""
    r = client.get("/auth/challenge")
    assert r.status_code == 200
    data = r.json()
    assert "challenge" in data
    assert len(data["challenge"]) > 32


def test_link_and_login_kep(client, mock_kep):
    """Тест повного циклу прив'язки КЕП та наступного входу за підписом."""
    # 1. Створюємо користувача без КЕП в БД
    from portal.db import SessionLocal, User
    with SessionLocal() as session:
        user = User(
            email="test@example.com",
            name="Олександр Петренко",
            password_hash=User.hash_password("password123")
        )
        session.add(user)
        session.commit()

    # 2. Авторизуємось за паролем, щоб отримати JWT
    r_login = client.post("/auth/login", json={"email": "test@example.com", "password": "password123"})
    assert r_login.status_code == 200
    token = r_login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Отримуємо челендж для прив'язки КЕП
    r_chal = client.get("/auth/challenge")
    assert r_chal.status_code == 200
    challenge = r_chal.json()["challenge"]

    # 4. Прив'язуємо КЕП (передаємо челендж та будь-який псевдо-підпис)
    payload = {
        "challenge": challenge,
        "signature_b64": base64.b64encode(b"dummy_signature").decode()
    }
    r_link = client.post("/auth/link-kep", json=payload, headers=headers)
    assert r_link.status_code == 200
    assert r_link.json()["status"] == "ok"
    
    # Перевіряємо, що у відповіді є збережені поля КЕП
    linked_user = r_link.json()["user"]
    assert linked_user["kep_serial_number"] == "3123456789"
    assert linked_user["kep_subject_cn"] == "ПЕТРЕНКО Олександр"

    # Перевіряємо в БД, що поля оновилися
    with SessionLocal() as session:
        db_user = session.query(User).filter_by(email="test@example.com").first()
        assert db_user.kep_serial_number == "3123456789"
        assert db_user.kep_subject_cn == "ПЕТРЕНКО Олександр"

    # 5. Перевіряємо ендпоінт /auth/me з новими полями
    r_me = client.get("/auth/me", headers=headers)
    assert r_me.status_code == 200
    me_data = r_me.json()
    assert me_data["kep_serial_number"] == "3123456789"
    assert me_data["kep_subject_cn"] == "ПЕТРЕНКО Олександр"

    # 6. Виконуємо вхід за КЕП (без пошти та пароля)
    r_chal2 = client.get("/auth/challenge")
    assert r_chal2.status_code == 200
    challenge2 = r_chal2.json()["challenge"]

    payload2 = {
        "challenge": challenge2,
        "signature_b64": base64.b64encode(b"dummy_signature").decode()
    }
    r_kep_login = client.post("/auth/login-kep", json=payload2)
    assert r_kep_login.status_code == 200
    
    login_data = r_kep_login.json()
    assert "token" in login_data
    assert login_data["user"]["email"] == "test@example.com"
    assert login_data["user"]["kep_serial_number"] == "3123456789"


def test_login_kep_not_linked(client, mock_kep):
    """Спроба входу за КЕП, який не прив'язаний до жодного користувача."""
    r_chal = client.get("/auth/challenge")
    challenge = r_chal.json()["challenge"]

    payload = {
        "challenge": challenge,
        "signature_b64": base64.b64encode(b"dummy_signature").decode()
    }
    r_login = client.post("/auth/login-kep", json=payload)
    # Повертає 401, оскільки користувача з РНОКПП 3123456789 немає в базі
    assert r_login.status_code == 401
    assert "не знайдено" in r_login.json()["detail"]


def test_link_kep_already_linked_to_another(client, mock_kep):
    """Спроба прив'язати КЕП, який вже прив'язаний до іншого користувача."""
    from portal.db import SessionLocal, User
    
    # Створюємо користувача №1 (вже має цей КЕП) та користувача №2 (намагатиметься прив'язати)
    with SessionLocal() as session:
        user1 = User(
            email="user1@example.com",
            password_hash=User.hash_password("pass"),
            kep_serial_number="3123456789",
            kep_subject_cn="ПЕТРЕНКО Олександр"
        )
        user2 = User(
            email="user2@example.com",
            password_hash=User.hash_password("pass")
        )
        session.add(user1)
        session.add(user2)
        session.commit()

    # Логінимось під користувачем №2
    r_login = client.post("/auth/login", json={"email": "user2@example.com", "password": "pass"})
    token = r_login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Спроба прив'язати той самий КЕП
    r_chal = client.get("/auth/challenge")
    challenge = r_chal.json()["challenge"]

    payload = {
        "challenge": challenge,
        "signature_b64": base64.b64encode(b"dummy_signature").decode()
    }
    r_link = client.post("/auth/link-kep", json=payload, headers=headers)
    # Має повернути 400 Bad Request
    assert r_link.status_code == 400
    assert "вже прив'язаний до іншого" in r_link.json()["detail"]


def test_unlink_kep(client, mock_kep):
    """Тест відв'язування КЕП від кабінету."""
    from portal.db import SessionLocal, User
    
    with SessionLocal() as session:
        user = User(
            email="test@example.com",
            password_hash=User.hash_password("pass"),
            kep_serial_number="3123456789",
            kep_subject_cn="ПЕТРЕНКО Олександр"
        )
        session.add(user)
        session.commit()

    r_login = client.post("/auth/login", json={"email": "test@example.com", "password": "pass"})
    token = r_login.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Відв'язуємо КЕП
    r_unlink = client.post("/auth/unlink-kep", headers=headers)
    assert r_unlink.status_code == 200
    assert r_unlink.json()["status"] == "ok"

    # Перевіряємо в БД, що поля очистилися
    with SessionLocal() as session:
        db_user = session.query(User).filter_by(email="test@example.com").first()
        assert db_user.kep_serial_number is None
        assert db_user.kep_subject_cn is None


def test_proxy_handler(client, monkeypatch):
    """Тест проксі-ендпоінту для OCSP/TSP запитів."""
    import httpx
    
    class MockResponse:
        def __init__(self, content):
            self.content = content
            
    class MockAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, content, headers, timeout):
            assert url == "http://zc.bank.gov.ua/services/ocsp"
            assert content == b"decoded_request"
            assert headers == {"Content-Type": "application/ocsp-request"}
            return MockResponse(b"ocsp_response")

    monkeypatch.setattr(httpx, "AsyncClient", lambda *args, **kwargs: MockAsyncClient())
    
    # Клієнт шле POST запит з base64-кодованим тілом
    payload_b64 = base64.b64encode(b"decoded_request").decode()
    r = client.post(
        "/signdata/ProxyHandler.php?address=http://zc.bank.gov.ua/services/ocsp",
        content=payload_b64
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "X-user/base64-data"
    
    # Відповідь має бути base64-кодованим вмістом відповіді сервера
    resp_bytes = base64.b64decode(r.text)
    assert resp_bytes == b"ocsp_response"

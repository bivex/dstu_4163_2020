"""Тести системи ролей (RBAC) та блокування документа після підписання.

Покриває:
- роль у JWT після login (admin / clerk)
- clerk не може видалити всі документи (DELETE /documents/all → 403)
- admin може
- звичайний юзер не може редагувати не-draft документ (PUT → 409)
- звичайний юзер не може видалити підписаний документ (DELETE → 409)
- звичайний юзер не може змінити роль іншому (PUT /users з role → 403)
- admin може призначити роль
- звичайний юзер не може підписати чужий документ (sign → 403)

Кожен тест — ізольована БД (tmp SQLite), dependency-override відключено,
щоб реальна перевірка JWT-токена відбувалася.
"""

from __future__ import annotations

import base64
import datetime as _dt
import importlib
import sys
from pathlib import Path

import jwt
import pytest

_PORTAL = Path(__file__).resolve().parents[1]
if str(_PORTAL.parent) not in sys.path:
    sys.path.insert(0, str(_PORTAL.parent))

_JWT_SECRET = "dilovod-dev-secret-change-in-prod"
_JWT_ALGO = "HS256"


def _token(sub: str, name: str, role: str, email: str = "x@org.local") -> str:
    payload = {
        "sub": sub,
        "email": email,
        "name": name,
        "role": role,
        "exp": _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=24),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _h(role: str, sub: str = "1", name: str = "Тестовий") -> dict:
    """Заголовки авторизації для вказаної ролі. Без dependency-override —
    реальна перевірка токена _current_user."""
    return {"Authorization": f"Bearer {_token(sub=sub, name=name, role=role)}"}


def _doc_payload(doc_id: str = "RBAC-1") -> dict:
    return {
        "doc_id": doc_id,
        "org_name": "ТОВ «ТЕСТ»",
        "doc_type": "Наказ",
        "title": "Тестовий наказ",
        "date_text": "15 червня 2026 р.",
        "fmt": "pdf",
        "body": ["Текст наказу."],
        "signers": [
            {"order_index": 0, "full_name": "ДИРЕКТОР Тестовий", "position": "Директор"}
        ],
        "retention_years": 5,
    }


def _fake_cms() -> str:
    return base64.b64encode(b"\x30\x82\x02\x00" + b"\x00" * 600).decode()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient зі свіжою ізольованою БД. БЕЗ dependency-override —
    реальна перевірка ролі з JWT."""
    db_file = tmp_path / "rbac_test.db"
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


# ============================================================
# Роль у JWT після login
# ============================================================


class TestRoleInLogin:
    def test_password_login_returns_role(self, client):
        """POST /auth/login має повертати role користувача."""
        db = importlib.import_module("portal.db")
        with db.SessionLocal() as s:
            s.add(db.User(
                email="dir@org.local", name="Директор", position="Директор",
                role=db.UserRole.DIRECTOR.value,
                password_hash=db.User.hash_password("pass"),
            ))
            s.commit()

        r = client.post("/auth/login", json={"email": "dir@org.local", "password": "pass"})
        assert r.status_code == 200
        assert r.json()["user"]["role"] == "director"

    def test_me_returns_role(self, client):
        db = importlib.import_module("portal.db")
        with db.SessionLocal() as s:
            s.add(db.User(
                email="acc@org.local", name="Бухгалтер", position="Головний бухгалтер",
                role=db.UserRole.ACCOUNTANT.value,
                password_hash=db.User.hash_password("pass"),
            ))
            s.commit()
        tok = client.post("/auth/login", json={"email": "acc@org.local", "password": "pass"}).json()["token"]
        r = client.get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
        assert r.json()["role"] == "accountant"


# ============================================================
# DELETE /documents/all — лише admin
# ============================================================


class TestDeleteAllAdminOnly:
    def test_clerk_forbidden(self, client):
        """clerk не може видалити всі документи → 403."""
        client.post("/documents", json=_doc_payload(), headers=_h("clerk", sub="10"))
        r = client.delete("/documents/all", headers=_h("clerk", sub="10"))
        assert r.status_code == 403

    def test_director_forbidden(self, client):
        """director також не може (небезпечна операція — лише admin)."""
        client.post("/documents", json=_doc_payload(), headers=_h("director", sub="11"))
        r = client.delete("/documents/all", headers=_h("director", sub="11"))
        assert r.status_code == 403

    def test_admin_allowed(self, client):
        client.post("/documents", json=_doc_payload("A-1"), headers=_h("admin"))
        client.post("/documents", json=_doc_payload("A-2"), headers=_h("admin"))
        r = client.delete("/documents/all", headers=_h("admin"))
        assert r.status_code == 200
        assert r.json()["deleted"] >= 2


# ============================================================
# Status-lock: не-draft документ не редагується звичайним юзером
# ============================================================


class TestStatusLock:
    def _make_signed(self, client, doc_id: str = "LOCK-1") -> None:
        """Створити документ і перевести у SIGNED напряму через БД."""
        client.post("/documents", json=_doc_payload(doc_id), headers=_h("director", sub="1"))
        db = importlib.import_module("portal.db")
        with db.SessionLocal() as s:
            doc = s.query(db.Document).filter_by(doc_id=doc_id).first()
            doc.status = db.DocStatus.SIGNED
            for sg in doc.signers:
                sg.status = db.SignerStatus.SIGNED
            s.commit()

    def test_clerk_cannot_edit_signed(self, client):
        """PUT підписаного документа від clerk → 409."""
        self._make_signed(client)
        r = client.put("/documents/LOCK-1", json={"title": "X"}, headers=_h("clerk", sub="20"))
        assert r.status_code == 409

    def test_director_cannot_edit_signed(self, client):
        """director теж підпадає під status-lock (не admin) → 409."""
        self._make_signed(client)
        r = client.put("/documents/LOCK-1", json={"title": "X"}, headers=_h("director", sub="21"))
        assert r.status_code == 409

    def test_clerk_cannot_delete_signed(self, client):
        """DELETE підписаного документа від clerk → 409."""
        self._make_signed(client)
        r = client.delete("/documents/LOCK-1", headers=_h("clerk", sub="22"))
        assert r.status_code == 409

    def test_clerk_cannot_generate_signed(self, client):
        """generate підписаного документа переписує digest → 409 (криптозахист)."""
        self._make_signed(client)
        r = client.post("/documents/LOCK-1/generate", headers=_h("clerk", sub="23"))
        assert r.status_code == 409

    def test_draft_editable_by_clerk(self, client):
        """draft документ можна редагувати будь-ким → 200."""
        client.post("/documents", json=_doc_payload("DR-1"), headers=_h("clerk", sub="24"))
        r = client.put("/documents/DR-1", json={"title": "Новий"}, headers=_h("clerk", sub="24"))
        assert r.status_code == 200
        assert r.json()["title"] == "Новий"


# ============================================================
# Управління ролями — лише admin
# ============================================================


class TestRoleManagement:
    def test_clerk_cannot_set_role_on_create(self, client):
        """clerk створює користувача із role → 403 (role ігнорується, але клерк не має права)."""
        r = client.post("/users", json={
            "name": "Новий", "email": "new@org.local", "password": "pass", "role": "admin"
        }, headers=_h("clerk", sub="30"))
        assert r.status_code == 403

    def test_clerk_cannot_change_role(self, client):
        """clerk намагається змінити роль іншому → 403."""
        db = importlib.import_module("portal.db")
        with db.SessionLocal() as s:
            u = db.User(email="victim@org.local", name="Жертва",
                        password_hash=db.User.hash_password("x"))
            s.add(u)
            s.commit()
            uid = u.id
        r = client.put(f"/users/{uid}", json={"role": "admin"}, headers=_h("clerk", sub="31"))
        assert r.status_code == 403

    def test_admin_can_set_role(self, client):
        """admin призначає роль → 200, роль збережена."""
        r = client.post("/users", json={
            "name": "Бухгалтер Новий", "email": "new-acc@org.local",
            "password": "pass", "role": "accountant"
        }, headers=_h("admin", sub="1"))
        assert r.status_code == 200
        assert r.json()["role"] == "accountant"

    def test_invalid_role_rejected(self, client):
        """невідома роль → 400."""
        r = client.post("/users", json={
            "name": "X", "email": "bad@org.local", "password": "pass", "role": "superuser"
        }, headers=_h("admin", sub="1"))
        assert r.status_code == 400

    def test_user_list_includes_role(self, client):
        """GET /users повертає role кожного користувача."""
        r = client.get("/users", headers=_h("admin", sub="1"))
        assert r.status_code == 200
        # дефолтний адмін сіється init_db → role=admin
        assert any(u.get("role") == "admin" for u in r.json())


# ============================================================
# Підпис чужого документа заборонено не-підписанту
# ============================================================


class TestSignAuthorization:
    def test_non_signer_forbidden(self, client):
        """Юзер, що не є активним підписантом, не може підписати → 403."""
        client.post("/documents", json=_doc_payload("SGN-1"), headers=_h("director", sub="1"))
        client.post("/documents/SGN-1/submit", headers=_h("director", sub="1"))
        # clerk (імʼя «Тестовий») не співпадає з підписантом «ДИРЕКТОР Тестовий»
        r = client.post("/documents/SGN-1/sign", json={
            "signer_order_index": 0, "signature_b64": _fake_cms()
        }, headers=_h("clerk", sub="40", name="Не Підписант"))
        assert r.status_code == 403

    def test_active_signer_allowed(self, client):
        """Активний підписант (імʼя співпадає) може підписати → 200."""
        client.post("/documents", json=_doc_payload("SGN-2"), headers=_h("director", sub="1"))
        client.post("/documents/SGN-2/submit", headers=_h("director", sub="1"))
        r = client.post("/documents/SGN-2/sign", json={
            "signer_order_index": 0, "signature_b64": _fake_cms()
        }, headers=_h("director", sub="2", name="ДИРЕКТОР Тестовий"))
        assert r.status_code == 200

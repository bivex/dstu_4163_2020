"""E2E-регресійні тести для фіксів сесії 2026-06-15.

Покриває:
  1. Авто-реєстрація при подачі на погодження (reg_index одразу, ідемпотентно).
  2. Авто-реєстрація при авто-переході в чергу підписання після погодження.
  3. Подвійний «№» у реєстраційному індексі за журналом (strip).
  4. Зв'язок виконавця завдання з користувачем системи через executor_user_id.
  5. /tasks/my і зміна статусу завдання матчаться за user_id (а не лише ПІБ).
  6. doc_type зберігається в content_json до реєстрації (не губиться).
  7. /submit без підписантів → 400 (контракт, на який спирається disabled-кнопка UI).

Кожен тест отримує ізольовану БД через фікстуру client (тимчасовий SQLite).
Дефолтний адмін: admin@dilovod.local / admin (sub=1), сіється init_db().
"""

from __future__ import annotations

import base64
import datetime as dt
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


def _make_token(name: str = "Адміністратор", email: str = "admin@dilovod.local", sub: str = "1") -> str:
    payload = {
        "sub": sub,
        "email": email,
        "name": name,
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _auth_headers(name: str = "Адміністратор", sub: str = "1") -> dict:
    return {"Authorization": f"Bearer {_make_token(name=name, sub=sub)}"}


def _fake_cms() -> str:
    """Мінімально валідний CMS-сурогат (DER SEQUENCE, >=256 байт)."""
    return base64.b64encode(b"\x30\x82\x02\x00" + b"\x00" * 600).decode()


def _doc_payload(
    doc_id: str,
    *,
    doc_type: str = "Наказ",
    signers: int = 1,
    approvers: list | None = None,
    journal_id: int | None = None,
) -> dict:
    sg = [
        {"order_index": 0, "full_name": "ПЕТРЕНКО Олександр", "position": "Директор"},
        {"order_index": 1, "full_name": "ТКАЧЕНКО Наталія", "position": "Бухгалтер"},
    ][:signers]
    payload = {
        "doc_id": doc_id,
        "org_name": "ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        "doc_type": doc_type,
        "title": "Про затвердження положення",
        "date_text": "",
        "fmt": "pdf",
        "body": ["Відповідно до законодавства.", "Наказати:"],
        "signers": sg,
        "approval_type": "sequential",
        "retention_years": 5,
    }
    if approvers is not None:
        payload["approvers"] = approvers
    if journal_id is not None:
        payload["journal_id"] = journal_id
    return payload


@pytest.fixture()
def client(tmp_path, monkeypatch):
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


def _seed_user(name: str, email: str, position: str = "") -> int:
    """Створити користувача напряму в БД, повернути id."""
    db = importlib.import_module("portal.db")
    with db.SessionLocal() as s:
        u = db.User(email=email, name=name, position=position,
                    password_hash=db.User.hash_password("x"))
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


# ============================================================
# 1. Авто-реєстрація при подачі на погодження
# ============================================================


class TestRegistrationOnApprovalSubmit:
    def test_submit_for_approval_assigns_reg_index(self, client):
        """approval/submit має одразу присвоїти reg_index/reg_date."""
        payload = _doc_payload(
            "REG-APP-1",
            approvers=[{"order_index": 0, "user_id": 1,
                        "full_name": "Адміністратор", "position": "Директор"}],
        )
        client.post("/documents", json=payload)

        r = client.post("/documents/REG-APP-1/approval/submit", headers=_auth_headers())
        assert r.status_code == 200
        assert r.json()["status"] == "pending_approval"

        doc = client.get("/documents/REG-APP-1", headers=_auth_headers()).json()
        assert doc["reg_index"], "reg_index має бути присвоєний при подачі на погодження"
        assert doc["reg_date"], "reg_date має бути присвоєна при подачі на погодження"

    def test_registration_idempotent_through_completion(self, client):
        """Фінальне погодження не перезаписує номер, присвоєний при подачі."""
        payload = _doc_payload(
            "REG-APP-2",
            approvers=[{"order_index": 0, "user_id": 1,
                        "full_name": "Адміністратор", "position": "Директор"}],
        )
        client.post("/documents", json=payload)
        client.post("/documents/REG-APP-2/approval/submit", headers=_auth_headers())

        doc1 = client.get("/documents/REG-APP-2", headers=_auth_headers()).json()
        idx_before = doc1["reg_index"]

        client.post(
            "/documents/REG-APP-2/approval/action",
            json={"action": "approve"},
            headers=_auth_headers(),  # admin sub=1 matches approver user_id=1
        )

        doc2 = client.get("/documents/REG-APP-2", headers=_auth_headers()).json()
        assert doc2["status"] == "pending_signatures"
        assert doc2["reg_index"] == idx_before, "номер не повинен змінюватись після погодження"


# ============================================================
# 2. Авто-реєстрація при авто-переході в чергу підписання
# ============================================================


class TestRegistrationOnAutoQueue:
    def test_completion_registers_before_signing_queue(self, client):
        """Документ із підписантами після погодження потрапляє в чергу з номером."""
        payload = _doc_payload(
            "REG-AUTO-1",
            signers=1,
            approvers=[{"order_index": 0, "user_id": 1,
                        "full_name": "Адміністратор", "position": "Директор"}],
        )
        client.post("/documents", json=payload)
        client.post("/documents/REG-AUTO-1/approval/submit", headers=_auth_headers())
        client.post(
            "/documents/REG-AUTO-1/approval/action",
            json={"action": "approve"},
            headers=_auth_headers(),
        )

        doc = client.get("/documents/REG-AUTO-1", headers=_auth_headers()).json()
        assert doc["status"] == "pending_signatures"
        assert doc["reg_index"], "документ у черзі підписання повинен мати reg_index"
        assert doc["signers"][0]["status"] == "invited"


# ============================================================
# 3. Подвійний «№» у журнальному індексі
# ============================================================


class TestJournalDoubleNumberSign:
    def test_seeded_templates_have_no_number_sign(self, client):
        r = client.get("/journals", headers=_auth_headers())
        assert r.status_code == 200
        for j in r.json():
            assert "№" not in j["number_template"]

    def test_journal_reg_index_has_no_leading_number_sign(self, client):
        """Навіть якщо в шаблоні лишився «№», індекс не повинен його містити."""
        # знаходимо журнал ВИХ
        journals = client.get("/journals", headers=_auth_headers()).json()
        vyh = next(j for j in journals if j["prefix"] == "ВИХ")

        payload = _doc_payload("JRNL-1", signers=1, journal_id=vyh["id"])
        client.post("/documents", json=payload)
        r = client.post("/documents/JRNL-1/submit", json={"auto_register": True})
        assert r.status_code == 200
        reg_index = r.json()["reg_index"]
        assert reg_index
        assert not reg_index.startswith("№"), f"індекс не повинен починатися з №: {reg_index!r}"
        assert "№ №" not in reg_index

    def test_migration_strips_number_sign_from_templates(self, client):
        """init_db має чистити «№» з наявних шаблонів журналів."""
        db = importlib.import_module("portal.db")
        # зіпсуємо шаблон вручну, потім повторно мігруємо
        with db.SessionLocal() as s:
            j = s.query(db.Journal).first()
            j.number_template = "№ {number}-{prefix}"
            s.commit()
            jid = j.id
        db.init_db()
        with db.SessionLocal() as s:
            j = s.query(db.Journal).filter_by(id=jid).first()
            assert not j.number_template.startswith("№")


# ============================================================
# 4-5. Зв'язок виконавця завдання з користувачем (executor_user_id)
# ============================================================


def _make_signed_doc(client, doc_id: str) -> None:
    """Створити документ і перевести його у статус SIGNED напряму через БД."""
    payload = _doc_payload(doc_id, signers=1)
    payload.pop("approvers", None)
    client.post("/documents", json=payload)

    db = importlib.import_module("portal.db")
    with db.SessionLocal() as s:
        doc = s.query(db.Document).filter_by(doc_id=doc_id).first()
        doc.status = db.DocStatus.SIGNED
        for sg in doc.signers:
            sg.status = db.SignerStatus.SIGNED
        s.commit()


class TestTaskExecutorLinkage:
    def test_resolution_persists_executor_user_id(self, client):
        uid = _seed_user("КОВАЛЬЧУК Ірина", "jurist@dilovod.local", "Юрист")
        _make_signed_doc(client, "RES-1")

        r = client.post(
            "/documents/RES-1/resolutions",
            json={
                "text": "Підготувати відповідь",
                "tasks": [{
                    "executor": "КОВАЛЬЧУК Ірина",
                    "executor_user_id": uid,
                    "description": "Підготувати проєкт",
                    "due_date": "2026-06-20",
                }],
            },
            headers=_auth_headers(),
        )
        assert r.status_code == 200

        res = client.get("/documents/RES-1/resolutions", headers=_auth_headers()).json()
        task = res[0]["tasks"][0]
        assert task["executor_user_id"] == uid

    def test_my_tasks_matched_by_user_id(self, client):
        """Виконавець бачить завдання за user_id, навіть якщо ПІБ у токені інший."""
        uid = _seed_user("КОВАЛЬЧУК Ірина", "jurist@dilovod.local", "Юрист")
        _make_signed_doc(client, "RES-2")
        client.post(
            "/documents/RES-2/resolutions",
            json={
                "text": "Доручення",
                "tasks": [{
                    "executor": "КОВАЛЬЧУК Ірина",
                    "executor_user_id": uid,
                    "description": "Завдання за user_id",
                    "due_date": "2026-06-22",
                }],
            },
            headers=_auth_headers(),
        )

        # токен з відмінним ПІБ, але правильним sub=uid
        headers = _auth_headers(name="ІНШЕ ПІБ", sub=str(uid))
        mine = client.get("/tasks/my", headers=headers).json()
        assert any(t["document_id"] == "RES-2" for t in mine)

    def test_task_status_update_by_user_id(self, client):
        uid = _seed_user("КОВАЛЬЧУК Ірина", "jurist@dilovod.local", "Юрист")
        _make_signed_doc(client, "RES-3")
        client.post(
            "/documents/RES-3/resolutions",
            json={
                "text": "Доручення",
                "tasks": [{
                    "executor": "КОВАЛЬЧУК Ірина",
                    "executor_user_id": uid,
                    "description": "Закрити завдання",
                    "due_date": "2026-06-25",
                }],
            },
            headers=_auth_headers(),
        )
        headers = _auth_headers(name="ІНШЕ ПІБ", sub=str(uid))
        mine = client.get("/tasks/my", headers=headers).json()
        task_id = mine[0]["id"]

        r = client.post(
            f"/tasks/{task_id}/status",
            json={"status": "completed"},
            headers=headers,
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

    def test_task_status_update_forbidden_for_other_user(self, client):
        uid = _seed_user("КОВАЛЬЧУК Ірина", "jurist@dilovod.local", "Юрист")
        other = _seed_user("СТОРОННІЙ Петро", "petro@dilovod.local", "Інженер")
        _make_signed_doc(client, "RES-4")
        client.post(
            "/documents/RES-4/resolutions",
            json={
                "text": "Доручення",
                "tasks": [{
                    "executor": "КОВАЛЬЧУК Ірина",
                    "executor_user_id": uid,
                    "description": "Чуже завдання",
                    "due_date": "2026-06-25",
                }],
            },
            headers=_auth_headers(),
        )
        mine = client.get("/tasks/my", headers=_auth_headers(name="КОВАЛЬЧУК Ірина", sub=str(uid))).json()
        task_id = mine[0]["id"]

        r = client.post(
            f"/tasks/{task_id}/status",
            json={"status": "completed"},
            headers=_auth_headers(name="СТОРОННІЙ Петро", sub=str(other)),
        )
        assert r.status_code == 403


# ============================================================
# 6. doc_type зберігається в content_json до реєстрації
# ============================================================


class TestDocTypePersistence:
    def test_doc_type_in_content_json_on_create(self, client):
        payload = _doc_payload("DT-1", doc_type="Розпорядження")
        payload.pop("approvers", None)
        r = client.post("/documents", json=payload)
        assert r.status_code == 200

        doc = client.get("/documents/DT-1", headers=_auth_headers()).json()
        # колонка doc_type може бути None до реєстрації, але значення живе в content_json
        assert doc["content_json"]["doc_type"] == "Розпорядження"

    def test_doc_type_survives_edit(self, client):
        payload = _doc_payload("DT-2", doc_type="Лист")
        payload.pop("approvers", None)
        client.post("/documents", json=payload)

        # повторний upsert (редагування чернетки) зі зміною виду
        payload["doc_type"] = "Акт"
        payload["title"] = "Оновлено"
        client.post("/documents", json=payload)

        doc = client.get("/documents/DT-2", headers=_auth_headers()).json()
        assert doc["content_json"]["doc_type"] == "Акт"

    def test_doc_type_promoted_to_column_on_registration(self, client):
        payload = _doc_payload("DT-3", doc_type="Наказ", signers=1)
        payload.pop("approvers", None)
        client.post("/documents", json=payload)
        client.post("/documents/DT-3/submit", json={"auto_register": True})

        doc = client.get("/documents/DT-3", headers=_auth_headers()).json()
        assert doc["doc_type"] == "Наказ"


# ============================================================
# 7. /submit без підписантів → 400 (контракт для disabled-кнопки)
# ============================================================


class TestSubmitWithoutSigners:
    def test_submit_without_signers_returns_400(self, client):
        payload = _doc_payload("NOSIGN-1", signers=0)
        payload.pop("approvers", None)
        client.post("/documents", json=payload)

        r = client.post("/documents/NOSIGN-1/submit", json={"auto_register": True})
        assert r.status_code == 400

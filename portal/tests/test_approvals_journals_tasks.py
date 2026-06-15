"""Тести для нових модулів: Journals, Approvals, Resolutions, Tasks.

Кожен тест отримує ізольовану БД (тимчасовий SQLite) через спільну фікстуру client.
Авторизація відбувається через дефолтного адміна (admin@dilovod.local / admin),
щого сіє init_db().
"""

from __future__ import annotations

import base64
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
        "exp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        + __import__("datetime").timedelta(hours=24),
    }
    return jwt.encode(payload, _JWT_SECRET, algorithm=_JWT_ALGO)


def _auth_headers(name: str = "Адміністратор", sub: str = "1") -> dict:
    return {"Authorization": f"Bearer {_make_token(name=name, sub=sub)}"}


def _doc_payload(doc_id: str = "AJ-001", signers: int = 1) -> dict:
    sg = [
        {"order_index": 0, "full_name": "ПЕТРЕНКО Олександр", "position": "Директор"},
        {"order_index": 1, "full_name": "ТКАЧЕНКО Наталія", "position": "Бухгалтер"},
    ][:signers]
    approvers = [
        {"order_index": 0, "full_name": "КОВАЛЬЧУК Ірина", "position": "Юрист"},
        {"order_index": 1, "full_name": "БОНДАРЕНКО Максим", "position": "Начальник відділу"},
    ]
    return {
        "doc_id": doc_id,
        "org_name": "ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        "doc_type": "Наказ",
        "title": "Про затвердження положення",
        "date_text": "15 червня 2026 р.",
        "fmt": "pdf",
        "body": ["Відповідно до законодавства.", "Наказати:"],
        "signers": sg,
        "approvers": approvers,
        "journal_id": 1,
        "approval_type": "sequential",
        "retention_years": 5,
    }


def _fake_cms() -> str:
    return base64.b64encode(b"\x30\x82\x02\x00" + b"\x00" * 600).decode()


# --- фікстура ---


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


# ============================================================
# JOURNALS
# ============================================================


class TestJournals:
    def test_seeded_defaults_exist(self, client):
        """init_db() має сіять 3 дефолтні журнали."""
        r = client.get("/journals", headers=_auth_headers())
        assert r.status_code == 200
        journals = r.json()
        assert len(journals) == 3
        prefixes = {j["prefix"] for j in journals}
        assert prefixes == {"ОД", "ВХ", "ВИХ"}

    def test_list_journs(self, client):
        r = client.get("/journals", headers=_auth_headers())
        assert r.status_code == 200
        for j in r.json():
            assert "id" in j
            assert "name" in j
            assert "prefix" in j
            assert "number_template" in j
            assert "next_number" in j

    def test_create_journal(self, client):
        payload = {
            "name": "Тестовий журнал",
            "prefix": "ТЕСТ",
            "number_template": "{number}/{prefix}",
        }
        r = client.post("/journals", json=payload, headers=_auth_headers())
        assert r.status_code == 200
        j = r.json()
        assert j["name"] == "Тестовий журнал"
        assert j["prefix"] == "ТЕСТ"
        assert j["next_number"] == 1

    def test_create_journal_unauthorized(self, client):
        r = client.post("/journals", json={"name": "X", "prefix": "X", "number_template": "{n}"})
        assert r.status_code == 401

    def test_journal_template_no_double_number_sign(self, client):
        """Шаблон не повинен містити «№» — його додає генератор PDF/DOCX."""
        r = client.get("/journals", headers=_auth_headers())
        for j in r.json():
            assert "№" not in j["number_template"]


# ============================================================
# APPROVALS
# ============================================================


class TestApprovals:
    def _create_doc(self, client) -> dict:
        client.post("/documents", json=_doc_payload("AP-001"))
        return client.get("/documents/AP-001", headers=_auth_headers()).json()

    def test_submit_requires_approvers(self, client):
        """Без погоджувачів submit має падати з 400."""
        payload = _doc_payload("AP-NOAPP")
        payload["approvers"] = []
        client.post("/documents", json=payload)
        r = client.post("/documents/AP-NOAPP/approval/submit", headers=_auth_headers())
        assert r.status_code == 400

    def test_submit_sets_pending_approval(self, client):
        doc = self._create_doc(client)
        assert doc["status"] == "draft"

        r = client.post("/documents/AP-001/approval/submit", headers=_auth_headers())
        assert r.status_code == 200
        assert r.json()["status"] == "pending_approval"

    def test_submit_first_approver_invited_sequential(self, client):
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())

        doc = client.get("/documents/AP-001", headers=_auth_headers()).json()
        approvers = doc["approvers"]
        assert approvers[0]["status"] == "invited"
        assert approvers[1]["status"] == "waiting"

    def test_submit_all_invited_parallel(self, client):
        payload = _doc_payload("AP-PAR")
        payload["approval_type"] = "parallel"
        client.post("/documents", json=payload)
        client.post("/documents/AP-PAR/approval/submit", headers=_auth_headers())

        doc = client.get("/documents/AP-PAR", headers=_auth_headers()).json()
        for a in doc["approvers"]:
            assert a["status"] == "invited"

    def test_approve_sequential_advances(self, client):
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())

        # Перший погоджувач (КОВАЛЬЧУК Ірина) → approve
        r = client.post(
            "/documents/AP-001/approval/action",
            json={"action": "approve", "comment": "Задовольняє"},
            headers=_auth_headers("КОВАЛЬЧУК Ірина"),
        )
        assert r.status_code == 200

        doc = client.get("/documents/AP-001", headers=_auth_headers()).json()
        a0 = doc["approvers"][0]
        a1 = doc["approvers"][1]
        assert a0["status"] == "approved"
        assert a1["status"] == "invited"

    def test_approve_all_transitions_to_pending_signatures(self, client):
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())

        for approver_name in ("КОВАЛЬЧУК Ірина", "БОНДАРЕНКО Максим"):
            client.post(
                "/documents/AP-001/approval/action",
                json={"action": "approve"},
                headers=_auth_headers(approver_name),
            )

        doc = client.get("/documents/AP-001", headers=_auth_headers()).json()
        assert all(a["status"] == "approved" for a in doc["approvers"])
        # has signers → transitions to pending_signatures after approval completes
        assert doc["status"] == "pending_signatures"

    def test_reject_returns_to_draft(self, client):
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())

        r = client.post(
            "/documents/AP-001/approval/action",
            json={"action": "reject", "comment": "Потребує доопрацювання"},
            headers=_auth_headers("КОВАЛЬЧУК Ірина"),
        )
        assert r.status_code == 200

        doc = client.get("/documents/AP-001", headers=_auth_headers()).json()
        assert doc["status"] == "draft"
        assert doc["approvers"][0]["status"] == "rejected"
        assert doc["approvers"][0]["comment"] == "Потребує доопрацювання"

    def test_reject_resets_invited_to_waiting(self, client):
        """При відхиленні всі інші INVITED повертаються в WAITING, APPROVED залишається."""
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())

        # first approver approves
        client.post(
            "/documents/AP-001/approval/action",
            json={"action": "approve"},
            headers=_auth_headers("КОВАЛЬЧУК Ірина"),
        )
        # second approver rejects
        client.post(
            "/documents/AP-001/approval/action",
            json={"action": "reject", "comment": "Не підходе"},
            headers=_auth_headers("БОНДАРЕНКО Максим"),
        )

        doc = client.get("/documents/AP-001", headers=_auth_headers()).json()
        # first approver stays approved (already approved before reject)
        assert doc["approvers"][0]["status"] == "approved"
        # second approver is rejected
        assert doc["approvers"][1]["status"] == "rejected"
        # document returns to draft
        assert doc["status"] == "draft"

    def test_non_approver_cannot_approve(self, client):
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())

        r = client.post(
            "/documents/AP-001/approval/action",
            json={"action": "approve"},
            headers=_auth_headers("НЕ_ІСНУЮЧИЙ"),
        )
        assert r.status_code == 403

    def test_approval_sheet_pdf(self, client):
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())
        client.post(
            "/documents/AP-001/approval/action",
            json={"action": "approve"},
            headers=_auth_headers("КОВАЛЬЧУК Ірина"),
        )

        r = client.get("/documents/AP-001/approval/sheet", headers=_auth_headers())
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")

    def test_approval_sheet_before_approval_returns_doc(self, client):
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())

        r = client.get("/documents/AP-001/approval/sheet", headers=_auth_headers())
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")

    def test_submit_nonexistent_document_404(self, client):
        r = client.post("/documents/MISSING/approval/submit", headers=_auth_headers())
        assert r.status_code == 404

    def test_action_on_non_pending_approval_400(self, client):
        self._create_doc(client)
        # не подавали на погодження
        r = client.post(
            "/documents/AP-001/approval/action",
            json={"action": "approve"},
            headers=_auth_headers(),
        )
        assert r.status_code == 400

    # --- GET /approvals/my (живить сторінку «Погодження на розгляд») ---

    def test_my_approvals_returns_list_for_invited(self, client):
        """Сторінка «Документи, що очікують вашого візування» тягне GET /approvals/my.

        Фронт робить Array.isArray(res) ? res : [] — тому ендпоінт має повернути
        саме список, інакше спіннер зупиниться на порожньому стані навіть для запрошеного.
        """
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())

        r = client.get("/approvals/my", headers=_auth_headers("КОВАЛЬЧУК Ірина"))
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        assert len(data) == 1

        entry = data[0]
        assert entry["doc_id"] == "AP-001"
        assert entry["approver_status"] == "invited"
        assert entry["full_name"] == "КОВАЛЬЧУК Ірина"
        assert entry["position"] == "Юрист"
        # усі поля, що їх читає MyApprovalEntry на фронті
        for key in (
            "doc_id",
            "title",
            "status",
            "approver_status",
            "full_name",
            "position",
            "order_index",
            "approval_type",
        ):
            assert key in entry

    def test_my_approvals_excludes_waiting_and_strangers(self, client):
        """WAITING погоджувач і стороння людина не бачать документа у своєму списку."""
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())

        # БОНДАРЕНКО — другий у послідовному маршруті, статус waiting
        r_wait = client.get("/approvals/my", headers=_auth_headers("БОНДАРЕНКО Максим"))
        assert r_wait.status_code == 200
        assert r_wait.json() == []

        # стороння людина
        r_stranger = client.get("/approvals/my", headers=_auth_headers("НЕ_ІСНУЮЧИЙ"))
        assert r_stranger.status_code == 200
        assert r_stranger.json() == []

    def test_my_approvals_empty_until_submitted(self, client):
        """Поки документ не подано на погодження — список порожній (але 200, не зависання)."""
        self._create_doc(client)
        r = client.get("/approvals/my", headers=_auth_headers("КОВАЛЬЧУК Ірина"))
        assert r.status_code == 200
        assert r.json() == []

    def test_my_approvals_advances_to_next_approver(self, client):
        """Після approve першого — запрошується другий, і він з'являється у /approvals/my."""
        self._create_doc(client)
        client.post("/documents/AP-001/approval/submit", headers=_auth_headers())
        client.post(
            "/documents/AP-001/approval/action",
            json={"action": "approve"},
            headers=_auth_headers("КОВАЛЬЧУК Ірина"),
        )

        r = client.get("/approvals/my", headers=_auth_headers("БОНДАРЕНКО Максим"))
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["approver_status"] == "invited"

    def test_my_approvals_matches_by_user_id(self, client):
        """Погоджувач, прив'язаний через user_id, бачить документ у /approvals/my і може діяти."""
        import importlib as _il
        db = _il.import_module("portal.db")
        with db.SessionLocal() as s:
            u = db.User(
                email="jurist@dilovod.local",
                name="КОВАЛЬЧУК Ірина",
                position="Юрист",
                password_hash=db.User.hash_password("x"),
            )
            s.add(u)
            s.commit()
            s.refresh(u)
            uid = u.id

        payload = _doc_payload("AP-UID")
        payload["approvers"] = [
            {"order_index": 0, "user_id": uid, "full_name": "КОВАЛЬЧУК Ірина", "position": "Юрист"}
        ]
        client.post("/documents", json=payload)
        client.post("/documents/AP-UID/approval/submit", headers=_auth_headers())

        headers = _auth_headers(name="КОВАЛЬЧУК Ірина", sub=str(uid))
        r = client.get("/approvals/my", headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert data[0]["doc_id"] == "AP-UID"
        assert data[0]["user_id"] == uid

        # може погодити — action матчить за user_id
        r2 = client.post(
            "/documents/AP-UID/approval/action",
            json={"action": "approve"},
            headers=headers,
        )
        assert r2.status_code == 200

        # після погодження зник із черги (статус != invited)
        assert client.get("/approvals/my", headers=headers).json() == []

    def test_user_id_takes_precedence_over_name(self, client):
        """За наявності user_id мач тільки по ньому; ПІБ не впливає."""
        import importlib as _il
        db = _il.import_module("portal.db")
        with db.SessionLocal() as s:
            u = db.User(
                email="a@x.local",
                name="АНДРІЄНКО Олег",
                position="Бухгалтер",
                password_hash=db.User.hash_password("x"),
            )
            s.add(u)
            s.commit()
            s.refresh(u)
            uid = u.id

        payload = _doc_payload("AP-PRE")
        payload["approvers"] = [
            {"order_index": 0, "user_id": uid, "full_name": "ХТОСЬ ЗОВСІМ ІНШИЙ", "position": "x"}
        ]
        client.post("/documents", json=payload)
        client.post("/documents/AP-PRE/approval/submit", headers=_auth_headers())

        # власник user_id бачить документ незважаючи на те, що ПІБ не збігається
        r = client.get("/approvals/my", headers=_auth_headers(sub=str(uid), name="АНДРІЄНКО Олег"))
        assert r.status_code == 200
        assert len(r.json()) == 1


# ============================================================
# RESOLUTIONS
# ============================================================


class TestResolutions:
    def _signed_doc(self, client) -> dict:
        client.post("/documents", json=_doc_payload("RS-001"))
        client.post("/documents/RS-001/generate")
        client.post("/documents/RS-001/submit")
        client.post(
            "/documents/RS-001/sign",
            json={
                "signer_order_index": 0,
                "signature_b64": _fake_cms(),
                "certificate_serial": "58E2D9",
                "issuer": "КН ЕДП Дія",
            },
        )
        return client.get("/documents/RS-001", headers=_auth_headers()).json()

    def test_resolution_on_draft_400(self, client):
        client.post("/documents", json=_doc_payload("RS-DRAFT"))
        r = client.post(
            "/documents/RS-DRAFT/resolutions",
            json={"text": "Тест", "tasks": []},
            headers=_auth_headers(),
        )
        assert r.status_code == 400

    def test_create_resolution_with_tasks(self, client):
        self._signed_doc(client)
        payload = {
            "text": "Виконати аудит",
            "tasks": [
                {
                    "executor": "ІВАНЕНКО Анна",
                    "description": "Підготувати звіт",
                    "due_date": "2026-07-01",
                },
                {
                    "executor": "ІВАНЕНКО Анна",
                    "description": "Надіслати копію",
                    "due_date": "2026-07-05",
                },
            ],
        }
        r = client.post("/documents/RS-001/resolutions", json=payload, headers=_auth_headers())
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"

        # verify tasks persisted via GET
        resolutions = client.get("/documents/RS-001/resolutions", headers=_auth_headers()).json()
        assert len(resolutions) == 1
        assert resolutions[0]["text"] == "Виконати аудит"
        assert len(resolutions[0]["tasks"]) == 2
        assert resolutions[0]["tasks"][0]["executor"] == "ІВАНЕНКО Анна"
        assert resolutions[0]["tasks"][0]["status"] == "pending"

    def test_get_resolutions(self, client):
        self._signed_doc(client)
        client.post(
            "/documents/RS-001/resolutions",
            json={
                "text": "Резолюція 1",
                "tasks": [
                    {
                        "executor": "ІВАНЕНКО Анна",
                        "description": "Задача 1",
                        "due_date": "2026-07-01",
                    }
                ],
            },
            headers=_auth_headers(),
        )

        r = client.get("/documents/RS-001/resolutions", headers=_auth_headers())
        assert r.status_code == 200
        data = r.json()
        # GET returns a list directly (not wrapped in {"resolutions": [...]})
        assert len(data) == 1
        assert data[0]["text"] == "Резолюція 1"

    def test_resolution_on_published_document(self, client):
        client.post("/documents", json=_doc_payload("RS-PUB"))
        client.post("/documents/RS-PUB/generate")
        client.post("/documents/RS-PUB/submit")
        client.post(
            "/documents/RS-PUB/sign",
            json={
                "signer_order_index": 0,
                "signature_b64": _fake_cms(),
                "certificate_serial": "58E2D9",
                "issuer": "КН ЕДП Дія",
            },
        )
        client.post("/documents/RS-PUB/publish")

        r = client.post(
            "/documents/RS-PUB/resolutions",
            json={"text": "Опубліковано", "tasks": []},
            headers=_auth_headers(),
        )
        assert r.status_code == 200


# ============================================================
# TASKS
# ============================================================


class TestTasks:
    def _setup_tasks(self, client) -> None:
        client.post("/documents", json=_doc_payload("TK-001"))
        client.post("/documents/TK-001/generate")
        client.post("/documents/TK-001/submit")
        client.post(
            "/documents/TK-001/sign",
            json={
                "signer_order_index": 0,
                "signature_b64": _fake_cms(),
                "certificate_serial": "58E2D9",
                "issuer": "КН ЕДП Дія",
            },
        )
        client.post(
            "/documents/TK-001/resolutions",
            json={
                "text": "Виконати завдання",
                "tasks": [
                    {
                        "executor": "ІВАНЕНКО Анна",
                        "description": "Задача A",
                        "due_date": "2026-12-31",
                    },
                    {
                        "executor": "ПЕТРОВ Богдан",
                        "description": "Задача B",
                        "due_date": "2026-12-31",
                    },
                ],
            },
            headers=_auth_headers(),
        )

    def test_my_tasks_lists_assigned(self, client):
        self._setup_tasks(client)
        r = client.get("/tasks/my", headers=_auth_headers("ІВАНЕНКО Анна"))
        assert r.status_code == 200
        tasks = r.json()
        assert len(tasks) == 1
        assert tasks[0]["description"] == "Задача A"
        assert tasks[0]["document_id"] == "TK-001"

    def test_my_tasks_empty_for_unassigned(self, client):
        self._setup_tasks(client)
        r = client.get("/tasks/my", headers=_auth_headers("НЕ_ВИКОНАВЕЦЬ"))
        assert r.status_code == 200
        assert r.json() == []

    def test_update_task_status_to_completed(self, client):
        self._setup_tasks(client)
        my = client.get("/tasks/my", headers=_auth_headers("ІВАНЕНКО Анна")).json()
        task_id = my[0]["id"]

        r = client.post(
            f"/tasks/{task_id}/status",
            json={"status": "completed"},
            headers=_auth_headers("ІВАНЕНКО Анна"),
        )
        assert r.status_code == 200
        assert r.json()["status"] == "completed"

        tasks = client.get("/tasks/my", headers=_auth_headers("ІВАНЕНКО Анна")).json()
        assert tasks[0]["completed_at"] is not None

    def test_update_other_user_task_forbidden(self, client):
        self._setup_tasks(client)
        my = client.get("/tasks/my", headers=_auth_headers("ІВАНЕНКО Анна")).json()
        task_id = my[0]["id"]

        r = client.post(
            f"/tasks/{task_id}/status",
            json={"status": "completed"},
            headers=_auth_headers("ПЕТРОВ Богдан"),
        )
        assert r.status_code == 403

    def test_update_missing_task_404(self, client):
        r = client.post(
            "/tasks/9999/status",
            json={"status": "completed"},
            headers=_auth_headers(),
        )
        assert r.status_code == 404

    def test_unauthorized_tasks_401(self, client):
        r = client.get("/tasks/my")
        assert r.status_code == 401

    def test_tasks_sorted_active_first(self, client):
        self._setup_tasks(client)
        # завершуємо задачу через прямого запиту до БД (швидкий тест сортування)
        import importlib as _il

        db = _il.import_module("portal.db")
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session

        # знаходимо задачу ІВАНЕНКО і завершуємо її напряму
        from portal.db import SessionLocal

        with SessionLocal() as s:
            t = s.query(db.Task).filter_by(executor="ІВАНЕНКО Анна").first()
            from portal.db import TaskStatus

            t.status = TaskStatus.COMPLETED
            t.completed_at = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            )
            s.commit()

        tasks = client.get("/tasks/my", headers=_auth_headers("ІВАНЕНКО Анна")).json()
        statuses = [t["status"] for t in tasks]
        assert statuses == ["completed"]

        # ПЕТРОВ все ще активний
        tasks_p = client.get("/tasks/my", headers=_auth_headers("ПЕТРОВ Богдан")).json()
        assert tasks_p[0]["status"] == "pending"


# ============================================================
# USERS
# ============================================================


class TestUsers:
    def test_list_users_returns_seeded_admin(self, client):
        r = client.get("/users", headers=_auth_headers())
        assert r.status_code == 200
        users = r.json()
        admin = next((u for u in users if u["email"] == "admin@dilovod.local"), None)
        assert admin is not None
        assert admin["position"] == "Адміністратор"
        for key in ("id", "name", "email", "position"):
            assert key in admin

    def test_list_users_unauthorized_401(self, client):
        r = client.get("/users")
        assert r.status_code == 401

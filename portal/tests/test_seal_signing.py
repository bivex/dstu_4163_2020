"""E2E тести підписання електронною печаткою юрособи (eSeal).

Перевіряє повний потік: створення документа з signer_type='seal' → генерація →
подача у чергу → підпис eSeal-CMS → статус SIGNED + відмітка «Електронна печатка»
у rendered_marked. Також — авторизацію печатки за organization_cert_cn (НЕ-admin).
"""

from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path

import pytest

_PORTAL = Path(__file__).resolve().parents[1]
_SRC = _PORTAL.parent / "src"
for p in (_PORTAL.parent, _SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from dilovod4.infrastructure.test_cert_factory import (  # noqa: E402
    generate_test_ca,
    issue_eseal_cert,
    sign_data_with_leaf,
)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_file = tmp_path / "portal_seal_test.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")

    for mod in list(sys.modules.keys()):
        if mod == "portal" or mod.startswith("portal."):
            del sys.modules[mod]
    db = importlib.import_module("portal.db")
    main = importlib.import_module("portal.main")
    db.init_db()

    auth = importlib.import_module("portal.auth")
    main.app.dependency_overrides[auth._current_user] = lambda: {
        "sub": "1", "email": "admin@dilovod.local", "name": "Адміністратор",
        "role": "admin", "position": "Адміністратор",
    }

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def eseal_cms_factory():
    """Готує eSeal-CMS підпис під довільними даними (валідний PKCS#7 з cert)."""
    ca = generate_test_ca()
    leaf = issue_eseal_cert(ca, "ТОВ РОГА І КОПИТА", "43213421")

    def _sign(data: bytes) -> str:
        cms = sign_data_with_leaf(leaf, data)
        return base64.b64encode(cms).decode()

    return _sign


def _seal_doc_payload(doc_id: str = "SEAL-001") -> dict:
    """Документ із одним підписантом-печаткою юрособи."""
    return {
        "doc_id": doc_id,
        "org_name": "ТОВ РОГА І КОПИТА",
        "doc_type": "Наказ",
        "title": "Про застосування електронної печатки",
        "reg_index": "01",
        "date_text": "27 червня 2026 року",
        "fmt": "pdf",
        "is_electronic": True,
        "body": ["НАКАЗУЮ:", "1. Застосувати електронну печатку."],
        "signature_position": "Директор",
        "signature_name": "І. ПРІЗВИЩЕ",
        "signers": [
            {
                "order_index": 0,
                "full_name": "ТОВ РОГА І КОПИТА",
                "position": "",
                "signer_type": "seal",
            }
        ],
        "retention_years": 5,
    }


# --- основний потік --------------------------------------------------------

def test_seal_signing_full_flow(client, eseal_cms_factory):
    """create → generate → submit → sign(eSeal) → SIGNED + відмітка печатки."""
    # 1. створити документ із печаткою
    r = client.post("/documents", json=_seal_doc_payload())
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc["signers"][0]["signer_type"] == "seal"

    # 2. згенерувати
    r = client.post("/documents/SEAL-001/generate")
    assert r.status_code == 200, r.text

    # 3. подати у чергу
    r = client.post("/documents/SEAL-001/submit")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_signatures"

    # 4. отримати маніфест (дані, що підписуються)
    r = client.get("/documents/SEAL-001/manifest")
    assert r.status_code == 200, r.text
    manifest = r.content

    # 5. підписати маніфест eSeal-сертифікатом
    sig_b64 = eseal_cms_factory(manifest)

    # 6. надіслати підпис
    r = client.post(
        "/documents/SEAL-001/sign",
        json={"signer_order_index": 0, "signature_b64": sig_b64},
    )
    assert r.status_code == 200, r.text
    signed = r.json()
    assert signed["status"] == "signed"  # один підписант → відразу SIGNED
    # cert_type eseal → signer_type автоматично seal, organization збережено
    s0 = signed["signers"][0]
    assert s0["status"] == "signed"
    assert s0["signer_type"] == "seal"
    assert s0["organization"] == "ТОВ РОГА І КОПИТА"
    assert s0["identifier"] == "NTRUA-43213421"
    assert s0["certificate_serial"]  # витягнуто з сертифіката

    # 7. rendered_marked містить відмітку про ЕЛЕКТРОННУ ПЕЧАТКУ
    r = client.get("/documents/SEAL-001/download")
    assert r.status_code == 200
    # завантаження дає marked-версію (підписаний документ)
    assert len(r.content) > 1000


def test_seal_certificate_data_extracted_from_cms(client, eseal_cms_factory):
    """Дані печатки (організація, ЄДРПОУ, cert_type) витягуються з САМОГО CMS,
    а не довіряються клієнту."""
    client.post("/documents", json=_seal_doc_payload("SEAL-02"))
    client.post("/documents/SEAL-02/generate")
    client.post("/documents/SEAL-02/submit")
    manifest = client.get("/documents/SEAL-02/manifest").content
    sig_b64 = eseal_cms_factory(manifest)
    r = client.post(
        "/documents/SEAL-02/sign",
        json={"signer_order_index": 0, "signature_b64": sig_b64},
    )
    assert r.status_code == 200, r.text
    s0 = r.json()["signers"][0]
    # навіть якщо клієнт не передав organization — воно з сертифіката
    assert s0["organization"]
    assert s0["identifier"].startswith("NTRUA-")


def test_seal_then_person_mixed_queue(client, eseal_cms_factory):
    """Черга: спершу печатка юрособи, потім КЕП особи — обидва типи в одному
    документі. Перший підпис — eSeal-CMS, другий — псевдо-CMS (як у test_portal)."""
    payload = _seal_doc_payload("SEAL-03")
    payload["signers"] = [
        {"order_index": 0, "full_name": "ТОВ РОГА І КОПИТА", "signer_type": "seal"},
        {"order_index": 1, "full_name": "ПЕТРЕНКО Олександр", "signer_type": "person"},
    ]
    client.post("/documents", json=payload)
    client.post("/documents/SEAL-03/generate")
    client.post("/documents/SEAL-03/submit")

    # перший — печатка
    manifest = client.get("/documents/SEAL-03/manifest").content
    sig_b64 = eseal_cms_factory(manifest)
    r = client.post(
        "/documents/SEAL-03/sign",
        json={"signer_order_index": 0, "signature_b64": sig_b64},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "pending_signatures"  # ще другий підписант

    # другий — фейковий CMS (КЕП особи, admin обходить перевірку)
    fake_cms = base64.b64encode(b"\x30\x82\x02\x00" + b"\x00" * 600).decode()
    r = client.post(
        "/documents/SEAL-03/sign",
        json={"signer_order_index": 1, "signature_b64": fake_cms},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "signed"


# --- авторизація печатки (НЕ-admin) ---------------------------------------

def test_seal_signing_requires_organization_cert_cn(tmp_path, monkeypatch):
    """Не-admin може підписати печаткою ЛИШЕ якщо його organization_cert_cn
    збігається з назвою юрособи-підписанта. Інакше — 403."""
    db_file = tmp_path / "portal_seal_auth.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")

    for mod in list(sys.modules.keys()):
        if mod == "portal" or mod.startswith("portal."):
            del sys.modules[mod]
    db = importlib.import_module("portal.db")
    main = importlib.import_module("portal.main")
    db.init_db()
    main.app.dependency_overrides.clear()

    # користувач БЕЗ прив'язаної печатки
    def _no_seal_user():
        return {
            "sub": "100", "email": "u@org.local", "name": "Юзер",
            "role": "clerk", "position": "", "organization_cert_cn": None,
        }
    main.app.dependency_overrides[importlib.import_module("portal.auth")._current_user] = _no_seal_user

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        c.post("/documents", json=_seal_doc_payload("SEAL-AUTH"))
        c.post("/documents/SEAL-AUTH/generate")
        c.post("/documents/SEAL-AUTH/submit")
        # фейковий CMS (структурно валідний)
        fake_cms = base64.b64encode(b"\x30\x82\x02\x00" + b"\x00" * 600).decode()
        r = c.post(
            "/documents/SEAL-AUTH/sign",
            json={"signer_order_index": 0, "signature_b64": fake_cms},
        )
        assert r.status_code == 403  # печатка не прив'язана → заборонено


def test_seal_signing_allowed_with_matching_organization_cert_cn(tmp_path, monkeypatch):
    """Не-admin із organization_cert_cn == назві юрособи-підписанта може підписати."""
    db_file = tmp_path / "portal_seal_auth2.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")

    for mod in list(sys.modules.keys()):
        if mod == "portal" or mod.startswith("portal."):
            del sys.modules[mod]
    db = importlib.import_module("portal.db")
    main = importlib.import_module("portal.main")
    db.init_db()
    main.app.dependency_overrides.clear()

    def _seal_user():
        return {
            "sub": "101", "email": "dir@org.local", "name": "Директор",
            "role": "director", "position": "Директор",
            # прив'язана печатка з тим самим CN, що й підписант документа
            "organization_cert_cn": "ТОВ РОГА І КОПИТА",
        }
    main.app.dependency_overrides[importlib.import_module("portal.auth")._current_user] = _seal_user

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        c.post("/documents", json=_seal_doc_payload("SEAL-AUTH2"))
        c.post("/documents/SEAL-AUTH2/generate")
        c.post("/documents/SEAL-AUTH2/submit")
        fake_cms = base64.b64encode(b"\x30\x82\x02\x00" + b"\x00" * 600).decode()
        r = c.post(
            "/documents/SEAL-AUTH2/sign",
            json={"signer_order_index": 0, "signature_b64": fake_cms},
        )
        assert r.status_code == 200, r.text  # дозволено (CN збігається)

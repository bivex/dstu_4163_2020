"""E2E тести ендпоінту серверного підпису печаткою (POST /documents/{id}/server-seal).

Перевіряє: 503 без конфігурації, 403 без прив'язаної печатки, 409 для person-підписанта,
успішний підпис (з реальним DSTU-контейнером — самопропуск без libuapki).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_PORTAL = Path(__file__).resolve().parents[1]
_SRC = _PORTAL.parent / "src"
for p in (_PORTAL.parent, _SRC):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# Той самий тестовий DSTU-контейнер ІІТ, що в test_uapki_signing / test_server_seal.
_UAPKI_DATA = _PORTAL.parent / "external" / "UAPKI" / "library" / "test" / "data"
_TEST_P12 = _UAPKI_DATA / "test-diia.p12"


def _uapki_init_works() -> bool:
    try:
        from dilovod4.infrastructure.uapki import UapkiClient, UapkiError, UapkiLibraryNotFound

        with UapkiClient() as cli:
            cli.init(str(_UAPKI_DATA / "certs"), str(_UAPKI_DATA / "crls"), offline=True)
        return _TEST_P12.is_file()
    except (UapkiLibraryNotFound, OSError, UapkiError):
        return False


_HAS_UAPKI = _uapki_init_works()


def _seal_doc_payload(doc_id: str = "SSEAL-001") -> dict:
    """Документ із одним підписантом-печаткою юрособи."""
    return {
        "doc_id": doc_id,
        "org_name": "ТОВ РОГА І КОПИТА",
        "doc_type": "Наказ",
        "title": "Про серверний підпис печаткою",
        "reg_index": "01",
        "date_text": "27 червня 2026 року",
        "fmt": "pdf",
        "is_electronic": True,
        "body": ["НАКАЗУЮ:", "1. Застосувати серверну печатку."],
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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient (admin-override) без налаштованої печатки (PORTAL_SEAL_P12 не задано)."""
    db_file = tmp_path / "portal_sseal.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.delenv("PORTAL_SEAL_P12", raising=False)

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
        "organization_cert_cn": "ТОВ РОГА І КОПИТА",  # печатка прив'язана (для тестів)
    }

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


# --- edge cases (працюють без UAPKI) ---------------------------------------

def test_server_seal_returns_503_when_not_configured(client):
    """Без PORTAL_SEAL_P12 → 503."""
    client.post("/documents", json=_seal_doc_payload())
    client.post("/documents/SSEAL-001/generate")
    client.post("/documents/SSEAL-001/submit")
    r = client.post("/documents/SSEAL-001/server-seal")
    assert r.status_code == 503
    assert "не налаштований" in r.json()["detail"]


def test_server_seal_returns_409_for_person_signer(tmp_path, monkeypatch):
    """Активний підписант person (КЕП) → 409: серверний підпис лише для печаток."""
    db_file = tmp_path / "portal_sseal_person.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")
    # печатка нібито налаштована, але підписант — person
    monkeypatch.setenv("PORTAL_SEAL_P12", str(_TEST_P12))
    monkeypatch.setenv("PORTAL_SEAL_PASSWORD", "testpassword")

    for mod in list(sys.modules.keys()):
        if mod == "portal" or mod.startswith("portal."):
            del sys.modules[mod]
    importlib.import_module("portal.db").init_db()
    main = importlib.import_module("portal.main")
    auth = importlib.import_module("portal.auth")
    main.app.dependency_overrides[auth._current_user] = lambda: {
        "sub": "1", "role": "admin", "name": "Адм",
        "organization_cert_cn": "Особа",
    }
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        payload = _seal_doc_payload("SSEAL-PERSON")
        payload["signers"] = [{"order_index": 0, "full_name": "Особа", "signer_type": "person"}]
        c.post("/documents", json=payload)
        c.post("/documents/SSEAL-PERSON/generate")
        c.post("/documents/SSEAL-PERSON/submit")
        r = c.post("/documents/SSEAL-PERSON/server-seal")
        assert r.status_code == 409
        assert "не є печаткою" in r.json()["detail"]


def test_server_seal_returns_403_without_bound_seal(tmp_path, monkeypatch):
    """Юзер без прив'язаної печатки (organization_cert_cn None) → 403."""
    db_file = tmp_path / "portal_sseal_noorg.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("PORTAL_SEAL_P12", str(_TEST_P12))
    monkeypatch.setenv("PORTAL_SEAL_PASSWORD", "testpassword")

    for mod in list(sys.modules.keys()):
        if mod == "portal" or mod.startswith("portal."):
            del sys.modules[mod]
    importlib.import_module("portal.db").init_db()
    main = importlib.import_module("portal.main")
    auth = importlib.import_module("portal.auth")
    # НЕ admin, БЕЗ печатки — має отримати 403
    main.app.dependency_overrides[auth._current_user] = lambda: {
        "sub": "2", "role": "director", "name": "Директор",
        "organization_cert_cn": None,
    }
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        c.post("/documents", json=_seal_doc_payload("SSEAL-NOORG"))
        c.post("/documents/SSEAL-NOORG/generate")
        c.post("/documents/SSEAL-NOORG/submit")
        r = c.post("/documents/SSEAL-NOORG/server-seal")
        assert r.status_code == 403


def test_server_seal_409_before_submit(tmp_path, monkeypatch):
    """Документ у draft (не у черзі) → 409."""
    db_file = tmp_path / "portal_sseal_draft.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("PORTAL_SEAL_P12", str(_TEST_P12))
    monkeypatch.setenv("PORTAL_SEAL_PASSWORD", "testpassword")

    for mod in list(sys.modules.keys()):
        if mod == "portal" or mod.startswith("portal."):
            del sys.modules[mod]
    importlib.import_module("portal.db").init_db()
    main = importlib.import_module("portal.main")
    auth = importlib.import_module("portal.auth")
    main.app.dependency_overrides[auth._current_user] = lambda: {
        "sub": "1", "role": "admin", "name": "Адм",
        "organization_cert_cn": "ТОВ РОГА І КОПИТА",
    }
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        c.post("/documents", json=_seal_doc_payload("SSEAL-DRAFT"))
        # НЕ generate, НЕ submit
        r = c.post("/documents/SSEAL-DRAFT/server-seal")
        assert r.status_code == 409


# --- успішний підпис (потребує libuapki) -----------------------------------

def test_server_seal_signs_and_marks_document(tmp_path, monkeypatch):
    """Повний потік: печатку підписано сервером → SIGNED + дані з сертифіката.

    Самопропускається без libuapki (як існуючі тести uapki_signing).
    """
    if not _HAS_UAPKI:
        pytest.skip("libuapki не зібрана або INIT/контейнер недоступні")

    db_file = tmp_path / "portal_sseal_ok.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")
    monkeypatch.setenv("PORTAL_SEAL_P12", str(_TEST_P12))
    monkeypatch.setenv("PORTAL_SEAL_PASSWORD", "testpassword")
    # кеш сертифікатів/CRL — ті ж фікстури UAPKI
    monkeypatch.setenv("PORTAL_SEAL_CERT_CACHE", str(_UAPKI_DATA / "certs"))
    monkeypatch.setenv("PORTAL_SEAL_CRL_CACHE", str(_UAPKI_DATA / "crls"))

    for mod in list(sys.modules.keys()):
        if mod == "portal" or mod.startswith("portal."):
            del sys.modules[mod]
    importlib.import_module("portal.db").init_db()
    main = importlib.import_module("portal.main")
    auth = importlib.import_module("portal.auth")
    main.app.dependency_overrides[auth._current_user] = lambda: {
        "sub": "1", "role": "admin", "name": "Адміністратор",
        "organization_cert_cn": "ТОВ РОГА І КОПИТА",
    }
    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        c.post("/documents", json=_seal_doc_payload("SSEAL-OK"))
        c.post("/documents/SSEAL-OK/generate")
        c.post("/documents/SSEAL-OK/submit")

        r = c.post("/documents/SSEAL-OK/server-seal")
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["status"] == "signed"  # один підписант → відразу SIGNED
        s0 = doc["signers"][0]
        assert s0["status"] == "signed"
        assert s0["certificate_serial"]  # витягнуто з сертифіката печатки
        assert s0["signer_type"] == "seal"  # позначено як печатку

        # аудит фіксує джерело server-seal
        r2 = c.get("/documents/SSEAL-OK")
        events = r2.json().get("events", [])
        signed_events = [e for e in events if e["kind"] == "signed"]
        assert signed_events
        assert "source=server-seal" in signed_events[0]["detail"]

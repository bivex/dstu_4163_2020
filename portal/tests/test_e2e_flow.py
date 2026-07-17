import base64
import io
import zipfile
import sys
import importlib
import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient зі свіжою ізольованою БД на кожен тест."""
    db_file = tmp_path / "portal_test.db"
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
def no_override_client(client):
    """Скинути mock-override авторизації, щоб перевірити реальні JWT токени."""
    main = importlib.import_module("portal.main")
    saved = dict(main.app.dependency_overrides)
    main.app.dependency_overrides.clear()
    yield client
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides.update(saved)


def _doc_payload(doc_id="E2E-001") -> dict:
    return {
        "doc_id": doc_id,
        "org_name": "E2E Test Org",
        "doc_type": "Наказ",
        "title": "E2E Test Title",
        "reg_index": "01/E2E",
        "date_text": "17 липня 2026 року",
        "fmt": "pdf",
        "is_electronic": True,
        "body": ["Paragraph 1", "Paragraph 2"],
        "signature_position": "Генеральний Директор",
        "signature_name": "О.П. Директор",
        "signers": [
            {"full_name": "О.П. Директор", "position": "Генеральний Директор"}
        ],
        "retention_years": 55,
    }


def _fake_cms() -> str:
    body = b"\x30\x82\x02\x00" + b"\x00" * 600
    return base64.b64encode(body).decode()


def test_full_signing_e2e_flow(no_override_client):
    # 1. Import DB models and auth helpers locally AFTER fixture has run and cleared sys.modules
    from portal.db import SessionLocal, User, UserRole
    from portal.auth import _make_token

    # 2. Create a test user and obtain a JWT token
    with SessionLocal() as session:
        user = User(
            email="e2e_admin@org.local",
            name="E2E Admin User",
            password_hash=User.hash_password("admin_pass"),
            role=UserRole.ADMIN.value,
        )
        session.add(user)
        session.commit()
        token = _make_token(user)

    headers = {"Authorization": f"Bearer {token}"}

    # 3. Create the document
    res_create = no_override_client.post("/documents", json=_doc_payload(), headers=headers)
    assert res_create.status_code == 200

    # 4. Add an attachment
    pdf_content = b"%PDF-1.5 \n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj"
    files = {"file": ("attachment.pdf", pdf_content, "application/pdf")}
    res_att = no_override_client.post(
        "/documents/E2E-001/attachments", files=files, headers=headers
    )
    assert res_att.status_code == 200
    att_id = res_att.json()["id"]

    # 5. Generate the document content and submit it to the queue
    res_gen = no_override_client.post("/documents/E2E-001/generate", headers=headers)
    assert res_gen.status_code == 200

    res_submit = no_override_client.post("/documents/E2E-001/submit", headers=headers)
    assert res_submit.status_code == 200

    # 6. E2E Test on Attachment Packaging:
    #    Sign the attachment file and pack it as ASiC-E and ASiC-S
    dummy_att_sig = _fake_cms()
    res_pack = no_override_client.post(
        f"/documents/E2E-001/attachments/{att_id}/pack-asic",
        json={"signature_b64": dummy_att_sig, "type": "asice"},
        headers=headers,
    )
    assert res_pack.status_code == 200
    assert res_pack.headers["content-type"] == "application/zip"

    # Verify ASiC-E zip structure
    with zipfile.ZipFile(io.BytesIO(res_pack.content)) as z:
        names = z.namelist()
        assert "mimetype" in names
        assert "attachment.pdf" in names
        assert "META-INF/signature001.p7s" in names
        assert "META-INF/ASiCManifest001.xml" in names

    # 7. E2E Test on Document Signing:
    #    Get the signing manifest, sign it, and submit the signature
    res_manifest = no_override_client.get("/documents/E2E-001/manifest", headers=headers)
    assert res_manifest.status_code == 200

    doc_sig = _fake_cms()
    res_sign = no_override_client.post(
        "/documents/E2E-001/sign",
        json={"signer_order_index": 0, "signature_b64": doc_sig},
        headers=headers,
    )
    assert res_sign.status_code == 200
    assert res_sign.json()["status"] == "signed"

    # 8. E2E Test on Individual Signature Retrieval:
    #    Download the detached p7s signature of the first signer
    res_sig_dl = no_override_client.get(
        "/documents/E2E-001/signers/0/download-signature", headers=headers
    )
    assert res_sig_dl.status_code == 200
    assert res_sig_dl.content == base64.b64decode(doc_sig)
    assert res_sig_dl.headers["content-type"] == "application/pkcs7-signature"

    # 9. E2E Test on Query Token Authentication:
    #    Download the fully compiled ASiC-E archive using query token auth (without headers)
    res_asice = no_override_client.get(
        f"/documents/E2E-001/download/asice?token={token}"
    )
    assert res_asice.status_code == 200
    assert res_asice.headers["content-type"] == "application/vnd.etsi.asic-e+zip"

    # Verify ASiC-E zip contents (must bundle main document + attachments + signatures)
    with zipfile.ZipFile(io.BytesIO(res_asice.content)) as z:
        names = z.namelist()
        assert "mimetype" in names
        assert "E2E-001.pdf" in names
        assert "attachment.pdf" in names
        assert "META-INF/signature001.p7s" in names
        assert "META-INF/ASiCManifest001.xml" in names

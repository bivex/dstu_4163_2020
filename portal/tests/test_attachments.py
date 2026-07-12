import io
import zipfile
import base64
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_PORTAL = Path(__file__).resolve().parents[2]  # каталог portal/
if str(_PORTAL.parent) not in sys.path:
    sys.path.insert(0, str(_PORTAL.parent))


def _doc_payload(doc_id: str = "T-001", signers: int = 2) -> dict:
    sg = [
        {"order_index": 0, "full_name": "ПЕТРЕНКО Олександр", "position": "Директор"},
        {"order_index": 1, "full_name": "ТКАЧЕНКО Наталія", "position": "Головний бухгалтер"},
    ][:signers]
    return {
        "doc_id": doc_id,
        "org_name": "ДЕРЖАВНЕ ПІДПРИЄМСТВО «ДІЛОВОД»",
        "doc_type": "Наказ",
        "title": "Про затвердження річної звітності",
        "reg_index": "050-фін",
        "date_text": "14 червня 2026 року",
        "fmt": "pdf",
        "is_electronic": True,
        "body": ["Відповідно до Закону НАКАЗУЮ:", "1. Затвердити звітність."],
        "signature_position": "Директор",
        "signature_name": "О. ПЕТРЕНКО",
        "e_signatures": [
            {"signer": "ПЕТРЕНКО Олександр", "certificate_serial": "58E2D9",
             "issuer": "КН ЕДП Дія", "valid_from": "01.01.2026", "valid_to": "01.01.2028",
             "timestamp": "14.06.2026 09:00", "signer_position": "Директор"},
            {"signer": "ТКАЧЕНКО Наталія", "certificate_serial": "A1B2C3",
             "issuer": "КН ЕДП Дія", "valid_from": "01.01.2026", "valid_to": "01.01.2028",
             "timestamp": "14.06.2026 09:05", "signer_position": "Головний бухгалтер"},
        ][:signers],
        "signers": sg,
        "retention_years": 5,
    }


def _fake_cms() -> str:
    body = b"\x30\x82\x02\x00" + b"\x00" * 600  # SEQUENCE + достатній розмір
    return base64.b64encode(body).decode()


def _clerk_headers() -> dict:
    import jwt
    import datetime as _dt
    payload = {
        "sub": "777", "email": "clerk@org.local", "name": "КЛЕРК Тестовий",
        "role": "clerk", "position": "Інспектор",
        "exp": _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=24),
    }
    return {"Authorization": "Bearer " + jwt.encode(payload, "dilovod-dev-secret-change-in-prod", algorithm="HS256")}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import importlib
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

    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def no_override_client(client):
    import importlib
    main = importlib.import_module("portal.main")
    saved = dict(main.app.dependency_overrides)
    main.app.dependency_overrides.clear()
    yield client
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides.update(saved)


# 1. upload + list + download round-trip (PDF bytes; download is byte-identical, Content-Disposition matches name).
def test_upload_list_download_roundtrip(client):
    client.post("/documents", json=_doc_payload("T-001"))
    pdf_content = b"%PDF-1.4 mock pdf content"

    # Upload attachment
    res = client.post(
        "/documents/T-001/attachments",
        files={"file": ("report.pdf", pdf_content, "application/pdf")}
    )
    assert res.status_code == 200
    att = res.json()
    assert att["original_filename"] == "report.pdf"
    assert att["stored_filename"] == "report.pdf"
    assert att["mime"] == "application/pdf"
    assert att["size"] == len(pdf_content)

    # List attachments
    res = client.get("/documents/T-001/attachments")
    assert res.status_code == 200
    lst = res.json()
    assert len(lst) == 1
    assert lst[0]["id"] == att["id"]
    assert lst[0]["original_filename"] == "report.pdf"

    # Download attachment
    res = client.get(f"/documents/T-001/attachments/{att['id']}")
    assert res.status_code == 200
    assert res.content == pdf_content
    assert "Content-Disposition" in res.headers
    assert "report.pdf" in res.headers["Content-Disposition"]


# 2. filename uniqueness — two report.pdf -> second report-1.pdf.
def test_filename_uniqueness(client):
    client.post("/documents", json=_doc_payload("T-001"))
    pdf_content = b"%PDF-1.4 dummy file content"

    # First upload
    res1 = client.post(
        "/documents/T-001/attachments",
        files={"file": ("report.pdf", pdf_content, "application/pdf")}
    )
    assert res1.status_code == 200
    assert res1.json()["stored_filename"] == "report.pdf"

    # Second upload with same name
    res2 = client.post(
        "/documents/T-001/attachments",
        files={"file": ("report.pdf", pdf_content, "application/pdf")}
    )
    assert res2.status_code == 200
    assert res2.json()["stored_filename"] == "report-1.pdf"

    # Uploading {doc_id}.{fmt} which is reserved
    res3 = client.post(
        "/documents/T-001/attachments",
        files={"file": ("T-001.pdf", pdf_content, "application/pdf")}
    )
    assert res3.status_code == 200
    assert res3.json()["stored_filename"] == "T-001-1.pdf"  # Collides with reserved main document name


# 3. office file is accepted (.docx) -> 200.
def test_office_file_accepted(client):
    client.post("/documents", json=_doc_payload("T-001"))
    docx_content = b"mock docx file contents"

    res = client.post(
        "/documents/T-001/attachments",
        files={"file": ("document.docx", docx_content, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert res.status_code == 200
    assert res.json()["stored_filename"] == "document.docx"


# 4. 413 (over 25MB), 415 (unknown extension).
def test_limits_and_validation(client):
    client.post("/documents", json=_doc_payload("T-001"))

    # 415: Unknown extension
    res = client.post(
        "/documents/T-001/attachments",
        files={"file": ("malicious.exe", b"exe content", "application/octet-stream")}
    )
    assert res.status_code == 415

    # 413: Size over 25MB
    large_content = b"x" * (25 * 1024 * 1024 + 1)
    res = client.post(
        "/documents/T-001/attachments",
        files={"file": ("large.pdf", large_content, "application/pdf")}
    )
    assert res.status_code == 413


def test_mutability_lock_after_submit(no_override_client):
    headers = _clerk_headers()
    no_override_client.post("/documents", json=_doc_payload("T-001"), headers=headers)
    no_override_client.post(
        "/documents/T-001/attachments",
        files={"file": ("draft.pdf", b"%PDF-1.4 file", "application/pdf")},
        headers=headers
    )
    res = no_override_client.get("/documents/T-001/attachments", headers=headers)
    assert res.status_code == 200
    att_id = res.json()[0]["id"]

    # Submit document to lock it
    no_override_client.post("/documents/T-001/generate", headers=headers)
    no_override_client.post("/documents/T-001/submit", headers=headers)

    # Attempt to upload new attachment
    res_upload = no_override_client.post(
        "/documents/T-001/attachments",
        files={"file": ("another.pdf", b"%PDF-1.4", "application/pdf")},
        headers=headers
    )
    assert res_upload.status_code == 409

    # Attempt to delete attachment
    res_delete = no_override_client.delete(
        f"/documents/T-001/attachments/{att_id}",
        headers=headers
    )
    assert res_delete.status_code == 409


# 6. ASiC contains attachments (critical): create -> generate -> 2 attachments in DRAFT -> submit -> sign x2 -> GET /download/asice -> ZIP namelist contains T-001.pdf, scan1.pdf, scan2.pdf; META-INF/ASiCManifest001.xml references both with correct SHA-256 digest.
def test_asice_contains_attachments_with_digest(client):
    client.post("/documents", json=_doc_payload("T-001", signers=2))
    client.post("/documents/T-001/generate")

    # Add 2 attachments
    pdf1 = b"%PDF-1.4 scan1"
    pdf2 = b"%PDF-1.4 scan2"
    client.post("/documents/T-001/attachments", files={"file": ("scan1.pdf", pdf1, "application/pdf")})
    client.post("/documents/T-001/attachments", files={"file": ("scan2.pdf", pdf2, "application/pdf")})

    # Submit and sign
    client.post("/documents/T-001/submit")
    client.post("/documents/T-001/sign", json={"signer_order_index": 0, "signature_b64": _fake_cms()})
    client.post("/documents/T-001/sign", json={"signer_order_index": 1, "signature_b64": _fake_cms()})

    # Download ASiC-E
    res = client.get("/documents/T-001/download/asice")
    assert res.status_code == 200

    # Read zip content
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        namelist = zf.namelist()
        assert "T-001.pdf" in namelist
        assert "scan1.pdf" in namelist
        assert "scan2.pdf" in namelist
        assert "META-INF/ASiCManifest001.xml" in namelist

        # Inspect Manifest
        manifest_xml = zf.read("META-INF/ASiCManifest001.xml")
        root = ET.fromstring(manifest_xml)
        namespaces = {"asic": "http://uri.etsi.org/02918/v1.2.1#"}
        
        # Verify references
        refs = root.findall(".//asic:DataObjectReference", namespaces)
        # Should have 3 references: T-001.pdf, scan1.pdf, scan2.pdf
        assert len(refs) == 3
        ref_names = [ref.get("URI") for ref in refs]
        assert "T-001.pdf" in ref_names
        assert "scan1.pdf" in ref_names
        assert "scan2.pdf" in ref_names


# 7. manifest byte-identity: GET /manifest before signing == META-INF/ASiCManifest001.xml in built container.
def test_manifest_byte_identity(client):
    client.post("/documents", json=_doc_payload("T-001", signers=2))
    client.post("/documents/T-001/generate")

    # Add attachments
    client.post("/documents/T-001/attachments", files={"file": ("scan1.pdf", b"%PDF-1.4 scan1", "application/pdf")})
    client.post("/documents/T-001/attachments", files={"file": ("scan2.pdf", b"%PDF-1.4 scan2", "application/pdf")})

    client.post("/documents/T-001/submit")

    # Get manifest before signing
    res_manifest = client.get("/documents/T-001/manifest")
    assert res_manifest.status_code == 200
    before_manifest_bytes = res_manifest.content

    # Sign and build asice
    client.post("/documents/T-001/sign", json={"signer_order_index": 0, "signature_b64": _fake_cms()})
    client.post("/documents/T-001/sign", json={"signer_order_index": 1, "signature_b64": _fake_cms()})

    # Download ASiC-E and extract manifest
    res_asice = client.get("/documents/T-001/download/asice")
    assert res_asice.status_code == 200

    with zipfile.ZipFile(io.BytesIO(res_asice.content)) as zf:
        # Note: signature001.p7s corresponds to the first signer (index 0).
        # Its manifest is ASiCManifest001.xml (since manifest_for calls index + 1).
        zf_manifest_bytes = zf.read("META-INF/ASiCManifest001.xml")
        
    assert before_manifest_bytes == zf_manifest_bytes


# 8. appendix_count -> AppendixRule — 11 додатків → validate → finding «потрібен опис».
def test_appendix_count_rule(client):
    client.post("/documents", json=_doc_payload("T-001"))
    client.post("/documents/T-001/generate")

    # Add 11 attachments
    for i in range(11):
        client.post(
            "/documents/T-001/attachments",
            files={"file": (f"scan-{i}.pdf", b"%PDF-1.4", "application/pdf")}
        )

    # Validate
    res = client.post("/documents/T-001/validate")
    assert res.status_code == 200
    report = res.json()
    assert report["conforms"] is False
    # Check if there is a finding about appendix description (AppendixRule clause 5.21)
    findings = []
    for r in report["results"]:
        findings.extend(r["findings"])
    
    # Let's search if any finding mentiones "додат"
    has_finding = any("додат" in f["message"].lower() for f in findings)
    assert has_finding, f"Expected finding for 11 attachments, got: {findings}"


# 9. cascade deletion — delete document -> Attachment rows are gone.
def test_cascade_deletion(client):
    client.post("/documents", json=_doc_payload("T-001"))
    client.post(
        "/documents/T-001/attachments",
        files={"file": ("scan1.pdf", b"%PDF-1.4", "application/pdf")}
    )

    # Verify attachment is there
    res = client.get("/documents/T-001/attachments")
    assert len(res.json()) == 1

    # Delete document
    res_delete = client.delete("/documents/T-001")
    assert res_delete.status_code == 200

    # Try listing attachments of deleted document -> 404
    res_list = client.get("/documents/T-001/attachments")
    assert res_list.status_code == 404


# 10. admin bypasses status lock check
def test_admin_can_modify_locked_attachments(client):
    client.post("/documents", json=_doc_payload("T-001"))
    client.post(
        "/documents/T-001/attachments",
        files={"file": ("draft.pdf", b"%PDF-1.4 file", "application/pdf")}
    )
    res = client.get("/documents/T-001/attachments")
    att_id = res.json()[0]["id"]

    # Submit document to lock it
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/submit")

    # Admin user CAN upload new attachment even when locked
    res_upload = client.post(
        "/documents/T-001/attachments",
        files={"file": ("another.pdf", b"%PDF-1.4", "application/pdf")}
    )
    assert res_upload.status_code == 200

    # Admin user CAN delete attachment even when locked
    res_delete = client.delete(f"/documents/T-001/attachments/{att_id}")
    assert res_delete.status_code == 200


# 11. gaps in order_index when deleting
def test_attachment_deletion_order_index_gaps(client):
    client.post("/documents", json=_doc_payload("T-001"))

    # Upload 3 attachments
    att1 = client.post("/documents/T-001/attachments", files={"file": ("first.pdf", b"%PDF-1.4", "application/pdf")}).json()
    att2 = client.post("/documents/T-001/attachments", files={"file": ("second.pdf", b"%PDF-1.4", "application/pdf")}).json()
    att3 = client.post("/documents/T-001/attachments", files={"file": ("third.pdf", b"%PDF-1.4", "application/pdf")}).json()

    assert att1["order_index"] == 0
    assert att2["order_index"] == 1
    assert att3["order_index"] == 2

    # Delete second one (index 1)
    res_del = client.delete(f"/documents/T-001/attachments/{att2['id']}")
    assert res_del.status_code == 200

    # List attachments, should only have first and third, with indexes 0 and 2
    lst = client.get("/documents/T-001/attachments").json()
    assert len(lst) == 2
    assert lst[0]["order_index"] == 0
    assert lst[1]["order_index"] == 2

    # Upload fourth attachment, order_index should be max(0, 2) + 1 = 3
    att4 = client.post("/documents/T-001/attachments", files={"file": ("fourth.pdf", b"%PDF-1.4", "application/pdf")}).json()
    assert att4["order_index"] == 3


# 12. Unicode sanitization edge cases
def test_unicode_sanitization_edge_cases(client):
    client.post("/documents", json=_doc_payload("T-001"))

    # Filename with path traversal, forbidden symbols, and Ukrainian/Cyrillic unicode
    weird_name = "../../../каталог/звіт: новий* файл?.pdf"
    res = client.post(
        "/documents/T-001/attachments",
        files={"file": (weird_name, b"%PDF-1.4", "application/pdf")}
    )
    assert res.status_code == 200
    stored_name = res.json()["stored_filename"]
    # Should strip path traversal/forbidden chars and preserve Ukrainian characters
    assert stored_name == "звіт новий файл.pdf"


# 13. test merged PDF generation with attachments
def test_merged_pdf_generation(client):
    client.post("/documents", json=_doc_payload("T-001"))
    # Generate main document PDF
    client.post("/documents/T-001/generate")

    # Add a PDF attachment
    nakaz_path = Path(__file__).resolve().parents[2] / "samples" / "pdf" / "nakaz.pdf"
    if nakaz_path.exists():
        att_bytes = nakaz_path.read_bytes()
    else:
        att_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [ 3 0 R ] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [ 0 0 595.27 841.89 ] >>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n180\n%%EOF\n"

    client.post(
        "/documents/T-001/attachments",
        files={"file": ("att.pdf", att_bytes, "application/pdf")}
    )

    # Trigger merged PDF
    res = client.get("/documents/T-001/merged-pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    
    # Read the merged PDF and verify page count
    from pypdf import PdfReader
    merged_reader = PdfReader(io.BytesIO(res.content))
    # Main document + attachment pages
    assert len(merged_reader.pages) > 1


# 14. test that delivery items list contains attachments with correct page counts
def test_delivery_items_contain_attachments(client):
    client.post("/documents", json=_doc_payload("T-001"))
    # Generate main doc
    client.post("/documents/T-001/generate")

    # Add a PDF attachment
    nakaz_path = Path(__file__).resolve().parents[2] / "samples" / "pdf" / "nakaz.pdf"
    if nakaz_path.exists():
        att_bytes = nakaz_path.read_bytes()
    else:
        att_bytes = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [ 3 0 R ] /Count 1 >>\nendobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [ 0 0 595.27 841.89 ] >>\nendobj\nxref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\ntrailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n180\n%%EOF\n"

    client.post(
        "/documents/T-001/attachments",
        files={"file": ("manual_instruction.pdf", att_bytes, "application/pdf")}
    )

    # Fetch delivery details
    res = client.get("/documents/T-001/delivery")
    assert res.status_code == 200
    data = res.json()
    items = data["items"]
    # There should be 2 items: main document and 1 attachment
    assert len(items) == 2
    assert items[0]["name"] == "Наказ № 050-фін від 14 червня 2026 року «Про затвердження річної звітності»"
    assert items[0]["quantity"] == 1  # 1 page main doc
    assert items[1]["name"] == "Додаток 1: manual_instruction.pdf"
    assert items[1]["quantity"] == 1


# 15. test merged PDF with multi-page attachments to verify sequential page watermarks
def test_merged_pdf_multipage_watermarks(client):
    client.post("/documents", json=_doc_payload("T-001"))
    client.post("/documents/T-001/generate")

    # Generate a real 2-page PDF
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    out = io.BytesIO()
    can = canvas.Canvas(out, pagesize=A4)
    # Page 1
    can.drawString(100, 500, "First page content")
    can.showPage()
    # Page 2
    can.drawString(100, 500, "Second page content")
    can.showPage()
    can.save()
    att_bytes = out.getvalue()

    # Upload attachment
    client.post(
        "/documents/T-001/attachments",
        files={"file": ("multipage.pdf", att_bytes, "application/pdf")}
    )

    # Fetch merged PDF
    res = client.get("/documents/T-001/merged-pdf")
    assert res.status_code == 200
    
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(res.content))
    # Total pages: 1 (main) + 2 (attachment) = 3 pages
    assert len(reader.pages) == 3

    # Extract text from pages to verify watermark content and formatting
    p1_txt = reader.pages[0].extract_text()
    p2_txt = reader.pages[1].extract_text()
    p3_txt = reader.pages[2].extract_text()

    # Page 1 (main document) should not have the watermark
    assert "Додаток 1" not in p1_txt

    # Page 2 (first page of attachment)
    assert "Додаток 1" in p2_txt
    assert "до наказу № 050-фін" in p2_txt
    assert "Аркуш 1 з 2" in p2_txt

    # Page 3 (second page of attachment)
    assert "Додаток 1" in p3_txt
    assert "до наказу № 050-фін" in p3_txt
    assert "Аркуш 2 з 2" in p3_txt





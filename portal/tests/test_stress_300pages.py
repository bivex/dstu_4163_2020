"""Stress test: 300-page PDF attachment in merged PDF."""
import io
import sys
import time
from pathlib import Path
import pytest

_PORTAL = Path(__file__).resolve().parents[2]
if str(_PORTAL.parent) not in sys.path:
    sys.path.insert(0, str(_PORTAL.parent))


def _make_pdf(n_pages: int) -> bytes:
    from reportlab.pdfgen import canvas as rl_canvas
    from reportlab.lib.pagesizes import A4
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    for i in range(1, n_pages + 1):
        c.drawString(72, 700, f"Stress-test page {i} of {n_pages}")
        c.showPage()
    c.save()
    return buf.getvalue()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import importlib
    db_file = tmp_path / "portal_stress.db"
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
    return TestClient(main.app)


_PAYLOAD = {
    "doc_id": "S-300", "org_name": "ТОВ СТРЕС-ТЕСТ", "doc_type": "Наказ",
    "title": "Стрес-тест 300 сторінок", "reg_index": "300-ст",
    "date_text": "12 липня 2026 року", "fmt": "pdf", "is_electronic": True,
    "body": ["Тест."], "signature_position": "Директор", "signature_name": "А. ТЕСТ",
    "signers": [{"order_index": 0, "full_name": "Тест Андрій", "position": "Директор", "signer_type": "person"}],
    "retention_years": 1,
}


def test_stress_300_pages_correct_watermarks(client):
    att = _make_pdf(300)
    print(f"\n  Generated PDF: {len(att):,} bytes ({300} pages)")

    client.post("/documents", json=_PAYLOAD)
    client.post("/documents/S-300/generate")
    client.post("/documents/S-300/attachments",
                files={"file": ("big300.pdf", att, "application/pdf")})

    t0 = time.time()
    res = client.get("/documents/S-300/merged-pdf")
    elapsed = time.time() - t0

    assert res.status_code == 200, res.text
    print(f"  Merged PDF size: {len(res.content):,} bytes")
    print(f"  Time to generate: {elapsed:.2f}s")

    from pypdf import PdfReader
    pages = PdfReader(io.BytesIO(res.content)).pages
    assert len(pages) == 301, f"Expected 301 pages, got {len(pages)}"
    print(f"  Total pages in merged PDF: {len(pages)} ✅")

    p_first = pages[1].extract_text()
    p_mid   = pages[150].extract_text()
    p_last  = pages[300].extract_text()

    assert "Аркуш 1 з 300"   in p_first, f"Missing watermark on page 2: {p_first!r}"
    assert "Аркуш 150 з 300" in p_mid,   f"Missing watermark on page 151: {p_mid!r}"
    assert "Аркуш 300 з 300" in p_last,  f"Missing watermark on page 301: {p_last!r}"

    print("  Аркуш 1 з 300   ✅")
    print("  Аркуш 150 з 300 ✅")
    print("  Аркуш 300 з 300 ✅")

    # Watermark must NOT appear on main document page
    main_txt = pages[0].extract_text()
    assert "Аркуш" not in main_txt, "Watermark leaked onto main document page!"
    print("  Main page clean (no watermark bleed) ✅")

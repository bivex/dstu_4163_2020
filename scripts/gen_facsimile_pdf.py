import io, sys, os, datetime as dt
from pathlib import Path

# isolated temp DB
tmp = Path("/data/facsimile_test.db")
if tmp.exists():
    tmp.unlink()
os.environ["PORTAL_DATABASE_URL"] = f"sqlite:///{tmp}"

for m in list(sys.modules):
    if m == "portal" or m.startswith("portal."):
        del sys.modules[m]

import importlib

db = importlib.import_module("portal.db")
main = importlib.import_module("portal.main")
db.init_db()

from portal.db import User, Document, Approver, ApproverStatus
from PIL import Image

# 1) user with a facsimile PNG
png = io.BytesIO()
Image.new("RGBA", (200, 80), (180, 30, 30, 255)).save(png, format="PNG")
fac = png.getvalue()

with db.SessionLocal() as s:
    u = User(
        email="fac@demo.local",
        name="ПІДПИСАРЕНКО Юрій",
        password_hash=User.hash_password("x"),
        facsimile_blob=fac,
        facsimile_mime="image/png",
    )
    s.add(u)
    s.flush()
    uid = u.id

    # 2) document with a minimal rendered A4 PDF + an approved approver
    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\n"
        b"endobj\n2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\n"
        b"endobj\n3 0 obj\n<< /Type /Page /Parent 2 0 R "
        b"/MediaBox [0 0 595.27 841.89] >>\nendobj\n"
        b"xref\n0 4\n0000000000 65535 f\n"
        b"0000000009 00000 n\n0000000056 00000 n\n"
        b"0000000111 00000 n\ntrailer\n<< /Size 4 /Root 1 0 R >>\n"
        b"startxref\n180\n%%EOF\n"
    )
    doc = Document(
        doc_id="FAC-DEMO",
        title="Наказ про демонстрацію факсиміле",
        status=db.DocStatus.SIGNED,
        fmt="pdf",
        content_json='{"doc_type":"Наказ","reg_index":"1-Д","title":"демо"}',
        rendered=minimal_pdf,
    )
    ap = Approver(
        document_id=doc.id,
        order_index=0,
        user_id=uid,
        full_name="ПІДПИСАРЕНКО Юрій",
        position="Директор",
        status=ApproverStatus.APPROVED,
        approved_at=dt.datetime.now(dt.timezone.utc),
    )
    doc.approvers.append(ap)
    s.add(doc)
    s.commit()

# 3) call merged-pdf?visa=true as the facsimile owner
auth = importlib.import_module("portal.auth")
main.app.dependency_overrides[auth._current_user] = lambda: {
    "sub": str(uid),
    "email": "fac@demo.local",
    "name": "ПІДПИСАРЕНКО Юрій",
    "role": "admin",
    "position": "Директор",
}
from fastapi.testclient import TestClient

with TestClient(main.app) as c:
    r = c.get("/documents/FAC-DEMO/merged-pdf?visa=true")
    print("status", r.status_code, "bytes", len(r.content))
    out = Path("/data/facsimile_test.pdf")
    out.write_bytes(r.content)
    print("written", out)

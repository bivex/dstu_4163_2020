#!/usr/bin/env python3
"""Насіяти великий тестовий документ з 11 додатками для перевірки автогенерації опису додатків.
"""

from __future__ import annotations

import sys
import datetime as dt
import tempfile
import os
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PORTAL = _HERE.parent / "portal"
_SRC = _HERE.parent / "src"
for p in (_PORTAL, _SRC, _PORTAL.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from portal.db import SessionLocal, Document, DocStatus, Attachment, Signer, SignerStatus, init_db
from portal import domain_bridge as bridge
from portal.helpers import ensure_attachments_inventory

def main():
    init_db()
    with SessionLocal() as session:
        # Видалимо старий демо-документ, якщо він є
        doc_id = "BIG-DEMO-01"
        doc = session.query(Document).filter_by(doc_id=doc_id).first()
        if doc:
            session.query(Attachment).filter_by(document_id=doc.id).delete()
            session.query(Signer).filter_by(document_id=doc.id).delete()
            session.delete(doc)
            session.flush()

        # Видалимо потенційно застарілі вкладення за іменами файлів
        filenames_to_clean = [f"doc_attachment_{i}.pdf" for i in range(1, 12)] + ["опис_додатків.pdf"]
        session.query(Attachment).filter(Attachment.stored_filename.in_(filenames_to_clean)).delete(synchronize_session=False)
        session.flush()

        # Створимо Заяву про надання інформації (BIG-DEMO-01)
        payload = {
            "doc_id": doc_id,
            "org_name": "Гр. ПЕТРЕНКО ІВАН ІВАНОВИЧ",
            "doc_type": "Заява",
            "title": "Заява про надання великого пакету супровідних документів (11 додатків)",
            "reg_index": "21-ЗВ",
            "date_text": "21 липня 2026 року",
            "fmt": "pdf",
            "is_electronic": True,
            "body": [
                "Надсилаю вам великий пакет супровідних документів для розгляду справи.",
                "Оскільки кількість додатків перевищує 10, додаю автоматично згенерований опис додатків."
            ],
            "signature_position": "Заявник",
            "signature_name": "І. ПЕТРЕНКО",
            "signers": [
                {"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Заявник", "signer_type": "person"}
            ],
            "retention_years": 3,
            "sender_contacts": "м. Київ, вул. Хрещатик, 1\nтел. +380000000000"
        }

        # Генеруємо PDF для Заяви
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            bridge.generate(payload, "pdf", tmp_path)
            with open(tmp_path, "rb") as f:
                pdf_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        doc_obj = Document(
            doc_id=doc_id,
            title=payload["title"],
            fmt=payload["fmt"],
            status=DocStatus.SIGNED,
            content_json=bridge.content_to_json(payload),
            rendered=pdf_bytes,
            retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365 * 3),
        )
        doc_obj.signers.append(
            Signer(
                order_index=0,
                full_name="Петренко Іван Іванович",
                position="Заявник",
                status=SignerStatus.SIGNED,
                signer_type="person"
            )
        )
        session.add(doc_obj)
        session.flush()

        # Додамо 11 тестових вкладень
        for i in range(1, 12):
            att = Attachment(
                document_id=doc_obj.id,
                order_index=i - 1,
                original_filename=f"doc_attachment_{i}.pdf",
                stored_filename=f"doc_attachment_{i}.pdf",
                mime="application/pdf",
                size=len(b"%PDF-1.4 mock_nested_attachment"),
                blob=b"%PDF-1.4 mock_nested_attachment"
            )
            doc_obj.attachments.append(att)
            session.add(att)
        session.flush()

        # Викличемо ensure_attachments_inventory — це автоматично згенерує 12-й додаток "Опис додатків.pdf"!
        ensure_attachments_inventory(session, doc_obj)
        session.commit()

        print("Successfully seeded BIG-DEMO-01 with 11 attachments and automatically generated inventory (Опис додатків)!")

if __name__ == "__main__":
    main()

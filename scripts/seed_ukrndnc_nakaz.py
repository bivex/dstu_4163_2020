#!/usr/bin/env python3
"""Насіяти конкретний наказ ДП «УКРНДНЦ» з додатком Інструкція з діловодства у БД + згенерувати PDF.
"""

from __future__ import annotations

import sys
import datetime as dt
import tempfile
import os
import json
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PORTAL = _HERE.parent / "portal"
_SRC = _HERE.parent / "src"
for p in (_PORTAL, _SRC, _PORTAL.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from portal.db import SessionLocal, Document, DocStatus, Attachment, Signer, SignerStatus, init_db
from portal import domain_bridge as bridge

def main():
    init_db()
    
    # Завантажимо валідний PDF для додатка
    instrukciya_sample_path = _HERE.parent / "samples" / "pdf" / "instrukciya_proekt.pdf"
    if instrukciya_sample_path.exists():
        pdf_bytes = instrukciya_sample_path.read_bytes()
    else:
        pdf_bytes = b"%PDF-1.4 mock instrukciya"

    with SessionLocal() as session:
        doc_id = "NAKAZ-UKRNDNC-014"
        
        # Видалимо старий, якщо існує
        existing = session.query(Document).filter_by(doc_id=doc_id).first()
        if existing:
            session.delete(existing)
            session.flush()

        payload = {
            "doc_id": doc_id,
            "org_name": "ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
            "doc_type": "Наказ",
            "title": "Про затвердження інструкції з діловодства",
            "reg_index": "014-од",
            "date_text": "13 червня 2026 року",
            "fmt": "pdf",
            "is_electronic": True,
            "body": [
                "З метою впорядкування роботи з документами та відповідно до вимог ДСТУ 4163:2020 НАКАЗУЮ:",
                "1. Затвердити Інструкцію з діловодства (додається).",
                "2. Керівникам структурних підрозділів забезпечити дотримання вимог Інструкції.",
                "3. Контроль за виконанням цього наказу залишаю за собою."
            ],
            "signature_position": "Директор",
            "signature_name": "О. ПЕТРЕНКО",
            "signers": [
                {"order_index": 0, "full_name": "Петренко Олександр Васильович", "position": "Директор", "signer_type": "person"}
            ],
            "retention_years": 5,
            "_attachment_count": 1
        }

        doc = Document(
            doc_id=doc_id,
            title=payload["title"],
            fmt=payload["fmt"],
            status=DocStatus.DRAFT,
            content_json=bridge.content_to_json(payload),
            retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365 * 5),
            reg_index=payload["reg_index"],
            reg_date=payload["date_text"],
            doc_type=payload["doc_type"]
        )
        
        doc.signers.append(
            Signer(
                order_index=0,
                full_name="Петренко Олександр Васильович",
                position="Директор",
                status=SignerStatus.WAITING,
                signer_type="person"
            )
        )

        # Додаємо додаток "Інструкція з діловодства"
        att = Attachment(
            order_index=0,
            original_filename="instruktsiya_z_dilovodstva.pdf",
            stored_filename="instruktsiya_z_dilovodstva.pdf",
            mime="application/pdf",
            size=len(pdf_bytes),
            blob=pdf_bytes
        )
        doc.attachments.append(att)

        # Згенеруємо PDF за допомогою bridge.generate
        with tempfile.NamedTemporaryFile(suffix=f".{doc.fmt}", delete=False) as tmp:
            dest = tmp.name
        try:
            out = bridge.generate(payload, doc.fmt, dest)
            with open(out["path"], "rb") as fh:
                doc.rendered = fh.read()
            doc.conformance_json = json.dumps(out["report"], ensure_ascii=False)
            print("Successfully rendered PDF document body.")
        finally:
            for p in (dest, dest + f".{doc.fmt}"):
                if os.path.exists(p):
                    os.remove(p)

        session.add(doc)
        session.commit()
        
        # Запишемо копію згенерованого документа на диск, щоб користувач міг його відкрити прямо зараз
        out_pdf_path = _HERE.parent / "nakaz_ukrndnc_014.pdf"
        out_pdf_path.write_bytes(doc.rendered)
        print(f"Exported nakaz PDF to: {out_pdf_path}")
        
        # Відкриємо в браузері (Safari)
        print("Opening Nakaz PDF in Safari...")
        subprocess.run(["open", "-a", "Safari", str(out_pdf_path)])

if __name__ == "__main__":
    main()

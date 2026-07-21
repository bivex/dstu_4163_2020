#!/usr/bin/env python3
"""Насіяти тестові документи з вкладеними додатками для перевірки накладання штампів.
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

def main():
    init_db()
    with SessionLocal() as session:
        # Видалимо старі демо-документи, якщо вони є
        for doc_id in ["ZAYAVA-DEMO-01", "SKARGA-DEMO-02"]:
            doc = session.query(Document).filter_by(doc_id=doc_id).first()
            if doc:
                session.query(Attachment).filter_by(document_id=doc.id).delete()
                session.query(Signer).filter_by(document_id=doc.id).delete()
                session.delete(doc)
                session.flush()

        # Спочатку видалимо потенційно застарілі вкладення за іменами файлів
        session.query(Attachment).filter(Attachment.stored_filename.in_([
            "zayava_demo_01.pdf",
            "technical_specs_demo.pdf"
        ])).delete(synchronize_session=False)
        session.flush()

        # 1. Створимо Заяву (ZAYAVA-DEMO-01), яка буде першим рівнем вкладення
        zayava_id = "ZAYAVA-DEMO-01"
        payload_z = {
            "doc_id": zayava_id,
            "org_name": "Гр. ПЕТРЕНКО ІВАН ІВАНОВИЧ",
            "doc_type": "Заява",
            "title": "Заява про надання матеріальної допомоги",
            "reg_index": "7-ЗВ",
            "date_text": "21 липня 2026 року",
            "fmt": "pdf",
            "is_electronic": True,
            "body": [
                "Прошу надати мені матеріальну допомогу у зв'язку зі скрутним фінансовим становищем.",
                "До заяви додаю копію довідки про доходи."
            ],
            "signature_position": "Заявник",
            "signature_name": "І. ПЕТРЕНКО",
            "signers": [
                {"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Заявник", "signer_type": "person"}
            ],
            "retention_years": 3,
            "sender_contacts": "м. Київ, вул. Хрещатик, 1\nтел. +380000000000"
        }

        # Генеруємо PDF для Заяви за допомогою нашого PdfDocumentWriter
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            bridge.generate(payload_z, "pdf", tmp_path)
            with open(tmp_path, "rb") as f:
                zayava_pdf_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        doc_z = Document(
            doc_id=zayava_id,
            title=payload_z["title"],
            fmt=payload_z["fmt"],
            status=DocStatus.SIGNED,  # одразу підписаний, щоб мав згенерований PDF
            content_json=bridge.content_to_json(payload_z),
            rendered=zayava_pdf_bytes,
            retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365 * 3),
        )
        doc_z.signers.append(
            Signer(
                order_index=0,
                full_name="Петренко Іван Іванович",
                position="Заявник",
                status=SignerStatus.SIGNED,
                signer_type="person"
            )
        )
        session.add(doc_z)
        session.flush()

        # 2. Створимо Скаргу (SKARGA-DEMO-02)
        skarga_id = "SKARGA-DEMO-02"
        payload_s = {
            "doc_id": skarga_id,
            "org_name": "Гр. ПЕТРЕНКО ІВАН ІВАНОВИЧ",
            "doc_type": "Скарга",
            "title": "Скарга на неправомірні дії посадових осіб при розгляді заяви",
            "reg_index": "10-ЗВ/01",
            "date_text": "21 липня 2026 року",
            "fmt": "pdf",
            "is_electronic": True,
            "body": [
                "Звертаюся зі скаргою на бездіяльність та неправомірні рішення посадових осіб.",
                "До цієї скарги додаю раніше подану Заяву про надання допомоги, на яку не отримав відповіді.",
                "Прошу розглянути скаргу у встановлений законом строк."
            ],
            "signature_position": "Скаржник",
            "signature_name": "І. ПЕТРЕНКО",
            "signers": [
                {"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Скаржник", "signer_type": "person"}
            ],
            "retention_years": 3,
            "sender_contacts": "м. Київ, вул. Хрещатик, 1\nтел. +380000000000"
        }

        # Генеруємо PDF для Скарги
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            bridge.generate(payload_s, "pdf", tmp_path)
            with open(tmp_path, "rb") as f:
                skarga_pdf_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        doc_s = Document(
            doc_id=skarga_id,
            title=payload_s["title"],
            fmt=payload_s["fmt"],
            status=DocStatus.SIGNED,
            content_json=bridge.content_to_json(payload_s),
            rendered=skarga_pdf_bytes,
            retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365 * 3),
        )
        doc_s.signers.append(
            Signer(
                order_index=0,
                full_name="Петренко Іван Іванович",
                position="Скаржник",
                status=SignerStatus.SIGNED,
                signer_type="person"
            )
        )

        # Додаємо згенеровану раніше Заяву (zayava_pdf_bytes) як ДОДАТОК 1 до Скарги!
        att_z = Attachment(
            order_index=0,
            original_filename="zayava_demo_01.pdf",
            stored_filename="zayava_demo_01.pdf",
            mime="application/pdf",
            size=len(zayava_pdf_bytes),
            blob=zayava_pdf_bytes
        )
        doc_s.attachments.append(att_z)
        session.add(doc_s)
        session.commit()

        print("Successfully seeded ZAYAVA-DEMO-01 and SKARGA-DEMO-02 with nested attachment rendering!")

if __name__ == "__main__":
    main()

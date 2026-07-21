#!/usr/bin/env python3
"""Насіяти тестовий документ з подвійно вкладеними додатками для перевірки вертикольного стекінгу штампів.
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
from portal.routers.attachments import get_merged_pdf

def main():
    init_db()
    with SessionLocal() as session:
        # 1. Очистимо попередні демо-документи
        for doc_id in ["ZAYAVA-NEST-01", "SKARGA-NEST-02"]:
            doc = session.query(Document).filter_by(doc_id=doc_id).first()
            if doc:
                session.query(Attachment).filter_by(document_id=doc.id).delete()
                session.query(Signer).filter_by(document_id=doc.id).delete()
                session.delete(doc)
                session.flush()

        filenames_to_clean = ["sub_att_1.pdf", "sub_att_2.pdf", "zayava_full_package.pdf"]
        session.query(Attachment).filter(Attachment.stored_filename.in_(filenames_to_clean)).delete(synchronize_session=False)
        session.flush()

        # 2. Створимо Заяву (ZAYAVA-NEST-01)
        zayava_id = "ZAYAVA-NEST-01"
        payload_z = {
            "doc_id": zayava_id,
            "org_name": "Гр. ПЕТРЕНКО ІВАН ІВАНОВИЧ",
            "doc_type": "Заява",
            "title": "Первинна заява із під-додатками",
            "reg_index": "1-ЗВ",
            "date_text": "21 липня 2026 року",
            "fmt": "pdf",
            "is_electronic": True,
            "body": ["До цієї заяви додаються 2 довідки."],
            "signature_position": "Заявник",
            "signature_name": "І. ПЕТРЕНКО",
            "signers": [{"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Заявник", "signer_type": "person"}],
            "retention_years": 3,
        }

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            bridge.generate(payload_z, "pdf", tmp_path)
            with open(tmp_path, "rb") as f:
                z_main_pdf_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        doc_z = Document(
            doc_id=zayava_id,
            title=payload_z["title"],
            fmt=payload_z["fmt"],
            status=DocStatus.SIGNED,
            content_json=bridge.content_to_json(payload_z),
            rendered=z_main_pdf_bytes,
        )
        doc_z.signers.append(Signer(order_index=0, full_name="Петренко Іван Іванович", position="Заявник", status=SignerStatus.SIGNED, signer_type="person"))
        
        # Додамо 2 вкладення до Заяви
        att_z1 = Attachment(order_index=0, original_filename="sub_att_1.pdf", stored_filename="sub_att_1.pdf", mime="application/pdf", size=len(z_main_pdf_bytes), blob=z_main_pdf_bytes)
        att_z2 = Attachment(order_index=1, original_filename="sub_att_2.pdf", stored_filename="sub_att_2.pdf", mime="application/pdf", size=len(z_main_pdf_bytes), blob=z_main_pdf_bytes)
        doc_z.attachments.append(att_z1)
        doc_z.attachments.append(att_z2)
        session.add(doc_z)
        session.commit()

        # Генеруємо ЗЛИТИЙ PDF пакет Заяви (з її штампами додатків!)
        res = get_merged_pdf(zayava_id, visa=False)
        zayava_full_package_bytes = res.body

        # 3. Створимо Скаргу (SKARGA-NEST-02) та додамо пакет Заяви як Додаток 1
        skarga_id = "SKARGA-NEST-02"
        payload_s = {
            "doc_id": skarga_id,
            "org_name": "Гр. ПЕТРЕНКО ІВАН ІВАНОВИЧ",
            "doc_type": "Скарга",
            "title": "Скарга з додаванням повного пакету первинної заяви (з її додатками)",
            "reg_index": "2-ЗВ/01",
            "date_text": "21 липня 2026 року",
            "fmt": "pdf",
            "is_electronic": True,
            "body": ["Додаємо повний пакет первинної заяви з її власними додатками."],
            "signature_position": "Скаржник",
            "signature_name": "І. ПЕТРЕНКО",
            "signers": [{"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Скаржник", "signer_type": "person"}],
            "retention_years": 3,
        }

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            bridge.generate(payload_s, "pdf", tmp_path)
            with open(tmp_path, "rb") as f:
                s_main_pdf_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        doc_s = Document(
            doc_id=skarga_id,
            title=payload_s["title"],
            fmt=payload_s["fmt"],
            status=DocStatus.SIGNED,
            content_json=bridge.content_to_json(payload_s),
            rendered=s_main_pdf_bytes,
        )
        doc_s.signers.append(Signer(order_index=0, full_name="Петренко Іван Іванович", position="Скаржник", status=SignerStatus.SIGNED, signer_type="person"))

        att_s1 = Attachment(
            order_index=0,
            original_filename="zayava_full_package.pdf",
            stored_filename="zayava_full_package.pdf",
            mime="application/pdf",
            size=len(zayava_full_package_bytes),
            blob=zayava_full_package_bytes
        )
        doc_s.attachments.append(att_s1)
        session.add(doc_s)
        session.commit()

        print("Successfully seeded ZAYAVA-NEST-01 and SKARGA-NEST-02 with double-nested attachment stacking!")

if __name__ == "__main__":
    main()

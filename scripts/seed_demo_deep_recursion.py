#!/usr/bin/env python3
"""Глибока рекурсія 4 рівнів вкладеності для перевірки автоматичного вертикального стекінгу штампів.
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
        # Очистка
        for doc_id in ["L1-NAKAZ", "L2-ZAYAVA", "L3-SKARGA", "L4-AKT"]:
            doc = session.query(Document).filter_by(doc_id=doc_id).first()
            if doc:
                session.query(Attachment).filter_by(document_id=doc.id).delete()
                session.query(Signer).filter_by(document_id=doc.id).delete()
                session.delete(doc)
                session.flush()

        session.query(Attachment).filter(Attachment.stored_filename.in_([
            "pkg_l1.pdf", "pkg_l2.pdf", "pkg_l3.pdf", "sub_att_base.pdf"
        ])).delete(synchronize_session=False)
        session.flush()

        # Рівень 1: Наказ
        payload_1 = {
            "doc_id": "L1-NAKAZ",
            "org_name": "ТОВ «ДІЛОВОД-ІНТЕГРАЦІЯ»",
            "doc_type": "Наказ",
            "title": "Первинний наказ (Рівень 1)",
            "reg_index": "100-ОД",
            "date_text": "21 липня 2026 року",
            "fmt": "pdf",
            "is_electronic": True,
            "body": ["Текст первинного наказу."],
            "signature_position": "Директор",
            "signature_name": "І. ПЕТРЕНКО",
            "signers": [{"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Директор", "signer_type": "person"}],
            "retention_years": 3,
        }
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            bridge.generate(payload_1, "pdf", tmp_path)
            with open(tmp_path, "rb") as f:
                l1_pdf_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        doc_1 = Document(
            doc_id="L1-NAKAZ", title=payload_1["title"], fmt=payload_1["fmt"],
            status=DocStatus.SIGNED, content_json=bridge.content_to_json(payload_1), rendered=l1_pdf_bytes,
        )
        doc_1.attachments.append(Attachment(order_index=0, original_filename="sub_att_base.pdf", stored_filename="sub_att_base.pdf", mime="application/pdf", size=len(l1_pdf_bytes), blob=l1_pdf_bytes))
        session.add(doc_1)
        session.commit()
        pkg_l1 = get_merged_pdf("L1-NAKAZ", visa=False).body

        # Рівень 2: Заява з пакетом L1
        payload_2 = {
            "doc_id": "L2-ZAYAVA", "org_name": "Гр. ПЕТРЕНКО ІВАН ІВАНОВИЧ", "doc_type": "Заява",
            "title": "Заява другого рівня (Рівень 2)", "reg_index": "200-ЗВ", "date_text": "21 липня 2026 року",
            "fmt": "pdf", "is_electronic": True, "body": ["Додаємо Наказ 100-ОД."],
            "signature_position": "Заявник", "signature_name": "І. ПЕТРЕНКО",
            "signers": [{"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Заявник", "signer_type": "person"}], "retention_years": 3,
        }
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            bridge.generate(payload_2, "pdf", tmp_path)
            with open(tmp_path, "rb") as f:
                l2_pdf_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        doc_2 = Document(
            doc_id="L2-ZAYAVA", title=payload_2["title"], fmt=payload_2["fmt"],
            status=DocStatus.SIGNED, content_json=bridge.content_to_json(payload_2), rendered=l2_pdf_bytes,
        )
        doc_2.attachments.append(Attachment(order_index=0, original_filename="pkg_l1.pdf", stored_filename="pkg_l1.pdf", mime="application/pdf", size=len(pkg_l1), blob=pkg_l1))
        session.add(doc_2)
        session.commit()
        pkg_l2 = get_merged_pdf("L2-ZAYAVA", visa=False).body

        # Рівень 3: Скарга з пакетом L2
        payload_3 = {
            "doc_id": "L3-SKARGA", "org_name": "Гр. ПЕТРЕНКО ІВАН ІВАНОВИЧ", "doc_type": "Скарга",
            "title": "Скарга третього рівня (Рівень 3)", "reg_index": "300-ЗВ", "date_text": "21 липня 2026 року",
            "fmt": "pdf", "is_electronic": True, "body": ["Додаємо Заяву 200-ЗВ з її пакетом."],
            "signature_position": "Скаржник", "signature_name": "І. ПЕТРЕНКО",
            "signers": [{"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Скаржник", "signer_type": "person"}], "retention_years": 3,
        }
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            bridge.generate(payload_3, "pdf", tmp_path)
            with open(tmp_path, "rb") as f:
                l3_pdf_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        doc_3 = Document(
            doc_id="L3-SKARGA", title=payload_3["title"], fmt=payload_3["fmt"],
            status=DocStatus.SIGNED, content_json=bridge.content_to_json(payload_3), rendered=l3_pdf_bytes,
        )
        doc_3.attachments.append(Attachment(order_index=0, original_filename="pkg_l2.pdf", stored_filename="pkg_l2.pdf", mime="application/pdf", size=len(pkg_l2), blob=pkg_l2))
        session.add(doc_3)
        session.commit()
        pkg_l3 = get_merged_pdf("L3-SKARGA", visa=False).body

        # Рівень 4: Акт з пакетом L3
        payload_4 = {
            "doc_id": "L4-AKT", "org_name": "ТОВ «ДІЛОВОД-ІНТЕГРАЦІЯ»", "doc_type": "Акт",
            "title": "Акт перевірки четвертого рівня (Рівень 4 - Глибока рекурсія)", "reg_index": "400-АКТ", "date_text": "21 липня 2026 року",
            "fmt": "pdf", "is_electronic": True, "body": ["Додаємо весь чотирирівневий рекурсивний пакет."],
            "signature_position": "Голова комісії", "signature_name": "І. ПЕТРЕНКО",
            "signers": [{"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Голова комісії", "signer_type": "person"}], "retention_years": 3,
        }
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            bridge.generate(payload_4, "pdf", tmp_path)
            with open(tmp_path, "rb") as f:
                l4_pdf_bytes = f.read()
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

        doc_4 = Document(
            doc_id="L4-AKT", title=payload_4["title"], fmt=payload_4["fmt"],
            status=DocStatus.SIGNED, content_json=bridge.content_to_json(payload_4), rendered=l4_pdf_bytes,
        )
        doc_4.attachments.append(Attachment(order_index=0, original_filename="pkg_l3.pdf", stored_filename="pkg_l3.pdf", mime="application/pdf", size=len(pkg_l3), blob=pkg_l3))
        session.add(doc_4)
        session.commit()

        print("Successfully seeded 4-level deep recursion documents: L1-NAKAZ -> L2-ZAYAVA -> L3-SKARGA -> L4-AKT!")

if __name__ == "__main__":
    main()

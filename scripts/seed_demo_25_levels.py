#!/usr/bin/env python3
"""Генерація 25 рівнів рекурсивного вкладення для тестування граничних можливостей стекінгу.
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

DOC_TYPES_25 = [
    ("Наказ", "201-ОД"), ("Заява", "202-ЗВ"), ("Скарга", "203-ЗВ"), ("Акт", "204-АКТ"),
    ("Лист", "205-ВИХ"), ("Рішення", "206-РІШ"), ("Розпорядження", "207-РОЗ"), ("Протокол", "208-ПР"),
    ("Договір", "209-ДОГ"), ("Угода", "210-УГО"), ("Довідка", "211-ДОВ"), ("Запит", "212-ЗП"),
    ("Інструкція", "213-ІНСТ"), ("Положення", "214-ПОЛ"), ("Контракт", "215-КТ"), ("Статут", "216-СТ"),
    ("Регламент", "217-РЕГ"), ("Проект", "218-ПРК"), ("Наказ", "219-ОД"), ("Заява", "220-ЗВ"),
    ("Скарга", "221-ЗВ"), ("Акт", "222-АКТ"), ("Лист", "223-ВИХ"), ("Рішення", "224-РІШ"),
    ("Розпорядження", "225-РОЗ"),
]

def main():
    init_db()
    with SessionLocal() as session:
        # Очистка
        for idx in range(1, 26):
            doc_id = f"L{idx}-25DOC"
            doc = session.query(Document).filter_by(doc_id=doc_id).first()
            if doc:
                session.query(Attachment).filter_by(document_id=doc.id).delete()
                session.query(Signer).filter_by(document_id=doc.id).delete()
                session.delete(doc)
                session.flush()

        filenames = [f"pkg_25_l{i}.pdf" for i in range(1, 26)]
        session.query(Attachment).filter(Attachment.stored_filename.in_(filenames)).delete(synchronize_session=False)
        session.flush()

        prev_pdf_bytes = None

        for idx, (doc_type, reg_idx) in enumerate(DOC_TYPES_25, start=1):
            doc_id = f"L{idx}-25DOC"
            payload = {
                "doc_id": doc_id,
                "org_name": "ТОВ «ДІЛОВОД-ІНТЕГРАЦІЯ»",
                "doc_type": doc_type,
                "title": f"Документ {doc_type} (Рівень {idx} з 25)",
                "reg_index": reg_idx,
                "date_text": "21 липня 2026 року",
                "fmt": "pdf",
                "is_electronic": True,
                "body": [f"Це текст документа {doc_type} № {reg_idx} (Рівень {idx})."],
                "signature_position": "Підписант",
                "signature_name": "І. ПЕТРЕНКО",
                "signers": [{"order_index": 0, "full_name": "Петренко Іван Іванович", "position": "Підписант", "signer_type": "person"}],
                "retention_years": 3,
            }

            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                bridge.generate(payload, "pdf", tmp_path)
                with open(tmp_path, "rb") as f:
                    main_pdf_bytes = f.read()
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

            doc_obj = Document(
                doc_id=doc_id, title=payload["title"], fmt=payload["fmt"],
                status=DocStatus.SIGNED, content_json=bridge.content_to_json(payload), rendered=main_pdf_bytes,
            )
            doc_obj.signers.append(Signer(order_index=0, full_name="Петренко Іван Іванович", position="Підписант", status=SignerStatus.SIGNED, signer_type="person"))

            if prev_pdf_bytes:
                att = Attachment(
                    order_index=0,
                    original_filename=f"pkg_25_l{idx-1}.pdf",
                    stored_filename=f"pkg_25_l{idx-1}.pdf",
                    mime="application/pdf",
                    size=len(prev_pdf_bytes),
                    blob=prev_pdf_bytes
                )
                doc_obj.attachments.append(att)

            session.add(doc_obj)
            session.commit()

            res = get_merged_pdf(doc_id, visa=False)
            prev_pdf_bytes = res.body

        print("Successfully generated 25-level nested document hierarchy (L1-25DOC -> L25-25DOC)!")

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Генерація 10 рівнів рекурсивного вкладення для тестування автоматичного вертикального стекінгу штампів.
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

DOC_TYPES = [
    ("Наказ", "101-ОД"),
    ("Заява", "102-ЗВ"),
    ("Скарга", "103-ЗВ"),
    ("Акт", "104-АКТ"),
    ("Лист", "105-ВИХ"),
    ("Рішення", "106-РІШ"),
    ("Розпорядження", "107-РОЗ"),
    ("Протокол", "108-ПР"),
    ("Договір", "109-ДОГ"),
    ("Угода", "110-УГО"),
]

def main():
    init_db()
    with SessionLocal() as session:
        # Очистка
        for idx in range(1, 11):
            doc_id = f"L{idx}-DOC"
            doc = session.query(Document).filter_by(doc_id=doc_id).first()
            if doc:
                session.query(Attachment).filter_by(document_id=doc.id).delete()
                session.query(Signer).filter_by(document_id=doc.id).delete()
                session.delete(doc)
                session.flush()

        filenames = [f"pkg_l{i}.pdf" for i in range(1, 11)] + ["sub_base.pdf"]
        session.query(Attachment).filter(Attachment.stored_filename.in_(filenames)).delete(synchronize_session=False)
        session.flush()

        prev_pdf_bytes = None

        for idx, (doc_type, reg_idx) in enumerate(DOC_TYPES, start=1):
            doc_id = f"L{idx}-DOC"
            payload = {
                "doc_id": doc_id,
                "org_name": f"ТОВ «ДІЛОВОД-ІНТЕГРАЦІЯ»",
                "doc_type": doc_type,
                "title": f"Документ {doc_type} (Рівень {idx} з 10)",
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
                    original_filename=f"pkg_l{idx-1}.pdf",
                    stored_filename=f"pkg_l{idx-1}.pdf",
                    mime="application/pdf",
                    size=len(prev_pdf_bytes),
                    blob=prev_pdf_bytes
                )
                doc_obj.attachments.append(att)

            session.add(doc_obj)
            session.commit()

            res = get_merged_pdf(doc_id, visa=False)
            prev_pdf_bytes = res.body

        print("Successfully generated 10-level nested document hierarchy (L1-DOC -> L10-DOC)!")

if __name__ == "__main__":
    main()

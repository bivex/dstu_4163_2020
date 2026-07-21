#!/usr/bin/env python3
"""Насіяти тестові документи з додатками у БД порталу «Діловод».
"""

from __future__ import annotations

import sys
import datetime as dt
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
        # Спочатку видалимо будь-які потенційні конфліктні вкладення за іменами файлів
        session.query(Attachment).filter(Attachment.stored_filename.in_([
            "spec_draft_final.pdf",
            "budget_2026.xlsx",
            "schema_v1.png",
            "technical_requirements.pdf"
        ])).delete(synchronize_session=False)
        session.flush()

        # 1. Створимо Наказ NAKAZ-SEED-01
        doc1_id = "NAKAZ-SEED-01"
        existing1 = session.query(Document).filter_by(doc_id=doc1_id).first()
        if existing1:
            session.query(Attachment).filter_by(document_id=existing1.id).delete()
            session.query(Signer).filter_by(document_id=existing1.id).delete()
            session.delete(existing1)
            session.flush()

        payload1 = {
            "doc_id": doc1_id,
            "org_name": "ТОВ «ДІЛОВОД-ІНТЕГРАЦІЯ»",
            "doc_type": "Наказ",
            "title": "Наказ про затвердження додатків та супровідних матеріалів",
            "reg_index": "12/ОД",
            "date_text": "12 липня 2026 року",
            "fmt": "pdf",
            "is_electronic": True,
            "body": ["З метою оптимізації документообігу та підготовки річної звітності НАКАЗУЮ:", "1. Затвердити супровідну специфікацію та бюджет (додаються).", "2. Додати матеріали до відповідних справ."],
            "signature_position": "Генеральний директор",
            "signature_name": "О. КРАВЧЕНКО",
            "signers": [
                {"order_index": 0, "full_name": "Кравченко Олександр Михайлович", "position": "Генеральний директор", "signer_type": "person"}
            ],
            "retention_years": 5
        }

        doc1 = Document(
            doc_id=doc1_id,
            title=payload1["title"],
            fmt=payload1["fmt"],
            status=DocStatus.DRAFT,
            content_json=bridge.content_to_json(payload1),
            retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365 * 5),
        )
        doc1.signers.append(
            Signer(
                order_index=0,
                full_name="Кравченко Олександр Михайлович",
                position="Генеральний директор",
                status=SignerStatus.WAITING,
                signer_type="person"
            )
        )

        # Додамо 2 додатки до Наказу
        att1_1 = Attachment(
            order_index=0,
            original_filename="spec_draft_final.pdf",
            stored_filename="spec_draft_final.pdf",
            mime="application/pdf",
            size=len(b"%PDF-1.4 spec_draft_final"),
            blob=b"%PDF-1.4 spec_draft_final"
        )
        att1_2 = Attachment(
            order_index=1,
            original_filename="budget_2026.xlsx",
            stored_filename="budget_2026.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            size=len(b"mock xlsx file contents"),
            blob=b"mock xlsx file contents"
        )
        doc1.attachments.append(att1_1)
        doc1.attachments.append(att1_2)

        session.add(doc1)

        # 2. Створимо Лист LIST-SEED-02
        doc2_id = "LIST-SEED-02"
        existing2 = session.query(Document).filter_by(doc_id=doc2_id).first()
        if existing2:
            session.query(Attachment).filter_by(document_id=existing2.id).delete()
            session.query(Signer).filter_by(document_id=existing2.id).delete()
            session.delete(existing2)
            session.flush()

        payload2 = {
            "doc_id": doc2_id,
            "org_name": "ТОВ «ДІЛОВОД-ІНТЕГРАЦІЯ»",
            "doc_type": "Лист",
            "title": "Лист-погодження технічного завдання",
            "reg_index": "45-вих",
            "date_text": "12 липня 2026 року",
            "fmt": "pdf",
            "is_electronic": True,
            "body": ["Надсилаємо вам для узгодження технічне завдання на проектування системи.", "Додаємо графічні схеми та опис функціональних вимог."],
            "signature_position": "Директор з ІТ",
            "signature_name": "О. НАЗАРЕНКО",
            "signers": [
                {"order_index": 0, "full_name": "Назаренко Олексій Дмитрович", "position": "Начальник ІТ-відділу", "signer_type": "person"}
            ],
            "retention_years": 3
        }

        doc2 = Document(
            doc_id=doc2_id,
            title=payload2["title"],
            fmt=payload2["fmt"],
            status=DocStatus.DRAFT,
            content_json=bridge.content_to_json(payload2),
            retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365 * 3),
        )
        doc2.signers.append(
            Signer(
                order_index=0,
                full_name="Назаренко Олексій Дмитрович",
                position="Начальник ІТ-відділу",
                status=SignerStatus.WAITING,
                signer_type="person"
            )
        )

        # Додамо 2 додатки до Листа
        att2_1 = Attachment(
            order_index=0,
            original_filename="schema_v1.png",
            stored_filename="schema_v1.png",
            mime="image/png",
            size=len(b"mock png file contents"),
            blob=b"mock png file contents"
        )
        att2_2 = Attachment(
            order_index=1,
            original_filename="technical_requirements.pdf",
            stored_filename="technical_requirements.pdf",
            mime="application/pdf",
            size=len(b"%PDF-1.4 technical_requirements"),
            blob=b"%PDF-1.4 technical_requirements"
        )
        doc2.attachments.append(att2_1)
        doc2.attachments.append(att2_2)

        session.add(doc2)

        session.commit()
        print(f"Successfully seeded {doc1_id} and {doc2_id} with mock attachments.")

if __name__ == "__main__":
    main()

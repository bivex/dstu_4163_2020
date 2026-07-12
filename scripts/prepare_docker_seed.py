#!/usr/bin/env python3
"""Скрипт для підготовки та запуску сідування бази даних у Docker реальними PDF-файлами (через Base64).
"""

import sys
import base64
import subprocess
from pathlib import Path

def main():
    # Шляхи на хості
    root = Path(__file__).resolve().parents[1]
    instrukciya_path = root / "samples" / "pdf" / "instrukciya_proekt.pdf"
    nakaz_path = root / "samples" / "pdf" / "nakaz.pdf"
    lyst_path = root / "samples" / "pdf" / "lyst.pdf"
    schema_path = root / "samples" / "pdf" / "enakaz.png"
    
    if not all(p.exists() for p in [instrukciya_path, nakaz_path, lyst_path, schema_path]):
        print("Error: Sample files not found on host!")
        return 1

    # Читаємо та кодуємо в base64
    instrukciya_b64 = base64.b64encode(instrukciya_path.read_bytes()).decode('utf-8')
    nakaz_b64 = base64.b64encode(nakaz_path.read_bytes()).decode('utf-8')
    lyst_b64 = base64.b64encode(lyst_path.read_bytes()).decode('utf-8')
    schema_b64 = base64.b64encode(schema_path.read_bytes()).decode('utf-8')

    # Шаблон скрипта для виконання всередині контейнера
    docker_script = f"""
import base64
import datetime as dt
import json
import tempfile
import os
import io
from portal.db import SessionLocal, Document, DocStatus, Attachment, Signer, SignerStatus, init_db
from portal import domain_bridge as bridge

init_db()

instrukciya_bytes = base64.b64decode("{instrukciya_b64}")
nakaz_bytes = base64.b64decode("{nakaz_b64}")
lyst_bytes = base64.b64decode("{lyst_b64}")
schema_bytes = base64.b64decode("{schema_b64}")

def generate_multipage_pdf(title: str, pages: int) -> bytes:
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from dilovod4.infrastructure.fonts import resolve_times_new_roman
        
        fonts = resolve_times_new_roman()
        FONT_REGULAR = "Temp-Font-Regular"
        pdfmetrics.registerFont(TTFont(FONT_REGULAR, fonts.regular))
        
        out = io.BytesIO()
        can = canvas.Canvas(out, pagesize=A4)
        for p in range(1, pages + 1):
            can.setFont(FONT_REGULAR, 12)
            can.drawCentredString(297, 800, "ПРОЕКТ")
            can.drawCentredString(297, 780, "ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»")
            can.drawCentredString(297, 760, "ІНСТРУКЦІЯ (" + title + ")")
            can.drawCentredString(297, 740, "10 червня 2026 року № 009-пр")
            can.drawCentredString(297, 720, "з діловодства та документообігу")
            
            can.drawString(54, 650, "Це тестова сторінка " + str(p) + " з " + str(pages) + " додатка.")
            can.drawString(54, 630, "1. Ця Інструкція визначає порядок роботи з документами відповідно до ДСТУ 4163:2020.")
            can.drawString(54, 610, "2. Документи оформлюють на бланках установленого зразка з дотриманням вимог.")
            can.drawString(54, 590, "3. Контроль за дотриманням Інструкції покладається на канцелярію.")
            
            can.drawString(54, 450, "Начальник канцелярії Л. МЕЛЬНИК")
            can.drawString(54, 420, "Розробник проєкту, провідний документознавець К. ШЕВЧЕНКО 10 червня 2026 року")
            can.drawString(54, 390, "Начальник юридичного відділу О. КОВАЛЬ 11 червня 2026 року")
            can.drawString(54, 360, "Зауваження: зауважень немає")
            
            can.showPage()
        can.save()
        return out.getvalue()
    except Exception as e:
        print("Error generating multipage: " + str(e))
        return b""

instrukciya_3pages = generate_multipage_pdf("Інструкція з діловодства", 3)
nakaz_2pages = generate_multipage_pdf("Специфікація", 2)
lyst_4pages = generate_multipage_pdf("Технічні вимоги", 4)

def finalize_and_sign(session, doc, payload):
    # 1. Generate PDF body
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        dest = tmp.name
    try:
        out = bridge.generate(payload, "pdf", dest)
        with open(out["path"], "rb") as fh:
            doc.rendered = fh.read()
        doc.conformance_json = json.dumps(out["report"], ensure_ascii=False)
    finally:
        for p in (dest, dest + ".pdf"):
            if os.path.exists(p):
                os.remove(p)

    # 2. Attach mock signatures
    fake_sig = b"\x30\x82\x02\x00" + b"\x00" * 600
    for s in doc.signers:
        s.status = SignerStatus.SIGNED
        s.signature = fake_sig
    doc.status = DocStatus.SIGNED

    # 3. Assemble ASiC-E container
    from portal.helpers import _assemble_asice
    _assemble_asice(session, doc)

with SessionLocal() as session:
    # 1. Оновимо NAKAZ-UKRNDNC-014
    doc_id = "NAKAZ-UKRNDNC-014"
    existing = session.query(Document).filter_by(doc_id=doc_id).first()
    if existing:
        session.delete(existing)
        session.flush()

    payload = {{
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
            {{"order_index": 0, "full_name": "Петренко Олександр Васильович", "position": "Директор", "signer_type": "person"}}
        ],
        "retention_years": 5,
        "_attachment_count": 1
    }}

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
    doc.attachments.append(Attachment(
        order_index=0,
        original_filename="instruktsiya_z_dilovodstva.pdf",
        stored_filename="instruktsiya_z_dilovodstva.pdf",
        mime="application/pdf",
        size=len(instrukciya_3pages),
        blob=instrukciya_3pages
    ))

    # Згенеруємо PDF, підпишемо та створимо ASiC-E
    finalize_and_sign(session, doc, payload)
    session.add(doc)

    # 2. Оновимо NAKAZ-SEED-01
    doc_id = "NAKAZ-SEED-01"
    existing = session.query(Document).filter_by(doc_id=doc_id).first()
    if existing:
        session.delete(existing)
        session.flush()

    payload = {{
        "doc_id": doc_id,
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
            {{"order_index": 0, "full_name": "Кравченко Олександр Михайлович", "position": "Генеральний директор", "signer_type": "person"}}
        ],
        "retention_years": 5,
        "_attachment_count": 2
    }}
    doc = Document(
        doc_id=doc_id,
        title=payload["title"],
        fmt=payload["fmt"],
        status=DocStatus.DRAFT,
        content_json=bridge.content_to_json(payload),
        retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365 * 5),
    )
    doc.signers.append(
        Signer(
            order_index=0,
            full_name="Кравченко Олександр Михайлович",
            position="Генеральний директор",
            status=SignerStatus.WAITING,
            signer_type="person"
        )
    )
    doc.attachments.append(Attachment(
        order_index=0,
        original_filename="spec_draft_final.pdf",
        stored_filename="spec_draft_final.pdf",
        mime="application/pdf",
        size=len(nakaz_2pages),
        blob=nakaz_2pages
    ))
    doc.attachments.append(Attachment(
        order_index=1,
        original_filename="budget_2026.xlsx",
        stored_filename="budget_2026.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        size=len(b"mock xlsx file contents"),
        blob=b"mock xlsx file contents"
    ))

    # Згенеруємо PDF, підпишемо та створимо ASiC-E
    finalize_and_sign(session, doc, payload)
    session.add(doc)

    # 3. Оновимо LIST-SEED-02
    doc_id = "LIST-SEED-02"
    existing = session.query(Document).filter_by(doc_id=doc_id).first()
    if existing:
        session.delete(existing)
        session.flush()

    payload = {{
        "doc_id": doc_id,
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
            {{"order_index": 0, "full_name": "Назаренко Олексій Дмитрович", "position": "Начальник ІТ-відділу", "signer_type": "person"}}
        ],
        "retention_years": 3,
        "_attachment_count": 2
    }}
    doc = Document(
        doc_id=doc_id,
        title=payload["title"],
        fmt=payload["fmt"],
        status=DocStatus.DRAFT,
        content_json=bridge.content_to_json(payload),
        retention_until=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365 * 3),
    )
    doc.signers.append(
        Signer(
            order_index=0,
            full_name="Назаренко Олексій Дмитрович",
            position="Начальник ІТ-відділу",
            status=SignerStatus.WAITING,
            signer_type="person"
        )
    )
    doc.attachments.append(Attachment(
        order_index=0,
        original_filename="schema_v1.png",
        stored_filename="schema_v1.png",
        mime="image/png",
        size=len(schema_bytes),
        blob=schema_bytes
    ))
    doc.attachments.append(Attachment(
        order_index=1,
        original_filename="technical_requirements.pdf",
        stored_filename="technical_requirements.pdf",
        mime="application/pdf",
        size=len(lyst_4pages),
        blob=lyst_4pages
    ))

    # Згенеруємо PDF, підпишемо та створимо ASiC-E
    finalize_and_sign(session, doc, payload)
    session.add(doc)

    session.commit()
    print("Database seeded with real signed PDF blobs successfully.")
"""

    # Записуємо тимчасовий скрипт
    temp_script_path = root / "scripts" / "seed_docker_attachments_real.py"
    temp_script_path.write_text(docker_script, encoding='utf-8')

    try:
        # Запускаємо в контейнері
        print("Executing seed script inside container...")
        res = subprocess.run(
            ["docker", "compose", "exec", "-T", "api", "python3"],
            input=docker_script.encode('utf-8'),
            capture_output=True
        )
        print("STDOUT:", res.stdout.decode('utf-8'))
        print("STDERR:", res.stderr.decode('utf-8'))
    finally:
        # Видаляємо тимчасовий файл
        if temp_script_path.exists():
            temp_script_path.unlink()

if __name__ == "__main__":
    sys.exit(main())

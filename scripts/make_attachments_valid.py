#!/usr/bin/env python3
"""Оновити блоби додатків у БД на валідні PDF та відкрити їх.
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PORTAL = _HERE.parent / "portal"
_SRC = _HERE.parent / "src"
for p in (_PORTAL, _SRC, _PORTAL.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from portal.db import SessionLocal, Attachment, init_db

def main():
    init_db()
    
    # 1. Шляхи до зразків
    lyst_path = _HERE.parent / "samples" / "pdf" / "lyst.pdf"
    nakaz_path = _HERE.parent / "samples" / "pdf" / "nakaz.pdf"
    
    if not lyst_path.exists() or not nakaz_path.exists():
        print("Samples not found!")
        return

    lyst_bytes = lyst_path.read_bytes()
    nakaz_bytes = nakaz_path.read_bytes()

    # 2. Оновлення в БД
    with SessionLocal() as session:
        # Знайдемо додаток spec_draft_final.pdf
        att1 = session.query(Attachment).filter_by(stored_filename="spec_draft_final.pdf").first()
        if att1:
            att1.blob = nakaz_bytes
            att1.size = len(nakaz_bytes)
            print("Updated spec_draft_final.pdf with valid nakaz.pdf bytes.")
            
        # Знайдемо додаток technical_requirements.pdf
        att2 = session.query(Attachment).filter_by(stored_filename="technical_requirements.pdf").first()
        if att2:
            att2.blob = lyst_bytes
            att2.size = len(lyst_bytes)
            print("Updated technical_requirements.pdf with valid lyst.pdf bytes.")
            
        session.commit()

    # 3. Експорт файлів для локального відкриття
    out_spec = _HERE.parent / "spec_draft_final.pdf"
    out_tech = _HERE.parent / "technical_requirements.pdf"
    
    out_spec.write_bytes(nakaz_bytes)
    out_tech.write_bytes(lyst_bytes)
    
    print(f"Exported valid files to:\n- {out_spec}\n- {out_tech}")
    
    # 4. Відкриття в браузері (Safari)
    print("Opening files in Safari...")
    subprocess.run(["open", "-a", "Safari", str(out_spec)])
    subprocess.run(["open", "-a", "Safari", str(out_tech)])

if __name__ == "__main__":
    main()

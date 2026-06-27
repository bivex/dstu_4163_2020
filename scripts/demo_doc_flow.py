#!/usr/bin/env python3
"""Демонстрація: як документ «крутиться» між користувачами штатної фірми.

Прогоняє повний lifecycle наказу через РЕАЛЬНЕ API порталу, показуючи, як
документ переходить від користувача до користувача (а не просто міняє статус).

Сценарій:
  1. CLERK (Іваненко, кадри) створює наказ про прийняття на роботу
  2. APPROVAL (послідовне):
     - Бойко А.В. (нач. юрвідділу, director) → погоджує
     - Бондаренко Н.П. (головбух, accountant) → погоджує
  3. SIGNING (черга):
     - Кравченко О.М. (директор) → підписує КЕП (через UAPKI, якщо є КНЕДП-ключ)
     - печатку юрособи → серверний підпис (якщо PORTAL_SEAL_P12)
  4. PUBLISH

На кожному кроці показує ХТО діє і ЯК змінюється статус документа. Це і є
наочна відповідь «як документи крутяться між юзерами».

Використання:
  python3 scripts/demo_doc_flow.py                      # повний цикл
  python3 scripts/demo_doc_flow.py --skip-sign          # без підписів (тільки flow)
  python3 scripts/demo_doc_flow.py --use-server-seal    # печатка через server-seal

Потребує: засіяний штат (scripts/seed_company.py) + запущений портал на :8000.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

BASE = "http://localhost:8000"


def _req(method: str, path: str, token: str | None = None, body: dict | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    # uvicorn --reload + важкий рендер PDF іноді скидає з'єднання — retry.
    last_exc = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read())
            except Exception:
                return e.code, {"error": e.read().decode("utf-8", "replace")}
        except (ConnectionResetError, TimeoutError, OSError) as e:
            last_exc = e
            time.sleep(0.8)
    return 599, {"error": f"network: {last_exc}"}


def login(email: str, password: str) -> str:
    st, d = _req("POST", "/auth/login", body={"email": email, "password": password})
    if st != 200:
        print(f"  [FAIL] логін {email}: {d}", file=sys.stderr)
        sys.exit(1)
    return d["token"]


# співробітники з засіяного штату (пароль 'password123' для всіх)
PASS = "password123"
CLERK = "ivanenko.o@rogy-kopyta.com.ua"        # Іваненко О.Г. — клерк кадрів
APPR1 = "boiko.a@rogy-kopyta.com.ua"           # Бойко А.В. — нач. юрвідділу
APPR2 = "bondarenko.n@rogy-kopyta.com.ua"      # Бондаренко Н.П. — головбух
SIGNER = "kravchenko.o@rogy-kopyta.com.ua"     # Кравченко О.М. — ген.директор


def banner(title: str) -> None:
    print()
    print("═" * 72)
    print(f"  {title}")
    print("═" * 72)


def who(token: str) -> str:
    _, d = _req("GET", "/auth/me", token=token)
    return f"{d.get('name','')} [{d.get('role','')}]"


def doc_state(token: str, doc_id: str) -> None:
    _, d = _req("GET", f"/documents/{doc_id}", token=token)
    print(f"     статус документа: {d.get('status')}")
    apprs = d.get("approvers", [])
    if apprs:
        print("     погоджувачі:")
        for a in apprs:
            print(f"       • {a.get('full_name'):<32} {a.get('status')}")
    sigs = d.get("signers", [])
    if sigs:
        print("     підписанти:")
        for s in sigs:
            extra = f" ({s.get('signer_type')})" if s.get("signer_type") == "seal" else ""
            print(f"       • {s.get('full_name'):<32} {s.get('status')}{extra}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Демо руху документа між користувачами.")
    ap.add_argument("--skip-sign", action="store_true", help="без підписів (зупинитись на черзі)")
    ap.add_argument("--use-server-seal", action="store_true",
                    help="накласти серверну печатку (PORTAL_SEAL_P12)")
    args = ap.parse_args()

    doc_id = f"DEMO-FLOW-{datetime.now().strftime('%H%M%S')}"
    print(f"Документ: {doc_id}")
    print(f"Портал: {BASE}")
    print("Сценарій: кадри → погодження(юр+бух) → печатка+директор → публікація")

    # Визначити CN печатки з PORTAL_SEAL_P12 (для підписанта-печатки у черзі).
    # Без PORTAL_SEAL_P12 демо печатки пропускається — лише КЕП директора.
    import os
    seal_p12 = os.environ.get("PORTAL_SEAL_P12")
    seal_pass = os.environ.get("PORTAL_SEAL_PASSWORD", "")
    seal_cn = ""
    if seal_p12 and args.use_server_seal:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
            from dilovod4.infrastructure.uapki import UapkiClient
            DATA = Path(__file__).resolve().parent.parent / "external" / "UAPKI" / "library" / "test" / "data"
            with UapkiClient() as cli:
                cli.init(str(DATA / "certs"), str(DATA / "crls"), offline=True)
                cli.open_pkcs12(seal_p12, seal_pass)
                cli.select_key(cli.list_keys()[0]["id"])
                cert_id = cli.call("SELECT_KEY", {"id": cli.list_keys()[0]["id"]}).get("certId")
                if cert_id:
                    info = cli.call("CERT_INFO", {"bytes": cert_id})
                    seal_cn = info.get("subjectCN", "")
            print(f"CN печатки (PORTAL_SEAL_P12): {seal_cn}")
        except Exception as e:  # noqa: BLE001
            print(f"[WARN] не вдалося визначити CN печатки: {e}")
    if not seal_cn:
        # дефолт для тестового ключа ДІЯ
        seal_cn = "ДП ДІЯ (Тестування)"
        print(f"CN печатки (дефолт): {seal_cn}")

    # ── 1. CLERK створює наказ ──────────────────────────────────────────
    banner("1️⃣  CLERK (Іваненко О.Г., кадри) створює наказ")
    tok = login(CLERK, PASS)
    print(f"  увійшов: {who(tok)}")
    body = {
        "doc_id": doc_id,
        "org_name": "ТОВ Рога і Копита",
        "doc_type": "Наказ",
        "title": "Про прийняття на роботу Сидоренка І.І.",
        "reg_index": "к/п-127",
        "date_text": "27.06.2026",
        "fmt": "pdf",
        "is_electronic": True,
        "body": [
            "НАКАЗУЮ:",
            "1. Прийняти Сидоренка Івана Івановича на посаду менеджера з продажу",
            "   з 01.07.2026 з окладом 18 000 грн.",
            "2. Бухгалтерії нараховувати заробітну плату відповідно до штатного розпису.",
        ],
        "signature_position": "Генеральний директор",
        "signature_name": "О.М. Кравченко",
        # погоджувачі (послідовно): юр, потім бух
        "approval_type": "sequential",
        "approvers": [
            {"order_index": 0, "full_name": "Бойко Андрій Вікторович", "position": "Начальник юридичного відділу"},
            {"order_index": 1, "full_name": "Бондаренко Наталія Петрівна", "position": "Головний бухгалтер"},
        ],
        # підписанти (черга). З --use-server-seal: спершу ПЕЧАТКА юрособи
        # (CN збігається з PORTAL_SEAL_P12), потім ДИРЕКТОР (КЕП). Без печатки —
        # лише директор (інакше печатка застрягне, директор не стане активним).
        "signers": (
            [
                {"order_index": 0, "full_name": seal_cn, "position": "Юрособа", "signer_type": "seal"},
                {"order_index": 1, "full_name": "Кравченко Олександр Михайлович", "position": "Генеральний директор", "signer_type": "person"},
            ] if args.use_server_seal else [
                {"order_index": 0, "full_name": "Кравченко Олександр Михайлович", "position": "Генеральний директор", "signer_type": "person"},
            ]
        ),
        "retention_years": 75,  # кадрові документи — тривалий строк
    }
    st, d = _req("POST", "/documents", token=tok, body=body)
    print(f"  створено: {st}")
    if st != 200:
        print(f"  [detail] {d}", file=sys.stderr)
        return 1

    # згенерувати PDF
    st, _ = _req("POST", f"/documents/{doc_id}/generate", token=tok)
    print(f"  PDF згенеровано: {st}")
    doc_state(tok, doc_id)

    # ── 2. APPROVAL (послідовне) ────────────────────────────────────────
    banner("2️⃣  ПОГОДЖЕННЯ — подача + дві згоди по черзі")
    # 2a. clerk подає на погодження
    st, _ = _req("POST", f"/documents/{doc_id}/approval/submit", token=tok)
    print(f"  {who(tok)} подав на погодження: {st}")
    doc_state(tok, doc_id)

    # 2b. перший погоджувач (Бойко, юр)
    tok_a1 = login(APPR1, PASS)
    print(f"\n  → активний погоджувач: {who(tok_a1)}")
    st, d = _req("POST", f"/documents/{doc_id}/approval/action", token=tok_a1,
                 body={"action": "approve", "comment": "Відповідає трудовому законодавству"})
    print(f"    погодив: {st} — {d.get('status', d)}")
    doc_state(tok_a1, doc_id)

    # 2c. другий погоджувач (Бондаренко, бух)
    tok_a2 = login(APPR2, PASS)
    print(f"\n  → активний погоджувач: {who(tok_a2)}")
    st, d = _req("POST", f"/documents/{doc_id}/approval/action", token=tok_a2,
                 body={"action": "approve", "comment": "Оклад у межах ШР"})
    print(f"    погодив: {st} — {d.get('status', d)}")
    doc_state(tok_a2, doc_id)

    # після погодження — документ переходить у чергу підписання автоматично
    # (або треба submit). Перевіримо статус:
    _, d = _req("GET", f"/documents/{doc_id}", token=tok_a2)
    if d.get("status") == "draft":
        # подаємо у чергу підписів
        st, _ = _req("POST", f"/documents/{doc_id}/submit", token=tok_a1)
        print(f"\n  {who(tok_a1)} подав у чергу підписання: {st}")

    # ── 3. SIGNING ──────────────────────────────────────────────────────
    banner("3️⃣  ПІДПИСАННЯ — черга")
    doc_state(tok_a2, doc_id)

    if args.skip_sign:
        print("\n  [--skip-sign] зупиняємось тут. Документ у черзі підписання.")
        return 0

    tok_admin = login("admin@dilovod.local", "admin")

    # 3a. ПЕЧАТКА юрособи (перший підписант, index 0) — через server-seal.
    #     CN підписанта-печатки має збігатися з organization_cert_cn автора
    #     печатки (див. _is_active_signer). Admin — службова заміна, пропускає.
    if args.use_server_seal:
        print(f"\n  → активний підписант #0: ПЕЧАТКА юрособи ({seal_cn})")
        st, d = _req("POST", f"/documents/{doc_id}/server-seal", token=tok_admin)
        print(f"    server-seal: {st} — {d.get('status', d) if isinstance(d, dict) else d}")
        if st != 200:
            print(f"    [деталь] {d}")
        doc_state(tok_admin, doc_id)

    # 3b. ДИРЕКТОР підписує КЕП (другий підписант, index 1).
    tok_s = login(SIGNER, PASS)
    order = 1 if args.use_server_seal else 0
    print(f"\n  → активний підписант #{order}: {who(tok_s)}")
    print("    Підпис КЕП вимагає сертифіката (EUSign/UAPKI).")
    print("    Для демо-пропуску підписуємо admin-ом (службова заміна).")
    # отримаємо маніфест (бінарний контент, не JSON)
    try:
        req = urllib.request.Request(f"{BASE}/documents/{doc_id}/manifest",
                                     headers={"Authorization": f"Bearer {tok_admin}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            manifest = r.read()
        st = 200
    except urllib.error.HTTPError as e:
        st, manifest = e.code, None
        print(f"    маніфест: {st} — підпис пропускаємо")
    if st != 200 or not manifest:
        print(f"    маніфест недоступний ({st}) — підпис пропускаємо")
    else:
        # підпишемо маніфест реальним КНЕДП-ключем через UAPKI, якщо є
        try:
            import base64
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
            from dilovod4.infrastructure.uapki import UapkiClient, UapkiError
            DATA = Path(__file__).resolve().parent.parent / "external" / "UAPKI" / "library" / "test" / "data"
            with UapkiClient() as cli:
                cli.init(str(DATA / "certs"), str(DATA / "crls"), offline=True)
                cli.open_pkcs12(str(DATA / "test-diia.p12"), "testpassword")
                cli.select_key(cli.list_keys()[0]["id"])
                sig = cli.sign_bytes(manifest, signature_format="CAdES-BES",
                                     detached=True, include_cert=True, ignore_cert_status=True)
                sig_b64 = sig["bytes"]
            st, d = _req("POST", f"/documents/{doc_id}/sign", token=tok_admin,
                         body={"signer_order_index": order, "signature_b64": sig_b64})
            print(f"    підписано КЕП (ДІЯ): {st} — {d.get('status', d)}")
        except Exception as e:  # noqa: BLE001
            print(f"    підпис КЕП пропущено: {e}")
            print("    (libuapki/ключ недоступні — використайте --skip-sign)")

    doc_state(tok_s, doc_id)

    # ── 4. PUBLISH ──────────────────────────────────────────────────────
    _, d = _req("GET", f"/documents/{doc_id}", token=tok_s)
    if d.get("status") == "signed":
        banner("4️⃣  ПУБЛІКАЦІЯ")
        st, d = _req("POST", f"/documents/{doc_id}/publish", token=tok_s)
        print(f"  {who(tok_s)} оприлюднив: {st} — {d.get('status', d) if isinstance(d, dict) else d}")
        doc_state(tok_s, doc_id)

    banner("✓ ДЕМО ЗАВЕРШЕНО")
    _, d = _req("GET", f"/documents/{doc_id}", token=tok_admin)
    print(f"  Підсумковий статус: {d.get('status')}")
    print(f"  Аудит-події:")
    for e in d.get("events", [])[-8:]:
        print(f"    • {e.get('kind'):<18} actor={e.get('actor',''):<22} {e.get('detail','')[:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

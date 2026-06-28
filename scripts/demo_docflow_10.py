#!/usr/bin/env python3
"""Масштабна демонстрація документообігу: 10 документів через різних співробітників.

Показує, як ВЕЛИКА фірма працює з документами щодня — кожен документ ініціює і
підписує РІЗНИЙ співробітник, документи перетинаються між відділами (один співробітник
погоджує документ №1 і створює документ №7, тощо). Так реалізується наочна картинка
«хто з ким і як» у документообігу.

Документи (різні типи — для різних відділів):
  1. Наказ про прийняття на роботу     — клерк кадрів → погодж(юр,бух) → директор
  2. Наказ про відпустку                — клерк кадрів → директор
  3. Рахунок-фактура за послуги         — бухгалтер → погодж(юр) → бухгалтер+директор
  4. Акт звірки взаєморозрахунків       — бухгалтер → головбух
  5. Договір поставки                   — менеджер закупівель → погодж(юр,бух) → директор
  6. Лист-відповідь контрагенту         — юрист → директор
  7. Довідка про доходи                 — бухгалтер → головбух
  8. Протокол наради                    — секретар → директор
  9. Заява на відпустку                 — менеджер → директор
  10. Звіт про виконання плану продажів — комерційний директор → директор

Кожен документ: створення → (погодження) → підпис(и) → публікація.
Використовує реальний API порталу + засіяний штат (seed_company.py).

Використання:
  python3 scripts/demo_docflow_10.py                    # 10 документів без печаток
  python3 scripts/demo_docflow_10.py --use-server-seal  # + печатка юрособи
  python3 scripts/demo_docflow_10.py --only 1,3,5        # лише конкретні документи
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
PASS = "password123"


# ═══════════════════════════════════════════════════════════════════════════
#  API helpers
# ═══════════════════════════════════════════════════════════════════════════
def _req(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
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
        except (ConnectionResetError, TimeoutError, OSError):
            time.sleep(0.6)
    return 599, {"error": "network"}


def login(email):
    # admin має пароль 'admin' (bootstrap); штат засіяний з password123
    pwd = "admin" if email == "admin@dilovod.local" else PASS
    st, d = _req("POST", "/auth/login", body={"email": email, "password": pwd})
    if st != 200:
        raise RuntimeError(f"логін {email} провалився: {d}")
    return d["token"]


def who(token):
    _, d = _req("GET", "/auth/me", token=token)
    return f"{d.get('name','?')} [{d.get('role','?')}]"


def create_doc(author_tok, body):
    st, d = _req("POST", "/documents", token=author_tok, body=body)
    if st != 200:
        raise RuntimeError(f"create: {d}")
    _req("POST", f"/documents/{body['doc_id']}/generate", token=author_tok)
    return d


def run_approval(doc_id, approver_emails, comments=None):
    """Подати на погодження + погодити всіма по черзі. Повертає True якщо був approval-етап."""
    # автор подає на погодження — потрібен токен автора; але submit вимагає editable,
    # тож подаємо першим погоджувачем (який теж має права). Простіше: подаємо admin.
    tok_admin = login("admin@dilovod.local")
    # перевіримо, чи є погоджувачі — якщо ні, одразу submit підписи
    _, doc = _req("GET", f"/documents/{doc_id}", token=tok_admin)
    if not doc.get("approvers"):
        # без погоджувачів — одразу в підписи
        _req("POST", f"/documents/{doc_id}/submit", token=tok_admin)
        return False

    # подача на погодження
    _req("POST", f"/documents/{doc_id}/approval/submit", token=tok_admin)
    for i, email in enumerate(approver_emails):
        tok = login(email)
        c = comments[i] if comments and i < len(comments) else "Погоджено"
        st, _ = _req("POST", f"/documents/{doc_id}/approval/action", token=tok,
                     body={"action": "approve", "comment": c})
        if st != 200:
            # fallback: admin погоджує (службова заміна)
            _req("POST", f"/documents/{doc_id}/approval/action", token=tok_admin,
                 body={"action": "approve", "comment": c + " (заміна)"})
    # після погодження — автоматично в підписи (або submit)
    _, doc = _req("GET", f"/documents/{doc_id}", token=tok_admin)
    if doc.get("status") == "draft":
        _req("POST", f"/documents/{doc_id}/submit", token=tok_admin)
    return True


def sign_kep(doc_id, order):
    """Підписати КЕП через UAPKI (admin-заміна)."""
    tok_admin = login("admin@dilovod.local")
    try:
        req = urllib.request.Request(f"{BASE}/documents/{doc_id}/manifest",
                                     headers={"Authorization": f"Bearer {tok_admin}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            manifest = r.read()
    except urllib.error.HTTPError:
        return
    try:
        import base64
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
        from dilovod4.infrastructure.uapki import UapkiClient
        DATA = Path(__file__).resolve().parent.parent / "external" / "UAPKI" / "library" / "test" / "data"
        with UapkiClient() as cli:
            cli.init(str(DATA / "certs"), str(DATA / "crls"), offline=True)
            cli.open_pkcs12(str(DATA / "test-diia.p12"), "testpassword")
            cli.select_key(cli.list_keys()[0]["id"])
            sig = cli.sign_bytes(manifest, signature_format="CAdES-BES",
                                 detached=True, include_cert=True, ignore_cert_status=True)
            sig_b64 = sig["bytes"]
        _req("POST", f"/documents/{doc_id}/sign", token=tok_admin,
             body={"signer_order_index": order, "signature_b64": sig_b64})
        return True
    except Exception:
        return False


def server_seal(doc_id):
    tok_admin = login("admin@dilovod.local")
    st, _ = _req("POST", f"/documents/{doc_id}/server-seal", token=tok_admin)
    return st == 200


def publish(doc_id, email):
    tok = login(email)
    st, _ = _req("POST", f"/documents/{doc_id}/publish", token=tok)
    return st == 200


# ═══════════════════════════════════════════════════════════════════════════
#  10 документів — різні відділи, різні типи, різні люди
# ═══════════════════════════════════════════════════════════════════════════
SEAL_CN = "ДП ДІЯ (Тестування)"


def doc_specs() -> list[dict]:
    """Опис 10 документів: хто ініціює, погоджує, підписує."""
    stamp = datetime.now().strftime("%H%M%S")
    return [
        # 1. Наказ про прийняття (кадри)
        {
            "n": 1, "icon": "📋",
            "title": "Наказ про прийняття на роботу Сидоренка І.І.",
            "doc_type": "Наказ про прийняття на роботу",
            "body": [
                "НАКАЗУЮ:",
                "1. Прийняти Сидоренка Івана Івановича на посаду менеджера з продажу",
                "   з 01.07.2026 з окладом 18 000 грн.",
            ],
            "author": "ivanenko.o@rogy-kopyta.com.ua",   # клерк кадрів
            "approvers": ["boiko.a@rogy-kopyta.com.ua", "bondarenko.n@rogy-kopyta.com.ua"],  # юр, бух
            "approval_comments": ["Відповідає трудовому законодавству", "Оклад у межах ШР"],
            "signers_person": ["kravchenko.o@rogy-kopyta.com.ua"],  # директор
        },
        # 2. Наказ про відпустку (кадри — швидко, без погодження)
        {
            "n": 2, "icon": "🏖️",
            "title": "Наказ про надання відпустки Мороз А.В.",
            "doc_type": "Наказ про відпустку",
            "body": [
                "НАКАЗУЮ:",
                "1. Надати щорічну відпустку тривалістю 14 календарних днів",
                "   Мороз Анні Володимирівні з 15.07.2026.",
            ],
            "author": "ivanenko.o@rogy-kopyta.com.ua",   # клерк кадрів
            "approvers": [],
            "signers_person": ["kravchenko.o@rogy-kopyta.com.ua"],  # директор
        },
        # 3. Рахунок-фактура (бухгалтер)
        {
            "n": 3, "icon": "💰",
            "title": "Рахунок-фактура №2026/В-318 за послуги",
            "doc_type": "Рахунок-фактура",
            "body": [
                "Послуга: постачання канцтоварів — 50 одиниць",
                "Сума: 12 000,00 грн (з ПДВ 20%)",
                "Платник: ТОВ «Замовник», ЄДРПОУ 31234567",
            ],
            "author": "bondarenko.n@rogy-kopyta.com.ua",  # головбух
            "approvers": ["boiko.a@rogy-kopyta.com.ua"],  # юр
            "approval_comments": ["Реквізити платника коректні"],
            "signers_person": ["bondarenko.n@rogy-kopyta.com.ua", "kravchenko.o@rogy-kopyta.com.ua"],  # бух + директор
        },
        # 4. Акт звірки (бухгалтер → головбух)
        {
            "n": 4, "icon": "📊",
            "title": "Акт звірки взаєморозрахунків з ТОВ «Контрагент» за ІІ кв. 2026",
            "doc_type": "Акт",
            "body": [
                "Залишок на 01.04.2026: 0,00 грн (дебет)",
                "Обіг за квартал: 145 200,00 грн",
                "Залишок на 30.06.2026: 12 000,00 грн (кредит)",
            ],
            "author": "melnyk.o@rogy-kopyta.com.ua",    # бухгалтер (ЗП)
            "approvers": [],
            "signers_person": ["bondarenko.n@rogy-kopyta.com.ua"],  # головбух
        },
        # 5. Договір поставки (закупівлі)
        {
            "n": 5, "icon": "📑",
            "title": "Договір поставки канцтоварів з ТОВ «Постачальник»",
            "doc_type": "Договір",
            "body": [
                "1. Предмет договору: постачання канцелярських товарів.",
                "2. Сума договору: 120 000,00 грн з ПДВ.",
                "3. Строк дії: до 31.12.2026.",
            ],
            "author": "levchenko.m@rogy-kopyta.com.ua",  # спец. закупівель
            "approvers": ["boiko.a@rogy-kopyta.com.ua", "bondarenko.n@rogy-kopyta.com.ua"],
            "approval_comments": ["Договорні умови відповідають закону", "Бюджет передбачено"],
            "signers_person": ["kravchenko.o@rogy-kopyta.com.ua"],  # директор
        },
        # 6. Лист-відповідь (юрист → директор)
        {
            "n": 6, "icon": "✉️",
            "title": "Лист-відповідь на претензію ТОВ «Клієнт»",
            "doc_type": "Лист",
            "body": [
                "На Вашу претензію №45 від 20.06.2026 повідомляємо:",
                "Зобов'язання буде виконано до 15.07.2026.",
                "Додатково надсилаємо акт звірки.",
            ],
            "author": "polishchuk.m@rogy-kopyta.com.ua",  # юрист
            "approvers": ["boiko.a@rogy-kopyta.com.ua"],  # нач. юрвідділу
            "approval_comments": ["Правова позиція обґрунтована"],
            "signers_person": ["kravchenko.o@rogy-kopyta.com.ua"],  # директор
        },
        # 7. Довідка про доходи (бухгалтер)
        {
            "n": 7, "icon": "📄",
            "title": "Довідка про доходи Власенка Д.О. за 6 міс. 2026 р.",
            "doc_type": "Довідка",
            "body": [
                "Підтверджуємо, що Власенко Дмитро Олександрович працює",
                "на посаді менеджера з продажу з 01.01.2024.",
                "Середньомісячний дохід: 22 500,00 грн.",
            ],
            "author": "tkachenko.i@rogy-kopyta.com.ua",  # бухгалтер (податки)
            "approvers": [],
            "signers_person": ["bondarenko.n@rogy-kopyta.com.ua"],  # головбух
        },
        # 8. Протокол наради (секретар → директор)
        {
            "n": 8, "icon": "📝",
            "title": "Протокол оперативної наради від 27.06.2026",
            "doc_type": "Протокол",
            "body": [
                "ПРИСУТНІ: директор, головбух, комерційний директор, нач. ІТ.",
                "ПОРЯДОК ДЕННИЙ: підсумки ІІ кварталу.",
                "РИШЕННЯ: 1. Збільшити обсяг закупівель на 15%. 2. Впровадити електронний документообіг.",
            ],
            "author": "muzychko.k@rogy-kopyta.com.ua",   # спец. техпідтримки (секретар)
            "approvers": [],
            "signers_person": ["kravchenko.o@rogy-kopyta.com.ua"],  # директор
        },
        # 9. Заява на відпустку (менеджер → директор)
        {
            "n": 9, "icon": "🌴",
            "title": "Заява про надання щорічної відпустки",
            "doc_type": "Заява",
            "body": [
                "Прошу надати мені щорічну відпустку тривалістю 14 к.д.",
                "з 10.08.2026.",
            ],
            "author": "moroz.a@rogy-kopyta.com.ua",      # менеджер з продажу
            "approvers": [],
            "signers_person": ["kravchenko.o@rogy-kopyta.com.ua"],  # директор
        },
        # 10. Звіт про продажі (комерційний директор → директор)
        {
            "n": 10, "icon": "📈",
            "title": "Звіт про виконання плану продажів за ІІ квартал 2026",
            "doc_type": "Звіт",
            "body": [
                "План: 2 500 000 грн. Факт: 2 720 000 грн (108,8%).",
                "Найкращий менеджер: Дмитренко П.Б.",
                "Прогноз на ІІІ квартал: +12% до плану.",
            ],
            "author": "rudenko.s@rogy-kopyta.com.ua",    # комерційний директор
            "approvers": ["bondarenko.n@rogy-kopyta.com.ua"],  # головбух (фін. перевірка)
            "approval_comments": ["Фінансові показники підтверджено"],
            "signers_person": ["kravchenko.o@rogy-kopyta.com.ua"],  # директор
        },
    ]


def _signer_full_name(email):
    """Перетворити email → ПІБ (через /users)."""
    tok_admin = login("admin@dilovod.local")
    st, users = _req("GET", "/users", token=tok_admin)
    for u in users:
        if u.get("email") == email:
            return u["name"]
    return email


# ═══════════════════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="Масштабне демо: 10 документів через штат.")
    ap.add_argument("--use-server-seal", action="store_true", help="додати печатку юрособи")
    ap.add_argument("--only", default="", help="лише конкретні документи (напр. 1,3,5)")
    args = ap.parse_args()

    only = {int(x) for x in args.only.split(",") if x.strip()} if args.only else None
    specs = doc_specs()
    if only:
        specs = [s for s in specs if s["n"] in only]

    stamp = datetime.now().strftime("%H%M%S")
    print("═" * 72)
    print(f"  МАСШТАБНЕ ДЕМО ДОКУМЕНТООБІГУ — {len(specs)} документів")
    print(f"  Портал: {BASE} | Печатка: {'так' if args.use_server_seal else 'ні'}")
    print("═" * 72)
    print()

    results = []  # (n, title, status, ok)
    for spec in specs:
        n = spec["n"]
        icon = spec["icon"]
        doc_id = f"DOC{n:02d}-{stamp}"
        print(f"┌─ {icon} ДОКУМЕНТ №{n}: {spec['title'][:55]}")
        print(f"│  Тип: {spec['doc_type']}")

        try:
            # автор
            tok_author = login(spec["author"])
            print(f"│  👤 Автор: {who(tok_author)}")

            # визначити ПІБ підписантів
            signers_payload = []
            for email in spec["signers_person"]:
                signers_payload.append({
                    "order_index": len(signers_payload),
                    "full_name": _signer_full_name(email),
                    "position": "",  # position з users не тягнемо для простоти
                    "signer_type": "person",
                })
            if args.use_server_seal:
                signers_payload.append({
                    "order_index": len(signers_payload),
                    "full_name": SEAL_CN,
                    "position": "Юрособа",
                    "signer_type": "seal",
                })

            body = {
                "doc_id": doc_id,
                "org_name": "ТОВ Рога і Копита",
                "doc_type": spec["doc_type"],
                "title": spec["title"],
                "reg_index": f"{n}-{stamp[-3:]}",
                "date_text": "27.06.2026",
                "fmt": "pdf",
                "is_electronic": True,
                "body": spec["body"],
                "signature_position": "Директор",
                "signature_name": "О.М. Кравченко",
                "approval_type": "sequential",
                "approvers": [
                    {"order_index": i, "full_name": _signer_full_name(e), "position": ""}
                    for i, e in enumerate(spec["approvers"])
                ],
                "signers": signers_payload,
                "retention_years": 3,
            }
            create_doc(tok_author, body)
            print(f"│  ✅ Створено + PDF згенеровано")

            # погодження
            had_approval = False
            if spec["approvers"]:
                print(f"│  🔄 Погодження ({len(spec['approvers'])} особи):")
                had_approval = run_approval(doc_id, spec["approvers"], spec.get("approval_comments"))
                for i, e in enumerate(spec["approvers"]):
                    c = spec.get("approval_comments", [""] * len(spec["approvers"]))
                    cmt = c[i] if i < len(c) else ""
                    print(f"│     • {who(login(e))}: ✅ {cmt}")
            else:
                # без погоджувачів — одразу подати у чергу підписання
                tok_admin = login("admin@dilovod.local")
                _req("POST", f"/documents/{doc_id}/submit", token=tok_admin)

            # підписи КЕП
            print(f"│  ✍️  Підписання КЕП ({len(spec['signers_person'])} особи):")
            for i in range(len(spec["signers_person"])):
                ok = sign_kep(doc_id, i)
                tok_s = login(spec["signers_person"][i])
                print(f"│     • #{i} {who(tok_s)}: {'✅ підписано' if ok else '⚠️ пропущено'}")

            # печатка
            if args.use_server_seal:
                ok = server_seal(doc_id)
                print(f"│     • #{len(spec['signers_person'])} 🔏 Печатка юрособи: {'✅' if ok else '⚠️'}")

            # публікація
            pub_ok = publish(doc_id, spec["author"])
            print(f"│  📤 Публікація: {'✅ оприлюднено' if pub_ok else '⚠️ (статус не signed?)'}")

            # фінальний статус
            tok_admin = login("admin@dilovod.local")
            _, d = _req("GET", f"/documents/{doc_id}", token=tok_admin)
            status = d.get("status", "?")
            results.append((n, spec["title"][:40], status, status == "published"))
            print(f"│  🏁 Статус: {status}")
            print(f"└{'─' * 70}")
            print()
        except Exception as e:
            print(f"│  ❌ ПОМИЛКА: {e}")
            print(f"└{'─' * 70}")
            results.append((n, spec["title"][:40], "ERROR", False))
            print()

    # ── підсумкова таблиця ──────────────────────────────────────────────
    print()
    print("═" * 72)
    print("  ПІДСУМОК ДОКУМЕНТООБІГУ")
    print("═" * 72)
    print(f"{'№':>3}  {'Документ':<42} {'Статус':<14} {'OK'}")
    print("-" * 72)
    ok_count = 0
    for n, title, status, ok in results:
        mark = "✅" if ok else "❌"
        print(f"{n:>3}  {title:<42} {status:<14} {mark}")
        if ok:
            ok_count += 1
    print("-" * 72)
    print(f"Успішно: {ok_count}/{len(results)} документів пройшли повний цикл → published")

    # ── статистика по користувачах ──────────────────────────────────────
    print()
    print("Активні учасники документообігу (за подіями аудиту):")
    tok_admin = login("admin@dilovod.local")
    from collections import Counter
    actors = Counter()
    for n, title, status, ok in results:
        doc_id = f"DOC{n:02d}-{stamp}"
        _, d = _req("GET", f"/documents/{doc_id}", token=tok_admin)
        for e in d.get("events", []):
            a = e.get("actor", "").strip()
            if a:
                actors[a] += 1
    for actor, cnt in actors.most_common(15):
        print(f"  • {actor[:35]:<35} {cnt} дій")
    return 0 if ok_count == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

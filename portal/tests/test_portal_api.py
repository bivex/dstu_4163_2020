"""Тести порталу підписання (FastAPI + dilovod4).

Кожен тест отримує ізольовану БД (тимчасовий SQLite) через фікстуру: env
PORTAL_DATABASE_URL встановлюється ДО імпорту portal.db, модулі перезавантажуються,
схема створюється наново. Перевіряється повний цикл багатопідписання, черга,
валідація ДСТУ/НПА, аудит та edge-cases.
"""

from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path

import pytest

_PORTAL = Path(__file__).resolve().parents[1]  # каталог portal/
if str(_PORTAL.parent) not in sys.path:
    sys.path.insert(0, str(_PORTAL.parent))


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """TestClient зі свіжою ізольованою БД на кожен тест."""
    db_file = tmp_path / "portal_test.db"
    monkeypatch.setenv("PORTAL_DATABASE_URL", f"sqlite:///{db_file}")

    # перезавантажити db та main, щоб engine підхопив тестовий URL
    for mod in ("portal.db", "portal.main"):
        if mod in sys.modules:
            del sys.modules[mod]
    db = importlib.import_module("portal.db")
    main = importlib.import_module("portal.main")
    db.init_db()

    from fastapi.testclient import TestClient

    with TestClient(main.app) as c:
        yield c


def _doc_payload(doc_id: str = "T-001", signers: int = 2) -> dict:
    sg = [
        {"order_index": 0, "full_name": "ПЕТРЕНКО Олександр", "position": "Директор"},
        {"order_index": 1, "full_name": "ТКАЧЕНКО Наталія", "position": "Головний бухгалтер"},
    ][:signers]
    return {
        "doc_id": doc_id,
        "org_name": "ДЕРЖАВНЕ ПІДПРИЄМСТВО «УКРНДНЦ»",
        "doc_type": "Наказ",
        "title": "Про затвердження річної звітності",
        "reg_index": "050-фін",
        "date_text": "14 червня 2026 року",
        "fmt": "pdf",
        "is_electronic": True,
        "body": ["Відповідно до Закону НАКАЗУЮ:", "1. Затвердити звітність."],
        "signature_position": "Директор",
        "signature_name": "О. ПЕТРЕНКО",
        "e_signatures": [
            {"signer": "ПЕТРЕНКО Олександр", "certificate_serial": "58E2D9",
             "issuer": "КН ЕДП Дія", "valid_from": "01.01.2026", "valid_to": "01.01.2028",
             "timestamp": "14.06.2026 09:00", "signer_position": "Директор"},
            {"signer": "ТКАЧЕНКО Наталія", "certificate_serial": "A1B2C3",
             "issuer": "КН ЕДП Дія", "valid_from": "01.01.2026", "valid_to": "01.01.2028",
             "timestamp": "14.06.2026 09:05", "signer_position": "Головний бухгалтер"},
        ][:signers],
        "signers": sg,
        "retention_years": 5,
    }


def _b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()


def _fake_cms() -> str:
    """Псевдо-CMS, що проходить серверну перевірку формату (DER SEQUENCE 0x30,
    ≥256 байт). Не криптографічно дійсний, але структурно прийнятний для тестів
    потоку черги/збирання ASiC-E."""
    body = b"\x30\x82\x02\x00" + b"\x00" * 600  # SEQUENCE + достатній розмір
    return base64.b64encode(body).decode()


# --- базові ---
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_document(client):
    r = client.post("/documents", json=_doc_payload())
    assert r.status_code == 200
    d = r.json()
    assert d["doc_id"] == "T-001"
    assert d["status"] == "draft"
    assert len(d["signers"]) == 2
    assert all(s["status"] == "waiting" for s in d["signers"])
    assert d["retention_until"] is not None  # ст.13 851-IV


def test_create_duplicate_upserts_draft(client):
    """POST на існуючу чернетку — upsert (оновлення), а не 409. Конфлікт 409
    лише якщо документ уже не draft (поданий/підписаний)."""
    client.post("/documents", json=_doc_payload())
    # повторний POST на draft → upsert (200), оновлює картку
    p2 = _doc_payload()
    p2["title"] = "Оновлений заголовок"
    r = client.post("/documents", json=p2)
    assert r.status_code == 200
    assert r.json()["title"] == "Оновлений заголовок"
    # після submit документ не draft → повторний POST дає 409
    client.post("/documents/T-001/submit", json={"auto_register": False})
    r2 = client.post("/documents", json=_doc_payload())
    assert r2.status_code == 409


def test_create_requires_doc_id(client):
    payload = _doc_payload()
    del payload["doc_id"]
    r = client.post("/documents", json=payload)
    assert r.status_code == 400


# --- генерація + валідація ---
def test_generate_conforms(client):
    client.post("/documents", json=_doc_payload())
    r = client.post("/documents/T-001/generate")
    assert r.status_code == 200
    rep = r.json()["report"]
    assert rep["conforms"] is True
    assert rep["findings_count"] == 0
    assert len(rep["results"]) == 15  # 13 ДСТУ + ст.7 + ст.21


def test_download_after_generate(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    r = client.get("/documents/T-001/download")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_download_before_generate_404(client):
    client.post("/documents", json=_doc_payload())
    r = client.get("/documents/T-001/download")
    assert r.status_code == 404


def test_validate_endpoint(client):
    """/validate інжектить реальні КЕП-відмітки з doc.signers (ст.7 851-IV):
    до підпису е-документ не оригінал (conforms=False через ELECTRONIC_ORIGINAL),
    після підпису всіма — conforms=True."""
    client.post("/documents", json=_doc_payload())
    # до підпису: не оригінал (відсутній підпис автора)
    r0 = client.post("/documents/T-001/validate")
    assert r0.status_code == 200
    assert r0.json()["conforms"] is False
    assert any(
        res["rule_id"] == "ELECTRONIC_ORIGINAL"
        for res in r0.json()["results"] if not res["conforms"]
    )
    # після підпису всіма: оригінал → conforms=True
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/submit", json={"auto_register": False})
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()})
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 1, "signature_b64": _fake_cms()})
    r1 = client.post("/documents/T-001/validate")
    assert r1.json()["conforms"] is True


# --- черга багатопідписання ---
def test_full_signing_lifecycle(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")

    # submit → перший INVITED
    d = client.post("/documents/T-001/submit").json()
    assert d["status"] == "pending_signatures"
    assert d["signers"][0]["status"] == "invited"
    assert d["signers"][1]["status"] == "waiting"

    # підпис #0 → наступний INVITED
    d = client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms(),
        "certificate_serial": "58E2D9", "issuer": "КН ЕДП Дія",
    }).json()
    assert d["signers"][0]["status"] == "signed"
    assert d["signers"][1]["status"] == "invited"
    assert d["status"] == "pending_signatures"

    # підпис #1 → SIGNED
    d = client.post("/documents/T-001/sign", json={
        "signer_order_index": 1, "signature_b64": _fake_cms(),
        "certificate_serial": "A1B2C3", "issuer": "КН ЕДП Дія",
    }).json()
    assert all(s["status"] == "signed" for s in d["signers"])
    assert d["status"] == "signed"

    # publish
    d = client.post("/documents/T-001/publish").json()
    assert d["status"] == "published"


def test_out_of_order_signing_rejected(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/submit")
    # спроба підписати #1 поки активний #0
    r = client.post("/documents/T-001/sign", json={
        "signer_order_index": 1, "signature_b64": _b64("x"),
    })
    assert r.status_code == 409


def test_sign_requires_signature(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/submit")
    r = client.post("/documents/T-001/sign", json={"signer_order_index": 0})
    assert r.status_code == 400


def test_sign_before_submit_rejected(client):
    client.post("/documents", json=_doc_payload())
    r = client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms(),
    })
    assert r.status_code == 409  # ще DRAFT, не PENDING_SIGNATURES


def test_resubmit_non_draft_rejected(client):
    """Документ, що вже у черзі/підписаний, не можна подати у чергу повторно —
    інакше скидаються статуси підписантів і затираються зібрані КЕП."""
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/submit")  # draft -> pending_signatures
    r = client.post("/documents/T-001/submit")  # повторно -> 409
    assert r.status_code == 409
    # після повного підпису -> також 409
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()})
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 1, "signature_b64": _fake_cms()})
    assert client.post("/documents/T-001/submit").status_code == 409


def test_garbage_signature_rejected(client):
    """Сервер відсікає не-CMS значення (тестові заглушки), щоб у контейнер не
    потрапило сміття, яке дає «помилку 33» при перевірці."""
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/submit")
    r = client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _b64("kep-signature-buh"),
    })
    assert r.status_code == 422


def test_publish_before_signed_rejected(client):
    client.post("/documents", json=_doc_payload())
    r = client.post("/documents/T-001/publish")
    assert r.status_code == 409


# --- архівування ---
def test_archive_and_unarchive(client):
    """Архівування — організаційна позначка, не змінює workflow-статус."""
    client.post("/documents", json=_doc_payload())
    d = client.post("/documents/T-001/archive").json()
    assert d["archived"] is True
    assert d["archived_at"] is not None
    assert d["status"] == "draft"  # workflow-статус не зачеплено
    # відновлення
    d2 = client.post("/documents/T-001/unarchive").json()
    assert d2["archived"] is False
    assert d2["archived_at"] is None


def test_archive_idempotent(client):
    """Повторне архівування не змінює мітку часу (ідемпотентно).

    Порівнюємо без tz-суфікса: SQLite зберігає naive datetime, тож друге
    читання приходить без «+00:00», хоча момент той самий.
    """
    client.post("/documents", json=_doc_payload())
    d1 = client.post("/documents/T-001/archive").json()
    first_at = d1["archived_at"]
    d2 = client.post("/documents/T-001/archive").json()
    norm = lambda s: s.replace("+00:00", "") if s else s  # noqa: E731
    assert norm(d2["archived_at"]) == norm(first_at)


def test_archive_preserves_through_signing(client):
    """Архівований документ зберігає позначку незалежно від підпису."""
    client.post("/documents", json=_doc_payload(signers=1))
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/archive")
    client.post("/documents/T-001/submit", json={"auto_register": False})
    d = client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()}).json()
    assert d["status"] == "signed"
    assert d["archived"] is True  # архів пережив підписання


def test_archive_missing_404(client):
    assert client.post("/documents/NOPE/archive").status_code == 404
    assert client.post("/documents/NOPE/unarchive").status_code == 404


def test_archived_appears_in_audit(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/archive")
    client.post("/documents/T-001/unarchive")
    d = client.get("/documents/T-001").json()
    kinds = [e["kind"] for e in d["events"]]
    assert "archived" in kinds
    assert "unarchived" in kinds


def test_reject_returns_to_draft(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/submit")
    d = client.post("/documents/T-001/reject", json={"reason": "помилка у тексті"}).json()
    assert d["status"] == "draft"
    assert d["signers"][0]["status"] == "rejected"


# --- редагування ---
def test_edit_draft(client):
    client.post("/documents", json=_doc_payload())
    d = client.put("/documents/T-001", json={"title": "Новий заголовок"}).json()
    assert d["title"] == "Новий заголовок"


def test_edit_after_submit_rejected(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/submit")
    r = client.put("/documents/T-001", json={"title": "X"})
    assert r.status_code == 409


# --- аудит (ст.13) ---
def test_audit_trail(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/submit")
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()})
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 1, "signature_b64": _fake_cms()})
    client.post("/documents/T-001/publish")
    d = client.get("/documents/T-001").json()
    kinds = [e["kind"] for e in d["events"]]
    assert "created" in kinds
    assert "all_signed" in kinds
    assert "published" in kinds


# --- single-signer ---
def test_single_signer_lifecycle(client):
    client.post("/documents", json=_doc_payload(doc_id="S-1", signers=1))
    client.post("/documents/S-1/submit")
    d = client.post("/documents/S-1/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()}).json()
    assert d["status"] == "signed"


# --- ASiC-E ---
def test_asice_assembled_and_downloadable(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/submit")
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()})
    d = client.post("/documents/T-001/sign", json={
        "signer_order_index": 1, "signature_b64": _fake_cms()}).json()
    assert d["status"] == "signed"
    assert d["has_asice"] is True

    r = client.get("/documents/T-001/download/asice")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.etsi.asic-e+zip"
    # ASiC-E — це ZIP: перші байти PK
    assert r.content[:2] == b"PK"


def test_asice_contains_document_and_signatures(client):
    import io
    import zipfile

    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/submit")
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()})
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 1, "signature_b64": _fake_cms()})
    r = client.get("/documents/T-001/download/asice")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "mimetype" in names
    assert "T-001.pdf" in names  # документ усередині
    sigs = [n for n in names if n.startswith("META-INF/signature") and n.endswith(".p7s")]
    assert len(sigs) == 2  # дві КЕП-підписи


def test_draft_pdf_has_no_marks_signed_has_marks(client):
    """Чернетка генерується чистою (без відміток про КЕП), а після підпису
    всіма download віддає версію з відмітками + QR (реальні дані сертифікатів)."""
    import io
    from pypdf import PdfReader

    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    # завантаження ДО підпису — чистий PDF без слова "Підписувач"/КЕП-відмітки
    r0 = client.get("/documents/T-001/download")
    assert r0.status_code == 200
    t0 = "".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r0.content)).pages)
    assert "Підписувач" not in t0

    client.post("/documents/T-001/submit")
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms(),
        "certificate_serial": "AABBCCDD11", "issuer": "КНЕДП ДПС"})
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 1, "signature_b64": _fake_cms(),
        "certificate_serial": "EE22FF33", "issuer": "КНЕДП monobank"})
    # завантаження ПІСЛЯ підпису — відмітка з ПІБ підписанта присутня
    r1 = client.get("/documents/T-001/download")
    assert r1.status_code == 200
    assert 'filename="T-001-signed.pdf"' in r1.headers.get("content-disposition", "")
    t1 = "".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r1.content)).pages)
    assert "Підписувач" in t1


def test_marked_progressive_after_each_sign(client):
    """Marked-візуалізація перебудовується після КОЖНОГО підпису: спершу видно
    лише першого підписанта, після другого — обох у порядку черги."""
    import io
    from pypdf import PdfReader

    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/submit")
    # перший підпис
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()})
    t1 = "".join((p.extract_text() or "") for p in
                 PdfReader(io.BytesIO(client.get("/documents/T-001/download").content)).pages)
    assert t1.count("Підписувач") == 1  # лише перший
    # другий підпис
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 1, "signature_b64": _fake_cms()})
    t2 = "".join((p.extract_text() or "") for p in
                 PdfReader(io.BytesIO(client.get("/documents/T-001/download").content)).pages)
    assert t2.count("Підписувач") == 2  # обидва
    # порядок: перший підписант іде раніше за другого у тексті
    p0 = _doc_payload()["signers"][0]["full_name"]
    p1 = _doc_payload()["signers"][1]["full_name"]
    assert t2.find(p0) < t2.find(p1)


def test_fop_subject_prefixes_name_in_pdf(client):
    """Документ типу ФОП: реквізит найменування формується з ПІБ підприємця
    з префіксом «ФІЗИЧНА ОСОБА — ПІДПРИЄМЕЦЬ»."""
    import io
    from pypdf import PdfReader

    payload = _doc_payload(doc_id="FOP-1")
    payload["org_name"] = "ПЕТРЕНКО Олександр Іванович"
    payload["subject_type"] = "fop"
    client.post("/documents", json=payload)
    client.post("/documents/FOP-1/generate")
    r = client.get("/documents/FOP-1/download")
    t = "".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "ФІЗИЧНА ОСОБА — ПІДПРИЄМЕЦЬ" in t
    assert "ПЕТРЕНКО Олександр Іванович" in t


def test_person_subject_plain_name_in_pdf(client):
    """Документ типу «фізична особа»: найменування — ПІБ без префікса
    (на відміну від ФОП, де додається «ФІЗИЧНА ОСОБА — ПІДПРИЄМЕЦЬ»)."""
    import io
    from pypdf import PdfReader

    payload = _doc_payload(doc_id="PERS-1")
    payload["org_name"] = "ШЕВЧЕНКО Тарас Григорович"
    payload["subject_type"] = "person"
    client.post("/documents", json=payload)
    client.post("/documents/PERS-1/generate")
    r = client.get("/documents/PERS-1/download")
    t = "".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "ШЕВЧЕНКО Тарас Григорович" in t
    assert "ПІДПРИЄМЕЦЬ" not in t  # без префікса ФОП


def test_asice_404_before_signed(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    r = client.get("/documents/T-001/download/asice")
    assert r.status_code == 404


def test_manifest_endpoint_returns_signable_bytes(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/submit")
    r = client.get("/documents/T-001/manifest")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/xml")
    body = r.content
    # це ASiCManifest для першого підписанта (signature001.p7s)
    assert b"ASiCManifest" in body
    assert b"signature001.p7s" in body
    assert b"DigestValue" in body


def test_manifest_before_generate_409(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/submit")
    r = client.get("/documents/T-001/manifest")
    assert r.status_code == 409


def test_manifest_advances_with_queue(client):
    client.post("/documents", json=_doc_payload())
    client.post("/documents/T-001/generate")
    client.post("/documents/T-001/submit")
    m0 = client.get("/documents/T-001/manifest").content
    assert b"signature001.p7s" in m0
    client.post("/documents/T-001/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()})
    # тепер активний другий підписант → манІфест для signature002
    m1 = client.get("/documents/T-001/manifest").content
    assert b"signature002.p7s" in m1


def test_list_documents(client):
    client.post("/documents", json=_doc_payload(doc_id="L-1"))
    client.post("/documents", json=_doc_payload(doc_id="L-2"))
    r = client.get("/documents")
    assert r.status_code == 200
    ids = {d["doc_id"] for d in r.json()["documents"]}
    assert {"L-1", "L-2"} <= ids


def test_get_missing_404(client):
    assert client.get("/documents/NOPE").status_code == 404


def test_delete_document_allows_recreate(client):
    # створити, підписати-зіпсувати неможливо (422), але видалити й перестворити — так
    client.post("/documents", json=_doc_payload(doc_id="DEL-1"))
    assert client.get("/documents/DEL-1").status_code == 200
    r = client.request("DELETE", "/documents/DEL-1")
    assert r.status_code == 200
    assert r.json()["deleted"] == "DEL-1"
    # після видалення — 404, і той самий doc_id можна створити заново
    assert client.get("/documents/DEL-1").status_code == 404
    r2 = client.post("/documents", json=_doc_payload(doc_id="DEL-1"))
    assert r2.status_code == 200


def test_delete_missing_404(client):
    assert client.request("DELETE", "/documents/NOPE").status_code == 404


def test_delete_cascades_signers_and_audit(client):
    # документ із чергою + подіями, далі видалення не лишає сиріт
    client.post("/documents", json=_doc_payload(doc_id="DEL-2"))
    client.post("/documents/DEL-2/generate")
    client.post("/documents/DEL-2/submit")
    client.request("DELETE", "/documents/DEL-2")
    # перестворення з тим самим id успішне → попередні signers/events пішли
    assert client.post("/documents", json=_doc_payload(doc_id="DEL-2")).status_code == 200


# --- авто-реєстрація: індекси, дати, журнал ---
def _auto_payload(doc_id: str, doc_type: str = "Наказ") -> dict:
    """Payload БЕЗ reg_index/date_text — для перевірки авто-присвоєння."""
    p = _doc_payload(doc_id=doc_id, signers=1)
    p["doc_type"] = doc_type
    p.pop("reg_index", None)
    p.pop("date_text", None)
    return p


def test_auto_registration_assigns_index_and_date(client):
    """submit з порожніми полями і auto_register=True присвоює наскрізний
    індекс із літерним суфіксом типу (наказ → «1-од») і дату реєстрації."""
    client.post("/documents", json=_auto_payload("AR-1"))
    d = client.post("/documents/AR-1/submit", json={"auto_register": True}).json()
    assert d["status"] == "pending_signatures"
    assert d["reg_index"] == "1-од"
    assert d["reg_number"] == 1
    assert d["reg_date"] and "р." in d["reg_date"]


def test_auto_registration_sequential_per_type(client):
    """Наскрізна нумерація в межах типу: накази 1-од, 2-од; лист — окрема 1."""
    client.post("/documents", json=_auto_payload("AR-N1", "Наказ"))
    client.post("/documents", json=_auto_payload("AR-N2", "Наказ"))
    client.post("/documents", json=_auto_payload("AR-L1", "Лист"))
    n1 = client.post("/documents/AR-N1/submit", json={}).json()
    n2 = client.post("/documents/AR-N2/submit", json={}).json()
    l1 = client.post("/documents/AR-L1/submit", json={}).json()
    assert n1["reg_index"] == "1-од"
    assert n2["reg_index"] == "2-од"
    assert l1["reg_index"] == "1"  # лист — окрема послідовність без літери


def test_auto_registration_default_when_no_body(client):
    """auto_register не передано у body → default True, індекс присвоюється."""
    client.post("/documents", json=_auto_payload("AR-DEF"))
    d = client.post("/documents/AR-DEF/submit").json()
    assert d["reg_index"] == "1-од"


def test_manual_index_respected(client):
    """Якщо reg_index заданий вручну — авто його не перетирає (фіксує як є)."""
    p = _auto_payload("AR-MAN")
    p["reg_index"] = "АБ-99"
    p["date_text"] = "01 січня 2026 р."
    client.post("/documents", json=p)
    d = client.post("/documents/AR-MAN/submit", json={"auto_register": True}).json()
    assert d["reg_index"] == "АБ-99"
    assert d["reg_date"] == "01 січня 2026 р."


def test_auto_register_disabled_assigns_nothing(client):
    """auto_register=False → реєстрація не виконується, індекс лишається None."""
    client.post("/documents", json=_auto_payload("AR-OFF"))
    d = client.post("/documents/AR-OFF/submit", json={"auto_register": False}).json()
    assert d["status"] == "pending_signatures"
    assert d["reg_index"] is None
    assert d["reg_date"] is None


def test_registration_idempotent_on_status(client):
    """Повторні запити не змінюють присвоєний номер (submit одноразовий, але
    реєстраційні поля стабільні після присвоєння)."""
    client.post("/documents", json=_auto_payload("AR-IDEM"))
    d1 = client.post("/documents/AR-IDEM/submit", json={}).json()
    idx = d1["reg_index"]
    # повторний submit заборонено (вже не draft) → номер не змінюється
    assert client.post("/documents/AR-IDEM/submit", json={}).status_code == 409
    d2 = client.get("/documents/AR-IDEM").json()
    assert d2["reg_index"] == idx


def test_generate_fills_draft_date_when_empty(client):
    """generate до submit (авто-реєстрація): дата проєкту підставляється,
    щоб документ не був порожнім; офіційний індекс ще не присвоєно."""
    import io

    from pypdf import PdfReader

    client.post("/documents", json=_auto_payload("AR-GEN"))
    r = client.post("/documents/AR-GEN/generate")
    assert r.status_code == 200
    # індекс ще не присвоєно (реєстрація лише при submit)
    d = client.get("/documents/AR-GEN").json()
    assert d["reg_index"] is None
    # але PDF згенеровано з датою проєкту — не порожній
    pdf = client.get("/documents/AR-GEN/download")
    assert pdf.status_code == 200
    text = "".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "р." in text  # дата у словесно-цифровому форматі присутня


def test_registry_journal(client):
    """GET /registry повертає зареєстровані документи з індексами, згруповані
    за типом і відсортовані за номером."""
    client.post("/documents", json=_auto_payload("RJ-N1", "Наказ"))
    client.post("/documents", json=_auto_payload("RJ-N2", "Наказ"))
    client.post("/documents", json=_auto_payload("RJ-L1", "Лист"))
    client.post("/documents/RJ-N1/submit", json={})
    client.post("/documents/RJ-N2/submit", json={})
    client.post("/documents/RJ-L1/submit", json={})

    r = client.get("/registry")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 3
    entries = data["entries"]
    # накази йдуть за номером
    nakazy = [e for e in entries if e["doc_type"] == "Наказ"]
    assert [e["reg_index"] for e in nakazy] == ["1-од", "2-од"]
    # лист — окремий запис
    lysty = [e for e in entries if e["doc_type"] == "Лист"]
    assert len(lysty) == 1 and lysty[0]["reg_index"] == "1"


def test_registry_excludes_unregistered(client):
    """Незареєстровані (auto_register=False або чернетки) не потрапляють у журнал."""
    client.post("/documents", json=_auto_payload("RJ-OFF"))
    client.post("/documents/RJ-OFF/submit", json={"auto_register": False})
    client.post("/documents", json=_auto_payload("RJ-DRAFT"))  # лишається draft
    r = client.get("/registry").json()
    ids = {e["doc_id"] for e in r["entries"]}
    assert "RJ-OFF" not in ids
    assert "RJ-DRAFT" not in ids


# --- registry unit (формат індексу та дати) ---
def test_registry_index_format_per_type():
    """Літерні суфікси за типом документа (Типова інструкція ПКМУ № 55/2018)."""
    from portal import registry

    assert registry._TYPE_SUFFIX["Наказ"] == "-од"
    assert registry._TYPE_SUFFIX["Розпорядження"] == "-р"
    assert registry._TYPE_SUFFIX["Лист"] == ""


def test_registry_ua_date_format():
    """Дата у словесно-цифровому форматі ДСТУ: «14 червня 2026 р.»."""
    import datetime as _dt

    from portal import registry

    assert registry.format_ua_date(_dt.date(2026, 6, 14)) == "14 червня 2026 р."
    assert registry.format_ua_date(_dt.date(2026, 1, 1)) == "1 січня 2026 р."
    assert registry.format_ua_date(_dt.date(2026, 12, 31)) == "31 грудня 2026 р."


# --- оцифрування: заливка сканів ---
def _png_bytes() -> bytes:
    """Мінімальне PNG-зображення (1×1 білий піксель) для тесту заливки скану."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (200, 280), "white").save(buf, format="PNG")
    return buf.getvalue()


def _minimal_pdf() -> bytes:
    """Мінімальний валідний PDF (сигнатура %PDF) для тесту заливки скану-PDF."""
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF"
    )


def test_scan_image_becomes_pdf_original(client):
    """Скан-фото конвертується в PDF і стає електронним оригіналом (rendered)."""
    files = {"file": ("scan.png", _png_bytes(), "image/png")}
    data = {"doc_id": "SCAN-1", "title": "Скан наказу",
            "signers": "ПЕТРЕНКО Олександр | Директор"}
    r = client.post("/documents/scan", files=files, data=data)
    assert r.status_code == 200
    d = r.json()
    assert d["is_scanned"] is True
    assert d["fmt"] == "pdf"
    assert d["has_rendered"] is True
    assert d["status"] == "draft"
    assert d["signers"][0]["full_name"] == "ПЕТРЕНКО Олександр"
    # завантажений оригінал — справді PDF
    pdf = client.get("/documents/SCAN-1/download")
    assert pdf.content[:5] == b"%PDF-"


def test_scan_pdf_passthrough(client):
    """Скан у форматі PDF приймається як є (електронний оригінал)."""
    files = {"file": ("scan.pdf", _minimal_pdf(), "application/pdf")}
    data = {"doc_id": "SCAN-PDF", "title": "PDF скан", "signers": "ІВАНОВ І. | Бухгалтер"}
    r = client.post("/documents/scan", files=files, data=data)
    assert r.status_code == 200
    assert r.json()["is_scanned"] is True


def test_scan_generate_blocked(client):
    """Генерація з полів для скану заборонена (409) — не перезаписує оригінал."""
    files = {"file": ("scan.png", _png_bytes(), "image/png")}
    data = {"doc_id": "SCAN-NOGEN", "title": "Скан", "signers": "П. | Дир"}
    client.post("/documents/scan", files=files, data=data)
    r = client.post("/documents/SCAN-NOGEN/generate")
    assert r.status_code == 409
    # оригінал-скан лишився недоторканим
    pdf = client.get("/documents/SCAN-NOGEN/download")
    assert pdf.content[:5] == b"%PDF-"


def test_scan_rejects_unsupported_type(client):
    """Непідтримуваний тип файлу → 415."""
    files = {"file": ("doc.exe", b"MZ\x00\x00binary", "application/octet-stream")}
    data = {"doc_id": "SCAN-BAD", "title": "Погане"}
    r = client.post("/documents/scan", files=files, data=data)
    assert r.status_code == 415


def test_scan_rejects_fake_pdf(client):
    """Файл з .pdf але без сигнатури %PDF → 422."""
    files = {"file": ("fake.pdf", b"not a real pdf", "application/pdf")}
    data = {"doc_id": "SCAN-FAKE", "title": "Фейк"}
    r = client.post("/documents/scan", files=files, data=data)
    assert r.status_code == 422


def test_scan_full_signing_lifecycle(client):
    """Повний цикл оцифрування: скан → реєстрація → підпис КЕП → ASiC-E."""
    files = {"file": ("scan.png", _png_bytes(), "image/png")}
    data = {"doc_id": "SCAN-SIGN", "title": "Скан до підпису",
            "signers": "ПЕТРЕНКО Олександр | Директор"}
    client.post("/documents/scan", files=files, data=data)
    # подати у чергу (з авто-реєстрацією)
    d = client.post("/documents/SCAN-SIGN/submit", json={"auto_register": True}).json()
    assert d["status"] == "pending_signatures"
    assert d["reg_index"]  # отримав реєстраційний індекс
    # підписати скан
    d2 = client.post("/documents/SCAN-SIGN/sign", json={
        "signer_order_index": 0, "signature_b64": _fake_cms()}).json()
    assert d2["status"] == "signed"
    assert d2["has_asice"] is True
    # ASiC-E містить скан-PDF + підпис
    import io
    import zipfile

    r = client.get("/documents/SCAN-SIGN/download/asice")
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert "SCAN-SIGN.pdf" in names
    assert any(n.endswith(".p7s") for n in names)


def test_scan_unit_normalize():
    """Unit: scan_ingest.normalize_to_pdf конвертує зображення й пропускає PDF."""
    from portal import scan_ingest

    # PDF — passthrough
    pdf = _minimal_pdf()
    assert scan_ingest.normalize_to_pdf(pdf, "application/pdf", "x.pdf") == pdf
    # зображення → PDF
    out = scan_ingest.normalize_to_pdf(_png_bytes(), "image/png", "x.png")
    assert out[:5] == b"%PDF-"
    # порожній файл → помилка
    import pytest as _pytest

    with _pytest.raises(scan_ingest.ScanError):
        scan_ingest.normalize_to_pdf(b"", "image/png", "x.png")

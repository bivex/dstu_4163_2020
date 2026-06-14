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


def test_create_duplicate_conflicts(client):
    client.post("/documents", json=_doc_payload())
    r = client.post("/documents", json=_doc_payload())
    assert r.status_code == 409


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
    client.post("/documents", json=_doc_payload())
    r = client.post("/documents/T-001/validate")
    assert r.status_code == 200
    assert r.json()["conforms"] is True


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

import pytest
from portal.domain_bridge import _get_addressee_count, build_content, generate
from portal.routers.delivery import get_document_delivery

def test_get_addressee_count_string_and_list():
    # String with double newlines
    p1 = {"addressees": "Адресат 1\nм. Київ\n\nАдресат 2\nм. Львів\n\nАдресат 3"}
    assert _get_addressee_count(p1) == 3

    # List of strings
    p2 = {"addressees": ["Адресат 1\nм. Київ", "Адресат 2\nм. Львів"]}
    assert _get_addressee_count(p2) == 2

    # Single string fallback
    p3 = {"addressee": "Один адресат\nвул. Миру"}
    assert _get_addressee_count(p3) == 1

    # Empty
    assert _get_addressee_count({}) == 0

def test_build_content_addressees_tuple():
    p = {
        "doc_id": "TEST-MULTI-1",
        "doc_type": "Лист",
        "org_name": "ТОВ «Діловод»",
        "addressees": "Адресат 1\nм. Київ\n\nАдресат 2\nм. Харків",
        "body": ["Текст листа"]
    }
    content = build_content(p, with_marks=False)
    assert len(content.addressees) == 2
    assert "Адресат 1" in content.addressees[0]
    assert "Адресат 2" in content.addressees[1]

def test_generate_pdf_multi_addressees(tmp_path):
    p = {
        "doc_id": "TEST-MULTI-PDF",
        "doc_type": "Лист",
        "org_name": "ТОВ «Діловод»",
        "addressees": [
            "Генеральному прокурору\nвул. Різницька, 13/15\nм. Київ",
            "Міністру внутрішніх справ\nвул. Богомольця, 10\nм. Київ",
            "Голові СБУ\nвул. Володимирська, 33\nм. Київ"
        ],
        "body": ["Повідомляємо про обставини справи..."]
    }
    out_file = str(tmp_path / "test.pdf")
    generate(p, "pdf", out_file)
    with open(out_file, "rb") as f:
        pdf_bytes = f.read()
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF")

def test_delivery_multi_recipients_export():
    from portal.routers.delivery import export_delivery_pdf
    payload = {
        "sender": {"name": "ТОВ «Діловод»", "address": "м. Київ", "phone": "0501234567"},
        "recipients": [
            {"name": "Одержувач 1", "address": "Адреса 1", "phone": "0991111111"},
            {"name": "Одержувач 2", "address": "Адреса 2", "phone": "0992222222"}
        ],
        "export_all_recipients": True,
        "generate_f107": True,
        "generate_label": True,
        "items": [{"name": "Лист", "quantity": 1, "declared_value": 1.0}]
    }
    response = export_delivery_pdf("TEST-DOC", payload)
    assert response.status_code == 200
    assert response.body.startswith(b"%PDF")
    assert len(response.body) > 2000

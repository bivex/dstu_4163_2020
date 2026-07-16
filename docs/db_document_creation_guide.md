# Інструкція: Програмне створення та реєстрація документів через БД

Цей документ описує процес створення, реєстрації та рендерингу документів безпосередньо у базі даних за допомогою Python-скриптів. Цей підхід корисний для автоматичного імпорту, реєстрації сторонньої вхідної кореспонденції або міграції даних.

---

## 1. Загальна архітектура документообігу

Для коректної реєстрації документа в системі задіяно кілька таблиць бази даних SQLite:

*   **`documents`**: Основні метадані документа (ідентифікатор `doc_id`, назва `title`, статус `status`, бінарні дані згенерованих файлів у `rendered` та `rendered_marked`, зв'язок із журналом через `journal_id`).
*   **`signers`**: Список підписантів документа та статус їхніх підписів.
*   **`approvers`**: Список осіб, що погоджують документ, та черговість погодження.
*   **`journals`**: Реєстраційні журнали (наприклад, Накази, Вхідне листування, Вихідне листування).

---

## 2. Процес реєстрації документа

Процес реєстрації складається з двох етапів:

1.  **Створення запису та присвоєння індексу**: Визначення журналу та автоматичне отримання наступного наскрізного номера за допомогою `registry.assign_registration`.
2.  **Візуалізація (Рендеринг)**: Генерація PDF-файлу з побудовою правильного штампу підпису та входящого штампу за допомогою `domain_bridge`.

---

## 3. Шаблон скрипта для створення документів

Нижче наведено загальний універсальний шаблон Python-скрипта для створення документів. Його слід адаптувати під конкретний тип документа (Чернетка або Підписаний/Вхідний).

```python
import datetime as dt
import json
import os
import tempfile
from portal.db import SessionLocal, Document, Journal, DocStatus, Signer, SignerStatus, Approver, ApproverStatus
from portal import registry, domain_bridge

def create_document():
    # 1. Ініціалізація сесії БД
    session = SessionLocal()
    try:
        # Унікальний ідентифікатор документа
        doc_id = "DOC-UNIQUE-ID"
        
        # Перевірка на дублікати
        existing = session.query(Document).filter_by(doc_id=doc_id).first()
        if existing:
            print(f"Документ {doc_id} вже існує.")
            return

        # 2. Вибір журналу реєстрації (наприклад, ID: 2 - Вхідні, ID: 3 - Вихідні)
        journal_id = 2 
        journal = session.query(Journal).filter_by(id=journal_id).first()
        
        # 3. Формування Payload (вміст документа)
        payload = {
            "doc_id": doc_id,
            "title": "Назва документа для реєстру",
            "org_name": "НАЗВА ОРГАНІЗАЦІЇ-ВІДПРАВНИКА",
            "subject_type": "legal", # legal | person | fop
            "doc_type": "Лист", # Тип документа за ДСТУ
            "fmt": "pdf",
            "date_text": "", # заповнюється автоматично при реєстрації
            "place": "Місто",
            "body": [
                "Перший абзац тексту документа.",
                "Другий абзац тексту документа."
            ],
            "addressees": [
                "Адресат (Отримувач)\nАдреса отримувача"
            ],
            "sender_contacts": "Контакти відправника (адреса, тел, email)",
            "signature_position": "Посада підписувача",
            "signature_name": "Ініціали та Прізвище",
            "journal_id": journal_id,
            "use_incoming_stamp": True,  # Додати синій вхідний штамп (для вхідних)
            "use_stamp": False,          # Додати гербову печатку відправника
            "stamp_type": "",
            "restriction_stamp": "",
            
            # Реквізити накладених електронних підписів (якщо документ вже підписано)
            "e_signatures": [
                {
                    "signer": "ПІБ Підписувача",
                    "certificate_serial": "СЕРІЙНИЙ_НОМЕР_СЕРТИФІКАТА",
                    "issuer": "Назва АЦСК / Надавача послуг",
                    "valid_from": "ДД.ММ.РРРР ГГ:ХХ:СС",
                    "valid_to": "ДД.ММ.РРРР ГГ:ХХ:СС",
                    "timestamp": "ДД.ММ.РРРР ГГ:ХХ:СС",
                    "is_qualified": True,
                    "status": "Active",
                    "signer_position": "Посада з сертифіката",
                    "kind": "esign", # esign (підпис) | eseal (печатка)
                    "organization": "Організація підписувача",
                    "identifier": "ЄДРПОУ або РНОКПП"
                }
            ]
        }

        # 4. Створення об'єкта документа
        # Для вхідних/підписаних документів встановлюється статус DocStatus.SIGNED, 
        # для нових вихідних проектів — DocStatus.DRAFT.
        doc = Document(
            doc_id=doc_id,
            title=payload["title"],
            fmt="pdf",
            status=DocStatus.SIGNED, 
            content_json=domain_bridge.content_to_json(payload),
            journal_id=journal_id,
            is_scanned=True # Вхідний скан або готовий зовнішній документ
        )

        # 5. Автоматичне присвоєння реєстраційного індексу та дати з журналу
        registry.assign_registration(session, doc, payload["doc_type"])
        
        # Оновлення індексу та дати всередині payload
        payload["reg_index"] = doc.reg_index
        payload["date_text"] = doc.reg_date
        doc.content_json = domain_bridge.content_to_json(payload)

        # 6. Запис підписантів до таблиці БД
        for s_payload in payload.get("e_signatures", []):
            signer = Signer(
                order_index=0,
                full_name=s_payload["signer"],
                position=s_payload["signer_position"],
                status=SignerStatus.SIGNED,
                certificate_serial=s_payload["certificate_serial"],
                issuer=s_payload["issuer"],
                valid_from=s_payload["valid_from"],
                valid_to=s_payload["valid_to"],
                signed_at=dt.datetime.strptime(s_payload["timestamp"], "%d.%m.%Y %H:%M:%S"),
                signer_type="person",
                organization=s_payload["organization"],
                identifier=s_payload["identifier"],
                signature=b"DUMMY_SIGNATURE_BYTES" # Дані підпису (у форматі PKCS#7/CADES)
            )
            doc.signers.append(signer)

        # 7. Рендеринг PDF з штампами та підписами
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            dest = tmp.name
        try:
            # - Генерація документа з накладанням відміток про підпис (KEP)
            path = domain_bridge.render_marked(payload, "pdf", dest)
            with open(path, "rb") as fh:
                doc.rendered = fh.read()
                doc.rendered_marked = doc.rendered
        finally:
            if os.path.exists(dest):
                os.remove(dest)

        # 8. Збереження змін у БД
        session.add(doc)
        session.commit()
        print(f"Документ {doc_id} успішно зареєстровано з індексом {doc.reg_index}!")
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()

if __name__ == '__main__':
    create_document()
```

---

## 4. Виконання скрипта в Docker-контейнері

Оскільки база даних SQLite підключена як Docker Volume, скрипти необхідно виконувати всередині оточення контейнера `api`.

1.  Збережіть скрипт у папці `portal/` на хост-машині (наприклад, як `portal/import_doc.py`).
2.  Виконайте команду для запуску скрипта всередині контейнера:

```bash
docker compose exec api env PYTHONPATH=/app:/app/src python /app/portal/import_doc.py
```

> [!NOTE]
> Змінна `PYTHONPATH` обов'язково повинна містити шляхи `/app` та `/app/src`, щоб інтерпретатор Python всередині контейнера міг імпортувати модулі `portal` та `dilovod4`.

3.  Після успішного завершення видаліть скрипт з хост-машини для чистоти репозиторію.

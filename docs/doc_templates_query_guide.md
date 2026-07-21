# Інструкція: Робота з таблицею `doc_templates` (Вибірка шаблонів та стилів)

Цей посібник описує схему таблиці `doc_templates` та надає приклади SQL і Python запитів для правильного отримання шаблонів документів, стилів та підказок.

---

## 1. Схема таблиці `doc_templates`

Колонки, які містяться в таблиці:

| Колонка | Тип даних | Опис |
| :--- | :--- | :--- |
| **`id`** | `INTEGER` | Унікальний ідентифікатор (Primary Key). |
| **`category`** | `VARCHAR(64)` | Категорія шаблону: `rozporyadchi`, `dovidkovi`, `lystuvannya`, `zvernennya`, `dohovirni`, `normatyvni`, `stylevi` (підказки). |
| **`doc_type`** | `VARCHAR(128)` | Вид документа (наприклад, `Наказ`, `Лист`, `Заява`, `Підказка`). |
| **`subject_type`** | `VARCHAR(16)` | Тип суб'єкта: `legal` (юрособа), `fop` (ФОП), `person` (фізична особа). |
| **`title`** | `VARCHAR(512)` | Назва шаблону (відображається в списку/картці). |
| **`description`** | `TEXT` | Опис призначення цього шаблону. |
| **`icon`** | `VARCHAR(64)` | Іконка для інтерфейсу (наприклад, `i-lucide-scale`). |
| **`title_tpl`** | `TEXT` | Типовий заголовок документа при автозаповненні. |
| **`body`** | `TEXT` | Текст документа з плейсхолдерами. |
| **`addressees`** | `TEXT` | Дані адресата (отримувача) за замовчуванням (може бути NULL). |
| **`sender_contacts`**| `TEXT` | Контакти відправника за замовчуванням (може бути NULL). |
| **`is_builtin`** | `BOOLEAN` | `1` (True) для системних (вбудованих) шаблонів, `0` (False) для користувацьких. |
| **`sort_order`** | `INTEGER` | Порядок сортування в інтерфейсі (за зростанням). |

---

## 2. Основні сценарії SQL-запитів

### 2.1. Отримання всіх шаблонів у правильному порядку
Для відображення повного списку шаблони слід сортувати за `sort_order` та за алфавітом (`title`):
```sql
SELECT id, category, doc_type, title, is_builtin 
FROM doc_templates 
ORDER BY sort_order ASC, title ASC;
```

### 2.2. Фільтрація за категорією
Наприклад, щоб обрати тільки **Стилі та підказки** (`stylevi`):
```sql
SELECT id, title, description, body 
FROM doc_templates 
WHERE category = 'stylevi'
ORDER BY sort_order ASC;
```
*Доступні категорії:* `rozporyadchi`, `dovidkovi`, `lystuvannya`, `zvernennya`, `dohovirni`, `normatyvni`, `stylevi`.

### 2.3. Пошук шаблонів за ключовими словами
Пошук за назвою, описом або текстом шаблону (наприклад, шукаємо все, що стосується "протоколу" чи "листа"):
```sql
SELECT id, title, category, doc_type 
FROM doc_templates 
WHERE title LIKE '%протокол%' 
   OR description LIKE '%протокол%' 
   OR body LIKE '%протокол%'
ORDER BY sort_order ASC;
```

### 2.4. Фільтрація за суб'єктом звернення
Наприклад, вибірка документів, які подаються від імені **фізичної особи** (`person`):
```sql
SELECT id, title, doc_type 
FROM doc_templates 
WHERE subject_type = 'person'
ORDER BY sort_order ASC;
```

---

## 3. Приклади коду для вибірки

### 3.1. Запуск через Docker CLI (Bash)
Щоб отримати список підказок та стилів прямо з терміналу хост-машини:
```bash
docker compose exec api python -c "
import sqlite3
conn = sqlite3.connect('/data/portal.db')
cursor = conn.cursor()
cursor.execute(\"SELECT id, title, description FROM doc_templates WHERE category='stylevi' ORDER BY sort_order;\")
for row in cursor.fetchall():
    print(f'ID: {row[0]} | {row[1]} ({row[2]})')
"
```

### 3.2. Через Python (SQLAlchemy) в бекенд-сервісі
Використовуйте ORM-модель `DocTemplate` для отримання об'єктів:
```python
from portal.db import SessionLocal, DocTemplate

def get_templates_by_category(category_name: str = "stylevi"):
    with SessionLocal() as session:
        # Запит з сортуванням та фільтрацією
        templates = (
            session.query(DocTemplate)
            .filter(DocTemplate.category == category_name)
            .order_by(DocTemplate.sort_order.asc(), DocTemplate.title.asc())
            .all()
        )
        return templates
```

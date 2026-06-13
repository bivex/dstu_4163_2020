# Dilovod4

Рушій перевірки оформлення організаційно-розпорядчих документів на відповідність
**ДСТУ 4163:2020**. Python-реалізація формальної Catala-специфікації
(`dstu_4163_2020.catala_en`) у чистій (гексагональній) архітектурі.

## Що це робить

Приймає опис документа (реквізити, геометрія, типографіка, метадані), застосовує
13 правил відповідності (по одному на параграф ДСТУ) і повертає структурований
звіт: загальний підсумок + перелік конкретних порушень із посиланням на параграф.

## Архітектура

Чотири шари, залежності спрямовані всередину (детальніше — `docs/adr/0001-*`):

```
presentation (CLI)  ->  application (use-cases, DTO)  ->  domain (модель, правила, порти)
                              ^
infrastructure (адаптери: config, repo, rule set, mapper) -- реалізують доменні порти
```

- `domain/` — чистий Python: value objects з інваріантами, агрегат `Document`,
  13 правил (`ConformanceRule`), порти. Без БД/мережі/UI/фреймворків.
- `application/` — use-case `ValidateDocument`, DTO. Залежить лише від портів (DIP).
- `infrastructure/` — адаптери: `AppConfig` (env), `DefaultRuleSetProvider`,
  `InMemoryDocumentRepository`, JSON-мапер (анти-корупційний шар).
- `presentation/` — CLI + рендерери (text/JSON). Композиційний корінь.

Кожне правило 1:1 відображає Catala-scope. Карта — у `docs/requirements.md`.

## Запуск

```bash
# перевірити документ (text-звіт)
PYTHONPATH=src python3 -m dilovod4.presentation.cli samples/conformant.json

# JSON-вивід зі stdin
cat samples/non_conformant.json | PYTHONPATH=src python3 -m dilovod4.presentation.cli --format json -

# або після інсталяції пакета
pip install -e .
dilovod4 samples/conformant.json
```

Код повернення: `0` — документ відповідає, `1` — є порушення норми, `2` — помилка
вхідних даних.

## Генерація .docx

Двигун уміє не лише перевіряти, а й **створювати** документи, що фізично
реалізують оформлення ДСТУ (поля, Times New Roman, кеглі, інтервал, нумерація
сторінок). Це окремий вихідний адаптер (порт `DocumentWriter`).

```bash
pip install -e ".[docx]"          # потрібен python-docx
PYTHONPATH=src python3 scripts/generate_samples.py samples docx
```

Скрипт збирає три реалістичні документи (наказ, лист, протокол), генерує .docx і
перевіряє кожен на відповідність нормі. Готові зразки — у `samples/docx/`.

Програмно:

```python
from dilovod4.application.generate_document import GenerateDocument
from dilovod4.infrastructure.docx_writer import DocxDocumentWriter
from dilovod4.infrastructure.rule_set_provider import DefaultRuleSetProvider

use_case = GenerateDocument(writer=DocxDocumentWriter(), rule_set=DefaultRuleSetProvider())
result = use_case.execute(document, content, "out.docx")  # перевіряє + пише
```

`Document` несе ПАРАМЕТРИ оформлення, `DocumentContent` — фактичний ТЕКСТ
реквізитів. Розділення дозволяє перевіряти оформлення окремо від наповнення.

## Генерація .pdf

PDF-адаптер реалізує **той самий** порт `DocumentWriter` (LSP) — взаємозамінний
з docx без зміни use-case. Будується на reportlab; кирилицю забезпечує системний
TTF Times New Roman.

```bash
pip install -e ".[pdf]"           # потрібен reportlab
PYTHONPATH=src python3 scripts/generate_samples.py samples pdf
# обидва формати одразу (типово):
PYTHONPATH=src python3 scripts/generate_samples.py samples
```

```python
from dilovod4.infrastructure.pdf_writer import PdfDocumentWriter
use_case = GenerateDocument(writer=PdfDocumentWriter(), rule_set=DefaultRuleSetProvider())
result = use_case.execute(document, content, "out.pdf")
```

Шрифт шукається автоматично (macOS/Linux). Перевизначити шлях — через оточення:

| Env | Призначення |
|---|---|
| `DILOVOD4_FONT_REGULAR` | шлях до TTF звичайного накреслення |
| `DILOVOD4_FONT_BOLD` | шлях до TTF напівжирного (необовʼязково) |

Якщо Times New Roman відсутній — використовуйте метрично сумісну Liberation Serif
або вкажіть власний TTF через env. Готові зразки — у `samples/pdf/`.

### Відмітка про електронний підпис (КЕП)

Для електронного документа (`Document.is_electronic = True`) із заданою
`DocumentContent.e_signature` PDF-адаптер замість рукописного реквізиту 22 малює
**відмітку про електронний підпис, побудовану за даними сертифіката** — рамку з
підписувачем, серійним номером, видавцем, строком дії та позначкою часу.

Це стик двох норм: §4.4 реквізит 22 ДСТУ 4163:2020 (для е-документів підпис =
електронний підпис/печатка) ↔ Закон 2155-VIII Art.18 (КЕП) і Art.24 (чинність
сертифіката). Якщо сертифікат нечинний за Art.24 (скасований/заблокований, строк
вийшов або сертифікат видавця нечинний) — відмітка позначається як **НЕДІЙСНИЙ**.

```python
from dilovod4.domain.model import ElectronicSignatureMark, CertificateStatus

content = DocumentContent(
    ...,
    e_signature=ElectronicSignatureMark(
        signer="ПЕТРЕНКО Олександр Іванович",
        certificate_serial="58E2D9C1F0A4B7E3",
        issuer="КН ЕДП «Дія»",
        valid_from="01.01.2026", valid_to="01.01.2028",
        timestamp="13.06.2026 16:42:05 EET",
        status=CertificateStatus.ACTIVE,
    ),
)
```

Готовий зразок — `samples/pdf/enakaz.pdf` (електронний наказ із КЕП-відміткою).

### QR-код (§5.10 / §5.31)

Для електронного документа з `e_signature` PDF-адаптер додає **QR-код 21×21 мм**
у верхньому правому куті. QR кодує дані про КЕП/печатку + кваліфіковану позначку
часу (крос-лінк заголовка dstu-файлу: §5.10 ↔ Закон 2155-VIII). Навантаження
будує домен (`build_signature_qr_payload`), растеризацію — segno.

Формат (версія 2) — компактний позиційний ASCII-рядок:

```
DSTU4163;2;QES;58E2D9C1F0A4B7E3;01.01.2026;01.01.2028;13.06.2026 16:42:05 EET;V
```

поля: маркер схеми, версія, тип (QES/AES), серійник, чинний від/до, позначка
часу, статус (`V`/`X` за Art.24).

Щільність — критична: норма жорстко вимагає 21 мм, тож навантаження тримаємо
ASCII і коротким. Підписувач та видавець (кирилиця) у QR НЕ кодуються — вони вже
є у видимій текстовій відмітці; інакше UTF-8 роздув би QR до версії 9 з модулем
<0.4 мм, який телефон не зчитує. Поточний модуль ~0.57 мм + тиха зона навколо
символу — впевнено сканується.

## Реальне підписання через UAPKI

Для справжнього (а не декларативного) КЕП є інфраструктурний адаптер
`infrastructure/uapki.py` — Python-обгортка (ctypes) над нативною бібліотекою
[UAPKI](external/UAPKI) (підсабмодуль). Підписує файли ключем за українськими
стандартами (ДСТУ 4145 тощо) і піднімає результат у доменну
`ElectronicSignatureMark` (стик §4.4(22) ДСТУ ↔ Art.18/24 Закону 2155-VIII).

Уся взаємодія — через єдину C-функцію `process(jsonRequest)` + `json_free`
(так само, як офіційні .NET/Java/Node.js інтеграції UAPKI). Lifecycle:
INIT → OPEN → SELECT_KEY → SIGN → CLOSE.

Збірка нативної бібліотеки (одноразово):

```bash
cd external/UAPKI/library && bash build-uapki.sh macos-arm64
# у build/out створіть симлінки major-версій (libuapki.dylib, libuapkif.2.dylib …)
```

Шлях до бібліотеки — автопошук у `external/UAPKI/library/build/out` або через
`DILOVOD4_UAPKI_LIB`. Приклад:

```python
from dilovod4.infrastructure.uapki import sign_file_pkcs12

res = sign_file_pkcs12(
    file_path="out.pdf",
    pkcs12_path="key.p12", password="…",
    cert_cache_dir="certs", crl_cache_dir="crls",
    signature_format="CMS",          # RAW / CMS / CAdES-BES/T/C/XL/A
)
mark = res.to_signature_mark(signer="…", issuer="…",
                             valid_from="…", valid_to="…")
```

UAPKI підключається лише за потреби; без зібраної бібліотеки тести
самопропускаються (`UapkiLibraryNotFound`). Збірочні артефакти лишаються всередині
підсабмодуля і не комітяться у головний репозиторій.

## Конфігурація (через оточення)

| Env | Призначення | Типово |
|---|---|---|
| `DILOVOD4_OUTPUT_FORMAT` | `text` \| `json` | `text` |
| `DILOVOD4_LOG_LEVEL` | рівень логів | `INFO` |
| `DILOVOD4_DISABLED_RULES` | CSV `rule_id` для профілю | (порожньо) |
| `DILOVOD4_FONT_REGULAR` / `_BOLD` | TTF для PDF | автопошук |
| `DILOVOD4_UAPKI_LIB` | шлях до libuapki | автопошук |

## Тести

```bash
python3 -m pytest -q
```

Доменні unit-тести (правила + інваріанти, межові значення) та інтеграційні тести
адаптерів і use-case. Зразки — у `samples/`.

## Межі

Кодуються лише обчислювані положення (як і в Catala). Поза межами: координатні
схеми (Додаток А), зразки бланків (Додаток Б), приклади документів, бібліографія.

# Dilovod4

Повноцінна система електронного документообігу за **ДСТУ 4163:2020**: рушій
перевірки оформлення, генератор PDF/DOCX, КЕП-підписання (UAPKI / EUSign) і
вебпортал із фронтендом. Починалось як Python-реалізація формальної
Catala-специфікації (`dstu_4163_2020.catala_en`) у чистій (гексагональній)
архітектурі.

## Склад системи

| Компонент | Де | Стек | Призначення |
|---|---|---|---|
| **Доменне ядро** | `src/dilovod4/` | Python (hexagonal) | правила відповідності, генерація PDF/DOCX, адаптери UAPKI/EUSign/CMP |
| **Портал (API)** | `portal/` | FastAPI + SQLAlchemy 2.0 | REST-бэкенд: документи, підписи, погодження, користувачі, папки, доставка |
| **Вебфронт** | `external/dms-dir/` (підмодуль) | Nuxt 4 + Nuxt UI 4 | дашборд документообігу, вхід/реєстрація, підпис КЕП у браузері |

```
┌──────────────┐   REST/JSON   ┌──────────────┐   import    ┌─────────────────┐
│  dms-dir     │ ────────────► │  portal      │ ─────────► │  dilovod4 ядро  │
│  (Nuxt:3000) │ ◄──────────── │  (FastAPI    │ ◄───────── │  (domain + UAPKI│
│  EUSign WASM │   Bearer JWT  │   :8000)     │            │   EUSign/CMP)   │
└──────────────┘               └──────────────┘            └─────────────────┘
        │                                                            │
        └─ підпис КЕП на клієнті (приватний ключ не покидає браузер) ─┘
```

- **Маршрути порталу:** `auth`, `documents`, `signing`, `approvals`,
  `counterparties`, `folders`, `journals`, `delivery`, `processes`,
  `resolutions`, `tasks`, `users`, `registry` — у `portal/routers/`.
- **БД:** SQLite на тому (типово) або PostgreSQL (прод). Конфіг через env.

### Ролі та блокування документів

Система має 4 ролі (`portal/db.py`, `UserRole`):

| Роль | Права |
|---|---|
| `admin` | усе, зокрема `DELETE /documents/all` та зміна ролей користувачам |
| `director` | створює/подає/підписує/публікує документи вищого рівня |
| `accountant` | фінансові документи, погодження, підпис |
| `clerk` | лише чернетки + перегляд (мінімум прав) |

**Блокування:** документ лочиться повністю при виході зі статусу `draft`
(`pending_approval` / `pending_signatures` / `signed` / `published`). Усі, крім
`admin`, отримують **409** на редагуванні/видаленні/генерації (`PUT`/`DELETE`/
`POST .../generate` через `_assert_editable`). Щоб змінити підписаний документ —
відхиліть підпис/погодження (`reject` повертає у `draft`). `admin` має службовий
обхід, але криптоцілісність ASiC-E при перепідписанні не гарантується —
використовуйте `reject`.

**Підпис:** підписати документ може лише **активний підписант** (збіг ПІБ/КЕП) або
`admin` (службова заміна) — `signing.py` `_is_active_signer`.

**Початковий admin:** `init_db()` сіє `admin@dilovod.local / admin` (env
`PORTAL_ADMIN_EMAIL`/`PORTAL_ADMIN_PASSWORD`). Для наявної бази, де міграція
проставила всім `role='clerk'`, задайте `PORTAL_BOOTSTRAP_ADMIN_EMAIL=your@org.local`
— цей користувач стане admin при старті. Далі ролі призначаються через
`PUT /users/{id}` (поле `role`) — зміну ролі дозволено лише `admin`.

Роль їде в JWT (`_make_token`) і повертається у `/auth/login`, `/auth/me`,
`/auth/login-kep`, `/auth/link-kep`. Фронт (`dms-dir`) використовує
`app/composables/useRoles.ts` для блокування UI (`StepDocument` — fieldset
`:disabled`, `KeypadPanel` — перевірка активного підписанта, `UserModal` — селект
ролі лише для admin).

### Швидкий старт усієї системи

```bash
./manage.sh up           # Docker: api:8000 + web:3000
./manage.sh status       # стан контейнерів і портів
# або окремо в dev-режимі:
./manage.sh backend-dev  # uvicorn --reload :8000
./manage.sh frontend-dev # nuxt dev :3000
./manage.sh help         # усі команди
```

Докладніше про портал — у `portal/README.md`, про фронт — у
`external/dms-dir/README.md`. Подальші розділи стосуються **доменного ядра**
(`src/dilovod4/`) як бібліотеки/CLI.

## Що робить ядро

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

### Верифікація підпису

`verify_signature(container, ...)` перевіряє підпис через UAPKI VERIFY — і сам
криптопідпис, і цілісність даних окремо:

```python
from dilovod4.infrastructure.uapki import verify_signature

res = verify_signature(
    container=open("out.pdf.p7s", "rb").read(),
    cert_cache_dir="certs", crl_cache_dir="crls",
    content=open("out.pdf", "rb").read(),   # для detached-підпису
)
res.is_valid                 # True лише при TOTAL-VALID
res.status                   # TOTAL-VALID / TOTAL-FAILED / INDETERMINATE
res.status_signature         # VALID / INVALID — криптопідпис
res.status_message_digest    # VALID / INVALID — цілісність даних
```

Підміна вмісту дає `TOTAL-FAILED` із `statusMessageDigest=INVALID` навіть коли
сам підпис валідний — тобто рушій розрізняє «підпис підроблено» та «дані
змінено після підписання».

### Онлайн-статус сертифіката (OCSP, повна Art.24)

`check_cert_status_online(cert_der, ...)` запитує OCSP-відповідач надавача й
повертає актуальний статус відкликання — це повна перевірка за Art.24 (не лише
строк дії, а й скасування/блокування в реальному часі):

```python
from dilovod4.infrastructure.uapki import check_cert_status_online

st = check_cert_status_online(
    cert_der=open("signer.cer", "rb").read(),
    cert_cache_dir="certs",        # має містити сертифікат надавача (CA)
    crl_cache_dir="crls",
    ocsp_url="http://ca.informjust.ua/services/ocsp/",
)
st.cert_status        # GOOD / REVOKED / UNKNOWN
st.is_good            # True лише коли SUCCESSFUL + GOOD
st.is_revoked         # True якщо відкликано
st.revocation_time    # час відкликання
st.revocation_reason  # напр. CESSATION_OF_OPERATION
```

Потребує мережі та сертифіката надавача в `cert_cache_dir`; вмикає онлайн-режим
(`offline=false`). Перевірено на реальному відповідачі Дія — тестовий сертифікат
повертає `REVOKED` (CESSATION_OF_OPERATION, 2024-04-05).

Обмеження: нативна libuapki — process-global singleton (один INIT на процес).
Онлайн-перевірку (`offline=false`) виконуйте в окремому процесі або першою, до
будь-якого offline-INIT у тому ж процесі.

### Дотягування сертифіката з КНЕДП (CMP)

Контейнери з лише приватними ключами (без вбудованого сертифіката) потребують
дотягування сертифіката підписувача з КНЕДП за public-key-id. UAPKI вбудованого
CMP-клієнта не має, тож `infrastructure/cmp.py` реалізує проприетарний
IIT-«transport» формат (сумісний із реалізацією jkurwa):

```python
from dilovod4.infrastructure.cmp import fetch_certificate

# id = subjectKeyIdentifier ключа (UAPKI SELECT_KEY 'id'), hex -> bytes
r = fetch_certificate(
    key_id_primary=bytes.fromhex("5BC6C06E…"),
    cmp_url="http://ca.informjust.ua/services/cmp/",   # з реєстру CAs.json
)
r.found          # True якщо сертифікат знайдено на CA
r.result_code    # 1 = успіх; інакше сертифікат не знайдено
r.signer_cert    # DER сертифіката підписувача (за успіху)
r.certificates   # повний дотягнутий ланцюг (DER)
```

Адреси CMP/OCSP кожного КНЕДП — у реєстрі CAs.json (напр. iit.com.ua). Формат
запиту: 120-байтовий payload з id на зміщеннях 0x0c/0x2c у ContentInfo type=data.
ВАЖЛИВО: сервер індексує за **subjectKeyIdentifier** ключа (UAPKI `id`), а НЕ за
keyId2. Перевірено на ca.informjust.ua: дотягує повний ланцюг тестового КЕП Дія.
Далі сертифікат додається у сховище через `client.add_cert(der)` і доступний для
підпису CAdES-BES. ОБМЕЖЕННЯ: якщо сертифікат до ключів не випущено/знято, сервер
повертає ненульовий код — це не помилка клієнта.

### Єдиний потік: підпис із дотягуванням сертифіката

`sign_file_with_remote_cert()` робить весь ланцюг одним викликом для контейнерів
без вбудованого сертифіката (лише ключі): OPEN → CMP fetch за SKI → ADD_CERT →
CAdES-BES SIGN.

```python
from dilovod4.infrastructure.uapki import sign_file_with_remote_cert, verify_signature

res = sign_file_with_remote_cert(
    file_path="document.pdf",
    pkcs12_path="key.pfx", password="…",
    cmp_url="http://ca.monobank.ua/services/cmp/",   # КНЕДП із CAs.json
    cert_cache_dir="certs", crl_cache_dir="crls",
)
open("document.pdf.p7s", "wb").write(res.container)
res.cert.subject_cn        # підписувач із дотягнутого сертифіката

v = verify_signature(res.container, cert_cache_dir="certs",
                     crl_cache_dir="crls", content=open("document.pdf","rb").read())
v.is_valid                 # True -> TOTAL-VALID
```

Перевірено на реальному КЕП Monobank: контейнер лише з ключами → сертифікат
дотягнуто з ca.monobank.ua → CAdES-BES → TOTAL-VALID. Для чинного КЕП можна
вимкнути `ignore_cert_status`. УВАГА безпеки: `.p7s`/`.pfx`/`.p12` (реальні
підписи та ключі — персональні дані) у `.gitignore`, у репозиторій не потрапляють.

### Кваліфікована позначка часу (CAdES-T, Art.26.4)

CAdES-BES несе лише недовірений час хоста — czo.gov.ua позначає його як «не
підтверджено кваліфікованою позначкою часу». Для постійного зберігання Закон
2155-VIII (ч.4 ст.26) вимагає **кваліфіковану позначку часу**. Це формат
CAdES-T: передайте `signature_format='CAdES-T'` і `tsp_url` КНЕДП:

```python
res = sign_file_with_remote_cert(
    file_path="document.pdf",
    pkcs12_path="key.pfx", password="…",
    cmp_url="http://ca.monobank.ua/services/cmp/",
    cert_cache_dir="certs", crl_cache_dir="crls",
    signature_format="CAdES-T",
    tsp_url="http://ca.monobank.ua/services/tsp/dstu/",   # TSP із CAs.json
)
```

Перевірено на реальному КЕП Monobank: підпис містить timeStampToken від TSP
Надавача, VERIFY повертає `signatureFormat=CAdES-T` і `bestSignatureTime` від
довіреної позначки (а не самозаявлений час хоста). TSP/OCSP/CMP-адреси — у
реєстрі CAs.json.

### Автоматичний підпис за реєстром КНЕДП

`sign_file_auto()` сам визначає CMP/TSP-адреси з реєстру CAs.json за назвою
надавача — URL вручну не потрібні:

```python
from dilovod4.infrastructure.uapki import sign_file_auto

res = sign_file_auto(
    file_path="document.pdf",
    pkcs12_path="key.pfx", password="…",
    provider_cn="monobank",        # issuer CN КНЕДП (частковий збіг ок)
    cert_cache_dir="certs", crl_cache_dir="crls",
    with_timestamp=True,           # CAdES-T із кваліфікованою позначкою часу
)
```

Реєстр (снапшот `infrastructure/data/CAs.json`, ~30 КНЕДП) резолвить cmp/tsp/ocsp
за issuer CN. Оновити — завантажити свіжий із iit.com.ua або передати
`registry_source=<шлях|URL>`. Перевірено: `sign_file_auto(..., 'monobank')` →
CAdES-T 4452 B із timeStampToken, адреси визначено автоматично.

### Підпис кількома КЕП (кілька SignerInfo)

UAPKI за один SIGN створює один SignerInfo. Щоб підписати документ кількома КЕП
«для факту», кожен підписує окремо, а підписи зводяться в один CMS через
MODIFY_CMS (один SignedData з кількома SignerInfo):

```python
from dilovod4.infrastructure.uapki import combine_signatures

# cms1, cms2 — detached-підписи ОДНИХ І ТИХ САМИХ даних різними КЕП
merged = combine_signatures(
    [cms1, cms2],
    cert_cache_dir="certs", crl_cache_dir="crls",
)
# merged — один контейнер із двома підписами; VERIFY поверне 2 signatureInfos
```

Перевірено на реальних ключах: документ підписано КЕП Monobank і тестовим КЕП
Дія → об'єднано в один CMS 3382 B → VERIFY: 2 SignerInfo, обидва TOTAL-VALID.
Усі підписи мають покривати однакові дані. Підписанти можуть бути рознесені в
часі — кожен підписує свій CMS, потім їх зводять.

### Підпис апаратним токеном (E.Key Almaz-1C, headless)

Захищені носії (ЗНКІ) не віддають приватний ключ — підпис робить сам токен.
UAPKI працює лише з файловими контейнерами, тож для токена є окремий адаптер
`infrastructure/token_sign.py` — JSON-RPC до рідного native-messaging host ІІТ
`euscpnmh` (його ставить «ІІТ Користувач ЦСК»). Протокол і структури звірено
з референс-клієнтами ІІТ EUSignES6 / SA-SignInfo.

```python
from dilovod4.infrastructure.token_sign import sign_file_with_token

res = sign_file_with_token(
    file_path="document.pdf",
    pin="…",                                   # лише у пам'яті, не логувати
    cmp_url="ca.tax.gov.ua/services/cmp/",     # КНЕДП-емітент (повний шлях!)
    with_timestamp=True,                        # CAdES-T (Art.26.4)
    tsp_url="ca.tax.gov.ua/services/tsp/",
    ocsp_url="ca.tax.gov.ua/services/ocsp/",
)
res.container        # CMS (CAdES-BES/T); res.has_timestamp; res.sign_type
```

Потік: euscp сам дотягує сертифікат підписувача з КНЕДП за ключем носія
(`GetKeyInfo` → `GetCertificatesByKeyInfo`), у сховище кладеться ланцюг БЕЗ
Key-Agreement-серта (інакше Sign code 50), підпис — через контекст
`CtxCreate`→`CtxReadPrivateKey`→`CtxSign`. CAdES-T валідує позначку часу онлайн,
тож потрібен досяжний OCSP. Перевірено: реальний токен E.Key Almaz-1C, КНЕДП ДПС,
czo.gov.ua приймає як **Кваліфікований** підпис (CAdES-T з timeStampToken).
CLI: `TOKEN_PIN='…' TOKEN_CADES_T=1 python3 scripts/token_sign_nmh.py <файл>`.

УВАГА: апаратний токен має ліміт спроб ПІН (~3) → блокування. Невірний ПІН дає
code 0x18 і ВИТРАЧАЄ спробу; помилки формату/носія (code 2/0x11) до автентифікації
спробу не витрачають. ПІН — лише через пам'ять/env, ніколи в аргументах чи логах.

### Підпис кількома КЕП через ASiC-контейнер

Коли підписи роблять різні стеки (токен euscp + файловий UAPKI), звести їх в один
CMS не можна (різний eContent → INVALID_DIGEST). Рішення — ASiC-контейнер
(ETSI EN 319 162-1): detached-підписи лежать ПОРУЧ у ZIP, кожна самодостатня.
`infrastructure/asic.py` пакує їх (пакування != підписання):

```python
from dilovod4.infrastructure.asic import build_asic_e, AsicSignature

build_asic_e(
    [("signed.pdf", pdf_bytes)],          # файли даних
    [AsicSignature(token_p7s),            # detached CAdES токена (ДПС)
     AsicSignature(mono_p7s)],            # detached CAdES monobank
    "signed.asice",
)
```

Розкладка ASiC-E: `mimetype` (STORED, перший) + файли даних +
`META-INF/signatureNNN.p7s` + `META-INF/ASiCManifestNNN.xml`. КРИТИЧНО: кожна
підпис має ВЛАСНИЙ ASiCManifestNNN.xml із SHA-256 `DigestValue` кожного
data-файла (не лише URI) — без digest czo.gov.ua дає помилку 33.
Альтернатива — нативний `token_sign.asic_sign_with_token()` (euscp CtxASiCSign
формує контейнер сам).

### CLI для ASiC: `dilovod4-asic`

Зручний CLI з підкомандами (точка входу `dilovod4-asic` або
`python3 -m dilovod4.presentation.asic_cli`):

```bash
# 1) дізнатися, що підписувати (манІфест для 1-го підпису)
dilovod4-asic manifest doc.pdf -n 1 -o manifest001.xml
# 2) підписати manifest001.xml detached токеном/UAPKI -> sig1.p7s (зовнішньо)
# 3) зібрати контейнер з готових підписів
dilovod4-asic pack doc.pdf -s sig1.p7s -s sig2.p7s -o doc.asice
# переглянути вміст
dilovod4-asic inspect doc.asice

# або підпис токеном одразу в ASiC-E (PIN через TOKEN_PIN, -t = CAdES-T):
TOKEN_PIN=*** dilovod4-asic sign doc.pdf -t \
    --cmp ca.tax.gov.ua/services/cmp/ \
    --tsp ca.tax.gov.ua/services/tsp/ --ocsp ca.tax.gov.ua/services/ocsp/
```

Підкоманди: `manifest` (вивести ASiCManifestNNN.xml для зовнішнього підпису),
`pack` (зібрати з готових detached-підписів над манІфестами), `sign` (підпис
токеном напряму в ASiC-E), `inspect` (розібрати наявний контейнер).

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
# доменне ядро (правила + інваріанти, межові значення, адаптери, use-case)
python3 -m pytest -q

# тести порталу (FastAPI routers)
./manage.sh backend-test
# або: python3 -m pytest portal/tests/

# фронтенд typecheck
./manage.sh frontend-check
```

Зразки — у `samples/`.

## Межі

Кодуються лише обчислювані положення (як і в Catala). Поза межами: координатні
схеми (Додаток А), зразки бланків (Додаток Б), приклади документів, бібліографія.

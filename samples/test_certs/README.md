# Тестові сертифікати

Два типи тестових ключів: **серверні** (для `PORTAL_SEAL_P12`, UAPKI/openssl) та
**клієнтський** (для EUSign WASM у браузері). ⚠ **ТЕСТОВІ** — не для продакшну.

## ⚠ Важливе про формат PKCS#12

EUSign WASM (клієнтський UI) відкриває **ЛИШЕ ГОСТ-контейнери** (DSTU Gost 34311
MAC, gost28147-CFB) — як реальні ключі КНЕДП. Генератор `gen_test_certs.py` будує
**PBES2/AES-256** (сучасний RFC 7292), який EUSign відхиляє помилкою 24.

Тому:
- **серверний підпис** (`PORTAL_SEAL_P12`, UAPKI) → PBES2/AES (генеровані `.p12`);
- **клієнтський UI** (EUSign WASM) → готовий ГОСТ `client_diia.p12` (нижче).

Причина: `cryptography` не парсить DSTU SubjectPublicKeyInfo, а UAPKI не випускає
сертифікати — повний міні-CA над UAPKI неможливий без реверсу ASN.1 UAPKI.

## Паролі

| Файл | Пароль |
|------|--------|
| `ca.p12`, `person_esign.p12`, `org_eseal.p12` | `TestPass-2026` |
| `client_diia.p12` | `testpassword` |

## Файли

### Серверні (PBES2/AES-256, для `PORTAL_SEAL_P12` та openssl)

Згенеровано `scripts/gen_test_certs.py` на `cryptography` (ECDSA P-256 + QC).

| Роль | .cer | .p12 | Subject CN | Subject ID | KeyUsage | cert_type |
|------|------|------|------------|------------|----------|-----------|
| **CA** | `ca.cer` | `ca.p12` | Тестовий КНЕДП «Діловод» | `NTRUA-00000000` | Cert Sign + CRL | — (корінь) |
| **КЕП особи** (eSign) | `person_esign.cer` | `person_esign.p12` | Петренко Петро Петрович | `serialNumber=1234512345` (РНОКПП) | Non Repudiation | `esign` |
| **Печатка юрособи** (eSeal) | `org_eseal.cer` | `org_eseal.p12` | ТОВ Рога і Копита | `organizationIdentifier=NTRUA-43213421` (ЄДРПОУ) | Non Repudiation | `eseal` |

### Клієнтський (ГОСТ, для EUSign WASM/віджету ІІТ)

| Файл | Source | Subject | РНОКПП | КНЕДП |
|------|--------|---------|--------|-------|
| `client_diia.p12` | `external/UAPKI/library/test/data/test-diia.p12` | "ДІЯ — Кваліфікований надавач електронних довірчих послуг тестового режиму" | `UA-43395033-10001` | Інформ'юст UA (QC eSign) |
| `client_diia.cer` | сертифікат витягнуто з `client_diia.p12` (через UAPKI) | (той самий) | `UA-43395033-10001` | Інформ'юст UA |

2 DSTU-ключі (підпис + TLS) у `.p12`. Це реальний тестовий сертифікат ДІЯ — криптошлях
тотожний печатці (DSTU 4145 + CAdES). Підписувач = фізособа, але для UI-тесту
механізму підписання/прив'язки сертифіката цього достатньо.

⚠ `client_diia.p12` — формат PKCS#12 (def-mode), тож EUSign не витягує сертифікат
з контейнеру автоматично, а тягне його онлайн з КНЕДП (CMP). Тестовий CMP ДІЯ
недоступний → помилка 51 «Сертифікат не знайдено». Тому поруч лежить
`client_diia.cer` — сертифікат окремим файлом, який EUSign читає офлайн.

## Абсолютні шляхи

```
/Volumes/External/Code/dstu_4163_2020/samples/test_certs/ca.cer
/Volumes/External/Code/dstu_4163_2020/samples/test_certs/ca.p12
/Volumes/External/Code/dstu_4163_2020/samples/test_certs/person_esign.cer
/Volumes/External/Code/dstu_4163_2020/samples/test_certs/person_esign.p12
/Volumes/External/Code/dstu_4163_2020/samples/test_certs/org_eseal.cer
/Volumes/External/Code/dstu_4163_2020/samples/test_certs/org_eseal.p12
/Volumes/External/Code/dstu_4163_2020/samples/test_certs/client_diia.p12
```

## Використання

### Серверний підпис печаткою (backend)
```bash
export PORTAL_SEAL_P12=/Volumes/External/Code/dstu_4163_2020/samples/test_certs/org_eseal.p12
export PORTAL_SEAL_PASSWORD='TestPass-2026'
# → POST /documents/{id}/server-seal
```

### Клієнтський підпис (UI EUSign WASM)
У формі «Сертифікати підписання» → завантажити `client_diia.p12` (пароль `testpassword`)
**та** `client_diia.cer` у поле «Сертифікат ключа (.cer)». Без `.cer` EUSign повідомить
«Сертифікат не знайдено (51)» — сертифікат береться з файлу в офлайн-режимі.

## Регенерація (серверних)

```bash
python3 scripts/gen_test_certs.py --out samples/test_certs/ --password 'TestPass-2026'
# опції: --ca-cn, --person-cn, --person-rnopp, --org-name, --edrpou
```

`client_diia.p12` НЕ регенерується — це готовий тестовий контейнер ІІТ (з
`external/UAPKI/library/test/data/test-diia.p12`).

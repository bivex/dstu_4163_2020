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

## Конфігурація (через оточення)

| Env | Призначення | Типово |
|---|---|---|
| `DILOVOD4_OUTPUT_FORMAT` | `text` \| `json` | `text` |
| `DILOVOD4_LOG_LEVEL` | рівень логів | `INFO` |
| `DILOVOD4_DISABLED_RULES` | CSV `rule_id` для профілю | (порожньо) |

## Тести

```bash
python3 -m pytest -q
```

Доменні unit-тести (правила + інваріанти, межові значення) та інтеграційні тести
адаптерів і use-case. Зразки — у `samples/`.

## Межі

Кодуються лише обчислювані положення (як і в Catala). Поза межами: координатні
схеми (Додаток А), зразки бланків (Додаток Б), приклади документів, бібліографія.

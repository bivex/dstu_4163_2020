"""Вбудовані типові бізнес-процеси документообігу (BPMN-lite графи)."""

from __future__ import annotations

import json
from typing import Callable
from sqlalchemy.orm import Session

from portal.db import Process


def seed_default_processes(session_factory: Callable[[], Session]) -> None:
    """Створити вбудовані бізнес-процеси документообігу якщо таблиця порожня."""
    with session_factory() as session:
        existing_names = {p.name for p in session.query(Process.name).all()}

        def graph(nodes, edges):
            return json.dumps({"nodes": nodes, "edges": edges}, ensure_ascii=False)

        def add_if_new(items):
            fresh = [p for p in items if p.name not in existing_names]
            if fresh:
                session.add_all(fresh)
                existing_names.update(p.name for p in fresh)
            return fresh

        # 1) Погодження та підписання вихідного документа
        p1_nodes = [
            {"id": "n1", "type": "start", "label": "Створення проєкту", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Погодження (візування)", "x": 220, "y": 120},
            {"id": "n3", "type": "gateway", "label": "Погоджено?", "x": 430, "y": 120},
            {"id": "n4", "type": "task", "label": "Доопрацювання", "x": 430, "y": 250},
            {"id": "n5", "type": "task", "label": "Підписання КЕП", "x": 620, "y": 120},
            {"id": "n6", "type": "task", "label": "Реєстрація", "x": 810, "y": 120},
            {"id": "n7", "type": "end", "label": "Відправлення", "x": 1000, "y": 120},
        ]
        p1_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n5", "label": "так"},
            {"from": "n3", "to": "n4", "label": "ні"},
            {"from": "n4", "to": "n2", "label": "повторно"},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 2) Реєстрація та виконання вхідного документа
        p2_nodes = [
            {"id": "n1", "type": "start", "label": "Надходження", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Реєстрація вхідного", "x": 220, "y": 120},
            {"id": "n3", "type": "task", "label": "Розгляд керівником", "x": 420, "y": 120},
            {"id": "n4", "type": "task", "label": "Накладення резолюції", "x": 620, "y": 120},
            {"id": "n5", "type": "task", "label": "Виконання доручення", "x": 820, "y": 120},
            {"id": "n6", "type": "gateway", "label": "Виконано?", "x": 1020, "y": 120},
            {"id": "n7", "type": "end", "label": "Списання у справу", "x": 1210, "y": 120},
        ]
        p2_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": "так"},
            {"from": "n6", "to": "n5", "label": "ні"},
        ]

        # 3) Видання наказу з основної діяльності
        p3_nodes = [
            {"id": "n1", "type": "start", "label": "Ініціювання наказу", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Підготовка проєкту", "x": 230, "y": 120},
            {"id": "n3", "type": "task", "label": "Візування (юрист, бухгалтер)", "x": 440, "y": 120},
            {"id": "n4", "type": "task", "label": "Підписання керівником", "x": 670, "y": 120},
            {"id": "n5", "type": "task", "label": "Реєстрація (наскрізний №)", "x": 880, "y": 120},
            {"id": "n6", "type": "task", "label": "Ознайомлення працівників", "x": 1100, "y": 120},
            {"id": "n7", "type": "end", "label": "Зберігання у справі", "x": 1320, "y": 120},
        ]
        p3_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        add_if_new([
            Process(
                name="Погодження та підписання вихідного документа",
                description="Типовий маршрут вихідного документа: візування → підписання КЕП → реєстрація → відправлення.",
                graph_json=graph(p1_nodes, p1_edges),
                is_builtin=True,
            ),
            Process(
                name="Реєстрація та виконання вхідного документа",
                description="Обробка вхідного: реєстрація → розгляд → резолюція → виконання → списання у справу.",
                graph_json=graph(p2_nodes, p2_edges),
                is_builtin=True,
            ),
            Process(
                name="Видання наказу з основної діяльності",
                description="Життєвий цикл наказу: підготовка → візування → підписання → реєстрація → ознайомлення.",
                graph_json=graph(p3_nodes, p3_edges),
                is_builtin=True,
            ),
        ])

        # --- Професійні процеси для ФОП (фізична особа — підприємець) ---

        # 4) Укладення договору з контрагентом
        f1_nodes = [
            {"id": "n1", "type": "start", "label": "Запит від клієнта", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Підготовка договору", "x": 230, "y": 120},
            {"id": "n3", "type": "task", "label": "Узгодження умов", "x": 440, "y": 120},
            {"id": "n4", "type": "gateway", "label": "Умови узгоджено?", "x": 650, "y": 120},
            {"id": "n5", "type": "task", "label": "Коригування", "x": 650, "y": 250},
            {"id": "n6", "type": "task", "label": "Підписання КЕП обома", "x": 860, "y": 120},
            {"id": "n7", "type": "end", "label": "Договір у силі", "x": 1070, "y": 120},
        ]
        f1_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n6", "label": "так"},
            {"from": "n4", "to": "n5", "label": "ні"},
            {"from": "n5", "to": "n3", "label": "повторно"},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 5) Виставлення рахунку та облік оплати
        f2_nodes = [
            {"id": "n1", "type": "start", "label": "Надання послуги/товару", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Виставлення рахунку", "x": 250, "y": 120},
            {"id": "n3", "type": "task", "label": "Надсилання клієнту", "x": 460, "y": 120},
            {"id": "n4", "type": "gateway", "label": "Оплачено?", "x": 670, "y": 120},
            {"id": "n5", "type": "task", "label": "Нагадування про оплату", "x": 670, "y": 250},
            {"id": "n6", "type": "task", "label": "Акт виконаних робіт", "x": 880, "y": 120},
            {"id": "n7", "type": "end", "label": "Облік доходу (Книга ОД)", "x": 1090, "y": 120},
        ]
        f2_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n6", "label": "так"},
            {"from": "n4", "to": "n5", "label": "ні"},
            {"from": "n5", "to": "n4", "label": "очікування"},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 6) Подання податкової звітності ФОП (єдиний податок + ЄСВ)
        f3_nodes = [
            {"id": "n1", "type": "start", "label": "Кінець звітного періоду", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Звірка доходів", "x": 240, "y": 120},
            {"id": "n3", "type": "task", "label": "Формування декларації", "x": 450, "y": 120},
            {"id": "n4", "type": "task", "label": "Підписання КЕП", "x": 660, "y": 120},
            {"id": "n5", "type": "task", "label": "Подання до ДПС", "x": 850, "y": 120},
            {"id": "n6", "type": "task", "label": "Сплата ЄП та ЄСВ", "x": 1050, "y": 120},
            {"id": "n7", "type": "end", "label": "Квитанція №2 отримана", "x": 1270, "y": 120},
        ]
        f3_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 7) Прийняття найманого працівника
        f4_nodes = [
            {"id": "n1", "type": "start", "label": "Потреба у працівникові", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Отримання документів від кандидата", "x": 230, "y": 120},
            {"id": "n3", "type": "task", "label": "Укладення трудового договору", "x": 450, "y": 120},
            {"id": "n4", "type": "task", "label": "Оформлення наказу про прийняття", "x": 670, "y": 120},
            {"id": "n5", "type": "task", "label": "Повідомлення ДПС про прийняття", "x": 890, "y": 120},
            {"id": "n6", "type": "task", "label": "Інструктаж та допуск до роботи", "x": 1110, "y": 120},
            {"id": "n7", "type": "end", "label": "Оформлено найм", "x": 1330, "y": 120},
        ]
        f4_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 8) Отримання первинних документів від постачальника
        f5_nodes = [
            {"id": "n1", "type": "start", "label": "Надходження послуг/товарів", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Отримання первинних документів", "x": 250, "y": 120},
            {"id": "n3", "type": "gateway", "label": "Перевірка ДСТУ та реквізитів", "x": 470, "y": 120},
            {"id": "n4", "type": "task", "label": "Запит на виправлення", "x": 470, "y": 250},
            {"id": "n5", "type": "task", "label": "Підписання КЕП (Вчасно/Дія)", "x": 690, "y": 120},
            {"id": "n6", "type": "task", "label": "Оплата рахунку постачальника", "x": 900, "y": 120},
            {"id": "n7", "type": "end", "label": "Первинні документи підписано", "x": 1110, "y": 120},
        ]
        f5_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n5", "label": "так"},
            {"from": "n3", "to": "n4", "label": "ні"},
            {"from": "n4", "to": "n2", "label": "повторно"},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 9) Реєстрація та робота з ПРРО
        f6_nodes = [
            {"id": "n1", "type": "start", "label": "Необхідність фіскалізації", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Подання форми 20-ОПП", "x": 230, "y": 120},
            {"id": "n3", "type": "task", "label": "Подання форми 1-ПРРО", "x": 440, "y": 120},
            {"id": "n4", "type": "task", "label": "Подання форми 5-ПРРО (касир)", "x": 650, "y": 120},
            {"id": "n5", "type": "task", "label": "Відкриття зміни та продажі", "x": 860, "y": 120},
            {"id": "n6", "type": "task", "label": "Створення Z-звіту та закриття", "x": 1070, "y": 120},
            {"id": "n7", "type": "end", "label": "Зміна успішно закрита", "x": 1280, "y": 120},
        ]
        f6_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        # 10) Припинення (закриття) діяльності ФОП
        f7_nodes = [
            {"id": "n1", "type": "start", "label": "Рішення припинити діяльність", "x": 40, "y": 120},
            {"id": "n2", "type": "task", "label": "Подання заяви в Дію (держреєстратор)", "x": 250, "y": 120},
            {"id": "n3", "type": "task", "label": "Подання ліквідаційної звітності", "x": 470, "y": 120},
            {"id": "n4", "type": "task", "label": "Остаточна сплата податків", "x": 680, "y": 120},
            {"id": "n5", "type": "task", "label": "Закриття рахунків у банках", "x": 890, "y": 120},
            {"id": "n6", "type": "task", "label": "Пройдення податкової звірки", "x": 1100, "y": 120},
            {"id": "n7", "type": "end", "label": "ФОП офіційно знято з обліку", "x": 1310, "y": 120},
        ]
        f7_edges = [
            {"from": "n1", "to": "n2", "label": ""},
            {"from": "n2", "to": "n3", "label": ""},
            {"from": "n3", "to": "n4", "label": ""},
            {"from": "n4", "to": "n5", "label": ""},
            {"from": "n5", "to": "n6", "label": ""},
            {"from": "n6", "to": "n7", "label": ""},
        ]

        add_if_new([
            Process(
                name="ФОП: Укладення договору з контрагентом",
                description="Договірна робота ФОП: запит → підготовка → узгодження → підписання КЕП обома сторонами.",
                graph_json=graph(f1_nodes, f1_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Виставлення рахунку та облік оплати",
                description="Розрахунки ФОП: рахунок → надсилання → контроль оплати → акт → запис у Книгу обліку доходів.",
                graph_json=graph(f2_nodes, f2_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Подання податкової звітності (ЄП + ЄСВ)",
                description="Звітність єдинника: звірка доходів → декларація → КЕП → подання до ДПС → сплата ЄП/ЄСВ.",
                graph_json=graph(f3_nodes, f3_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Прийняття найманого працівника",
                description="Оформлення найму: пакет документів → трудовий договір → наказ про прийняття → повідомлення ДПС → інструктаж.",
                graph_json=graph(f4_nodes, f4_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Отримання первинних документів від постачальника",
                description="Контроль вхідної первинки: рахунок/накладна → перевірка реквізитів та відповідності ДСТУ → підписання КЕП → оплата.",
                graph_json=graph(f5_nodes, f5_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Реєстрація та робота з ПРРО",
                description="Робота з програмною касою: подання 20-ОПП → реєстрація каси 1-ПРРО → реєстрація касира 5-ПРРО → Z-звіти.",
                graph_json=graph(f6_nodes, f6_edges),
                is_builtin=True,
            ),
            Process(
                name="ФОП: Припинення (закриття) діяльності",
                description="Процедура закриття ФОП: заява держреєстратору → ліквідаційна звітність → закриття рахунків → податкова звірка.",
                graph_json=graph(f7_nodes, f7_edges),
                is_builtin=True,
            ),
        ])

"""Реестр 8.05 «Стенд облака: полный набор, нагрузка, классы сбоев»: стенд на настоящем контроллере работает как инструмент.

Здесь не полный набор тестов и не 3 часа (это ночной прогон), а короткие прогоны тех же инструментов tools/replay: марафон (нагрузка: серия вопросов подряд
на виртуальном времени), хаос (один сбой из классов в цепочке вопросов) и то, что стенд ловит подсаженный дефект продукта. Контроллер настоящий, подделки только
на внешней границе (часы, телефон, облако, синтез, поиск), как в самих стендах. Смотрим на отчёты инструментов: сколько спрошено/отвечено, нарушения.
"""
import pytest

import helpers_t_classes_mutants as broken
from tools.replay import chaos, marathon


def test_the_stand_runs_a_load_a_fault_class_and_catches_a_planted_defect(monkeypatch):
    # 1. нагрузка: короткий марафон через настоящую цепочку; каждый вопрос получил свой ответ по порядку, нарушений нет
    load = marathon.one(0, questions=2, hours=0.1)
    assert load['asked'] == 2, 'опора: марафон не задал вопросы'
    assert load['answered'] == 2 and not load['lost'] and not load['order'], load
    assert not load['crash'] and not load['violations'], load['violations'][:2]

    # 2. класс сбоя: облачная модель зависла на втором вопросе, стенд проверил, что звонок жив и следующие вопросы получили ответы
    hang = chaos.run(0, 'model_hang', 2, steps=3)
    assert len(hang.asked) == 3 and hang.cues, 'опора: цепочка вопросов не отработала'
    assert chaos.first(hang) is None, hang.violations[:2]

    # 3. подсаженный дефект продукта (курсор подсказки идёт сам по таймеру): стенд обязан его поймать, на целом продукте тот же прогон чист
    clean = chaos.run(1, 'none', 1, steps=2)
    assert len(clean.asked) == 2 and clean.cues and not clean.violations, clean.violations[:2]
    broken.the_timer_advances_the_cursor(monkeypatch)
    caught = chaos.run(1, 'none', 1, steps=2)
    assert caught.cues, 'опора: на сломанном продукте звонок не отработал'
    assert caught.violations, 'стенд не поймал подсаженный дефект'

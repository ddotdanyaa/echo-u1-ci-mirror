"""Функция 2.09 «Язык реплики: английская речь, ответ и голос по языку».
Состояние: ДЕЙСТВУЕТ без ключа (f84a05a9: lang_turn удалён, русское ухо над не русским ходом отбрасывается всегда); ключи answer_lang, tts_lang, cross_script, ear_en удалены: сравнение письменностей в повторе идёт всегда, английское ухо не правило.
Стенд: tests/helpers_night_memory.Call (настоящие ControlledMedia, NativeMediaSocket, fast_text.for_call, CallTrace на виртуальном времени;
подделаны облачные события, телефон, текстовая модель и ухо: запись уха подаётся в публичный вход ear_heard, как это делают стенды).
Настройки: LIVE = живые значения сервера (остальные по умолчанию), fast_text=on для канала текстовой модели;
память разговора (Call включает её по умолчанию) выключена, чтобы запрос модели нёс только политику.
Снаружи видно: инструкции, ушедшие текстовой модели; строки lang_gate и ear act в логе echo-sync.
Зелёный: на английском ходу строка lang_gate mode=on, запись уха отброшена; на английский вопрос уходит английская инструкция; на русском ходу строки нет.
Не покрыто: голос Zira (tts_lang) и английское ухо kroko (ear_en) — только на ноутбуке, см. registry_proof/2.09.json."""
import logging
import re

import pytest

from echo_sync.lang_hint import LANG_RULES

import helpers_night_memory as M

LIVE = {'fast_text': 'on', 'conversation_ledger': 'off', 'topic_recap': 'off'}
EN_Q = 'What is the capital of Canada, please?'
EN_EAR = 'ват из зе кэпитал оф канада плиз'      # английские слова русскими буквами: так их слышит русское ухо
RU_Q = 'Какая столица у Канады, подскажите?'
RU_EAR = 'какая столица у канады подскажите'


@pytest.fixture
def make(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    calls = []

    def build(**over):
        call = M.Call(tmp_path / f'c{len(calls)}', mind=lambda request: 'Первая часть ответа. Вторая часть ответа.', **{**LIVE, **over})
        calls.append(call)
        return call
    yield build
    for call in calls:
        call.close()


def hear(call, text, uid):
    """Ухо услышало реплику: запись уха в публичный вход контроллера."""
    return call.c.ear_heard({'uid': uid, 'text': text, 'offset': call.w.clock.now(), 'kind': 'final', 'speech_ms': 900})


def lines(caplog, pattern):
    return [r.getMessage() for r in caplog.records if re.search(pattern, r.getMessage())]


def test_the_ear_over_an_english_turn_is_gated_and_the_line_names_numbers_and_labels_only(make, caplog):
    call = make()
    call.say(EN_Q)
    assert [r['instructions'] for _, _, r in call.requests] == [M.POLICY + '\n\n' + LANG_RULES['en']['instruction']], 'one-input U19: строка языка в запросе без ключа, ухо в тени'
    assert hear(call, EN_EAR, 'e1') == []
    gate = lines(caplog, r'lang_gate mode=on')
    assert len(gate) == 1 and 'why=turn_en' in gate[0] and 'turn=en' in gate[0] and 'uid=e1' in gate[0]
    assert not any('Canada' in m or 'канад' in m for m in gate), 'в строке только числа и метки'
    caplog.clear()
    ru = make()
    ru.say(RU_Q)
    hear(ru, RU_EAR, 'r1')
    assert [r['instructions'] for _, _, r in ru.requests] == [M.POLICY] and not lines(caplog, r'lang_gate'), 'на русском ходу строки нет'


def test_english_question_gets_an_english_answer_instruction(make):
    call = make()
    call.say(EN_Q)
    sent = [r['instructions'] for _, _, r in call.requests]
    assert len(sent) == 1 and 'Answer in English' in sent[0]
    call.say(RU_Q)
    assert 'English' not in call.requests[-1][2]['instructions'], 'русский вопрос после английского — инструкция снова без английской строки'


def test_russian_ear_over_english_turn_is_set_aside(make, caplog):
    call = make()
    call.say(EN_Q)
    hear(call, EN_EAR, 'e1')
    assert lines(caplog, r'lang_gate mode=on uid=e1 why=turn_en'), 'запись уха отброшена по языку хода (ожидает облачный итог), а не принята за русскую речь'

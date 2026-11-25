"""Реестр 3.01: единый шлюз действий. Человек: стоп, продолжай и новый вопрос над ответом двигают порцию, вопрос и звук ровно по одному разу,
и у каждого такого шага в журнале звонка есть одна запись шлюза (act/reason/verdict). Ключа act_gate больше нет: шлюз всегда включён.
ГРАНИЦА ДОКАЗАННОГО: вердикты stale и park (действие с устаревшим основанием не исполняется) через звонок не вызываются: каждое место вызова проверяет основание за миг до шлюза,
поэтому в журнале сценария все вердикты do; устаревшее основание доказано в tests/test_night_gate_act.py.
"""
import pytest

import _h3 as H

ANSWER = 'Озеро Байкал находится в Сибири. Оно самое глубокое на планете. Его возраст двадцать пять миллионов лет.'
QUESTION = 'Где находится озеро Байкал?'
SUM = 'Сколько будет двадцать пять плюс семнадцать?'


def call(tmp_path, monkeypatch, **own):
    """Вопрос с ответом из порций, «стоп», «продолжай», новый вопрос поверх ответа. Возвращает (журнал, подсказки на каждом шаге)."""
    async def body(host):
        steps = []
        for text in (QUESTION, 'стоп', 'продолжай', SUM):
            await H.say(host, text)
            await host.advance(1)
            steps.append(list(host.spoken()))
        return H.journal(host), steps
    return H.play(tmp_path, monkeypatch, body, model=H.Model({'байкал': ANSWER}), **own)


def gate(rows):
    return [(r['act'], r['reason'], r['verdict']) for r in rows if r['ev'] == 'why' and r.get('kind') == 'act']


def need(condition, what):
    """Условие сценария, не проверка шлюза: его провал не должен прятаться за ожидаемым красным (xfail ловит только AssertionError)."""
    if not condition:
        raise RuntimeError('scenario precondition: %s' % what)


def behaviour(rows, steps):
    """Что человек получает и без записей шлюза: ответ, пауза на «стоп», возобновление, новый ответ."""
    asked, stopped, resumed, summed = steps
    need(asked and 'Сибир' in asked[0], 'the answer sounded: %s' % asked)
    need(stopped == asked, 'after «стоп» nothing new is sounded: %s' % stopped)
    need(len(resumed) > len(stopped) and 'Сибир' in resumed[-1], 'after «продолжай» the portion is said again: %s' % resumed)
    need(summed and summed[-1] == 'Сорок два.', 'the new question over the answer is answered: %s' % summed)
    kinds = [kind for kind, _ in H.decisions(rows)]
    assert kinds.count('stop') == 1 and kinds.count('resume') == 1, 'one reaction per phrase, no doubles: %s' % kinds


def entries(rows):
    """Каждый шаг прошёл через шлюз один раз: пауза по «стоп», вопрос уступил место новому, звук режется при каждой реплике человека."""
    got = gate(rows)
    assert got.count(('pause', 'stop', 'do')) == 1, got
    assert got.count(('supersede', 'open_question', 'do')) == 2, got
    assert sum(1 for act, _, _ in got if act == 'cut_sound') == 4, got
    assert all(verdict == 'do' for _, _, verdict in got), 'nothing is late in a calm talk: %s' % got


def test_every_irreversible_step_goes_through_the_gate_once(tmp_path, monkeypatch):
    rows, steps = call(tmp_path, monkeypatch)
    behaviour(rows, steps)
    entries(rows)

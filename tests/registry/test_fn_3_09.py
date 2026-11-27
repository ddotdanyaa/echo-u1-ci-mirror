"""Реестр 3.09 «Удержание порции и устаревший план». Граница стенда: локальное ухо (его в облаке нет): синхронный распознаватель, отдающий заготовленный текст
на конец каждой речи; громкий звук в микрофоне телефона даёт речь по энергии. Всё остальное настоящее; судим по подсказкам и журналу звонка."""
import _h3 as H

QUESTION = 'Какая столица у Австралии?'
FIRST = 'Столица Австралии — город Канберра.'
SECOND = 'Она стоит между Сиднеем и Мельбурном.'
ANSWER = FIRST + ' ' + SECOND


MODEL = {'столица': ANSWER}


def test_first_cue_waits_while_the_person_is_speaking_then_plays(tmp_path, monkeypatch):
    async def body(host):
        host.voice('loud')
        await host.advance(0.5)
        await H.say(host, QUESTION)                    # ответ готов, а речь вокруг ещё идёт
        await host.advance(4)
        during = (list(host.spoken()), H.cues(H.journal(host)))
        host.voice('quiet')
        await host.advance(0.8)
        tail = list(host.spoken())                      # речь только что кончилась: на её хвост подсказка тоже не ложится
        await host.advance(3.2)
        return (during, tail), host.spoken(), H.journal(host)
    (during, tail), spoken, rows = H.play(tmp_path, monkeypatch, body, model=MODEL, ear=['Какая столица у Австралии'])
    assert during == ([], []) and tail == [], 'the cue did not run over the speech nor over its tail'
    assert spoken[0] == FIRST and H.cues(rows)[0] == FIRST, 'the speech is over: the held cue plays'
    assert ('answer', 'fast_text_owns') in H.decisions(rows)


def test_control_nobody_speaks_and_the_cue_plays_at_once(tmp_path, monkeypatch):
    async def body(host):
        await H.say(host, QUESTION)
        await host.advance(1)
        return host.spoken(), H.cues(H.journal(host))
    spoken, cues = H.play(tmp_path, monkeypatch, body, model=MODEL, ear=[])
    assert spoken[:1] == [FIRST] and cues[:1] == [FIRST]


def test_the_hold_has_a_limit_speech_that_never_ends_does_not_silence_the_cue(tmp_path, monkeypatch):
    async def body(host):
        host.voice('talk')                          # речь не кончается: паузы короче порога конца речи
        await host.advance(0.5)
        await H.say(host, QUESTION)
        await host.advance(5)
        early = list(host.spoken())
        await host.advance(7)
        return early, list(host.spoken()), H.journal(host)
    early, late, rows = H.play(tmp_path, monkeypatch, body, model=MODEL, ear=[])
    assert early == [], 'first the cue is held'
    assert late[:1] == [FIRST], 'but not for ever: 12 s after the answer was ready it is said, the talk still going'
    assert not [r for r in rows if r['ev'] == 'ear_final'], 'the speech had not ended when the cue was said'


def test_a_stopped_plan_does_not_come_back_by_itself(tmp_path, monkeypatch):
    async def body(host):
        await H.say(host, QUESTION)
        await host.advance(1)
        await H.say(host, FIRST)                       # человек повторил первую порцию: звучит вторая
        await host.advance(1)
        await H.say(host, 'Стоп.')
        await host.advance(40)                         # молчание
        stopped = list(host.spoken())
        await H.say(host, 'Как зовут соседа моей бабушки?')      # вопрос без ответа: прежний план мог бы вернуться
        await host.advance(30)
        return stopped, list(host.spoken()), H.decisions(H.journal(host))
    stopped, after, decisions = H.play(tmp_path, monkeypatch, body, model=MODEL, ear=[])
    assert stopped[:2] == [FIRST, SECOND] and ('stop', 'stop_pauses_the_answer') in decisions, decisions
    assert after == stopped + ['Нет ответа. Повторите вопрос.'], 'of the stopped answer nothing was said again, only the honest phrase of the unanswered question: ' + repr(after[len(stopped):])      # cm_speech._answer_watchdog: a question whose job failed is no talk, the honest phrase is said and the older plan stays in the history


import pytest      # noqa: E402

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

"""Реестр 3.03: единая таблица времени и порядка отказа; timer_guard стал правилом хозяина таймеров (ключа нет); order_guard и refuse_anchor остаются ключами.
Что видно снаружи: (1) при открытии звонка журнал называет нарушенные связи сроков (call_open.timer_violations); (2) устаревший слот снимается сразу строкой «timer_stale» и больше не возвращается.
Проверка на пустышку: правило снятия в _new_epoch и _repeat_gate; без него тест 3 краснеет."""
import logging

import _h3 as H

F = H.F                                                  # провод облака стенда: реплика человека пословно (turn.delta)
FIRST = 'Столица Австралии — город Канберра.'
SECOND = 'Она стоит между Сиднеем и Мельбурном.'
THIRD = 'Город основан в начале двадцатого века.'
MODEL = {'столица': ' '.join([FIRST, SECOND, THIRD])}    # ответ из трёх порций
DOUBT = 'не может быть'


async def _speak(host, tid, text, start):
    """Реплика человека словами, по одному в 0,14 с (как её присылает распознавание); возвращает номер следующего слова."""
    for number, word in enumerate(text.split(), start):
        host.cloud(F.delta(tid, ' ' + word, number))
        await host.advance(0.14)
    return start + len(text.split())


def _open_rows(tmp_path, monkeypatch, **own):
    async def body(host):
        await host.advance(1)
        return H.journal(host)
    return [row for row in H.play(tmp_path, monkeypatch, body, **own) if row['ev'] == 'call_open']


def _doubt_after_the_portion(tmp_path, monkeypatch, caplog, **own):
    """Первая порция ответа звучит; человек повторяет её вслух (устойчивый частичный текст засчитан), тут же добавляет слова сомнения: движок берёт шаг назад и
    ответ идёт заново. Возвращает журнал и строки «timer_stale» (слот, взведённый до смены номера ответа и оставшийся после неё)."""
    caplog.set_level(logging.INFO)

    async def body(host):
        await H.say(host, 'Какая столица у Австралии?')
        await host.advance(1.0)
        host.cloud(F.created('u9', 'user', ''))
        number = await _speak(host, 'u9', FIRST, 0)
        await host.advance(0.4)
        await _speak(host, 'u9', DOUBT, number)
        await host.advance(0.5)
        host.cloud(F.done('u9', 'user', FIRST + ' ' + DOUBT))
        await H.settle(host)
        await host.advance(10)
        return H.journal(host)

    rows = H.play(tmp_path, monkeypatch, body, model=MODEL, **own)
    return rows, [r.getMessage() for r in caplog.records if 'timer_stale' in r.getMessage()]


def _human_hears_the_answer_again(rows):
    cues = H.cues(rows)
    assert cues[:2] == [FIRST, SECOND] and THIRD not in cues, cues
    assert ('ack', 'stable_partial') in H.decisions(rows) and ('question', 'cloud_admitted') in H.decisions(rows), H.decisions(rows)
    assert cues[-1] == FIRST and cues.count(FIRST) == 5, ('after the doubt the answer starts over and is repeated by the timer up to the cap', cues)
    assert H.decisions(rows)[-1] == ('silent', 'auto_repeat_cap')


def _cleared_once(lines):
    """Устаревший слот найден один раз и снят; при следующей смене номера ответа он не возвращается."""
    assert len(lines) == 1 and 'reason=early_tail' in lines[0], lines


def test_control_a_live_call_opens_with_no_violated_timer_relation(tmp_path, monkeypatch):
    rows = _open_rows(tmp_path, monkeypatch)
    assert len(rows) == 1 and rows[0]['timer_violations'] == [], rows


def test_a_violated_timer_relation_is_named_when_the_call_opens(tmp_path, monkeypatch):
    rows = _open_rows(tmp_path, monkeypatch, cycle_max_repeats=2)      # потолок цикла (2) ниже max_auto_repeats=3 живого профиля: связь R9 нарушена
    assert len(rows) == 1 and rows[0]['timer_violations'] == ['R9'], rows


def test_a_stale_timer_slot_is_cleared_and_does_not_come_back(tmp_path, monkeypatch, caplog):
    rows, lines = _doubt_after_the_portion(tmp_path, monkeypatch, caplog)
    _human_hears_the_answer_again(rows)
    _cleared_once(lines)

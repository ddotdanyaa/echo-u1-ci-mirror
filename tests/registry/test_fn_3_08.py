"""Реестр 3.08: продолжение с того же слова после запинки и «продолжай» (окно resume_window_s, 10 минут). Живой профиль сервера, судим по подсказкам и журналу.
Пустышка: "resume_window_s=60" краснит второй, "resume_window_s=3600" краснит третий.
Часы движка в стенде настоящие (time.time), виртуальное время их не двигает: десять минут «проходят» сдвигом time.time (стандартная библиотека, не внутренность движка)."""
import time

import _h3 as H

QUESTION = 'Как работает налог?'
ANSWER = 'Общие условия задаёт кодекс. Ставка налога составляет 20 процентов с 1 января. Платить нужно ежегодно.'
SECOND = 'Ставка налога составляет 20 процентов с 1 января.'
OTHER_QUESTION = 'Какая столица у Австралии?'
OTHER_ANSWER = 'Столица Австралии — город Канберра.'


async def second_portion(host):
    """Вопрос, ответ из трёх порций, человек повторил первую: подсказкой стоит вторая."""
    await H.say(host, QUESTION)
    await host.advance(1)
    await H.say(host, host.spoken()[0])
    await host.advance(1)
    assert host.spoken()[-1] == SECOND, host.spoken()


def test_a_stumble_is_cued_from_the_word_the_listener_stopped_before(tmp_path, monkeypatch):
    """Человек начал вторую порцию, ухо записало одно слово не так («наложа») и он замолчал после «с»: подсказка начинается со слова после последнего сказанного."""
    async def body(host):
        await second_portion(host)
        before = len(host.spoken())
        await H.say(host, 'ставка наложа составляет двадцать процентов с')
        await host.advance(4)
        return host.spoken()[before:], H.journal(host)

    cues, rows = H.play(tmp_path, monkeypatch, body, model={'налог': ANSWER})
    assert cues and cues[0] == '1 января.', cues
    assert ('silent', 'attempt_ru_alignment') in H.decisions(rows)


def resume_after(tmp_path, monkeypatch, seconds):
    """Вторая порция первого ответа не подтверждена, его перебил новый вопрос; через ``seconds`` по часам движка человек говорит «Продолжай.»."""
    real, skew = time.time, [0.0]
    monkeypatch.setattr(time, 'time', lambda: real() + skew[0])
    model = H.Model({'налог': ANSWER, 'столица': OTHER_ANSWER, 'продолжай': 'Модель получила просьбу.'})

    async def body(host):
        await second_portion(host)
        await H.say(host, OTHER_QUESTION)
        await host.advance(1)
        assert host.spoken()[-1] == OTHER_ANSWER, host.spoken()
        skew[0] = seconds
        await host.advance(10)
        before = len(host.spoken())
        await H.say(host, 'Продолжай.')
        await host.advance(3)
        return host.spoken()[before:], H.decisions(H.journal(host))

    cues, decisions = H.play(tmp_path, monkeypatch, body, model=model)
    return cues, decisions, model.questions()


def test_continue_within_ten_minutes_returns_the_unfinished_answer(tmp_path, monkeypatch):
    cues, decisions, asked = resume_after(tmp_path, monkeypatch, 300)
    assert cues and cues[0] == SECOND, cues
    assert ('resume', 'suspended_answer_resumed') in decisions
    assert asked == [QUESTION, OTHER_QUESTION], 'the words «Продолжай.» did not go to the model'


def test_an_explicit_continue_after_ten_minutes_still_returns_the_unfinished_answer(tmp_path, monkeypatch):
    """6.04 (resume_next_day is always on): the explicit «продолжай» reaches back 36 hours, not the 10 minutes of resume_window_s (which stays the window of every other utterance)."""
    cues, decisions, asked = resume_after(tmp_path, monkeypatch, 700)
    assert cues and cues[0] == SECOND, cues
    assert ('resume', 'suspended_answer_resumed') in decisions and asked == [QUESTION, OTHER_QUESTION]


def test_continue_after_the_next_day_window_does_not_bring_back_the_old_answer(tmp_path, monkeypatch):
    cues, decisions, _ = resume_after(tmp_path, monkeypatch, 40 * 3600)
    assert SECOND not in cues and ('resume', 'suspended_answer_resumed') not in decisions, (cues, decisions)
    assert cues and cues[0] == OTHER_ANSWER, 'the current answer waits as it did'

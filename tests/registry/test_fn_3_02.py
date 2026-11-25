"""3.02 Ворота ответа (v5_gate): готовый ответ на старую форму вопроса не звучит, если человек его уже поправляет. Реестр: «в тени» (v5_answer_gate=shadow)."""
import pytest

import _h3 as H

QUESTION = 'Во сколько поезд на Лион в понедельник?'
STALE = 'Поезд в понедельник уходит в восемь утра.'
FRESH = 'Поезд в среду уходит в девять утра.'


def answers(question, request):
    return FRESH if question.rstrip().endswith('Нет') else STALE if 'понедельник' in question else None


def run(tmp_path, monkeypatch, correction=True, **own):
    """Человек задал вопрос; пока ответ готов, он уже поправляет себя («Нет...», реплика не закончена); облако шлёт события как есть."""
    model = H.Model(answers)

    async def body(host):
        a = await H.hears(host, 'Во')
        if correction:
            await H.hears(host, 'Нет')
        await H.final(host, a, QUESTION)
        await host.advance(12)
        return host.spoken(), H.journal(host)
    spoken, rows = H.play(tmp_path, monkeypatch, body, model=model, **own)
    return spoken, rows, model


def check_old_answer_is_not_said(spoken, model):
    assert spoken and FRESH in spoken[0], 'the first thing said is the answer to the question as corrected: %r' % spoken
    assert STALE not in spoken, 'the answer to the old form of the question is not said at all: %r' % spoken
    assert model.questions()[-1].rstrip().endswith('Нет'), 'the question was asked again with the correction: %r' % model.questions()


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 3.02: в тени, v5_answer_gate=shadow: устаревший ответ звучит, ворота только пишут вердикт')
def test_target_the_old_answer_is_not_said_when_the_person_is_correcting_the_question(tmp_path, monkeypatch):
    spoken, rows, model = run(tmp_path, monkeypatch)
    check_old_answer_is_not_said(spoken, model)


def test_with_the_key_on_the_old_answer_is_refused_and_the_question_is_asked_again(tmp_path, monkeypatch):
    spoken, rows, model = run(tmp_path, monkeypatch, v5_answer_gate='on')
    check_old_answer_is_not_said(spoken, model)
    assert ('silent', 'v5_stale_answer') in H.decisions(rows)


def test_in_shadow_the_gate_writes_the_verdict_and_changes_nothing(tmp_path, monkeypatch):
    spoken, rows, model = run(tmp_path, monkeypatch)
    verdicts = [row for row in rows if row['ev'] == 'v5_gate']
    first_stale = [row for row in verdicts if row['meaning'] == 'stale']
    assert verdicts and all(row['mode'] == 'shadow' for row in verdicts)
    assert first_stale and first_stale[0]['would_answers'] == 'refuse' and first_stale[0]['code_answers'] == 'veto_negation', first_stale[:1]
    assert spoken[0] == STALE, 'shadow: the stale answer is said as without the gate'
    assert model.questions() == [QUESTION] and ('silent', 'v5_stale_answer') not in H.decisions(rows)
    assert not any(STALE in str(value) or FRESH in str(value) for row in verdicts for value in row.values()), 'the verdict carries codes, no text'


def test_control_without_a_correction_the_answer_passes_and_the_verdict_is_pass(tmp_path, monkeypatch):
    spoken, rows, model = run(tmp_path, monkeypatch, correction=False)
    verdicts = [row for row in rows if row['ev'] == 'v5_gate']
    assert spoken and spoken[0] == STALE and model.questions() == [QUESTION]
    assert verdicts and {row['would_answers'] for row in verdicts} == {'pass'} and {row['meaning'] for row in verdicts} == {'fresh'}

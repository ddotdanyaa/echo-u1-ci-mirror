"""«Повтори» after the last portion of an answer (scenarios sc06 «Ещё раз» and sc09 «Повтори» were silent): the last portion once more,
the cursor and the completion unchanged, and nothing of the old answer once a new question has replaced it."""
from test_first_cue_never_silent import created, done
from test_task1_review_round2 import Session

ANSWER = 'Вода кипит при ста градусах Цельсия.'


def answered(tmp_path):
    s = Session(tmp_path, ack_after=0.3)
    s.ask('При какой температуре кипит вода', tid='u1')
    s.at(0.05, created('a1', 'assistant', ANSWER))
    s.at(0.5, done('a1', 'assistant', ANSWER))
    s.until(15)
    return s


def test_repeat_after_the_last_portion_speaks_it_once_more(tmp_path):
    s = answered(tmp_path)
    state = s.state()
    assert state.get('completed'), state
    before = len(s.cues)
    s.at(16.0, created('u9', 'user', 'Повтори'))
    s.at(16.4, done('u9', 'user', 'Повтори'))
    s.until(22)
    again = [text for at, text in s.cues[before:]]
    assert again[:1] == [state['chunks'][-1]], s.cues
    assert len(again) == 1, f'the last portion is said once, not repeated by the silence timer: {s.cues}'
    after = s.state()
    assert after['completed'] and after['chunk_index'] == state['chunk_index'] and after['revision'] == state['revision']


def test_an_ack_after_the_last_portion_stays_silent(tmp_path):
    s = answered(tmp_path)
    state = s.state()
    before = len(s.cues)
    s.at(16.0, created('u9', 'user', state['chunks'][-1]))
    s.at(16.4, done('u9', 'user', state['chunks'][-1]))
    s.until(22)
    assert s.cues[before:] == [], s.cues

"""U237 break, family «таймеры»: the owner goes quiet for a long time, comes back, writes by hand, asks and gets no answer.
Counts, not phrases (К26): seconds of silence against the number of times the controller speaks by itself. Through the real ControlledMedia."""
import helpers_s6_ack as H
from bps_common import dictation, silence


def test_b12_more_than_ten_minutes_of_silence_wake_the_portion_at_most_the_cap_and_the_owner_comes_back(tmp_path):
    d = dictation(tmp_path)
    index, portion = d.index, d.current
    woke = silence(d, 700, step=5.0)
    cap = d.controller.max_auto_repeats
    assert len(woke) <= cap, f'{len(woke)} self-made repeats in 700 s of silence, the cap is {cap}: {woke}'
    back = d.say(portion)                               # after 700 s the owner reads the waiting portion
    assert back.after == index + 1 and back.speaks == [d.current], back.actions
    assert back.model_calls == 0 and not back.destroyed


def test_b13_once_the_cycle_is_spent_ten_more_minutes_of_silence_stay_silent(tmp_path):
    for mode in ('plain', 'dictation'):
        d = dictation(tmp_path, name=mode)
        if mode == 'dictation':
            d.say('Диктуй медленно.')
        silence(d, 600, step=2.0)
        later = silence(d, 600, step=2.0)
        assert later == [], f'{mode}: the portion was spoken by itself {len(later)} times between minute 10 and minute 20 of silence'


def test_b14_no_answer_for_more_than_ten_minutes_is_told_once_not_on_every_tick(tmp_path):
    d = H.Dictation(tmp_path / 'noanswer', None)
    c = d.controller
    c.speech_started()
    c.provider(H.created('q1', 'user', ''))
    asked = c.provider(H.done('q1', 'user', 'Что такое инерция'))
    assert [a['type'] for a in asked][:2] == ['cancel', 'route'], asked
    told = []
    for _ in range(140):                                # 700 s, a tick every 5 s, the model never answers
        d.clock.advance(5.0)
        actions = c.tick(now=d.clock())
        told += [a for a in actions if a.get('text')]
        d.play(actions)
    assert len(told) <= 1, f'the listener was told about the missing answer {len(told)} times: {[a["text"] for a in told]}'


def test_b15_stop_while_writing_ends_the_dictation_cycle(tmp_path):
    d = dictation(tmp_path)
    d.say('Диктуй медленно.')
    assert d.controller.dictation, 'precondition: the owner said it, the mode is on'
    out = d.say('Стоп.')
    assert out.types == ['cancel'] and out.model_calls == 0, out.actions
    assert d.state.get('paused')
    assert silence(d, 300, step=1.0) == [], 'the dictation cycle went on after «стоп»'
    again = d.say('Ещё раз.')
    assert len(again.speaks) == 1 and again.model_calls == 0, again.actions

"""Registry 5.06 «Следующая порция заранее по темпу; длина порций по слушателю» - state per registry: ВЫКЛЮЧЕНО; since 16.11 flow_ahead is the rule of an acting ear (no key), portion_adapt=off.

Real controller through the h3 stand (real NativeMediaSocket + ShadowEar + ControlledMedia on virtual time, the answer from the fast_text job;
only the recognizer worker is scripted: it shows the text the speaker has said so far to every 100 ms peek, and the final). The speaker repeats
each cue word by word at a steady pace; the cloud's final of the repeat comes 1 s after its end, the ear's final 0.35 s after it.
Proved (as the target for whoever turns it on): (1) the next cue is SENT within 0.15 s after the last word of the repeat, once the speaker's pace
is known, and nothing is advanced twice; (2) after «повтори» asked twice the LATER portions get shorter than for a smooth listener.
Part 1 (flow_ahead) is OFF but works when the key is on (local_ear=act); part 2 (portion_adapt) is NOT BUILT: the code exists, the controller never calls it.
Keys: flow_ahead and portion_adapt are NOT set (code default off). Other keys at the live server values: local_ear=act, fast_text=on,
preset=meaning, max_words=9. Dummy check (private copy, --runxfail): flow_ahead='on' in the profile of the test (test 1 turns green; test 2 stays red even with
portion_adapt='on': the controller never feeds PortionAdapter / calls adapt_rest, so there is no green outcome for test 2).
"""
import pytest

import helpers_s6_state as S
import test_h3_tempo as H3
from echo_sync.textutil import syllables
from test_h3_tempo import TICK, call  # noqa: F401 - the fixture

SPS = 0.2           # the speaker: seconds per syllable
EAR_LAG = 0.3       # the ear shows a word this long after its end
ANSWER = ('Вода закипает в обычной кастрюле на плите при ста градусах Цельсия. В горах она закипает раньше, потому что давление воздуха ниже. '
          'Поэтому в горах еду готовят дольше обычного, и кастрюли с плотной крышкой там очень удобны. '
          'Скороварка поднимает давление внутри и возвращает кипение к привычной температуре, поэтому блюда в ней готовятся заметно быстрее.')


class Peeker(H3.Recognizer):
    """The recognizer's worker that answers a peek (the text so far) with what the scripted speaker has said."""
    text = ''

    def submit(self, sink, uid, op, payload=None):
        super().submit(sink, uid, op, payload)
        if op == 'peek':
            sink.early_results.append((uid, payload, self.text or None, 40))      # the worker's answer to a peek


@pytest.fixture(autouse=True)
def live_profile(monkeypatch, tmp_path):
    """The stand's profile route (as the controller is built on the server): an empty profile file, the test's keys over it."""
    (tmp_path / 'profile.json').write_text('{}')
    monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(tmp_path / 'profile.json'))
    monkeypatch.delenv('ECHO_REPLAY_SET', raising=False)
    monkeypatch.setattr(H3, 'Recognizer', Peeker)


def repeat(rig, portion):
    """The listener repeats ``portion`` word by word; the ear's text grows, its final and the cloud's later final follow. Returns the end of the last word."""
    words = portion.replace(',', '').replace('.', '').split()
    ends, t = [], 0.0
    for word in words:
        t += max(1, syllables(word)) * SPS
        ends.append(t)
    start, uid, quiet = rig.w.clock.t, rig.onset(), False
    tid = f'r{round(start)}'
    rig.w.feed(S.turn_created(tid, 'user', words[0].lower()))
    now, cloud = 0.0, False
    while now < ends[-1] + 2.0:
        shown = sum(1 for e in ends if e + EAR_LAG <= now)
        rig.worker.text = ' '.join(words[:shown]).lower()
        if now < ends[-1]:
            rig.packet('speech')
        elif not quiet:
            rig.packet('end')
            quiet = True
        if now >= ends[-1] + EAR_LAG + 0.05 and shown == len(words) and rig.worker.text:
            rig.worker.heard(uid, rig.worker.text)
            rig.worker.text = ''
        if now >= ends[-1] + 1.0 and not cloud:
            rig.w.feed(S.turn_done(tid, 'user', ' '.join(words)))
            cloud = True
        rig.pump(TICK)
        now += TICK
    return start + ends[-1]


def profile():
    return dict(fast_text='on', preset='meaning', max_words=9)      # live server values; flow_ahead has no key: an acting ear always has it; portion_adapt: the code default


def test_the_next_portion_is_sent_with_the_end_of_the_repeat_once_the_pace_is_known(call):
    rig = call(**profile())
    rig.asks('u1', 'Расскажи про кипение воды', 0, ANSWER)
    plan = rig.said()
    assert plan == ['Вода закипает в обычной кастрюле на плите'], 'precondition: the first portion is cued'
    for i in range(3):                      # the first repeat times the speaker; the next two are repeated at his pace
        ended = repeat(rig, rig.said()[-1])
        cue = rig.cues()[i + 1]
        assert len(rig.said()) == i + 2, 'the next portion is cued exactly once: the later finals do not advance again'
        if i:
            assert cue.t - ended <= 0.15, f'portion {i + 1}: cued {cue.t - ended:.2f} s after the last word of the repeat'
    assert 'потому что давление воздуха ниже.' == rig.said()[-1]


def test_after_asked_again_the_later_portions_are_shorter(call):
    def later_portions(stumbles):
        rig = call(**profile())
        rig.asks('u1', 'Расскажи про кипение воды', 0, ANSWER)
        for i in range(5):
            for k in range(2 if stumbles and i < 2 else 0):         # «повтори»: the listener could not take the portion
                rig.w.feed(S.turn_created(f's{i}{k}', 'user', 'повтори'))
                rig.w.feed(S.turn_done(f's{i}{k}', 'user', 'повтори ещё раз'))
                rig.pump(1.0)
            repeat(rig, rig.said()[-1])
        return [len(text.split()) for text in rig.said()[-3:]]       # the portions that were still unsaid at the stumbles
    smooth, stumbled = later_portions(False), later_portions(True)
    assert sum(stumbled) < sum(smooth), f'words per later portion: smooth {smooth}, after «повтори» {stumbled}'

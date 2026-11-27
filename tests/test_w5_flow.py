"""w5-flow: the next portion on time (flow_ahead.py), and the length of the rest following the speaker.

Pure: time is injected, nothing sleeps, no sound. The last test drives the REAL ControlledMedia and is xfail(strict) until the integration
patch of the report (``cloud_context/reports/w5-flow.md``) is applied by the owner of controlled_media.py: then it must pass.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))

from echo_sync import flow_ahead as F
from echo_sync.flow_ahead import FlowAhead, progress
from echo_sync.settings import resolve
from echo_sync.textutil import syllables


# ------------------------------------------------------------------------------------------------ the setting
def test_flow_ahead_is_off_by_default_and_only_on_turns_it_on():
    assert resolve({})['flow_ahead'] == 'off'
    assert resolve({'flow_ahead': 'on', 'local_ear': 'act'})['flow_ahead'] == 'on'
    assert resolve({'flow_ahead': 'on'})['flow_ahead'] == 'off', 'without an acting ear nothing gives the text so far: the one rule of resolve'
    assert resolve({'flow_ahead': 'yes'})['flow_ahead'] == 'off'


# ------------------------------------------------------------------------------------------------ alignment of the repeat so far
def test_progress_counts_the_words_said_in_order():
    p = progress('земельный налог платят', 'Земельный налог платят владельцы участков,')
    assert (p.said, p.total, p.clean, p.deviates) == (3, 5, True, False)


def test_progress_takes_another_case_of_a_word_and_a_filler_before_the_start():
    p = progress('ну земельного налога', 'Земельный налог платят')
    assert p.said == 2 and p.clean


def test_progress_sees_another_word_a_hesitation_and_a_restart():
    assert progress('земельный сбор', 'Земельный налог платят').deviates
    h = progress('земельный э налог', 'Земельный налог платят')
    assert h.hesitated and not h.clean
    r = progress('земельный налог земельный', 'Земельный налог платят')
    assert r.restarted and r.said == 1 and not r.clean


def test_a_number_or_ne_at_the_end_is_protected_and_a_growing_number_is_not_wrong():
    assert progress('', 'Закон был принят в 1945.').last_protected
    assert progress('', 'ставка не выше полутора процентов').last_protected      # «процент» is a unit after the number
    assert progress('', 'и это не').last_protected
    assert not progress('', 'платят владельцы участков').last_protected
    g = progress('закон был принят в тысяча девятьсот', 'Закон был принят в 1945.')
    assert g.said == 4 and not g.deviates, 'a number on its way is not yet said, and not wrong'
    w = progress('закон был принят в тысяча девятьсот сорок шестом году', 'Закон был принят в 1945 году.')
    assert w.deviates, 'another number before more words is wrong'


# ------------------------------------------------------------------------------------------------ the release ahead
PLAN = ['Земельный налог платят владельцы участков,', 'а ставку устанавливает муниципалитет,',
        'но не выше полутора процентов.', 'Налог на имущество считают от кадастровой стоимости,']
SPS = 0.22          # the speaker: seconds per syllable as the ear shows the words


def say(flow, portion, start, sps=SPS, upto=None, ear=F.EAR_SEEN_S, tick=0.02, extra=None):
    """The speaker says ``portion`` (words ``[:upto]``) from ``start``; the ear shows each word ``ear`` after its end. Returns
    (decisions with their times, the end of the last word said). ``extra``: a word said instead of the next one."""
    words = portion.replace(',', '').replace('.', '').split()[:upto]
    if extra:
        words = words + [extra]
    t, ends = start, []
    for w in words:
        t += max(1, syllables(w)) * sps
        ends.append(t)
    out, now, shown = [], start, 0
    while now < (ends[-1] if ends else start) + 3.0:
        while shown < len(words) and ends[shown] + ear <= now:
            shown += 1
            flow.heard(' '.join(words[:shown]), now)
        d = flow.decide(now)
        out.append((now, d))
        if d.action in ('release', 'withdraw') and (d.at is None or d.at <= now):
            break
        now = round(now + tick, 6)
    return out, (ends[-1] if ends else start)


def warmed(duplex='full'):
    """A flow whose speaker has been timed on one portion already (the tempo is known)."""
    flow = FlowAhead(duplex=duplex)
    warm = 'Местные налоги платят владельцы домов и арендаторы земли'
    flow.cue(warm, 'x', 0.0)
    say(flow, warm, 0.5)
    assert flow.tempo.known
    return flow


def first(out, action):
    """The first decision of ``action`` that acts now (a release: the moment it is SENT, not when it was scheduled)."""
    return next(((t, d) for t, d in out if d.action == action and (d.at is None or d.at <= t + 1e-9)), (None, None))


def test_the_synthesis_of_the_next_portion_is_prepared_at_the_cue():
    flow = warmed()
    flow.cue(PLAN[0], PLAN[1], 10.0)
    assert flow.decide(10.0).action == 'prepare'
    assert flow.decide(10.1).action == 'wait'


def test_the_next_portion_is_heard_100_to_300_ms_after_the_last_word():
    flow = warmed()
    flow.cue(PLAN[0], PLAN[1], 10.0)
    out, end = say(flow, PLAN[0], 10.5)
    t, d = first(out, 'release')
    assert d is not None and d.at <= t + 1e-9
    heard = t + F.DOWN_S + F.PLAY_S
    lo, hi = F.FLOW_TARGET_S
    assert end + lo - 0.05 <= heard <= end + hi, (end, heard)


def test_half_duplex_never_closes_the_microphone_before_the_last_word_is_sent():
    flow = warmed('half')
    flow.cue(PLAN[0], PLAN[1], 10.0)
    out, end = say(flow, PLAN[0], 10.5)
    t, d = first(out, 'release')
    assert t + F.DOWN_S >= end + F.MIC_PACKET_S - 1e-9, 'the gate closes on the first event of the cue: the last packet must be out'


def test_nothing_ahead_before_the_tempo_is_known():
    flow = FlowAhead(duplex='full')
    flow.cue(PLAN[0], PLAN[1], 10.0)
    out, _ = say(flow, PLAN[0], 10.5, upto=4)
    assert first(out, 'release')[1] is None and any(d.reason == 'tempo_unknown' for _, d in out)


@pytest.mark.parametrize('portion', ['но не выше полутора процентов.', 'Закон был принят в 1945.', 'и это не'])
def test_nothing_ahead_when_the_last_word_is_a_number_a_unit_or_ne(portion):
    flow = warmed()
    flow.cue(portion, 'дальше', 10.0)
    out, _ = say(flow, portion, 10.5)
    assert first(out, 'release')[1] is None
    assert any(d.reason == 'number_at_the_end' for _, d in out)


def test_nothing_ahead_on_the_last_portion_of_an_answer():
    flow = warmed()
    flow.cue(PLAN[0], None, 10.0)
    out, _ = say(flow, PLAN[0], 10.5)
    assert {d.action for _, d in out} == {'off'}


def test_another_word_withdraws_before_anything_was_sent():
    flow = warmed('half')
    flow.cue(PLAN[0], PLAN[1], 10.0)
    out, _ = say(flow, PLAN[0], 10.5, upto=4, extra='дома', sps=0.4)    # slower than the tempo: the release waits; then a wrong word
    assert any(d.reason in ('slowing', 'deviates') for _, d in out), 'a speaker slower than his own tempo is not guessed ahead'
    assert not any(d.action == 'release' and d.at <= t for t, d in out), 'nothing was sent'


def test_the_last_word_never_said_withdraws_the_sent_portion():
    flow = warmed()
    flow.cue(PLAN[0], PLAN[1], 10.0)
    out, _ = say(flow, PLAN[0], 10.5, upto=4)          # stops before «участков»
    t, d = first(out, 'release')
    assert d is not None, 'released on the tempo'
    now, got = t, None
    while now < t + 3:
        now += 0.05
        got = flow.decide(now)
        if got.action == 'withdraw':
            break
    assert got.action == 'withdraw' and got.reason == 'last_word_not_heard:sent'


def test_a_wrong_last_word_after_the_release_withdraws_it():
    flow = warmed()
    flow.cue(PLAN[0], PLAN[1], 10.0)
    out, _ = say(flow, PLAN[0], 10.5, upto=4)
    t, d = first(out, 'release')
    flow.heard('земельный налог платят владельцы домов', t + 0.3)
    assert flow.decide(t + 0.31).reason == 'changed_after_release:sent'


def test_a_long_pause_in_the_middle_is_a_stumble_not_a_release():
    flow = warmed()
    flow.cue(PLAN[0], PLAN[1], 10.0)
    flow.decide(10.0)
    flow.heard('земельный налог', 11.5)
    assert flow.decide(13.0).reason == 'pause'


# ------------------------------------------------------------------------------------------------ the simulation
def test_the_simulation_cuts_the_silence_of_a_20_portion_answer_and_keeps_false_releases_rare():
    import flow_sim
    rows = flow_sim.run(seeds=60)
    for tempo in ('slow', 'mid', 'fast'):
        before, after = rows[tempo]['now'], rows[tempo]['flow']
        assert after['silence_med'] < before['silence_med'] * 0.6, (tempo, before, after)
        assert after['false_sent_rate'] <= 0.03 and after['overlap_rate'] <= 0.02, (tempo, after)
        assert after['silence_med'] < rows[tempo]['ear']['silence_med'], 'the release ahead adds to what the acting ear gives alone'


# ------------------------------------------------------------------------------------------------ the real controller
def test_real_controller_sends_the_next_portion_before_the_repeat_ends(tmp_path):
    from test_stable_partial_ack import ANSWER, Speaker, dictation, speaks
    # plan: «Вода закипает в обычной кастрюле на плите,» | «при ста градусах Цельсия.» | «При ста градусах вода кипит.» | «В горах …»
    d = dictation(tmp_path, ANSWER, 2, settings={'preset': 'meaning', 'ack_match': 'ru_aligned', 'on_mismatch': 'silent',
                                                  'local_ear': 'act', 'flow_ahead': 'on'})
    portion = d.current
    assert portion == 'При ста градусах вода кипит.', 'precondition'
    d.controller.flow.tempo.per_syllable = [SPS] * 8          # the speaker was timed on the portions before (the patch keeps ``flow``)
    words = portion.rstrip('.').split()
    d.controller.ear_onset(1)
    cloud = Speaker(d).start()                             # the cloud hears the speech begin too; its final comes long after
    spoken = []
    for k in range(1, len(words)):
        d.clock.advance(max(1, syllables(words[k - 1])) * SPS)
        spoken += speaks(d.controller.ear_progress({'uid': 1, 'text': ' '.join(words[:k]).lower()}))
        spoken += speaks(d.controller.tick(now=d.clock()))
    for _ in range(5):
        d.clock.advance(0.1)
        spoken += speaks(d.controller.tick(now=d.clock()))
    assert spoken == [d.chunks[3]] and d.index == 3, 'the next portion goes before the ear heard the end of the utterance'
    assert cloud.final(portion) == [] and d.index == 3, 'the cloud\'s final of the same repeat never advances a second time'

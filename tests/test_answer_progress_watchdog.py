"""WAVE 2 / Task E, ruling 1 (fix round on d4c15e9): the answer watchdog is PROGRESS-based, and the lookup route has a budget of its own.

What the independent review found (both reviewers, journal wf_6ab05fe8): the 8 s of ``ANSWER_WAIT_SECONDS`` were derived from the
MODEL route (p95 3.78 s final -> first cue) but counted, for a question that needs the public lookup, from ``delivery_sent``, which
the wire calls as soon as the context frames are only QUEUED (native_media_socket.py, ``actions('context')``; the helper then
appends them for another 2.5-3.1 s), up to the first CUE, not up to the first sign of life of the cloud. Since stalling openers are
no longer cues (Task C), a healthy lookup answer streams for 5.6-8.1 s of text before its first cue is formed. The watchdog gave
the question up while the answer was arriving; the late answer then failed the owner check and was never dictated, and the listener
heard «Нет ответа. Повторите вопрос.» over a working call. The base dictated all of these answers.

Rulings (coordinator): (a) any activity of an assistant turn owned by the current question restarts the count; (b) the lookup route
has its own budget, a named constant, at least twice the lookup p95 after the real delivery (20 s); (c) the budget counts from the
REAL delivery, not from queueing; (d) a truly silent cloud is still reported within the budget; and (the only thing added to the
ruling) (e) an absolute cap, because a count that any activity restarts would otherwise be put off for ever by a cloud that only
keeps producing text that never becomes a cue.

The first half replays real lookup timelines (the cloud's event times in 03_TESTS probe reports, extracted by the review's
``replay_lookup.py``) through the production ``ControlledMedia`` on an injected clock. Nothing here sleeps.
"""
import re

import pytest

import helpers_s6_fault as F
from echo_sync import controlled_media
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, ControlledMedia
from helpers_spoken_diagnostics import ANSWER, phrases_heard, run_wire
from test_answer_watchdog import Call, reports

ACK = {'type': 'delegation.context.appended', 'item': {'id': 'd1'}}
LOOKUP_ROWS = [{'url': 'https://www.consultant.ru/document/cons_doc_LAW_5142/',
                'text': 'Статья 218. Основания приобретения права собственности. 1. Право собственности на новую вещь, изготовленную '
                        'или созданную лицом для себя с соблюдением закона и иных правовых актов, приобретается этим лицом.'}]


def rows_for(question):
    """The lookup rows of the timeline's own article (E3c, amendment R2a: a row about article 218 is no grounding for a question about
    article 421 - the same stems with another number)."""
    article = re.search(r'статья (\d+)', question).group(1)
    return [{**row, 'text': row['text'].replace('Статья 218.', f'Статья {article}.')} for row in LOOKUP_ROWS]


# ======================================================================================================
# 1. real lookup timelines (cloud event times of the recorded probe reports, milliseconds on the probe's clock)
# ======================================================================================================

Q218 = 'Что устанавливает статья 218 Гражданского кодекса Российской Федерации'
Q218B = 'Что устанавливает статья 218-я Гражданского кодекса Российской Федерации'
Q421 = 'Что устанавливает статья 421 Гражданского кодекса Российской Федерации'

# native_controlled_socket.json, previous_attempts main.prev48 (build f84efc4b)
PREV48 = dict(question=Q218, user_created=7000, delegation=14237, final=14993, lookup_end=16889, delivered=16922, acks=[], end=40000,
              assistant=[(15358, 'created', 'Сейчас '), (15375, 'delta', 'уточню'), (15402, 'delta', ' по'), (15487, 'delta', ' источ'),
                         (16343, 'delta', 'никам'), (20144, 'delta', '.'), (20310, 'delta', ' Статья'), (20409, 'delta', ' 218'),
                         (20503, 'delta', ' ГК'), (20531, 'delta', ' РФ'), (22304, 'delta', ' устанавливает'),
                         (23071, 'delta', ' основания'), (23876, 'delta', ' приобретения'), (24672, 'delta', ' права'),
                         (25058, 'delta', ' собственности'), (25883, 'delta', '.'), (26242, 'delta', ' Например,'),
                         (26704, 'delta', ' право'), (27127, 'delta', ' собственности'), (27702, 'delta', ' на'),
                         (27901, 'delta', ' вновь'), (28143, 'delta', ' созданную'), (28683, 'delta', ' вещь'),
                         (30011, 'delta', ' возникает.'), (30100, 'done', None)])
# ... main.prev41
PREV41 = dict(question=Q218B, user_created=6497, delegation=13292, final=13902, lookup_end=14661, delivered=14692, acks=[], end=36000,
              assistant=[(13933, 'created', 'Сейчас '), (13950, 'delta', 'уточню'), (14380, 'delta', ' по'),
                         (14604, 'delta', ' источникам'), (16432, 'delta', '.'), (16926, 'delta', ' Статья'), (17768, 'delta', ' 218'),
                         (19301, 'delta', ' ГК РФ'), (20011, 'delta', ' устанавливает'), (20529, 'delta', ' основания'),
                         (21733, 'delta', ' приобретения'), (22162, 'delta', ' права'), (22398, 'delta', ' собственности'),
                         (23413, 'delta', ':'), (23444, 'delta', ' например,'), (23854, 'delta', ' создание'),
                         (24453, 'delta', ' вещи'), (27614, 'delta', ' для себя.'), (27700, 'done', None)])
# ... main.prev37
PREV37 = dict(question=Q218B, user_created=7069, delegation=12646, final=13296, lookup_end=14357, delivered=14373, acks=[], end=36000,
              assistant=[(13315, 'created', 'Сейчас уточню '), (13491, 'delta', 'по'), (13679, 'delta', ' источникам'),
                         (16191, 'delta', '.'), (16902, 'delta', ' Статья'), (16926, 'delta', ' 218'), (17497, 'delta', ' ГК'),
                         (17997, 'delta', ' РФ'), (18532, 'delta', ' устанавливает'), (19301, 'delta', ' основания'),
                         (19884, 'delta', ' приобретения'), (20483, 'delta', ' права'), (20849, 'delta', ' собственности'),
                         (21514, 'delta', '.'), (21664, 'delta', ' Там'), (23887, 'delta', ' перечислено,'), (24486, 'delta', ' что'),
                         (24686, 'delta', ' право'), (26800, 'done', None)])
# corpus_v1/runs/20261102-000520/lookup_law_article.json (build of 01.11 23:54): with the 26 acknowledgements of the appended frames
CORPUS421 = dict(question=Q421, user_created=9991, delegation=15987, final=16553, lookup_end=17651, delivered=17671, end=40000,
                 acks=[17768, 17838, 17930, 18000, 18058, 18128, 18316, 18398, 18498, 18605, 18700, 18790, 18882, 19027, 19122,
                       19261, 19346, 19439, 19544, 19628, 19730, 19837, 19932, 20034, 20099, 20237],
                 assistant=[(16558, 'created', 'Понял,'), (16561, 'delta', ' сейчас быстро'), (16929, 'delta', ' проверю'),
                            (17349, 'delta', ' и'), (17550, 'delta', ' скажу.'), (20507, 'delta', ' Статья'), (20538, 'delta', ' 421'),
                            (20543, 'delta', ' ГК'), (20552, 'delta', ' РФ'), (20640, 'delta', ' устанавливает'),
                            (22020, 'delta', ' принцип'), (22725, 'delta', ' свободы'), (23282, 'delta', ' договора:'),
                            (24410, 'delta', ' граждане'), (24413, 'done', None)])
TIMELINES = {'prev48': PREV48, 'prev41': PREV41, 'prev37': PREV37, 'corpus421': CORPUS421}


def replay(tmp_path, line, shift_ms=0):
    """The production controller (the keywords controlled_host.serve passes) fed with the cloud's events at their recorded times,
    ticked every 0.1 s like the host. ``shift_ms`` delays every assistant event after the delivery (a bigger source set that is
    appended more slowly). Returns ``(controller, [(seconds, action)])``."""
    now = [line['user_created'] / 1000]
    controller = ControlledMedia(tmp_path / 'replay.sqlite3', session_id='replay', clock=lambda: now[0], **F.HOST_KWARGS)
    words = line['question'].split()
    events = [(line['user_created'], 'u_created'), (line['delegation'], 'deleg'), (line['final'], 'u_done'),
              (line['lookup_end'], 'ground'), (line['delivered'], 'deliver')]
    events += [(t, 'ack') for t in line['acks']]
    for t, kind, text in line['assistant']:
        events.append((t + (shift_ms if t > line['delivered'] else 0), 'a_' + kind, text))
    events.sort(key=lambda row: row[0])
    out, pending, lookup, said, n, i, tick = [], None, None, '', 0, 0, line['user_created']

    def note(t, actions):
        out.extend((round(t / 1000, 3), a) for a in actions)

    while tick <= line['end'] + shift_ms:
        while i < len(events) and events[i][0] <= tick:
            t, kind = events[i][0], events[i][1]
            text = events[i][2] if len(events[i]) > 2 else None
            now[0] = t / 1000
            if kind == 'u_created':
                note(t, controller.provider(F.created('u1', 'user', ' '.join(words[:3]))))
            elif kind == 'deleg':
                controller.provider(F.delta('u1', ' ' + ' '.join(words[3:]), 1))
                acts = controller.provider(F.delegation('d1', 'u1'))
                note(t, acts)
                lookup = [a for a in acts if a['type'] == 'lookup']
            elif kind == 'u_done':
                note(t, controller.provider(F.done('u1', 'user', line['question'])))
            elif kind == 'ground':
                F.precondition(lookup, 'the delegation made the controller ask for a lookup')
                pending = controller.grounding(lookup[0]['epoch'], rows_for(line['question']))
                F.precondition(pending, 'the sources were grounded and a context is to be sent')
                note(t, pending)
            elif kind == 'deliver':
                F.precondition(controller.delivery_sent(pending[0]['epoch'], pending[0]['delegation_id']), 'the context reached the model')
            elif kind == 'ack':
                note(t, controller.provider(ACK))
            elif kind == 'a_created':
                said = text
                note(t, controller.provider(F.created('a1', 'assistant', text)))
            elif kind == 'a_delta':
                n += 1
                said += text
                note(t, controller.provider(F.delta('a1', text, n)))
            elif kind == 'a_done':
                note(t, controller.provider(F.done('a1', 'assistant', said)))
            i += 1
        now[0] = tick / 1000
        note(tick, controller.tick(now=now[0]))
        tick += 100
    return controller, out


@pytest.mark.parametrize('shift_ms', [0, 2500], ids=['as_recorded', 'sources_appended_2.5s_slower'])
@pytest.mark.parametrize('name', sorted(TIMELINES))
def test_a_real_lookup_answer_is_dictated_not_abandoned(tmp_path, name, shift_ms):
    """Review: with the recorded timing 2 of 4 runs are only 0.3-1.5 s from the 8 s limit, and with the sources appended 2.5 s slower
    all 4 are abandoned while the answer is streaming. Every one of them must reach the listener."""
    controller, out = replay(tmp_path, TIMELINES[name], shift_ms)
    assert [a for _, a in out if a['type'] == 'unanswered'] == [], 'a healthy answer was given up: ' + str(
        [(t, a) for t, a in out if a['type'] == 'unanswered'])
    cues = [(t, a['text']) for t, a in out if a['type'] == 'speak']
    assert cues, 'no cue: the answer never reached the listener'
    assert controller.published, 'and nothing of the answer was kept'


# ======================================================================================================
# 2. the controller on an injected clock: a lookup question, a slow but healthy cloud, a silent cloud
# ======================================================================================================

def deliver_lookup(call, acks=0, ack_gap=0.1):
    """A question that needs the public lookup, whose sources reach the model (queued; then ``acks`` acknowledgements, ``ack_gap`` apart)."""
    call.ask(F.LOOKUP_QUESTION)
    F.precondition(call.controller.direct_content is False, 'this question needs the lookup')
    call.run(1.5)
    epoch = call.controller.epoch
    call.controller.grounding(epoch, F.sources_for(F.LOOKUP_QUESTION))
    F.precondition(call.controller.delivery_sent(epoch, None), 'the context reached the model')
    delivered = call.clock.now
    for _ in range(acks):
        call.clock.now += ack_gap
        call.controller.provider(ACK)
    return delivered


@pytest.mark.parametrize('after', [10.0, 12.0, 15.0])
def test_a_healthy_lookup_answer_that_arrives_10_to_15_s_after_the_delivery_is_spoken(tmp_path, after):
    call = Call(tmp_path)
    deliver_lookup(call)
    assert reports(call.run(after)) == [], 'the cloud was still working and was given up'
    out = call.cloud(F.LOOKUP_ANSWER)
    assert [a for a in out if a['type'] == 'speak'], 'the answer arrived and was not spoken'
    assert reports(call.run(60)) == []


def test_a_silent_cloud_on_the_lookup_route_is_still_reported_within_its_own_budget(tmp_path):
    budget = controlled_media.LOOKUP_ANSWER_WAIT_SECONDS
    call = Call(tmp_path)
    deliver_lookup(call)
    assert reports(call.run(budget - 0.5)) == [], 'reported before the budget was over'
    found = reports(call.run(3.0))
    assert len(found) == 1, found
    assert found[0][1]['reason'] == 'no_assistant_turn'
    assert 0.4 <= found[0][0] <= 1.5, f'reported {budget - 0.5 + found[0][0] - 0.0:.1f} s after the delivery, the budget is {budget}'


def test_the_lookup_budget_is_twice_the_slowest_healthy_wait_after_the_delivery():
    """05_WORK/scripts/LATENCY_BASELINE.md, lookup route: end of the question -> first PCM p95 12.6 s (old builds, N=15); the sources are
    delivered 1.5-3.5 s after the end of the question, so the slowest healthy wait after the delivery is about 10 s. The ruling: at least
    twice that (20 s unless the data say otherwise), and a healthy answer at 10-15 s must be spoken."""
    assert controlled_media.LOOKUP_ANSWER_WAIT_SECONDS >= 2 * 10.0
    assert controlled_media.LOOKUP_ANSWER_WAIT_SECONDS > ANSWER_WAIT_SECONDS, 'the model route keeps its own, tighter budget'


def test_activity_of_the_cloud_restarts_the_count(tmp_path):
    """The model route: a cloud that keeps producing text which gives no cue (the review's lookup replays, in miniature) is alive."""
    call = Call(tmp_path)
    call.ask()
    c = call.controller
    c.provider(F.created('a1', 'assistant', 'Сейчас'))
    found = []
    for n in range(1, 5):                                          # 20 s: an event every 5 s, never a pause as long as the budget
        found += reports(call.run(5.0))
        c.provider(F.delta('a1', ' уточню' if n % 2 else ' по источникам.', n))
    assert found == [], 'a cloud that is producing text was given up at the first deadline'


def test_the_end_of_a_turn_that_gave_no_cue_is_a_sign_of_life_too(tmp_path):
    """The cloud said «Сейчас уточню.» and finished its turn at 5 s: the silence that counts starts there."""
    call = Call(tmp_path)
    call.ask()
    c = call.controller
    c.provider(F.created('a1', 'assistant', 'Сейчас'))
    call.run(5.0)
    c.provider(F.done('a1', 'assistant', 'Сейчас уточню.'))
    assert reports(call.run(ANSWER_WAIT_SECONDS - 0.5)) == [], 'counted from the start of the turn, not from its end'
    found = reports(call.run(1.5))
    assert len(found) == 1 and found[0][1]['reason'] == 'no_usable_text'


def test_a_streaming_answer_of_an_earlier_question_is_no_sign_of_life_for_the_next_one(tmp_path):
    """Only the assistant turns the CURRENT question owns count: the cloud going on about the first question says nothing about the second."""
    call = Call(tmp_path)
    call.ask(F.DIRECT_QUESTION, 'u1')
    c = call.controller
    c.provider(F.created('a1', 'assistant', 'Сейчас'))
    call.run(1.0)
    call.ask(F.OTHER_DIRECT_QUESTION, 'u2')
    epoch = c.epoch
    found = []
    for n in range(1, 4):                                          # a1 goes on every 3 s; the second question gets nothing
        c.provider(F.delta('a1', ' ещё', n))
        found += reports(call.run(3.0))
    assert [a['epoch'] for _, a in found] == [epoch], "the second question was kept waiting by the answer to the first"


def test_but_activity_that_never_becomes_a_cue_is_reported_at_the_absolute_cap(tmp_path):
    cap = controlled_media.ANSWER_CAP_SECONDS
    assert cap > ANSWER_WAIT_SECONDS
    call = Call(tmp_path)
    call.ask()
    c = call.controller
    start = call.clock.now
    c.provider(F.created('a1', 'assistant', 'Сейчас'))
    found, n = [], 0
    while not found and call.clock.now - start < cap + 10:        # an event every 5 s, for ever
        n += 1
        c.provider(F.delta('a1', ' уточню.' if n % 2 else ' секунду.', n))
        base = call.clock.now - start
        found = [(base + t, a) for t, a in reports(call.run(5.0))]
    assert len(found) == 1, 'a cloud that only dribbles chatter was never reported'
    assert cap <= found[0][0] <= cap + 0.5, f'reported {found[0][0]:.1f} s after the question, the cap is {cap}'
    assert found[0][1]['reason'] == 'no_usable_text'


def test_the_count_starts_at_the_real_delivery_not_at_queueing(tmp_path):
    """The wire calls ``delivery_sent`` as soon as the frames are queued; the helper then appends them for 2.5-3.1 s and acknowledges
    every one (``delegation.context.appended``). The cloud cannot answer before the last one: the count starts there."""
    budget = controlled_media.LOOKUP_ANSWER_WAIT_SECONDS
    call = Call(tmp_path)
    deliver_lookup(call, acks=26, ack_gap=0.1)                     # 2.6 s of acknowledgements, like the recorded run
    last_ack = call.clock.now
    assert reports(call.run(budget - 0.5)) == [], 'counted from queueing: the acknowledgements were not taken into account'
    found = reports(call.run(2.0))
    assert len(found) == 1 and found[0][1]['reason'] == 'no_assistant_turn'
    assert budget - 0.5 <= call.clock.now - last_ack <= budget + 2.0


def test_acknowledgements_of_an_old_delivery_do_not_prolong_the_wait_of_the_next_question(tmp_path):
    """The helper's acknowledgements keep arriving for a moment after the listener has moved on to a model-route question: they belong to the old
    delivery and do not move the new question's 8 s (the acknowledgement is only the start of a LOOKUP question's budget)."""
    call = Call(tmp_path)
    deliver_lookup(call, acks=3)
    call.ask(F.DIRECT_QUESTION, 'u2')                              # a new question: nothing delivered for it
    call.run(2.0)
    call.controller.provider(ACK)                                  # a late acknowledgement of the first delivery, 2 s into the second question
    assert reports(call.run(ANSWER_WAIT_SECONDS - 2.0 - 0.5)) == []
    assert len(reports(call.run(1.5))) == 1, 'the late acknowledgement put off a question that has no delivery (the report is due 8 s after its final)'


def test_a_zero_wait_switches_the_watchdog_off_on_the_lookup_route_too(tmp_path):
    call = Call(tmp_path, answer_wait_seconds=0)
    deliver_lookup(call)
    assert reports(call.run(120)) == []


def test_each_budget_is_a_keyword_of_the_controller(tmp_path):
    call = Call(tmp_path, lookup_answer_wait_seconds=3.0, answer_cap_seconds=5.0)
    deliver_lookup(call)
    assert len(reports(call.run(4.0))) == 1, 'the lookup budget keyword is not honoured'


# ======================================================================================================
# 3. through the wire (virtual time): what the phone receives
# ======================================================================================================

def test_a_healthy_lookup_answer_12_s_after_the_delivery_reaches_the_phone_and_no_phrase_is_spoken(tmp_path, monkeypatch):
    async def body(rig):
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(0.5)                                     # the lookup works; the context is queued for the helper
        F.precondition({k for k, _ in rig.source.frames} == {'E'}, 'the context reached the helper')
        t_delivered = rig.now()
        await rig.advance(12.0)
        assert not rig.errors() and phrases_heard(rig.frames) == [], 'the question was given up while the cloud was working: ' + str(rig.timeline())
        await rig.answer(F.LOOKUP_ANSWER)
        await rig.advance(8.0)
        assert phrases_heard(rig.frames) == [] and not rig.errors(), rig.timeline()
        spoken = rig.spoken(t_delivered)
        assert spoken and spoken[0] in F.LOOKUP_ANSWER, spoken
    run_wire(tmp_path, monkeypatch, body)


def test_a_silent_cloud_after_a_lookup_is_still_announced_through_the_wire(tmp_path, monkeypatch):
    budget = controlled_media.LOOKUP_ANSWER_WAIT_SECONDS

    async def body(rig):
        t0 = rig.now()                                             # the question is final and the lookup answers at once (virtual time)
        await rig.ask(F.LOOKUP_QUESTION)
        await rig.advance(budget - 1.0)
        assert not rig.errors(), 'announced before the budget was over'
        await rig.advance(8.0)
        assert phrases_heard(rig.frames) == [ANSWER] and rig.errors() == ['controlled_answer_timeout'], rig.timeline()
        assert budget - 0.2 <= [r for r in rig.frames if r.type == 'error'][0].t - t0 <= budget + 1.0
    run_wire(tmp_path, monkeypatch, body)


# ======================================================================================================
# 4. WAVE 2 / Task E2, ruling 4 (scoped re-review P3): the absolute cap is checked before the controller's own windows
# ======================================================================================================
# The cap says «whatever the cloud does, a question that has produced no cue is given up this long after its start». The watchdog returned
# before reaching it while the controller held a window of its own, and the window that never closes by itself is the idle wait of a
# CONTINUATION segment (a finished stall turn, then a second assistant turn that streams text which gives no cue): ``SEGMENT_IDLE_SECONDS``
# (15 s) counts from the segment's last event, so a keep-alive less than 15 s apart put the end of the answer off for ever and the call stayed
# silent for good. (rr2_keepalive2.py K2b, K2c, K6b: no report in 120 s on bf76690 and on d4c15e9.)

def stall_then_continuation(call, every, *, first='Сейчас посмотрю.', keep=' …'):
    """The cloud finishes a stall turn (no cue), then streams ``keep`` every ``every`` seconds in a second turn that continues the answer. Yields the
    seconds since the question's final at which each report arrived, for as long as the caller keeps iterating."""
    c = call.controller
    start = call.clock.now
    c.provider(F.created('a1', 'assistant', first))
    c.provider(F.done('a1', 'assistant', first))
    call.run(1.0)
    c.provider(F.created('a2', 'assistant', '…'))
    n = 0
    while True:
        n += 1
        before = call.clock.now
        for t, action in reports(call.run(every)):
            yield (before - start) + t, action
        c.provider(F.delta('a2', keep, n))
        yield None, None


@pytest.mark.parametrize('every', [2.0, 10.0], ids=['every_2_s', 'every_10_s'])
def test_keep_alives_in_a_continuation_segment_cannot_keep_the_call_silent_for_ever(tmp_path, every):
    cap = controlled_media.ANSWER_CAP_SECONDS
    call = Call(tmp_path)
    call.ask()
    start = call.clock.now
    found = []
    for when, action in stall_then_continuation(call, every):
        if action is not None:
            found.append((when, action))
        if found or call.clock.now - start > cap + 25:
            break
    assert len(found) == 1, 'a continuation segment that only produces keep-alives kept the question unanswered for ever'
    assert cap <= found[0][0] <= cap + every + 1.0, f'reported {found[0][0]:.1f} s after the question, the cap is {cap}'
    assert found[0][1]['reason'] == 'no_usable_text'
    assert call.controller.question_id is None and call.controller.unsettled is None and call.controller.held_source is None


def test_keep_alives_in_a_continuation_segment_of_a_lookup_answer_are_reported_at_the_cap_after_the_delivery(tmp_path):
    cap = controlled_media.ANSWER_CAP_SECONDS
    call = Call(tmp_path)
    delivered = deliver_lookup(call)                               # the clock stands at the delivery: ``when`` below counts from there
    found = []
    for when, action in stall_then_continuation(call, 2.0, first='Сейчас проверю.'):
        if action is not None:
            found.append((when, action))
        if found or call.clock.now - delivered > cap + 25:
            break
    assert len(found) == 1, 'the lookup route was kept silent by keep-alives in a continuation segment'
    assert cap <= found[0][0] <= cap + 4.0, f'reported {found[0][0]:.1f} s after the delivery, the cap is {cap}'


def test_a_continuation_segment_that_goes_quiet_is_still_flushed_by_its_own_idle_wait_before_the_cap(tmp_path):
    """The window the cap now overrides is still what ends an answer that really went quiet: a continuation with real words that stops
    15 s after its last event is the end of the answer (and is dictated), well before the cap."""
    call = Call(tmp_path)
    call.ask()
    c = call.controller
    c.provider(F.created('a1', 'assistant', 'Сейчас посмотрю.'))
    c.provider(F.done('a1', 'assistant', 'Сейчас посмотрю.'))
    call.run(1.0)
    c.provider(F.created('a2', 'assistant', 'Инерция — это свойство тела'))
    out = call.run(controlled_media.SEGMENT_IDLE_SECONDS + 3.0)
    assert [a for _, a in out if a['type'] == 'speak'], 'the idle wait of a continuation no longer ends the answer'
    assert reports(out) == []


def test_the_cap_is_still_off_with_a_zero_cap(tmp_path):
    call = Call(tmp_path, answer_cap_seconds=0)
    call.ask()
    found = []
    for when, action in stall_then_continuation(call, 2.0):
        if action is not None:
            found.append((when, action))
        if found or call.clock.now - 1000.0 > 90:
            break
    assert found == [], 'a zero cap switches the absolute cap off, as before'


def test_the_cap_ends_the_hold_for_a_possible_continuation_too(tmp_path):
    """The other windows of the controller's own yield to the cap as well (a small cap makes each of them observable): an answer held for a
    possible continuation of the question (3.2 s) is not waited for beyond the cap."""
    call = Call(tmp_path, answer_cap_seconds=2.0)
    call.ask('Что такое инерция в', 'u1')
    call.cloud(F.DIRECT_ANSWER)
    F.precondition(call.controller.held_source is not None, 'the answer is held back')
    out = call.run(5.0)
    assert len(reports(out)) == 1 and [a for _, a in out if a['type'] == 'speak'] == [], out


def test_the_cap_ends_the_grace_window_of_an_answer_that_may_be_cut_too(tmp_path):
    """…and so is the grace window (1.2 s) of an answer without terminal punctuation."""
    call = Call(tmp_path, answer_cap_seconds=0.5)
    call.ask('Как называется наука о насекомых', 'u1')
    call.cloud('Энтомология')
    F.precondition(call.controller.unsettled is not None, 'the lone word waits out the grace window')
    out = call.run(3.0)
    assert len(reports(out)) == 1 and [a for _, a in out if a['type'] == 'speak'] == [], out

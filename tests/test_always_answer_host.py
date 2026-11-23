"""The track «the system always answers», through the REAL host (controlled_host.serve) with only the boundaries faked (tests/helpers_always_answer.py).

Target behaviour of SPEC.md sections 1 and 5: the refusal or the stall of the first road (Codex) is never heard: the next road (Groq, Gemini) is asked by itself, at once after a refusal before the
first word and not later than N = 2 s of a silence; a phrase of the system is heard only when every road is dead, and not later than M = 8 s. These tests are written for that target: on the code
before the change part of the cells is red on purpose.

Groups: A the failure of the first road x the road that lives; B the same with a dead GPT-Live (at the opening and in the middle of the call); C every road dead; D the link comes back in the same
call; E the opening does not depend on the first road; F the third question of a call whose first road keeps silent; G the matrix goes red when the switching is broken (mutants).
A cell is K calls (seeds) of one scenario; the failure says how many were silent, how many heard a phrase, how many broke the expectation, and the worst time to the answer.
"""
import json
import os

import pytest

import helpers_always_answer as H
import helpers_s6_fault as F
from echo_sync import native_media_socket, reserve_text
from helpers_always_answer import GAP_S, MARKS, M, N, QUESTIONS, QUESTIONS_NO_MARK, SYNTH_TICK_S, Stand, blank, cut, empty, fail, hang, heard, late, ok, run_stand, text_of

K_HEAVY, K_LIGHT = 20, 5
HANG_LIVE_MAX_S = 1.2               # the live road asked at 3N = 6 s after two silent roads: its word must come by 7.2 s, before the refusal at 7.5 s (8 s - REFUSE_BEFORE_DROP_SECONDS)
OPEN_S = 6.0 + 0.2                  # the local opening: LOCAL_OPEN_GRACE_S and a tick
REPORT = []


@pytest.fixture(scope='module', autouse=True)
def _report():
    """With ALWAYS_ANSWER_REPORT=<path> the journal of the cells (what was heard, when) is written there when the module is done."""
    yield
    path = os.environ.get('ALWAYS_ANSWER_REPORT')
    if path:
        with open(path, 'w', encoding='utf-8') as out:
            json.dump(REPORT, out, ensure_ascii=False, indent=1)


def spread(seed, low, high, salt=0.0):
    """A number of [low, high] that moves with the seed in a fixed, even way (no two near seeds near each other)."""
    return low + (high - low) * (((seed + 1) * 0.6180339887 + salt) % 1.0)


# ---- the engine ----------------------------------------------------------------------------------------------------------------------------
class Result:
    """What the phone heard of ONE question: from its moment ``t_q`` until ``until`` (the next question). Times are seconds after ``t_q``."""

    def __init__(self, stand, host, t_q, text, *, t0=None, until=None):
        saw = heard(host, t0 if t0 is not None else t_q)

        def window(items):
            return [i for i in items if i['first'] >= t_q - 1e-9 and (until is None or i['first'] < until)]
        self.text, self.t_q = text, t_q
        self.service_all = [i for i in saw['service'] if until is None or i['first'] < until]
        self.answers, self.service, self.other = window(saw['answers']), window(saw['service']), window(saw['other'])
        self.calls = [(t, a) for t, a in stand.calls_since(t_q) if until is None or t + t_q < until]
        self.heard = text_of(sorted(self.answers + self.service, key=lambda i: i['first']))
        firsts = [i['first'] - t_q for i in self.answers + self.service]
        self.first_sound = min(firsts) if firsts else None
        self.first_answer = min([i['first'] - t_q for i in self.answers], default=None)
        self.first_phrase = min([i['first'] - t_q for i in self.service], default=None)
        self.order = []
        for at, alias in self.calls:
            if alias not in [a for a, _ in self.order]:
                self.order.append((alias, at))                # the roads in the order they were first asked, with the time
        self.plan = dict(stand.plan)

    def asked_at(self, alias):
        return next((at for a, at in self.order if a == alias), None)

    def codex_calls(self):
        return [t for t, alias in self.calls if alias == 'codex']


class Run:
    """One call of a cell: the results of its questions (``q``, the last is the one the summary speaks of) and what the opening took."""

    def __init__(self, cell, seed, q, **info):
        self.cell, self.seed, self.q, self.info, self.violations = cell, seed, q, info, []

    def __getattr__(self, name):
        if name in ('q', 'cell', 'seed', 'info', 'violations'):
            raise AttributeError(name)
        return getattr(self.q[-1], name)


class Cell:
    """A call of the matrix: the scenarios of the roads (``plan(seed)``), the state of GPT-Live (``mode``), the expectation (``judge``). ``run`` replaces the one-question call."""

    def __init__(self, name, plan, judge, *, mode='live', horizon=14.0, k=K_LIGHT, cloud=None, cloud_reply=None, default=None, run=None, loss=None, patches=(), profile=None):
        self.name, self.plan, self.judge, self.mode, self.horizon, self.k, self.profile = name, plan, judge, mode, horizon, k, profile or {}
        self.cloud = (mode in ('live', 'cloud_back')) if cloud is None else cloud
        self.cloud_reply, self.default, self.run, self.loss, self.patches = cloud_reply, default, run, loss, patches
        self.params = self.hanging = None


OPEN_MODES = ('no_offer', 'refused', 'start_fault', 'closed_before_ready', 'never_ready')
LOSSES = {'X frame': lambda bridge: bridge.push('X', b''), 'EOF': lambda bridge: bridge.inbox.put_nowait(None),
          'corrupt pipe': lambda bridge: bridge.inbox.put_nowait(ValueError('truncated helper payload'))}


def question_of(seed, n=0):
    return (QUESTIONS if seed % 2 == 0 else QUESTIONS_NO_MARK)[(seed // 2 + n) % len(QUESTIONS)]


async def open_call(host, cell):
    """The state of the helper the cell asks for, as the test of the cell finds it: (what the opening took, the host's own ``t0``)."""
    t0, info = host.now(), {}
    if cell.mode in OPEN_MODES:
        if cell.mode == 'start_fault':
            host.start_fault = OSError('helper is not there')
        info['updated'], info['ready'] = await H.open_local(host)
        await host.advance(1.0)
    elif cell.mode == 'lost':
        LOSSES[cell.loss](host.bridge)
        await host.advance(2.0)
    return t0, info


def play(tmp_path, cell, seed):
    """One call of the cell with the seed ``seed``: the question's wording, its moment against the tick, the lag of the cloud's final and the delay of the road that lives all follow the seed."""
    if cell.run is not None:
        return cell.run(tmp_path, cell, seed)
    stand = Stand(cell.plan(seed), default=cell.default, profile=cell.profile)
    text, pre, lag = question_of(seed), spread(seed, 0.0, 0.1, 0.31), spread(seed, 0.0, 0.5, 0.57)
    rig = {'handshake': cell.mode in ('live', 'lost')}
    if cell.mode in ('no_offer', 'refused', 'closed_before_ready', 'never_ready'):
        rig['setup'] = [cell.mode]

    async def body(host, stand):
        t0, info = await open_call(host, cell)
        t_q = await stand.ask(host, text, cloud=cell.cloud, lag=lag, pre=pre)
        if cell.cloud_reply is not None:
            await host.advance(cell.cloud_reply)
            await host.answer(H.cloud_answer(text)[0], tid='a1')
        await host.advance(cell.horizon)
        info['finished'] = host.finished
        info['updated_count'] = sum(1 for f in host.ws.frames if f.type == 'session.updated')
        info['errors'] = host.errors()
        return Run(cell, seed, [Result(stand, host, t_q, text, t0=t0)], **info)
    return run_stand(tmp_path, stand, body, patches=cell.patches, **rig)


def check_cell(tmp_path, cell, k=None, report=True):
    """K calls with K seeds; the summary of the cell is the message of the failure. Raises AssertionError when any call of the cell breaks its expectation."""
    __tracebackhide__ = True
    k = cell.k if k is None else k
    done = []
    for seed in range(k):
        run = play(tmp_path / f'{cell.name}-{seed}', cell, seed)
        run.violations = cell.judge(run)
        done.append(run)
    bad = [r for r in done if r.violations]
    silent = [r for r in done if r.first_sound is None]
    phrased = [r for r in done if r.service]
    worst = max([r.first_answer for r in done if r.first_answer is not None], default=None)
    sample = bad[0] if bad else done[0]
    (REPORT.append if report else lambda entry: None)({'cell': cell.name, 'heard': sample.heard, 'at_s': None if sample.first_sound is None else round(sample.first_sound, 2),
                   'next_road_at_s': round(sample.order[1][1], 2) if len(sample.order) > 1 else None, 'roads_asked': [a for a, _ in sample.order],
                   'silent_of_K': f'{len(silent)}/{k}', 'phrase_of_K': f'{len(phrased)}/{k}', 'broken_of_K': f'{len(bad)}/{k}',
                   'verdict': 'red' if bad else 'green', 'why': sample.violations[:3] if bad else []})
    if bad:
        summary = (f'cell {cell.name}: silent {len(silent)} of {k}, with a phrase of the system {len(phrased)} of {k}, broken {len(bad)} of {k}, worst time to the answer '
                   f'{"none" if worst is None else round(worst, 2)} s. ')
        shown = '; '.join(f'seed {r.seed}: ' + ' | '.join(r.violations) + f' (heard {r.heard[:70]!r}, roads {[(a, round(t, 2)) for a, t in r.order]})' for r in bad[:3])
        raise AssertionError(summary + shown)
    return done


# ---- the judges -------------------------------------------------------------------------------------------------------------------------------
def chain_gaps(result, hanging=()):
    """The roads in the order they were asked: each next one is asked at once after a refusal before the first word (GAP_S) and not later than N + GAP_S after a road that is silent."""
    out = []
    for (road, at), (nxt, then) in zip(result.order, result.order[1:]):
        bound = (2 * N + GAP_S if 'codex' in hanging and road != 'codex' else N + GAP_S) if road in hanging else GAP_S      # a reserve road silent beside a silent first road is let go at 2N of its own (the first road is never let go for it)
        if then - at > bound + 1e-9:
            out.append(f'{nxt} asked {then - at:.2f} s after {road} (more than {bound:.1f})')
    return out


def answered_by(road, delay, hanging=(), whole=False, opening=False):
    """The judge of the cells A and B: the answer of ``road`` is heard, no phrase of the system (``whole``: in the whole call), the chain of the roads is quick, the first sound is in time.
    ``opening``: the call opened by its local way in time and was ready."""
    def judge(run):
        result, found = run.q[-1], []
        if MARKS[road] not in text_of(result.answers):
            found.append(f'the answer of {road} was not heard')
        phrases = result.service_all if whole else result.service
        if phrases:
            found.append('phrase of the system: ' + text_of(phrases))
        if result.asked_at(road) is None:
            found.append(f'{road} was never asked (asked: {[a for a, _ in result.order]})')
        else:
            # A live road whose own delay reaches N is a silent road too: the next one is asked at N by SPEC (rule 4), not at once.
            slow = tuple(hanging) + tuple(name for name, plan in result.plan.items() if plan[0] == 'late' and plan[1] >= N)
            found += chain_gaps(result, slow)
            if result.first_answer is not None and result.first_answer > result.asked_at(road) + delay + SYNTH_TICK_S:
                found.append(f'first sound {result.first_answer:.2f} s, later than {result.asked_at(road):.2f} + {delay:.2f} + {SYNTH_TICK_S}')
        if opening:
            found += opened_in_time(run)
        return found
    return judge


def opened_in_time(run):
    updated, ready = run.info.get('updated'), run.info.get('ready')
    if 'updated' not in run.info:
        return []
    found = []
    if updated is None or updated > OPEN_S:
        found.append(f'session.updated {"never" if updated is None else format(updated, ".2f") + " s"} after session.update (more than {OPEN_S})')
    if not ready:
        found.append('no readiness marker')
    return found


# ---- A. the first road fails, the reserve lives -----------------------------------------------------------------------------------------------
KINDS = ['http_401', 'http_403', 'http_429', 'response_failed', 'http_500', 'ConnectError', 'RemoteProtocolError', 'hang', 'empty']
HEAVY = {'hang', 'http_429', 'http_401', 'empty'}


def scenario_of(kind):
    return hang() if kind == 'hang' else empty() if kind == 'empty' else fail(kind)


def a_cell(kind, roads, *, mode='live', suffix='live', **extra):
    """``roads``: a = the first Groq lives, b = it failed with the same kind and the second key lives, c = every Groq road refused at once (429) and Gemini lives."""
    live = {'a': 'groq1', 'b': 'groq2', 'c': 'gemini'}[roads]
    hanging = ('codex', 'groq1') if kind == 'hang' else ()

    def plan(seed):
        base = {'codex': scenario_of(kind), live: late(spread(seed, 0.3, HANG_LIVE_MAX_S if kind == 'hang' and roads == 'b' else 2.4))}      # a hanging first road beside a hanging groq1: the live road is asked at 3N (6 s) and its answer must come before the refusal, due 0.5 s before the question is let go at 8 s (REFUSE_BEFORE_DROP_SECONDS): round 3, the owner's 8 s is for the decision, the stand's road may not answer after it
        if roads == 'b':
            base['groq1'] = scenario_of(kind)
        if roads == 'c':
            base.update(groq1=fail('http_429'), groq2=fail('http_429'))
        return base

    def judge(run):
        return answered_by(live, run.q[-1].plan[live][1], hanging, whole=mode != 'live', opening=mode != 'live')(run)
    extra.setdefault('k', K_HEAVY if kind in HEAVY else K_LIGHT)
    return Cell(f'{kind}-{roads}-{suffix}', plan, judge, mode=mode, **extra)


A_CELLS = [a_cell(kind, roads) for kind in KINDS for roads in 'abc']


@pytest.mark.parametrize('cell', A_CELLS, ids=lambda cell: cell.name)
def test_a_the_failure_of_the_first_road_is_not_heard(tmp_path, cell):
    check_cell(tmp_path, cell)


def groq_host_cell(kind, *, mode='live', suffix='live'):
    """Silence is the host's: every road of Groq (``groq1``, ``groq2`` and ``other``) hangs with the first road gone (``kind``: it hangs or it is refused at once), Gemini lives. A hanging host is skipped as a whole: Gemini is asked
    not later than ``2 * N`` s (the first road silent, then Groq) or ``N`` s (the first road refused, then Groq) after the question, plus a tick."""
    hanging = ('codex', 'groq1') if kind == 'hang' else ('groq1',)
    late_by = (3 * N if kind == 'hang' else N) + GAP_S      # hang: the first road silent, Groq asked at N and let go at 3N (its own 2N: the silent first road is not let go for it)

    def plan(seed):
        return {'codex': scenario_of(kind), 'groq1': hang(), 'groq2': hang(), 'other': hang(), 'gemini': late(spread(seed, 0.3, HANG_LIVE_MAX_S if kind == 'hang' else 2.4))}

    def judge(run):
        found = answered_by('gemini', run.q[-1].plan['gemini'][1], hanging, whole=mode != 'live', opening=mode != 'live')(run)
        at = run.q[-1].asked_at('gemini')
        if at is not None and at > late_by + 1e-9:
            found.append(f'gemini asked at {at:.2f} s (later than {late_by:.1f}): the roads of a hanging host were asked one by one')
        return found
    return Cell(f'{kind}-groqhost-{suffix}', plan, judge, mode=mode, k=K_HEAVY, horizon=16.0)


GROQ_HOST = [groq_host_cell('hang'), groq_host_cell('http_429'), groq_host_cell('http_429', mode='no_offer', suffix='nooffer')]


@pytest.mark.parametrize('cell', GROQ_HOST, ids=lambda cell: cell.name)
def test_a_a_hanging_host_is_skipped_as_a_whole_and_the_live_host_is_asked_next(tmp_path, cell):
    check_cell(tmp_path, cell)


def cut_cell(*, mode='live', suffix='live'):
    """The first road says a word and is torn off: the road rests like one that failed before its word, the retry of the controller is answered by the reserve (the word of the first road was never spoken)."""
    def plan(seed):
        return {'codex': cut('RemoteProtocolError'), 'groq1': late(spread(seed, 0.3, 1.2))}

    def judge(run):
        result, found = run.q[-1], []
        if MARKS['groq1'] not in text_of(result.answers):
            found.append('the answer of groq1 was not heard')
        if result.service_all or result.other:
            found.append('phrase of the system or a cut answer: ' + text_of(result.service_all + result.other))
        if run.info['errors']:
            found.append(f'frames of error went to the phone: {run.info["errors"]}')
        if result.first_sound is None or result.first_sound > 4.0:
            found.append(f'first sound {result.first_sound} s after the question (more than 4.0)')
        if mode != 'live':
            found += opened_in_time(run)
        return found
    return Cell(f'cut-a-{suffix}', plan, judge, mode=mode, k=K_HEAVY, horizon=16.0)


CUT_CELLS = [cut_cell(), cut_cell(mode='no_offer', suffix='nooffer')]


@pytest.mark.parametrize('cell', CUT_CELLS, ids=lambda cell: cell.name)
def test_a_a_first_road_torn_off_after_its_first_word_is_answered_whole_by_the_reserve_and_sends_no_error(tmp_path, cell):
    check_cell(tmp_path, cell)


def held_cell(*, mode='live'):
    """Codex 429; groq1 hangs to its own ReadTimeout (6 s); groq2 and gemini 429; the last road says a word and is torn off (the word of a twin nobody heard). The question is not held for ever: the local mode says its
    line not later than M + 1.5 s and nothing is silent; GPT-Live that answers by itself at 3 s is heard not later than ALL_DEAD_S + 1.5 s and no line of the system is said."""
    plan = {'codex': fail('http_429'), 'groq1': hang(), 'groq2': fail('http_429'), 'gemini': fail('http_429'), 'other': cut('RemoteProtocolError')}
    if mode == 'live':
        return Cell('held-twin-cut-cloud-answers', lambda seed: plan, lambda run: c_cloud_answers(run, reserve_text.ALL_DEAD_S + 1.5), cloud_reply=3.0, k=K_HEAVY, horizon=14.0)
    return Cell('held-twin-cut-local', lambda seed: plan, lambda run: c_phrase_in(M + 1.5)(run), mode='no_offer', k=K_HEAVY, horizon=16.0)


@pytest.mark.parametrize('cell', [held_cell(), held_cell(mode='no_offer')], ids=lambda cell: cell.name)
def test_a_a_twin_that_spoke_and_broke_while_the_released_road_timed_out_does_not_hold_the_question_for_ever(tmp_path, cell):
    check_cell(tmp_path, cell)


def blank_cell(*, mode='live', suffix='live'):
    """The first road says white space only and ends: that is no word, the next road answers at once and nothing of the blanks is heard."""
    def plan(seed):
        return {'codex': blank(), 'groq1': late(spread(seed, 0.3, 2.4))}
    return Cell(f'blank-a-{suffix}', plan, lambda run: answered_by('groq1', run.q[-1].plan['groq1'][1], whole=mode != 'live', opening=mode != 'live')(run), mode=mode, k=K_HEAVY)


@pytest.mark.parametrize('cell', [blank_cell()], ids=lambda cell: cell.name)
def test_a_an_answer_of_white_space_only_is_no_word_and_the_next_road_answers(tmp_path, cell):
    check_cell(tmp_path, cell)


# ---- B. GPT-Live is dead: the question comes from the ear alone ----------------------------------------------------------------------------------
B_CELLS = [a_cell(kind, roads, mode='no_offer', suffix='nooffer') for kind in KINDS for roads in 'abc']
B_OPENINGS = [a_cell(kind, 'a', mode=mode, suffix=mode, k=K_LIGHT) for kind in ('http_429', 'hang') for mode in ('refused', 'start_fault', 'closed_before_ready', 'never_ready')]
B_LOST = [a_cell(kind, 'a', mode='lost', suffix='lost-' + loss.replace(' ', '_'), loss=loss, k=K_LIGHT) for kind in ('http_429', 'hang') for loss in LOSSES]


@pytest.mark.parametrize('cell', B_CELLS, ids=lambda cell: cell.name)
def test_b_a_dead_gpt_live_at_the_opening_still_gets_the_answer_of_the_text_roads_and_no_phrase(tmp_path, cell):
    check_cell(tmp_path, cell)


@pytest.mark.parametrize('cell', B_OPENINGS, ids=lambda cell: cell.name)
def test_b_every_kind_of_failed_opening_opens_in_time_and_answers_without_a_phrase(tmp_path, cell):
    check_cell(tmp_path, cell)


@pytest.mark.parametrize('cell', B_LOST, ids=lambda cell: cell.name)
def test_b_gpt_live_lost_in_the_middle_of_the_call_the_next_question_of_the_ear_is_answered_by_the_text(tmp_path, cell):
    check_cell(tmp_path, cell)


# ---- C. every road of the text is dead ----------------------------------------------------------------------------------------------------------------
def dead(kind):
    """Every road refuses at once (429) or every road is silent."""
    return {'codex': hang() if kind == 'hang' else fail('http_429')}


def c_phrase_in(bound):
    def judge(run):
        result, found = run.q[-1], []
        if result.answers:
            found.append('an answer from a dead system: ' + text_of(result.answers))
        if result.first_phrase is None:
            found.append('silence: no phrase and no answer after the question')
        elif result.first_phrase > bound:
            found.append(f'the phrase came {result.first_phrase:.2f} s after the question (more than {bound})')
        return found
    return judge


def c_cloud_answers(run, bound=None):
    result, found = run.q[-1], []
    if H.cloud_answer(result.text)[1] not in text_of(result.answers).lower():
        found.append(f'the answer of the cloud was not heard: {result.heard!r}')
    if result.service:
        found.append('phrase of the system: ' + text_of(result.service))
    if bound is not None and (result.first_answer is None or result.first_answer > bound):
        found.append(f'the first sound of the answer came {result.first_answer} s after the question (more than {bound})')
    if result.first_sound is None:
        found.append('silence')
    return found


def c_local_unknown(run, bound=1.0):
    """No cloud, every road dead: the one honest line of the local mode (``local_unknown``) not later than ``bound`` after the question, and no frame of error on the phone (the generic line of the controller's own watchdog is not it)."""
    result, found = run.q[-1], c_phrase_in(bound)(run)
    said = [item['text'] for item in result.service]
    if said and any(' '.join(str(t).split()) != native_media_socket.LOCAL_PHRASES['local_unknown'] for t in said):
        found.append(f'not the line local_unknown: {said!r}')
    if run.info['errors']:
        found.append(f'frames of error went to the phone: {run.info["errors"]}')
    return found


C_CELLS = [
    Cell('dead-fast-local', lambda seed: dead('fast'), c_local_unknown, mode='no_offer', k=K_HEAVY, horizon=14.0),
    Cell('dead-hang-local', lambda seed: dead('hang'), c_phrase_in(M + SYNTH_TICK_S), mode='no_offer', k=K_HEAVY, horizon=16.0, default=hang()),
    Cell('dead-fast-cloud-answers', lambda seed: dead('fast'), c_cloud_answers, cloud_reply=3.0, k=K_HEAVY, horizon=10.0),
    # every road hangs, the live cloud answered at 3 s: the guard says no sentence, the roads are dead at M (failed), the question goes back to the cloud and its answer is heard
    Cell('dead-hang-cloud-answers', lambda seed: dead('hang'), lambda run: c_cloud_answers(run, M + 1.5), cloud_reply=3.0, k=K_HEAVY, horizon=10.0, default=hang()),
    Cell('dead-fast-cloud-silent', lambda seed: dead('fast'), c_phrase_in(M + 4.0 + SYNTH_TICK_S), k=K_HEAVY, horizon=18.0),
    Cell('dead-hang-cloud-silent', lambda seed: dead('hang'), c_phrase_in(M + 4.0 + SYNTH_TICK_S), k=K_HEAVY, horizon=18.0, default=hang()),
]


@pytest.mark.parametrize('cell', C_CELLS, ids=lambda cell: cell.name)
def test_c_when_every_road_is_dead_the_listener_is_never_left_in_silence(tmp_path, cell):
    check_cell(tmp_path, cell)


# ---- U127: the link of the model is dead while the call is open (GPT-Live gives up at the opening: ``controlled_upstream_unavailable`` at 6 s, the greeting is played, no prompt ever reaches the cloud) ----------
# With ONE road (``Roads`` always) a question still gets an answer of the reserve or the one honest line, never silence: with the keys of the reserve (the cells A/B above, ``no_offer``), and with none (the first
# road alone, an empty reserve): Codex lives and answers; Codex is dead and the one line of the local mode is said, with no frame of error on the phone.
NO_KEYS = [(reserve_text, 'read_keys', lambda path=None: {})]
U127_CELLS = [
    Cell('u127-no-keys-codex-answers', lambda seed: {'codex': late(spread(seed, 0.3, 1.2))}, lambda run: answered_by('codex', run.q[-1].plan['codex'][1], whole=True, opening=True)(run), mode='no_offer', k=K_HEAVY, patches=NO_KEYS),
    Cell('u127-no-keys-codex-hangs', lambda seed: dead('hang'), lambda run: c_phrase_in(M + 1.5)(run) + opened_in_time(run) + ['frames of error went to the phone: %s' % run.info['errors']] * bool(run.info['errors']), mode='no_offer', k=K_HEAVY, horizon=16.0, default=hang(), patches=NO_KEYS),      # a silent road: the honest sentence of the roads at M (not the line of the local mode, which is for roads that refuse at once)
    Cell('u127-no-keys-codex-refuses', lambda seed: dead('fast'), lambda run: c_local_unknown(run, N + 1.5) + opened_in_time(run), mode='no_offer', k=K_HEAVY, horizon=14.0, patches=NO_KEYS),
    Cell('u127-keys-codex-hangs-the-reserve-answers', lambda seed: {'codex': hang(), 'groq1': late(spread(seed, 0.3, 2.4))}, lambda run: answered_by('groq1', run.q[-1].plan['groq1'][1], ('codex',), whole=True, opening=True)(run),
         mode='no_offer', k=K_HEAVY),
]


@pytest.mark.parametrize('cell', U127_CELLS, ids=lambda cell: cell.name)
def test_u127_the_link_of_the_model_dead_while_the_call_is_open_a_question_gets_the_reserve_answer_or_the_honest_line_never_silence(tmp_path, cell):
    check_cell(tmp_path, cell)


def c_rested_run(tmp_path, cell, seed):
    """Every road refuses at once and rests after the first question; then GPT-Live is torn off in the middle of the call: the roads are dead (they rest), so the line «the cloud is unavailable» is true and is said."""
    stand = Stand(dead('fast'))

    async def body(host, stand):
        keep_phone(host)
        q1 = await stand.ask(host, question_of(seed), lag=0.2, pre=spread(seed, 0.0, 0.1, 0.31))
        await host.advance(9.0)
        lost_at = host.now()
        LOSSES['EOF'](host.bridge)
        await host.advance(10.0)
        saw = heard(host, lost_at)
        return Run(cell, seed, [Result(stand, host, q1, question_of(seed), t0=q1)], opened=[i for i in saw['service'] if ' '.join(str(i['text']).split()) == native_media_socket.LOCAL_PHRASES['local_opened']])
    return run_stand(tmp_path, stand, body)


def c_rested_judge(run):
    return [] if run.info['opened'] else ['the line local_opened was not said although every road rests and GPT-Live was torn off']


C_RESTED = Cell('all-rest-gpt-live-falls', None, c_rested_judge, run=c_rested_run, k=K_HEAVY)


def test_c_when_every_road_rests_and_gpt_live_falls_the_line_that_the_cloud_is_unavailable_is_said(tmp_path):
    check_cell(tmp_path, C_RESTED)


# ---- D. the link comes back without a new call ---------------------------------------------------------------------------------------------------------
def any_answer(result):
    return any(mark in text_of(result.answers) for mark in MARKS.values())


def keep_phone(host, every=20.0):
    """The phone sends audio all the time; the stand sends nothing between two questions, and the host hangs up on a phone silent RECEIVE_TIMEOUT_S (65 s): a stand artefact for the cells of 70 s. A packet of silence every ``every`` s."""
    def packet():
        host.ws.push({'type': 'input_audio_buffer.append', 'audio': 'AA' * 480})
        host.loop.call_later(every, packet)
    host.loop.call_later(every, packet)


def d_revive_run(tmp_path, cell, seed):
    """Every road dead -> a phrase; the roads come alive ``revive`` s after the first question; the next question comes ``second`` s after it. The same call: one session.updated, serve goes on."""
    revive, second = cell.params
    stand = Stand(dead('hang' if cell.hanging else 'fast'), default=hang() if cell.hanging else None)

    async def body(host, stand):
        t0 = host.now()
        updated, ready = await H.open_local(host)
        keep_phone(host)
        await host.advance(1.0)
        q1 = await stand.ask(host, question_of(seed), cloud=False, pre=spread(seed, 0.0, 0.1, 0.31))

        def alive():
            stand.plan.clear()
            stand.default = ok()
        host.loop.call_at(q1 + revive, alive)
        await host.advance(second)
        q2 = await stand.ask(host, question_of(seed, 1), cloud=False, uid='u2')
        await host.advance(8.0)
        first = Result(stand, host, q1, question_of(seed), t0=t0, until=q2)
        again = Result(stand, host, q2, question_of(seed, 1), t0=t0)
        return Run(cell, seed, [first, again], updated=updated, ready=ready, finished=host.finished, updated_count=sum(1 for f in host.ws.frames if f.type == 'session.updated'))
    return run_stand(tmp_path, stand, body, handshake=False, setup=['no_offer'])


def d_revive_judge(run):
    first, again, found = run.q[0], run.q[1], []
    if first.first_phrase is None and not any_answer(first):      # a road that lives again before the phrase (the 5 s of a hanging cell: the walk is still on) may answer the first question: never silence is the rule
        found.append('the dead system said nothing to the first question')
    if not any_answer(again):
        found.append(f'the question after the return was not answered: {again.heard!r}')
    if again.service:
        found.append('phrase of the system after the return: ' + text_of(again.service))
    if again.first_answer is not None and again.first_answer > SYNTH_TICK_S + 0.5:
        found.append(f'the answer after the return came {again.first_answer:.2f} s after the question')
    if run.info['finished'] or run.info['updated_count'] != 1:
        found.append(f'not the same call: finished={run.info["finished"]} session.updated x{run.info["updated_count"]}')
    return found


def d_cell(name, revive, second, hanging):
    cell = Cell(name, None, d_revive_judge, run=d_revive_run, k=K_LIGHT)
    cell.params, cell.hanging = (revive, second), hanging
    return cell


D_REVIVE = [d_cell('revive-5s-fast', 5.0, 13.0, False), d_cell('revive-70s-fast', 70.0, 71.0, False), d_cell('revive-5s-hang', 5.0, 15.0, True), d_cell('revive-70s-hang', 70.0, 71.0, True)]


@pytest.mark.parametrize('cell', D_REVIVE, ids=lambda cell: cell.name)
def test_d_the_roads_come_back_and_the_next_question_of_the_same_call_is_answered(tmp_path, cell):
    check_cell(tmp_path, cell)


def d_primary_run(tmp_path, cell, seed):
    """Codex is silent for two questions (the reserve answers), then it lives again: after PRIMARY_FAIL_REST_S and a margin the question is asked of Codex first and Codex answers."""
    stand = Stand({'codex': hang(), 'groq1': late(spread(seed, 0.3, 1.2))})

    async def body(host, stand):
        t0 = host.now()
        asked = []
        for n in range(2):
            asked.append(await stand.ask(host, question_of(seed, n), uid=f'u{n + 1}', lag=0.2))
            await host.advance(12.0)
        stand.plan.update(codex=ok(), groq1=late(5.0))
        await host.advance(reserve_text.PRIMARY_FAIL_REST_S + 5.0)
        asked.append(await stand.ask(host, question_of(seed, 2), uid='u3', lag=0.2))
        await host.advance(8.0)
        bounds = asked[1:] + [None]
        return Run(cell, seed, [Result(stand, host, at, question_of(seed, n), t0=t0, until=until) for n, (at, until) in enumerate(zip(asked, bounds))])
    return run_stand(tmp_path, stand, body)


def d_primary_judge(run):
    first, second, third, found = run.q[0], run.q[1], run.q[2], []
    for n, result in ((1, first), (2, second)):
        if MARKS['groq1'] not in text_of(result.answers):
            found.append(f'question {n}: the reserve did not answer ({result.heard!r})')
    if MARKS['codex'] not in text_of(third.answers):
        found.append(f'question 3 (Codex alive again after {reserve_text.PRIMARY_FAIL_REST_S:.0f} s of rest): Codex did not answer ({third.heard!r}, roads {[a for a, _ in third.order]})')
    if third.service_all:
        found.append('phrase of the system: ' + text_of(third.service_all))
    return found


D_PRIMARY = Cell('codex-silent-then-alive', None, d_primary_judge, run=d_primary_run, k=K_LIGHT)


def test_d_the_first_road_that_was_silent_comes_back_after_its_rest_in_the_same_call(tmp_path):
    check_cell(tmp_path, D_PRIMARY)


def d_cloud_back_run(tmp_path, cell, seed):
    """GPT-Live is dead at the opening (local mode), the roads live; the helper comes back (a late connect) in the same call: the next question of the cloud is answered."""
    stand = Stand({'codex': fail('http_429'), 'groq1': late(spread(seed, 0.3, 1.2))} if not cell.params else {'codex': fail('http_429')})

    async def body(host, stand):
        t0 = host.now()
        updated, ready = await H.open_local(host)
        await host.advance(1.0)
        q1 = await stand.ask(host, question_of(seed), cloud=False)
        await host.advance(5.0)
        host.setup_script.clear()
        bridges = len(host.bridges)
        await host.until(lambda: len(host.bridges) > bridges and any(k == 'A' for k, _ in host.bridges[-1].sent), 80)
        await host.advance(5.0)
        q2 = await stand.ask(host, question_of(seed, 1), cloud=True, uid='u2', lag=0.2)
        if cell.params:
            await host.advance(2.0)
            await host.answer(H.cloud_answer(question_of(seed, 1))[0], tid='a1')
        await host.advance(10.0)
        return Run(cell, seed, [Result(stand, host, q1, question_of(seed), t0=t0, until=q2), Result(stand, host, q2, question_of(seed, 1), t0=t0)], updated=updated, ready=ready,
                   finished=host.finished, updated_count=sum(1 for f in host.ws.frames if f.type == 'session.updated'), bridges=len(host.bridges))
    patches = [(native_media_socket, 'LOCAL_RETRY_FIRST_S', 0), (native_media_socket, 'LOCAL_RETRY_EVERY_S', 0)]
    return run_stand(tmp_path, stand, body, handshake=False, setup=['no_offer'], patches=patches)


def d_cloud_back_judge(run):
    first, again, found = run.q[0], run.q[1], []
    if run.info['finished'] or run.info['updated_count'] != 1 or run.info['bridges'] < 3:
        found.append(f'not the same call: finished={run.info["finished"]} session.updated x{run.info["updated_count"]} bridges {run.info["bridges"]}')
    if run.cell.params:
        if H.cloud_answer(again.text)[1] not in text_of(again.answers).lower():
            found.append(f'the answer of the returned cloud was not heard: {again.heard!r}')
    elif not any_answer(again):
        found.append(f'the question after the cloud came back was not answered: {again.heard!r}')
    if again.service:
        found.append('phrase of the system after the return: ' + text_of(again.service))
    if run.cell.params:      # no road of text lives here: the honest phrase of the first question is right (never silence); what GPT-Live says after its return is judged above
        if first.first_phrase is None and not any_answer(first):
            found.append('the dead system said nothing to the first question')
    elif first.service_all:
        found.append('phrase of the system in the call: ' + text_of(first.service_all))
    return found


def d_back_cell(name, cloud_speaks):
    cell = Cell(name, None, d_cloud_back_judge, run=d_cloud_back_run, k=K_LIGHT)
    cell.params = cloud_speaks
    return cell


D_BACK = [d_back_cell('cloud-back-roads-answer', False), d_back_cell('cloud-back-cloud-answers', True)]


@pytest.mark.parametrize('cell', D_BACK, ids=lambda cell: cell.name)
def test_d_gpt_live_comes_back_in_the_same_call_and_its_question_is_answered(tmp_path, cell):
    check_cell(tmp_path, cell)


# ---- E. the opening does not depend on the first road --------------------------------------------------------------------------------------------------
def open_time(tmp_path, plan, mode):
    """Seconds from session.update to session.updated (None: never) and whether the readiness marker came."""
    stand = Stand(plan)
    rig = {'handshake': False}
    if mode in ('no_offer', 'refused', 'closed_before_ready', 'never_ready'):
        rig['setup'] = [mode]

    async def body(host, stand):
        if mode == 'start_fault':
            host.start_fault = OSError('helper is not there')
        return await H.open_local(host)
    return run_stand(tmp_path, stand, body, **rig)


def test_e_a_silent_first_road_does_not_slow_the_opening_of_a_healthy_call(tmp_path):
    healthy, _ = open_time(tmp_path / 'ok', {'codex': ok()}, 'live')
    silent, ready = open_time(tmp_path / 'hang', {'codex': hang()}, 'live')
    assert healthy is not None and silent is not None and ready, (healthy, silent, ready)
    assert silent <= healthy + 0.2, f'session.updated {silent:.2f} s with a silent first road, {healthy:.2f} s with a healthy one'


@pytest.mark.parametrize('road', ['ok', 'hang', 'http_401'])
@pytest.mark.parametrize('mode', ['no_offer', 'refused', 'start_fault', 'closed_before_ready', 'never_ready'])
def test_e_a_dead_gpt_live_opens_the_call_in_time_whatever_the_first_road_does(tmp_path, mode, road):
    plan = {'codex': {'ok': ok(), 'hang': hang(), 'http_401': fail('http_401')}[road]}
    updated, ready = open_time(tmp_path, plan, mode)
    assert updated is not None and updated <= OPEN_S, f'{mode}/{road}: session.updated {updated} after session.update (more than {OPEN_S})'
    assert ready, f'{mode}/{road}: no readiness marker'


# ---- F. the third question of a call whose first road keeps silent ----------------------------------------------------------------------------------
def f_run(tmp_path, cell, seed):
    d = spread(seed, 0.3, 1.2)
    stand = Stand({'codex': hang(), 'groq1': late(d)})

    async def body(host, stand):
        t0 = host.now()
        asked = []
        for n in range(3):
            asked.append(await stand.ask(host, question_of(seed, n), uid=f'u{n + 1}', lag=0.2, pre=spread(seed, 0.0, 0.1, 0.31 * n)))
            await host.advance(12.0)
        bounds = asked[1:] + [None]
        return Run(cell, seed, [Result(stand, host, at, question_of(seed, n), t0=t0, until=until) for n, (at, until) in enumerate(zip(asked, bounds))], delay=d)
    return run_stand(tmp_path, stand, body)


def f_judge(run):
    one, two, three, found, d = run.q[0], run.q[1], run.q[2], [], run.info['delay']
    for n, result in enumerate((one, two, three), 1):
        if MARKS['groq1'] not in text_of(result.answers):
            found.append(f'question {n}: the reserve did not answer ({result.heard!r})')
        if result.service:
            found.append(f'question {n}: phrase of the system: ' + text_of(result.service))
    if three.codex_calls():
        found.append(f'question 3: the silent first road was asked again at {three.codex_calls()} (it lost twice in a row)')
    if three.asked_at('groq1') is None or three.asked_at('groq1') > GAP_S:
        found.append(f'question 3: the live road was asked at {three.asked_at("groq1")} (not at once)')
    if three.first_answer is None or one.first_answer is None or three.first_answer > one.first_answer - 1.0:
        found.append(f'question 3 came {three.first_answer} s after its question, question 1 {one.first_answer} s: not faster by a second')
    return found


F_CELL = Cell('hang-third-question', None, f_judge, run=f_run, k=K_HEAVY)


def test_f_after_two_silent_losses_the_third_question_does_not_wait_for_the_first_road(tmp_path):
    check_cell(tmp_path, F_CELL)


# ---- G. the matrix is not a dummy: it goes red when the switching is broken ----------------------------------------------------------------------------
def a_one(kind, roads):
    return a_cell(kind, roads, k=3)


def test_g_without_the_next_road_after_a_silence_the_cells_of_a_silent_first_road_are_red(tmp_path, monkeypatch):
    monkeypatch.setattr(reserve_text, 'NEXT_ROAD_S', 1e9)      # the name of SPEC.md: absent before the change (AttributeError)
    for roads in 'abc':
        with pytest.raises(AssertionError):
            check_cell(tmp_path / roads, a_one('hang', roads), k=3, report=False)


def test_g_without_the_reserve_the_cells_a_to_c_are_red(tmp_path, monkeypatch):
    monkeypatch.setattr(reserve_text, 'for_stream', lambda primary, **k: primary)
    for roads in 'abc':
        with pytest.raises(AssertionError):
            check_cell(tmp_path / roads, a_one('http_429', roads), k=3, report=False)


def test_g_with_only_the_first_road_in_the_order_the_cells_are_red(tmp_path, monkeypatch):
    whole = reserve_text.Roads.order      # SPEC.md: Roads.order (absent before the change: AttributeError)
    monkeypatch.setattr(reserve_text.Roads, 'order', lambda self, request: whole(self, request)[:1])
    for roads in 'abc':
        with pytest.raises(AssertionError):
            check_cell(tmp_path / roads, a_one('http_429', roads), k=3, report=False)


def test_g_when_the_roads_are_never_alive_the_local_mode_says_its_phrase_and_the_cell_is_red(tmp_path, monkeypatch):
    whole = native_media_socket.NativeMediaSocket._text_road
    monkeypatch.setattr(native_media_socket.NativeMediaSocket, '_text_road', lambda self, alive=False: False if alive else whole(self))      # SPEC.md section 4: absent before the change
    with pytest.raises(AssertionError):
        check_cell(tmp_path, a_cell('http_429', 'a', mode='no_offer', suffix='nooffer'), k=3, report=False)


def test_g_when_the_roads_never_say_the_question_is_over_the_cells_without_the_guard_are_red(tmp_path, monkeypatch):
    from echo_sync import controlled_media
    monkeypatch.setattr(reserve_text, 'ALL_DEAD_S', 1e9)
    monkeypatch.setattr(controlled_media.ControlledMedia, 'decision_due', lambda self, qid=None: None)      # round 3 (hold8): the walk's bound is the controller's one moment (``decision_due``), ALL_DEAD_S is only its fallback: both are cut
    with pytest.raises(AssertionError):
        check_cell(tmp_path, next(c for c in C_CELLS if c.name == 'dead-hang-cloud-answers'), k=3, report=False)


def test_g_when_a_road_rests_no_more_alive_is_true_the_local_mode_does_not_say_its_line_after_a_rest_and_the_cell_is_red(tmp_path, monkeypatch):
    whole = native_media_socket.NativeMediaSocket._text_road
    monkeypatch.setattr(native_media_socket.NativeMediaSocket, '_text_road', lambda self, alive=False: True if alive else whole(self))
    with pytest.raises(AssertionError):
        check_cell(tmp_path, C_RESTED, k=3, report=False)


def test_g_without_the_stall_two_roads_that_hang_one_after_the_other_are_never_let_go_and_the_cell_is_red(tmp_path, monkeypatch):
    whole = reserve_text.Roads.step      # the action ``stall`` of the rule of twice NEXT_ROAD_S is never said, so the place it frees is never taken by the next road (the give-up time is not touched)

    def without_the_stall(self, now, tried, walk, **k):
        acts = whole(self, now, tried, walk, **k)
        kept = [act for act in acts if act[0] != 'stall' or now - k['asked'] >= k['give_up']]
        return kept if len(kept) == len(acts) else [act for act in kept if act[0] != 'next']
    monkeypatch.setattr(reserve_text.Roads, 'step', without_the_stall)
    with pytest.raises(AssertionError):      # the first road and groq1 hang: groq1 is the one let go (the first road never is) and groq2 and Gemini wait for its place
        check_cell(tmp_path / 'b', a_one('hang', 'b'), k=3, report=False)


def test_g_without_the_count_of_the_losses_the_third_question_waits_for_the_first_road_again_and_the_cell_f_is_red(tmp_path, monkeypatch):
    monkeypatch.setattr(reserve_text.Roads, 'lost', lambda self, walk, key, now: None)
    with pytest.raises(AssertionError):
        check_cell(tmp_path, F_CELL, k=3, report=False)

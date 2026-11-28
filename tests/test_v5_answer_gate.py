"""V5 slice «answer gate» (echo_sync/v5_gate.py, setting ``v5_answer_gate`` = off | shadow | on, default off).

Every answer cue about to be handed to the transport passes the gate: (1) is the meaning of the question the answer was prepared for the meaning of the
question as the system knows it now (numbers, dates, negations, content stems), (2) was the cue held, by which rule, how long, and was the speech that held it
known to be the owner's, (3) how old is the answer. Off: nothing is built. Shadow: the verdict is written into the journal and the v5 record and nothing
changes (the replay of the call of 10:27 gives the same actions and frames). On: a stale answer is refused once per question and asked again through the
controller; a hold by speech not known to be the owner's ends at the cap of the one cost table. Nothing here measures a call.
"""
import json
import re
from pathlib import Path

import pytest

from echo_sync import ear_shadow, settings as cfg
from echo_sync import v5_gate, v5_tap
from echo_sync.controlled_media import ControlledMedia
from test_h3_tempo import call      # noqa: F401 - the fixture
from test_h7 import replay_1027
from test_v5_step1a_tap import Returns, lines, plain, validator

ROOT = Path(__file__).resolve().parents[1]


# -- the setting --------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_setting_defaults_to_off_and_an_unknown_value_is_off():
    assert cfg.DEFAULTS['v5_answer_gate'] == 'off' and cfg.resolve({})['v5_answer_gate'] == 'off'
    for mode in ('off', 'shadow', 'on'):
        assert cfg.resolve({'v5_answer_gate': mode})['v5_answer_gate'] == mode
    assert cfg.resolve({'v5_answer_gate': 'maybe'})['v5_answer_gate'] == 'off' and cfg.resolve({'v5_answer_gate': True})['v5_answer_gate'] == 'off'
    assert '`v5_answer_gate`' in (ROOT / 'SETTINGS.md').read_text(encoding='utf-8')


def test_off_builds_no_gate():
    assert v5_gate.attach({'v5_answer_gate': 'off'}, object(), object()) is None
    assert v5_gate.attach({}, object(), object()) is None
    assert v5_gate.attach({'v5_answer_gate': 'shadow'}, object(), object()).mode == 'shadow'


def test_one_cost_table_holds_every_number_of_the_gate():
    costs = v5_gate.COSTS
    assert {'hold_other_s', 'hold_unknown_s', 'stale_refusals', 'newer_words', 'subject_kept'} <= set(costs)
    assert 0 < costs['hold_other_s'] <= costs['hold_unknown_s'] < 8.0, 'a hold not caused by the owner ends before the 8 s of today'
    assert costs['stale_refusals'] == 1, 'a stale answer is refused once per question: never a loop'
    source = (ROOT / 'echo_sync' / 'v5_gate.py').read_text(encoding='utf-8')
    assert not re.findall(r'^[A-Z_]+_(?:S|SECONDS|MS)\s*=', source, re.M), 'no time constant outside the table'


# -- (1) the meaning fingerprint ----------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('prepared, now, verdict, why', [
    ('Сколько будет сорок на два', 'Сколько будет 40 на 2', 'fresh', ''),
    ('Сколько будет сорок на два', 'ну скажи сколько будет сорок на два', 'fresh', ''),
    ('Сколько будет сорок на два', 'Сколько будет пятьдесят на два', 'stale', 'number'),
    ('Сколько будет сорок', 'Сколько будет сорок на два', 'stale', 'number'),
    ('Когда было крещение Руси', 'Когда было крещение Руси в 988 году', 'stale', 'date'),
    ('Нужно нагревать жидкость', 'Нужно не нагревать жидкость', 'stale', 'negation'),
    ('Кто написал Войну и мир', 'Кто написал Анну Каренину', 'stale', 'subject'),
    ('Что такое инфляция', 'Что такое инфляция простыми словами', 'fresh', ''),
    ('', 'Что такое инфляция', 'unknown', ''),
])
def test_the_meaning_of_the_question_then_and_now(prepared, now, verdict, why):
    got = v5_gate.compare(v5_gate.fingerprint(prepared), v5_gate.fingerprint(now))
    assert got == (verdict, why)


def test_a_fingerprint_keeps_numbers_dates_negations_and_stems():
    fp = v5_gate.fingerprint('Не в 1988 году, а сорок два')
    assert '#42' in fp['numbers'] and [a for a in fp['numbers'] if '1988' in a] == [a for a in fp['dates'] if '1988' in a] != [] and fp['negations'] == 1 and fp['stems']
    assert v5_gate.fingerprint('')['stems'] == frozenset()


# -- a controller and a wire with only what the gate reads -------------------------------------------------------------------------------------------------------------

class Ledger:
    def __init__(self, turns):
        self.turns = turns

    def history(self):
        return [dict(t) for t in self.turns]


class Voice:
    def __init__(self, kind):
        self._verdict = type('V', (), {'kind': kind})()


class Controller:
    def __init__(self, question='Сколько будет сорок на два', **kw):
        self.question_id, self.question_text, self.question_part, self.question_tail = 'u1', question, '', ''
        self.fast_text, self.fast_turn, self.source_id, self.question_clock = question, None, 'a1', 100.0
        self.ledger = Ledger([{'id': 'u1', 'role': 'user', 'valid': True, 'final': True, 'text': question}])
        self.plan = {'revision': 7, 'question': question}
        self.stale_calls = []
        self.__dict__.update(kw)

    def state(self):
        return dict(self.plan)

    def _part(self):
        return self.question_part or self.question_text

    def v5_stale(self, cue, asked):
        self.stale_calls.append((cue['revision'], asked))
        return [{'type': 'cancel', 'epoch': 2}, {'type': 'fast', 'op': 'release', 'qid': self.question_id, 'turn': 'fast-2', 'question': asked}]


class Fast:
    def __init__(self, asked):
        self.asked = asked

    def asked_of(self, qid):
        return self.asked.get(qid)


class Wire:
    def __init__(self, fast=None):
        self.fast = fast


def cue(index=0, revision=7, **kw):
    return {'type': 'speak', 'text': 'Восемьдесят.', 'epoch': 1, 'nonce': 'n', 'revision': revision, 'index': index, 'replay': False, **kw}


def gate_of(mode, controller, wire=None, notes=None, tap=None, same='words'):
    """The tests of this file pin the rule of the stems: they run under ``v5_gate_same`` = "words" (their meaning is unchanged; the new rule is in test_v5_gate_same.py)."""
    notes = [] if notes is None else notes
    return v5_gate.attach({'v5_answer_gate': mode, 'v5_gate_same': same}, controller, wire or Wire(), tap=tap, note=lambda ev, **f: notes.append((ev, f)))


# -- (1)+(3) an answer for an old question arrives after a revised question --------------------------------------------------------------------------------------------

def test_a_job_answer_for_the_old_question_after_a_revised_one_is_stale_in_shadow_and_changes_nothing():
    c = Controller(question='Сколько будет пятьдесят на два', fast_turn='fast-1')
    c.source_id = 'fast-1'
    notes = []
    gate = gate_of('shadow', c, Wire(Fast({'u1': 'Сколько будет сорок на два'})), notes)
    gate.asked({'type': 'fast', 'op': 'release', 'qid': 'u1', 'turn': 'fast-1', 'question': 'Сколько будет сорок на два'}, 100.0)
    assert gate.handed(cue(), 103.5) is None, 'shadow: the cue goes on as it would'
    [(ev, row)] = notes
    assert ev == 'v5_gate' and row['would'] == 'refuse' and row['meaning'] == 'stale' and row['why'] == 'number' and row['route'] == 'job'
    assert row['age_s'] == 3.5 and row['mode'] == 'shadow' and c.stale_calls == []
    assert 'сорок' not in json.dumps(row, ensure_ascii=False) and 'пятьдесят' not in json.dumps(row, ensure_ascii=False), 'no words of the conversation in the journal'


def test_the_same_answer_for_the_question_as_it_stands_passes():
    c = Controller(fast_turn='fast-1')
    c.source_id = 'fast-1'
    notes = []
    gate = gate_of('on', c, Wire(Fast({'u1': 'сколько будет 40 на 2'})), notes)
    assert gate.handed(cue(), 101.0) is None and c.stale_calls == []
    assert notes[0][1]['would'] == 'pass' and notes[0][1]['meaning'] == 'fresh'


def test_on_refuses_the_stale_answer_once_and_asks_again_with_the_question_as_it_stands():
    c = Controller(question='Сколько будет пятьдесят на два', fast_turn='fast-1')
    c.source_id = 'fast-1'
    notes = []
    gate = gate_of('on', c, Wire(Fast({'u1': 'Сколько будет сорок на два'})), notes)
    got = gate.handed(cue(), 102.0)
    assert got == [{'type': 'cancel', 'epoch': 2}, {'type': 'fast', 'op': 'release', 'qid': 'u1', 'turn': 'fast-2', 'question': 'Сколько будет пятьдесят на два'}]
    assert c.stale_calls == [(7, 'Сколько будет пятьдесят на два')] and notes[-1][1]['did'] == 'refused'
    assert gate.handed(cue(revision=8), 104.0) is None, 'the second stale answer of the same question (the one asked again) is not refused again (COSTS stale_refusals)'
    assert notes[-1][1]['would'] == 'refuse' and notes[-1][1]['did'] == 'passed_refusals_spent'


def test_a_newer_utterance_that_revises_the_question_makes_the_answer_stale():
    """The cloud route: the plan was published for «сорок на два»; after it the listener said «нет, пятьдесят на два» and the controller has not made it a question."""
    c = Controller()
    c.ledger.turns.append({'id': 'u2', 'role': 'user', 'valid': True, 'final': False, 'text': 'нет, пятьдесят на два'})
    notes = []
    gate = gate_of('shadow', c, notes=notes)
    gate.handed(cue(), 101.0)
    row = notes[0][1]
    assert row['route'] == 'plan' and row['meaning'] == 'stale' and row['newer'] == 1 and row['would'] == 'refuse'


def test_chatter_after_the_question_is_no_revision():
    c = Controller()
    c.ledger.turns.append({'id': 'u2', 'role': 'user', 'valid': True, 'final': True, 'text': 'угу, хорошо, давай дальше по плану работы'})
    notes = []
    gate_of('shadow', c, notes=notes).handed(cue(), 101.0)
    assert notes[0][1]['meaning'] == 'fresh' and notes[0][1]['newer'] == 0


def test_a_plan_of_an_older_question_given_back_and_a_repeat_are_told_and_pass():
    """G3: the controller gives the plan of the question before back on purpose when the new utterance got no answer: its meaning is told, it is not refused.
    A portion handed on again (a repeat) is no new answer either."""
    c = Controller(question='наличие и движение денег организации')
    c.plan['question'] = 'какой например 51 счет в плане счетов'
    notes = []
    gate = gate_of('on', c, notes=notes)
    assert gate.handed(cue(), 101.0) is None and c.stale_calls == []
    assert notes[0][1]['meaning'] == 'stale' and notes[0][1]['would'] == 'pass'
    c2 = Controller(question='Сколько будет пятьдесят на два', fast_turn='fast-1')
    c2.source_id = 'fast-1'
    notes2 = []
    gate2 = gate_of('shadow', c2, Wire(Fast({'u1': 'Сколько будет сорок на два'})), notes2)
    gate2.handed(cue(), 101.0)
    gate2.handed(cue(), 104.0)
    assert [(n[1]['would'], n[1]['again']) for n in notes2] == [('refuse', 0), ('pass', 1)]


def test_only_the_first_portion_is_refused_and_a_later_one_is_only_told():
    c = Controller(question='Сколько будет пятьдесят на два')
    c.plan['question'] = 'Сколько будет сорок на два'
    notes = []
    gate = gate_of('on', c, notes=notes)
    assert gate.handed(cue(index=1), 101.0) is None and c.stale_calls == []
    assert notes[0][1]['meaning'] == 'stale' and notes[0][1]['would'] == 'pass', 'an answer half said is not cut by the gate'


def test_on_with_no_way_to_ask_again_passes_and_says_so():
    c = Controller(question='Сколько будет пятьдесят на два')
    c.plan['question'] = 'Сколько будет сорок на два'
    c.ledger.turns.append({'id': 'u2', 'role': 'user', 'valid': True, 'final': False, 'text': 'нет, пятьдесят на два'})
    del Controller.v5_stale      # noqa - a controller without the hook
    try:
        notes = []
        assert gate_of('on', c, notes=notes).handed(cue(), 101.0) is None
        assert notes[0][1]['did'] == 'passed_no_reask'
    finally:
        Controller.v5_stale = _v5_stale


_v5_stale = Controller.v5_stale


# -- (2) holds: by which rule, how long, whose speech ------------------------------------------------------------------------------------------------------------------

def test_shadow_tells_a_hold_by_speech_not_known_to_be_the_owners_and_changes_nothing():
    c = Controller()
    notes = []
    gate = gate_of('shadow', c, notes=notes)
    a = cue(first=True)
    for t in (100.0, 102.0, 105.0, 107.5):
        assert gate.held(a, 'speech_with_content', t) is None, 'shadow never moves a hold'
    gate.handed(a, 108.0)
    row = notes[0][1]
    assert row['rule'] == 'speech_with_content' and row['held_s'] == 8.0 and row['speaker'] == 'unknown'
    assert row['would'] == 'release_earlier' and row['earlier_s'] == round(8.0 - v5_gate.COSTS['hold_unknown_s'], 2)


def test_a_hold_by_the_owners_own_speech_stands():
    c = Controller(speaker_gate=Voice('own'))
    notes = []
    gate = gate_of('on', c, notes=notes)
    a = cue()
    assert gate.held(a, 'cloud_hears_listener', 100.0) is None and gate.held(a, 'cloud_hears_listener', 109.0) is None
    gate.handed(a, 109.5)
    assert notes[0][1]['speaker'] == 'owner' and notes[0][1]['would'] == 'pass'


@pytest.mark.parametrize('kind, speaker, cap', [('other', 'other', 'hold_other_s'), ('unknown', 'unknown', 'hold_unknown_s'), (None, 'unknown', 'hold_unknown_s')])
def test_on_caps_a_hold_by_speech_not_known_to_be_the_owners(kind, speaker, cap):
    c = Controller(**({'speaker_gate': Voice(kind)} if kind else {}))
    gate = gate_of('on', c)
    a = cue()
    limit = v5_gate.COSTS[cap]
    assert gate.held(a, 'local_ear_onset', 50.0) == 50.0 + limit, 'the deadline of the hold'
    assert gate.held(a, 'local_ear_onset', 50.0 + limit / 2) == 50.0 + limit
    assert gate.held(a, 'local_ear_onset', 50.0 + limit) == 50.0 + limit, 'at the cap: the caller lets it go'
    assert gate.speaker() == speaker


def test_a_hold_that_is_no_speech_is_never_capped():
    gate = gate_of('on', Controller())
    a = cue()
    assert gate.held(a, 'job_pending', 10.0) is None and gate.held(a, 'question_final', 30.0) is None


def test_a_new_cue_starts_its_own_hold():
    gate = gate_of('on', Controller())
    gate.held(cue(), 'speech_with_content', 10.0)
    assert gate.held(cue(revision=8), 'speech_with_content', 20.0) == 20.0 + v5_gate.COSTS['hold_unknown_s']


def test_the_verdict_goes_into_the_v5_record_and_validates(tmp_path):
    class Fake:
        def tick(self, *, now):
            return []
    tap = v5_tap.attach(Fake(), {'v5_tap': 'shadow'}, tmp_path, 'g', clock=lambda: 10.0)
    c = Controller()
    c.ledger.turns.append({'id': 'u2', 'role': 'user', 'valid': True, 'final': False, 'text': 'нет, пятьдесят на два'})
    gate_of('shadow', c, tap=tap).handed(cue(), 101.0)
    tap.close()
    rows = lines(next(tmp_path.glob('*.v5tap.jsonl')))
    mine = [r for r in rows if r['source'] == 'journal:v5_gate']
    assert len(mine) == 1 and mine[0]['payload']['reason'] == 'would_refuse_stale_meaning' and mine[0]['payload']['flags']['meaning'] == 'stale'
    check = validator()
    assert all(check.is_valid(r) for r in rows)


def test_the_gate_never_raises_into_the_call():
    class Broken:
        @property
        def question_text(self):
            raise RuntimeError('x')
    gate = gate_of('on', Broken())
    assert gate.handed(cue(), 1.0) is None and gate.held(cue(), 'speech_with_content', 1.0) == 1.0 + v5_gate.COSTS['hold_unknown_s']


# -- the wire: off identical, shadow identical plus verdicts (the replay of the call of 10:27) --------------------------------------------------------------------------

def run_1027(call, monkeypatch, mode, returns):
    returns.rows = []
    rig = call(fast_text='on', max_auto_repeats=3, **({'v5_answer_gate': mode} if mode else {}))
    notes = []
    rig.w.wire.v5_gate = v5_gate.attach(rig.settings, rig.c, rig.w.wire, note=lambda ev, **f: notes.append((ev, f)))
    cues = replay_1027(rig, monkeypatch)
    rig.fast.close()
    frames = [(round(t, 3), plain(f)) for _, t, f in rig.w.frames]
    return list(returns.rows), frames, [(round(a, 3), text) for a, text, _ in cues], notes, rig


def test_the_replay_gives_the_same_actions_off_and_in_shadow_and_shadow_tells_a_verdict_per_answer_cue(call, monkeypatch):
    returns = Returns(monkeypatch)
    base = run_1027(call, monkeypatch, None, returns)
    assert base[4].w.wire.v5_gate is None and base[3] == [] and base[0] and base[2]
    shadow = run_1027(call, monkeypatch, 'shadow', returns)
    assert shadow[0] == base[0], 'every action the controller returned is the same'
    assert shadow[1] == base[1], 'and every frame the phone got'
    assert shadow[2] == base[2]
    verdicts = [f for ev, f in shadow[3] if ev == 'v5_gate']
    assert verdicts and len(verdicts) >= len(base[2]), 'a verdict next to every answer cue handed to the transport'
    assert {v['would'] for v in verdicts} <= {'pass', 'refuse', 'release_earlier'} and all(v['mode'] == 'shadow' for v in verdicts)
    assert all(v['meaning'] in ('fresh', 'stale', 'unknown') for v in verdicts)


def test_the_wire_has_the_gate_at_its_hand_off_and_off_is_none():
    wire = (ROOT / 'echo_sync' / 'native_media_socket.py').read_text(encoding='utf-8')
    assert 'self.v5_gate=None' in wire and wire.count('self.v5_gate.handed(') == 1, 'one hand-off, None unless the host attaches a gate'
    source = (ROOT / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')
    assert source.count('v5_gate.attach(') == 1 and source.index('v5_gate.attach(') > source.index('wire=NativeMediaSocket(')
    assert hasattr(ControlledMedia, 'v5_stale')


# -- the controller: the stale answer is refused and asked again through the existing path -------------------------------------------------------------------------------

def test_the_controller_asks_a_stale_job_answer_again_with_the_question_as_it_stands(call):
    rig = call(fast_text='on')
    c = rig.c
    c.question_id, c.question_text, c.fast_text, c.fast_turn, c.fast_asked, c.fast_done = 'u9', 'Сколько будет пятьдесят на два', 'Сколько будет сорок на два', 'fast-1', ('u9', 'fast-1'), True
    epoch = c.epoch
    assert c.v5_stale({'epoch': epoch - 1, 'nonce': c.nonce, 'revision': None, 'index': 0}, 'x') == [], 'a cue that is no longer authorized: nothing'
    c.state = lambda: {'revision': 3, 'chunk_index': 0, 'chunks': ['a']}
    got = c.v5_stale({'epoch': epoch, 'nonce': c.nonce, 'revision': 3, 'index': 0}, 'Сколько будет пятьдесят на два')
    assert got[0] == {'type': 'cancel', 'epoch': epoch + 1} and c.epoch == epoch + 1 and c.question_id == 'u9', 'the question stays open'
    [release] = [a for a in got if a.get('type') == 'fast']
    assert release['op'] == 'release' and release['qid'] == 'u9' and release['question'] == 'Сколько будет пятьдесят на два'
    assert 'fast-1' in c.retired_assistants and c.published == '' and c.fast_turn is None
    del c.state

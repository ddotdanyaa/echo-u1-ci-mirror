"""V5 slice «answer gate» without «words instead of meaning» (setting ``v5_gate_same`` = answers | words, default answers; ``v5_answer_gate`` = off | shadow | on).

«answers»: the closed classes (a number or a date not asked, a turned negation) only FORBID «the same» and make the old answer stale at once; otherwise the relation of
the two questions is UNKNOWN: the old answer is held within the one cap of the gate (on), and the answer for the present form, when it is there, is compared with it by
its exact things (numbers, dates, yes or no): the same, the old one goes; they differ, the newer one goes and the old is refused «ответ изменился»; no newer answer in
time, the old one goes marked «тождество не проверено». No content stem is read. «words»: the old stem rule, kept to compare. Shadow writes both verdicts, codes only.
"""
import json
from pathlib import Path

import pytest

from echo_sync import settings as cfg
from echo_sync import v5_gate
from echo_sync.controlled_media import ControlledMedia
from test_h3_tempo import call      # noqa: F401 - the fixture
from test_v5_answer_gate import Controller, Wire, cue, run_1027
from test_v5_step1a_tap import Returns

ROOT = Path(__file__).resolve().parents[1]
OLD_COSTS = {'hold_other_s', 'hold_unknown_s', 'stale_refusals', 'newer_words', 'subject_kept'}


class Fast:
    """What the gate reads of the text channel: what a job was asked, and what a job on a form has said so far (a look)."""
    def __init__(self, asked, prepared=None):
        self.asked, self.looks = asked, prepared or {}

    def asked_of(self, qid):
        return self.asked.get(qid)

    def prepared(self, text):
        return self.looks.get(text)


def job_gate(old, now, answer, newer=None, mode='shadow', same='answers', notes=None, voice=None):
    """A job answer ``answer`` made for ``old`` while the question stands as ``now``; ``newer`` = what the job on the present form has said so far, (text, over) or None."""
    c = Controller(question=now, fast_turn='fast-1')
    c.source_id = 'fast-1'
    if voice:
        c.speaker_gate = voice
    notes = [] if notes is None else notes
    fast = Fast({'u1': old}, {now: newer} if newer else {})
    gate = v5_gate.attach({'v5_answer_gate': mode, 'v5_gate_same': same}, c, Wire(fast), note=lambda ev, **f: notes.append((ev, f)))
    return c, gate, cue(text=answer), notes


CHANGED = ('Кто написал Войну и мир', 'Кто написал Анну Каренину')       # no closed class in the difference: the relation is unknown


# -- the setting --------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_setting_defaults_to_answers_and_an_unknown_value_is_answers():
    assert cfg.DEFAULTS['v5_gate_same'] == 'answers' and cfg.resolve({})['v5_gate_same'] == 'answers'
    for value in ('answers', 'words'):
        assert cfg.resolve({'v5_gate_same': value})['v5_gate_same'] == value
    assert cfg.resolve({'v5_gate_same': 'maybe'})['v5_gate_same'] == 'answers' and cfg.resolve({'v5_gate_same': 1})['v5_gate_same'] == 'answers'
    assert '`v5_gate_same`' in (ROOT / 'SETTINGS.md').read_text(encoding='utf-8')


def test_attach_reads_the_rule_and_off_builds_nothing_whatever_the_rule():
    for same in ('answers', 'words', 'x', None):
        assert v5_gate.attach({'v5_answer_gate': 'off', 'v5_gate_same': same}, object(), object()) is None
    assert v5_gate.attach({'v5_answer_gate': 'shadow'}, object(), object()).same == 'answers'
    assert v5_gate.attach({'v5_answer_gate': 'shadow', 'v5_gate_same': 'words'}, object(), object()).same == 'words'
    assert v5_gate.attach({'v5_answer_gate': 'on', 'v5_gate_same': 'zzz'}, object(), object()).same == 'answers'


def test_no_new_number_the_one_table_stays_as_it_was():
    assert set(v5_gate.COSTS) == OLD_COSTS


def test_off_is_the_same_as_before_the_replay_gives_the_same_actions_with_either_rule(call, monkeypatch):
    returns = Returns(monkeypatch)
    base = run_1027(call, monkeypatch, None, returns)
    assert base[4].w.wire.v5_gate is None and base[3] == []
    for same in ('words', 'answers'):
        got = run_1027(call, monkeypatch, None, returns)
        assert got[4].w.wire.v5_gate is None and got[3] == [] and got[0] == base[0] and got[1] == base[1] and got[2] == base[2]
    shadow = run_1027(call, monkeypatch, 'shadow', returns)
    assert shadow[0] == base[0] and shadow[1] == base[1] and shadow[2] == base[2], 'shadow with the default rule changes no action and no frame'


def test_the_hold_is_one_call_and_without_a_gate_it_asks_nothing(call):
    source = (ROOT / 'echo_sync' / 'cm_speech.py').read_text(encoding='utf-8')
    assert source.count('v5.parks(') == 1 and 'def hold(' in source
    wheel = (ROOT / 'echo_sync' / 'native_media_socket.py').read_text(encoding='utf-8').split('def _can_play')[1].split('def _release_at')[0]
    assert wheel.count('self.controller.hold(cue,self.v5_gate)') == 1 and 'v5_gate' not in wheel.replace('self.controller.hold(cue,self.v5_gate)', ''), 'the wheel hands the gate over in the one hold call and reads nothing of it'
    rig = call(fast_text='on')
    rig.w.wire.v5_gate = None
    assert rig.c.hold(cue(), None)[1] is None, 'no gate: no moment to look again at'


def test_the_controller_holds_a_cue_the_gate_parks_and_names_the_moment_to_look_again(call):
    rig = call(fast_text='on')
    c = rig.c

    class Parks:
        def parks(self, cue, now):
            return now + 2.0
    a = cue()
    held, until = c.hold(a, Parks())
    assert held is True and until is not None and until > c.clock()

    class Free:
        def parks(self, cue, now):
            return None
    assert c.hold(a, Free())[1] is None
    wire, looked = rig.w.wire, []
    wire.v5_gate, wire._release_at = Parks(), looked.append
    wire._can_play(a)
    assert len(looked) == 1 and looked[0] > 0, 'the transport looks again at the moment the controller names'


# -- (a) the closed-class veto: stale at once ---------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('old, now, code', [
    ('Сколько будет сорок на два', 'Сколько будет пятьдесят на два', 'veto_number'),
    ('Когда было крещение Руси', 'Когда было крещение Руси в 988 году', 'veto_date'),
    ('Нужно нагревать жидкость', 'Нужно не нагревать жидкость', 'veto_negation'),
])
def test_a_number_a_date_or_a_turned_negation_makes_the_old_answer_stale_at_once_even_with_a_newer_answer_coming(old, now, code):
    c, gate, a, notes = job_gate(old, now, 'Восемьдесят.', newer=('Сто.', False), mode='on')
    assert gate.parks(a, 100.0) is None, 'a veto is not held: nothing to wait for'
    got = gate.handed(a, 100.0)
    assert got and c.stale_calls == [(7, now)] and notes[0][1]['code_answers'] == code and notes[0][1]['would_answers'] == 'refuse' and notes[0][1]['did'] == 'refused'


def test_the_veto_reads_no_stem_a_turned_negation_in_a_short_utterance_is_stale_and_both_verdicts_are_written():
    c = Controller(question='Нужно нагревать жидкость')
    c.ledger.turns.append({'id': 'u2', 'role': 'user', 'valid': True, 'final': False, 'text': 'нет, не надо'})
    notes = []
    v5_gate.attach({'v5_answer_gate': 'shadow', 'v5_gate_same': 'answers'}, c, Wire(), note=lambda ev, **f: notes.append(f)).handed(cue(), 101.0)
    assert notes[0]['would'] == 'refuse' and notes[0]['code_answers'] == 'veto_negation' and notes[0]['would_words'] in ('pass', 'refuse') and notes[0]['code_words'] in v5_gate.CODES


# -- (b) the relation is unknown: the answers are compared --------------------------------------------------------------------------------------------------------------

def test_the_stem_rule_calls_it_another_question_the_answers_rule_does_not_decide_by_words():
    c, gate, a, notes = job_gate(*CHANGED, 'Париж.', newer=('Париж.', True))
    gate.handed(a, 101.0)
    row = notes[0][1]
    assert row['would_words'] == 'refuse' and row['would_answers'] == 'pass' and row['would'] == 'pass' and row['code_answers'] == 'answers_agree'
    c2, gate2, a2, notes2 = job_gate(*CHANGED, 'Париж.', newer=('Париж.', True), same='words')
    gate2.handed(a2, 101.0)
    assert notes2[0][1]['would'] == 'refuse' and notes2[0][1]['meaning'] == 'stale' and notes2[0][1]['why'] == 'subject', 'under "words" the old rule decides, as it did'


@pytest.mark.parametrize('old_answer, new_answer, over, code, would', [
    ('Около 2 миллионов.', 'Около 2 миллионов человек.', True, 'answers_agree', 'pass'),
    ('Около 2 миллионов.', 'Около 3 миллионов.', True, 'answer_changed', 'refuse'),
    ('Около 2 миллионов.', 'Около 3 миллионов.', False, 'answer_changed', 'refuse'),
    ('Да, можно.', 'Да, конечно можно.', True, 'answers_agree', 'pass'),
    ('Да, можно.', 'Нет, нельзя.', True, 'answer_changed', 'refuse'),
    ('Это было в 1988 году.', 'Это было в 1987 году.', True, 'answer_changed', 'refuse'),
    ('Париж.', 'Берлин.', True, 'answer_new_no_things', 'refuse'),
    ('Париж.', 'Париж.', True, 'answers_agree', 'pass'),
])
def test_two_answers_are_compared_by_their_numbers_dates_and_yes_or_no(old_answer, new_answer, over, code, would):
    c, gate, a, notes = job_gate(*CHANGED, old_answer, newer=(new_answer, over))
    gate.handed(a, 101.0)
    row = notes[0][1]
    assert (row['code_answers'], row['would_answers']) == (code, would)


def test_on_when_the_answers_agree_the_old_one_goes_and_nothing_is_asked_again():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 2 миллионов.', True), mode='on')
    assert gate.handed(a, 101.0) is None and c.stale_calls == [] and 'did' not in notes[0][1]
    assert notes[0][1]['code_answers'] == 'answers_agree'


def test_on_when_the_answers_differ_the_old_one_is_refused_with_the_reason_and_the_newer_is_asked():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 3 миллионов.', True), mode='on')
    got = gate.handed(a, 101.0)
    assert got and c.stale_calls == [(7, CHANGED[1])] and notes[0][1]['did'] == 'refused'
    assert notes[0][1]['code_answers'] == 'answer_changed' and notes[0][1]['reason_ru'] == 'ответ изменился'


def test_the_hold_is_within_the_one_cap_and_ends_at_it():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около', False), mode='on')      # a newer answer is on its way, nothing to compare yet
    cap = v5_gate.COSTS['hold_unknown_s']
    assert gate.parks(a, 100.0) == 100.0 + cap and gate.parks(a, 100.0 + cap / 2) == 100.0 + cap
    assert gate.parks(a, 100.0 + cap) is None, 'at the cap: it goes'
    gate.handed(a, 100.0 + cap)
    row = notes[0][1]
    assert row['code_answers'] == 'identity_unchecked' and row['would_answers'] == 'pass' and row['reason_ru'] == 'тождество не проверено' and c.stale_calls == []


def test_when_the_newer_answer_comes_in_time_the_hold_ends_with_a_verdict_on_the_answers():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около', False), mode='on')
    assert gate.parks(a, 100.0) is not None
    c.ledger.turns.clear()
    gate.wire.fast.looks[CHANGED[1]] = ('Около 3 миллионов.', False)
    assert gate.parks(a, 100.5) is None, 'comparable at once: no more waiting'
    assert gate.handed(a, 100.5) and notes[0][1]['code_answers'] == 'answer_changed'


def test_nothing_in_preparation_no_hold_and_the_old_answer_goes_marked_unchecked():
    c, gate, a, notes = job_gate(*CHANGED, 'Париж.', newer=None, mode='on')
    assert gate.parks(a, 100.0) is None
    assert gate.handed(a, 100.0) is None and c.stale_calls == []
    assert notes[0][1]['code_answers'] == 'identity_unchecked' and notes[0][1]['would'] == 'pass'


def test_parks_holds_only_in_on_with_the_rule_answers_and_only_a_first_portion_of_a_job_or_revised_answer():
    for mode, same in (('shadow', 'answers'), ('on', 'words')):
        c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около', False), mode=mode, same=same)
        assert gate.parks(a, 100.0) is None, (mode, same)
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около', False), mode='on')
    assert gate.parks(cue(index=1, text='Около 2.'), 100.0) is None, 'an answer half said is not held'
    c2 = Controller(question='Кто написал Войну и мир')
    c2.plan['question'] = 'Кто написал Анну Каренину'
    plan = v5_gate.attach({'v5_answer_gate': 'on'}, c2, Wire(Fast({}, {'Кто написал Войну и мир': ('Толстой', False)})))
    assert plan.parks(cue(), 100.0) is None, 'a plan of an older question given back on purpose (G3) is no revised answer'


# -- (d) / (c) --------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_an_answer_with_no_exact_things_and_a_differing_newer_one_the_newer_goes():
    c, gate, a, notes = job_gate(*CHANGED, 'Это столица.', newer=('Это город на реке.', True), mode='on')
    assert gate.handed(a, 101.0) and notes[0][1]['code_answers'] == 'answer_new_no_things' and c.stale_calls


def test_the_refusals_are_not_a_loop_the_second_is_spent():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 3 миллионов.', True), mode='on')
    gate.handed(a, 101.0)
    assert gate.handed(cue(revision=8, text='Около 2 миллионов.'), 103.0) is None and notes[-1][1]['did'] == 'passed_refusals_spent'


# -- shadow: both verdicts, codes only --------------------------------------------------------------------------------------------------------------------------------

def test_shadow_writes_both_verdicts_with_a_code_from_the_closed_list_and_no_words_and_changes_nothing():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 3 миллионов.', True))
    assert gate.parks(a, 100.0) is None and gate.handed(a, 100.0) is None and c.stale_calls == []
    row = notes[0][1]
    assert row['same'] == 'answers' and row['would_words'] == 'refuse' and row['would_answers'] == 'refuse' and row['code_words'] in v5_gate.CODES and row['code_answers'] in v5_gate.CODES
    flat = json.dumps(row, ensure_ascii=False)
    for word in ('Войну', 'Каренину', 'миллион', 'написал'):
        assert word not in flat, 'no utterance and no answer text in the journal'
    assert all(isinstance(v, (int, float, str, type(None))) for v in row.values())
    assert row['n_old'] == 1 and row['n_new'] == 1, 'counts of exact things, not the things'


def test_every_code_the_gate_can_write_is_in_the_closed_list():
    assert {'veto_number', 'veto_date', 'veto_negation', 'answers_agree', 'answer_changed', 'answer_new_no_things', 'identity_unchecked', 'same_words', 'question_unknown', 'not_judged'} <= set(v5_gate.CODES)
    assert v5_gate.CODES['answer_changed'] == 'ответ изменился' and v5_gate.CODES['identity_unchecked'] == 'тождество не проверено'


def test_a_question_not_known_and_an_identical_wording_are_told_and_pass():
    c, gate, a, notes = job_gate('', 'Что такое инфляция', 'Это рост цен.', newer=('Это рост цен.', True))
    gate.handed(a, 101.0)
    assert notes[0][1]['code_answers'] == 'question_unknown' and notes[0][1]['would_answers'] == 'pass'
    c, gate, a, notes = job_gate('Что такое инфляция', 'что такое инфляция', 'Это рост цен.', newer=None)
    gate.handed(a, 101.0)
    assert notes[0][1]['code_answers'] == 'same_words' and notes[0][1]['would_answers'] == 'pass'


def test_the_gate_still_never_raises_into_the_call_under_the_new_rule():
    class Broken:
        @property
        def question_text(self):
            raise RuntimeError('x')
    gate = v5_gate.attach({'v5_answer_gate': 'on'}, Broken(), Wire())
    assert gate.handed(cue(), 1.0) is None and gate.parks(cue(), 1.0) is None

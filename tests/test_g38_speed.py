"""G38: the way to the first cue on the stand (``tools/replay/speed.py``) and the cuts of it, each behind a flag that is off by default. Numbers and «не» are not weakened.

Times are the stand's (``speed.PHONE``: the cloud's final 3.3 s after the speech, the model's first text 1.9 s, the search 2.0 s, the phone's numbers of BACKLOG E93), not a laptop's nor a phone's.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from echo_sync import two_witnesses as W                                         # noqa: E402
from echo_sync.settings import DEFAULTS, resolve                                          # noqa: E402
from tools.replay import first_clock as F                                       # noqa: E402
from tools.replay import speed as G                                             # noqa: E402


def stable(*texts):
    """The stable piece after the cloud's open turn grew through ``texts`` and then held the last one (a pause)."""
    p = W.Pieces()
    for text in texts:
        p.feed('t', text)
    return p.feed('t', texts[-1], still=True)


MULT = ('Сколько', 'Сколько будет 4', 'Сколько будет 4 умножить на', 'Сколько будет 4 умножить на 8?')


# --- cut 1 (g38 ``witness_mark``): in the base already WITHOUT a flag (G32, laptop c20): a number closed by «?»/«!» at the end of the cloud's open turn is the cloud's.
# c22-speed keeps the base and adds no flag that would only switch the laptop's own behaviour off.

def test_no_witness_mark_flag_the_base_closes_on_a_mark():
    assert 'witness_mark' not in resolve({})
    assert stable(*MULT).endswith('на 8')


def test_a_number_closed_by_a_question_mark_is_stable():
    piece = stable(*MULT)
    assert W.verdict('сколько будет четыре умножить на восемь', piece) == W.SOUND


def test_another_number_in_the_closed_turn_cuts():
    assert W.verdict('сколько будет четыре умножить на восемь', stable('Сколько', 'Сколько будет 4 умножить на', 'Сколько будет 4 умножить на 9?')) == W.CUT


@pytest.mark.parametrize('texts', [
    ('Сколько', 'Сколько будет 4 умножить на 8'),            # no mark: «8» may still be «80»
    ('Сколько', 'Сколько будет 4 умножить на 2,'),           # a comma: «2,5»
    ('Сколько', 'Сколько будет 4 умножить на 2.'),           # a point: «2.5»
    ('Нужно', 'Нужно не'),                                  # «не» at the end
    ('Нужно', 'Нужно не?'),                                 # «не» is never closed by a mark: the next word is what is denied
])
def test_an_open_number_or_a_negation_still_waits(texts):
    piece = stable(*texts)
    assert not W.norm_words(piece) or W.norm_words(piece)[-1] not in ('8', '2', 'не'), piece


def test_the_stand_mult_goes_on_two_witnesses_before_the_final():
    """Phone times: the answer is ready at 2.0 s, the final comes at 3.3 s: the cue goes on two witnesses, right."""
    row = G.scene(1, family='mult', profile=F.candidate(), **G.PHONE)
    assert row['right'] and not row['violations']
    assert row['cue'] < row['final'] - 0.5, row


# --- cut 3 (after G32): a personal question the model's route takes is prepared before the final: the owner's rule of fast_text since f84a05a9, the key ``fast_private`` is deleted ----------

def test_fast_private_has_no_key():
    from echo_sync.settings import DEFAULTS
    assert 'fast_private' not in DEFAULTS and 'fast_private' not in resolve({'fast_text': 'on', 'fast_private': 'on'})


def test_a_personal_question_is_prepared_before_the_final():
    """«Если у меня было 70 рублей…»: «у меня» closes the public search, not the job its final goes to (``no_search``). Phone times: before the rule the job began at the final, 3.3 s; now it begins on the ear's text."""
    cut = G.scene(0, family='money', profile=F.candidate(), **G.PHONE)
    assert cut['right'] and not cut['violations']
    assert cut['job'] < 1.0, cut


def test_privacy_still_keeps_a_personal_question_from_the_search():
    """The search gate is the same: a question about «у меня» never reaches the public lookup."""
    row = G.scene(0, family='money', profile=F.candidate(), early=True, **G.PHONE)
    assert row['lookups'] == 0 and row['right']


# --- cut 2, the early search (the call's ``ear_lookup``, off by default; the code is Q1 / B9): the search starts from the ear's text -------------

def test_the_search_starts_from_the_ear_and_the_cue_comes_two_seconds_sooner():
    base = G.scene(0, family='article', profile=F.candidate(), **G.PHONE)
    cut = G.scene(0, family='article', profile=F.candidate(), early=True, **G.PHONE)
    assert base['right'] and cut['right'] and not cut['violations']
    assert base['search'] >= base['final'] - 0.05 and cut['search'] < 1.0
    assert cut['cue'] < base['cue'] - 1.5 and cut['lookups'] == 1, (base, cut)


def test_the_stand_turns_the_early_search_on_from_the_profile():
    from tools.replay import stand as A
    s = A.Stand(0, length=1.0, profile={**F.candidate(), 'prefetch': 'on'})
    try:
        assert s.w.wire.early.enabled
    finally:
        s.close()
    s = A.Stand(0, length=1.0, profile=F.candidate())
    try:
        assert not s.w.wire.early.enabled
    finally:
        s.close()


# --- found on the way (g38, verb seed 15): «Сейчас,» at the head is no name, the question after a preface is not «said to a person» -------------------------

@pytest.mark.parametrize('text', ['Сейчас, подожди, я подумаю. Нужно не увеличивать, а уменьшать эту жидкость при таком давлении?',
                                  'Теперь, нужно не нагревать, а охлаждать эту жидкость?', 'Так, сейчас, какой налог платит ИП?'])
def test_a_preface_adverb_is_no_vocative(text):
    from echo_sync import gate_text
    assert gate_text.decide(text).kind != gate_text.TALK


@pytest.mark.parametrize('text', ['Лена, ты придёшь завтра?', 'Серёж, а вы где были?'])
def test_a_name_still_is(text):
    from echo_sync import gate_text
    assert gate_text.decide(text) == gate_text.Verdict(gate_text.TALK, 'to_person')


# --- found on the way (g38, fuzz with the candidate's flags): «стоп» while the answer is on its way, no portion yet ----------------------------------------------
# The ear heard the stop and did nothing (``_ear_verdict``: ``nothing_waits``); the cloud's final of it came 2-5 s later, the cue between: an answer after «стоп».
# 7 of 600 seeds of the base (A2 «after стоп»). The patch: cloud_context/reports/g38-speed.stop.controlled_media.diff.

CANDIDATE_STAND = {'prepare_wide': 'on', 'gate_text': 'on', 'instant': 'on', 'spare_helper': 'on', 'open_overlap': 'on', 'warm_start': 'on'}


def test_stop_in_flight_has_no_key_it_is_a_rule_of_the_fast_channel():
    assert 'stop_in_flight' not in DEFAULTS and 'stop_in_flight' not in resolve({'fast_text': 'on', 'stop_in_flight': 'on'})


@pytest.mark.parametrize('seed', [493, 88])
def test_no_cue_after_a_stop_said_while_the_answer_is_on_its_way(seed):
    from tools.replay import stand as A
    out = A.run(seed, profile={**A.profile_of(seed), **CANDIDATE_STAND})
    assert not [v for v in out.violations if v[0] == 'A2' and 'стоп' in v[2]], out.violations

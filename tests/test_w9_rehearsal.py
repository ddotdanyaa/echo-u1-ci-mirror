"""w9-rehearsal: the stand of tools/rehearsal. Its plan, its ear and latency models, its board, and: a controller known to be broken turns the board red."""
import difflib
import random
import statistics

import pytest

from tools.rehearsal import ear_model as E
from tools.rehearsal import plan as P
from tools.rehearsal import run as R
from tools.rehearsal import score, sim
from tools.replay.stand import Outcome, Said

SEEDS = range(4)


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def boards(name, mutant=None, seeds=SEEDS):
    return score.total([score.board(sim.play(sim.Spec(name), s, mutant=mutant, keep_log=False))[0] for s in seeds])


def test_the_plan_is_one_line_per_rehearsal_and_every_line_parses():
    assert list(P.PLAN) == [f'Р{n:03d}' for n in range(1, 105)]      # c23: the laptop's c18 added Р101-Р104 (plan.py: «Р001-Р104»)
    for name in P.PLAN:
        spec = sim.Spec(name)
        assert spec.title and spec.minutes > 0
        for family in spec.ask:
            assert family in P.BANK or family in ('money', 'mult', 'verb', 'year', 'article', 'compound'), (name, family)
        for kind in spec.others:
            assert kind in sim.OTHERS or kind in ('passer', 'answer_other'), (name, kind)
    assert P.names('Р001-Р003,Р100') == ['Р001', 'Р002', 'Р003', 'Р100'] and P.names('P064') == ['Р064']


def test_the_ear_model_is_learned_from_n2_and_noise_makes_it_worse():
    learned, stored = E.learn(), E.load()
    assert {k: learned[k] for k in ('runs', 'words', 'sub', 'del', 'ins')} == {k: stored[k] for k in ('runs', 'words', 'sub', 'del', 'ins')}
    assert learned['runs'] == 536 and 0.06 < learned['sub'] + learned['del'] + learned['ins'] < 0.10      # clean N2: 7.8 % of the words
    assert learned['subs']['ну'].get('но')                                                                  # a confusion of N2 kept as it was
    ear, text = E.Ear(stored), 'если у меня было семьдесят рублей и я потратил пятьдесят'

    def wrong(noise):
        r, n = random.Random(7), 0
        for _ in range(300):
            ops = difflib.SequenceMatcher(None, text.split(), ear.hear(r, text, noise).split(), autojunk=False).get_opcodes()
            n += sum(max(a2 - a1, b2 - b1) for op, a1, a2, b1, b2 in ops if op != 'equal')
        return n
    assert wrong('clean') < wrong('snr10') < wrong('snr5')


def test_latencies_follow_the_chain_by_median_and_p90():
    r = random.Random(3)
    xs = sorted(sim.lognormal(r, 2.35, 3.48) for _ in range(20000))
    assert abs(statistics.median(xs) - 2.35) < 0.05 and abs(xs[int(0.9 * len(xs))] - 3.48) < 0.1


def test_a_seed_is_the_same_conversation_every_time():
    a, b = (sim.play(sim.Spec('Р021'), 5, keep_log=False) for _ in range(2))
    assert [(u.onset, u.text, u.ear) for u in a.said] == [(u.onset, u.text, u.ear) for u in b.said]
    assert [c[:2] for c in a.cues] == [c[:2] for c in b.cues]


def test_the_real_controller_answers_most_questions_of_a_plain_rehearsal():
    b = boards('Р001')
    assert b['questions'] >= 20 and b['answered'] >= 0.6 * b['questions']
    assert 'nothing_answered' not in b['red'] and 'crash' not in b['red']


@pytest.mark.parametrize('mutant, red', [('mute', 'missed'), ('stale', 'old_answer')])
def test_a_broken_controller_turns_the_board_red(mutant, red):
    real, broken = boards('Р001'), boards('Р001', mutant)
    assert broken['red'], broken
    assert red in broken['red'] and red not in real['red']
    assert broken['rate'][red] > real['rate'][red]


def _out(said, cues, states=()):
    out = Outcome(1, {'rehearsal': 'Р000'})
    out.said, out.cues, out.states = said, cues, list(states)
    return out


def _said(n, kind, text, onset, offset, meaning=None, who='user'):
    u = Said(n, kind, text, text.lower(), onset, offset, ear_at=offset + 0.2, final_at=offset + 2.0, meaning=meaning)
    u.who = who
    return u


def test_the_board_counts_each_kind_on_a_record_built_for_it():
    q1 = P.Fact('num', ('a',), 'Сколько дней в високосном году?', 'В високосном году 366 дней.')
    q2 = P.Fact('num', ('b',), 'Сколько часов в неделе?', 'В неделе 168 часов.')
    said = [_said(1, 'question', q1.text, 1.0, 3.0, ('q', q1), 'friend'), _said(2, 'question', q2.text, 10.0, 12.0, ('q', q2), 'friend'),
            _said(3, 'other', 'Ой, а где тут столовая?', 30.0, 31.0, None, 'chatter')]
    cue = lambda t, text, rev, index: (t, text, rev, index, (text,), False, False, None)
    cues = [cue(5.0, q1.reply, 1, 0), cue(16.0, q1.reply, 1, 0), cue(32.0, 'Обь вместе с Иртышом.', 3, 0)]
    out = _out(said, cues, [(5.0, 1, 0, False, False, False, 1), (31.5, 1, 1, False, False, False, 1)])
    out.violations = [('A2', 16.0, 'cue of the older question 1 after question 2')]
    m, eps = score.board(out)
    assert m['to_cue'] == [2.0] and m['answered'] == 1
    assert m['false_cue'] == 1 and m['old_answer'] == 1 and m['false_step'] == 1
    assert m['missed'] == 1                                     # question 2: only the old answer came, and nothing until the end
    assert {e['kind'] for e in eps} >= {'false_cue', 'old_answer', 'false_step', 'missed'}


def test_one_command_writes_a_board_and_two_boards_compare(tmp_path):
    a = {'head': 'aaa', 'flags': '', 'seeds': 1, 'seed0': 0, 'cap': 1, 'jobs': 1, 'mutant': None, 'wall': 1, 'long_seeds': None,
         'boards': {'Р001': score.total([score.board(sim.play(sim.Spec('Р001'), 0, keep_log=False))[0]])}, 'worst': [], 'red': []}
    b = {**a, 'head': 'bbb', 'boards': {'Р001': {**a['boards']['Р001'], 'missed': a['boards']['Р001']['missed'] + 2, 'red': ['missed']}}}
    text = R.markdown(a)
    assert '| Р001 | Один вопрос по ОП.09 |' in text and 'Худшие 20' in text
    diff = R.compare(a, b)
    assert '▲' in diff and '— → missed' in diff


def test_p1_a_code_with_a_leading_zero_is_the_same_number_as_the_ear_says_it():
    from echo_sync import fast_text as FT
    assert FT.refusal('что такое информационная безопасность по оп девять', 'Что такое информационная безопасность по ОП.09?') is None


def test_p1_another_number_is_still_refused():     # w10 item 2: P1 patch applied (fast_text._value without a leading zero)
    from echo_sync import fast_text as FT
    assert FT.refusal('сколько будет девять', 'сколько будет 90') == 'numbers'           # the patch must keep this one

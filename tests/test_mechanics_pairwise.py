"""P13 / U154 (OWNER_REQUIREMENTS 14.11, U-new-24): the mechanics do not break each other. For every scene of a call and every TWO always-on rules that act in it and belong to DIFFERENT families, what one of them
decides is the same with the other present or not (the effect of a rule is additive across families); a pair that is not goes into ``registry_proof/pairwise/conflicts.json`` as a row with its reason, or the test fails.

The rules and the way each is taken out are DATA (``inventory``): a family appears here when it has rows a test can drop without editing its owner, today
    kind    a row of the judge's table (``utterance_judge.JUDGE_RULES``; ``base`` and the two vetoes of the end are the walker's own, not rows to drop)
    speech  a row of the gate (``ControlledMedia.ACTS``: the row stays, its steps are emptied: the act is asked and does nothing)
The memory kinds (``conversation_ledger.KINDS``), the deadlines of the timers (P08) and the roads join the day their rows can be dropped; adding them is a line of ``inventory``, no other edit.

How it is measured (the real ControlledMedia, ``helpers_night_memory.Call``, one run a configuration):
  1. the scene is run with everything on: the rules that ACT are those whose row spoke / whose act was asked; the SIGNATURE is what the call DECIDED (the judge's lines and the acts the gate was asked for with
     their verdict): decisions, not outputs (the ``decision`` lines of the log are the consequence of an act and are left out);
  2. each acting rule is taken out alone: ``D(a)`` is the difference of the signatures (a multiset of the items that differ); a rule whose removal changes nothing is inert here and is not paired;
  3. a pair where the effect of one contains the lines of the other (one decides whether the other is asked: a kind verdict feeds a speech act) is a dependency and is left out; for each other pair (a, b) of different families that both act: the effect of ``a`` with ``b`` already taken out, ``D(a | not b)``, must equal ``D(a)``; and ``D(b | not a)`` must equal ``D(b)``. Any other result is an interaction.
First-order only: a rule that did not act in a scene cannot be shown to interact in it (the scenes of every row of the judge's table are in the set, so each row acts in at least one)."""
import json
import logging
import re
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import pytest

import helpers_night_memory as M
from echo_sync import utterance_judge as J
from echo_sync.controlled_media import ControlledMedia

ROOT = Path(__file__).resolve().parents[1]
CONFLICTS = ROOT / 'registry_proof' / 'pairwise' / 'conflicts.json'
ANSWER = 'Первая часть ответа про инерцию. Вторая часть ответа про силу. Третья часть ответа про массу.'
Q = 'Что такое инерция?'
# the scenes: (said before..., the last thing said). The last four are rows of the recorded corpus of calls (``tests/fixtures/brain_eval_n2.json``), read from the fixture when it is there.
SCENES = [((), Q), ((Q,), 'повтори'), ((Q,), 'дальше'), ((Q,), 'стоп'), ((Q,), 'но ведь это не так'), ((Q,), 'ну пример'), ((Q,), 'Что такое сила?'),
          ((), 'Миша, ты зарядку не видел?'), ((Q,), 'в смысле'), ((Q,), 'продолжай')]
CORPUS = ('b2_CH_009', 'b2_RH_048', 'b2_DS_003', 'b2_CH_042')
KINDS = {reason: row[0] for reason, row in ControlledMedia.ACTS.items()}      # the kind of act a reason is asked as: reasons of one kind ride one road (the cue and the wire's question before it are both ``speak``)
UNDROPPABLE = {'base', 'recall', 'early_tail', 'not_addressed', 'going_on', 'own_voice'}      # the walker's own rows: the verdict is made by ``base``; the others are the first and the vetoes after the table


def corpus_scenes():
    path = ROOT / 'tests' / 'fixtures' / 'brain_eval_n2.json'
    if not path.is_file():
        return []
    rows = {row['id']: row for row in json.loads(path.read_text(encoding='utf-8'))['rows']}
    return [(tuple(c['text'] for c in rows[i]['context'] if c['kind'] != 'answer')[-2:], rows[i]['text']) for i in CORPUS if i in rows]


def inventory():
    """``{family: [rule names]}``: the rows of the families that have a table a test can drop a row from."""
    return {'kind': [row.name for row in J.JUDGE_RULES if row.name not in UNDROPPABLE], 'speech': sorted(ControlledMedia.ACTS)}


@contextmanager
def instrumented(fired, items, off=()):
    """The rules with their eyes on (``fired`` collects the names that acted) and the rules in ``off`` taken out. Always on, in every run: the same instrument in all of them."""
    table, acts, original = J.JUDGE_RULES, dict(ControlledMedia.ACTS), ControlledMedia._act

    def watch(rule):
        def fn(c):
            before = (id(c.decision), c.text, c.going, c.disputed, len(c.chain))
            out = rule.fn(c)
            if out is not None or before != (id(c.decision), c.text, c.going, c.disputed, len(c.chain)):
                fired.add(('kind', rule.name))
            return out
        return J.Rule(rule.name, fn, rule.pos_examples, rule.neg_examples, rule.after)

    def act(self, kind, reason, **keywords):
        fired.add(('speech', reason))
        out = original(self, kind, reason, **keywords)
        items[('act', reason, out[0], kind)] += 1
        return out
    J.JUDGE_RULES = tuple(watch(rule) for rule in table if ('kind', rule.name) not in off)
    ControlledMedia.ACTS = {reason: ((row[0], (), row[2], row[3]) if ('speech', reason) in off else row) for reason, row in acts.items()}
    ControlledMedia._act = act
    try:
        yield
    finally:
        J.JUDGE_RULES, ControlledMedia.ACTS, ControlledMedia._act = table, acts, original


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def signature(tmp_path, scene, off=()):
    """``(signature, fired)``: what the call decided for ``scene`` with the rules in ``off`` taken out. The signature is a Counter of items; an exception is an item (it differs from a call that goes on)."""
    fired, handler = set(), Lines()
    log = logging.getLogger('echo-sync')
    level, log.level = log.level, logging.INFO
    log.addHandler(handler)
    items = Counter()
    try:
        with instrumented(fired, items, off):
            call = M.Call(tmp_path, mind=lambda request: ANSWER, fast_text='on')
            try:
                for said in scene[0]:
                    call.say(said)
                    call.pump(1.0)
                call.say(scene[1])
                call.pump(2.0)
            except Exception as error:      # noqa: BLE001 - a rule taken out may break what stood on it: that is a difference, named
                items[('raised', type(error).__name__)] += 1
            finally:
                call.close()
    finally:
        log.removeHandler(handler)
        log.level = level
    for line in handler.lines:
        fields = dict(re.findall(r'(\w+)=(\S+)', line))
        if line.startswith('echo-sync judge '):
            items[('judge', fields.get('kind'), fields.get('reason'), fields.get('rule'))] += 1
    return items, fired


def effect(with_it, without_it):
    """What taking a rule out changes: the items that are in one signature more than in the other, each with the side it is on."""
    return frozenset(('+', key, n) for key, n in (with_it - without_it).items()) | frozenset(('-', key, n) for key, n in (without_it - with_it).items())


def about(item, rule):
    """Is ``item`` (of an effect) a line of the rule itself: its act asked (the verdict of an emptied row differs by the instrument) or its row of the judge. Such lines (an act of the same kind rides the same road) are the rule's own presence, not what it does to others."""
    key = item[1]
    return (rule[0] == 'speech' and key[0] == 'act' and (key[1] == rule[1] or key[3] == KINDS.get(rule[1]))) or (rule[0] == 'kind' and key[0] == 'judge' and key[3] == rule[1])


def seen_without(change, *rules):
    """The effect ``change`` without the lines of the ``rules`` themselves (how often a rule is asked depends on its neighbours by design; what it does to the OTHERS is what must not)."""
    return frozenset(item for item in change if not any(about(item, rule) for rule in rules))


def interactions(tmp_path, scene):
    """``[(a, b, effect of a, effect of a without b)]`` for the pairs of acting rules of different families whose effects are not additive, and the acting rules."""
    full, fired = signature(tmp_path / 'full', scene)
    droppable = {(family, name) for family, names in inventory().items() for name in names}
    fired &= droppable      # the walker's own rows are no rules to drop
    alone = {rule: signature(tmp_path / ('off_' + '_'.join(rule)), scene, off={rule})[0] for rule in sorted(fired)}
    acting = [rule for rule in sorted(fired) if effect(full, alone[rule])]
    found, n = [], 0
    for i, a in enumerate(acting):
        for b in acting[i + 1:]:
            if a[0] == b[0]:
                continue
            if any(about(item, b) for item in effect(full, alone[a])) or any(about(item, a) for item in effect(full, alone[b])):
                continue      # a DEPENDENCY: one decides whether the other is asked (a kind verdict is what a speech act is asked for); its effect goes through the other by design, it is not a clash
            n += 1
            both = signature(tmp_path / ('pair_%d' % n), scene, off={a, b})[0]
            if seen_without(effect(full, alone[a]), a, b) != seen_without(effect(alone[b], both), a, b):
                found.append((a, b, 'what %s does to the others changes when %s is out' % (a[1], b[1])))
            elif seen_without(effect(full, alone[b]), a, b) != seen_without(effect(alone[a], both), a, b):
                found.append((b, a, 'what %s does to the others changes when %s is out' % (b[1], a[1])))
    return found, acting, len(fired)


def recorded():
    path = CONFLICTS
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {'conflicts': []}


def scene_id(scene):
    return ' / '.join(scene[0] + (scene[1],))[:60]


def all_scenes():
    return SCENES + corpus_scenes()


@pytest.mark.parametrize('scene', all_scenes(), ids=[scene_id(scene) for scene in all_scenes()])
def test_two_rules_of_different_families_keep_each_others_decisions_on_a_scene(scene, tmp_path, request):
    found, acting, seen = interactions(tmp_path, scene)
    request.config._p13_pairwise = getattr(request.config, '_p13_pairwise', {})
    request.config._p13_pairwise[scene_id(scene)] = {'acting': acting, 'conflicts': found, 'asked': seen}
    allowed = {(row['scene'], tuple(row['a']), tuple(row['b'])) for row in recorded()['conflicts']}
    new = [(scene_id(scene), a, b, why) for a, b, why in found if (scene_id(scene), a, b) not in allowed and (scene_id(scene), b, a) not in allowed]
    assert new == [], 'rules of two families break each other on this scene (record the pair in registry_proof/pairwise/conflicts.json with the reason, or make the effects independent): %s' % new


def test_every_family_with_a_table_is_in_the_inventory_and_the_rows_are_droppable():
    rows = inventory()
    assert set(rows) == {'kind', 'speech'} and len(rows['kind']) >= 10 and len(rows['speech']) >= 10, rows
    with instrumented(set(), Counter(), off={('kind', rows['kind'][0]), ('speech', rows['speech'][0])}):
        assert rows['kind'][0] not in [row.name for row in J.JUDGE_RULES]
        assert ControlledMedia.ACTS[rows['speech'][0]][1] == ()
    assert rows['kind'][0] in [row.name for row in J.JUDGE_RULES] and ControlledMedia.ACTS[rows['speech'][0]][1] != (), 'the tables are put back'


def test_the_recorded_conflicts_are_rows_with_a_reason_and_no_pair_repeats():
    rows = recorded()['conflicts']
    assert all(row.get('scene') and row.get('a') and row.get('b') and len(row.get('why', '')) > 20 for row in rows), 'a conflict is written with its scene, both rules and why it stands'
    keys = [(row['scene'], tuple(row['a']), tuple(row['b'])) for row in rows]
    assert len(keys) == len(set(keys))


def test_the_lines_of_a_rule_itself_are_not_what_it_does_to_the_others():
    change = effect(Counter({('act', 'cue', 'do', 'speak'): 1, ('act', 'authorized', 'do', 'speak'): 1, ('judge', 'q', 'r', 'remark_form'): 1}), Counter())
    assert seen_without(change, ('speech', 'cue')) == frozenset({('+', ('judge', 'q', 'r', 'remark_form'), 1)}), 'the cue and the wire question before it ride one road'
    assert len(seen_without(change, ('kind', 'remark_form'))) == 2
    assert seen_without(change, ('kind', 'other')) == change


def test_the_effect_of_a_rule_is_the_difference_of_two_signatures_both_ways():
    a, b = Counter({('judge', 'question'): 1, ('cue', 'x'): 1}), Counter({('judge', 'quiet'): 1, ('cue', 'x'): 1})
    assert effect(a, a) == frozenset()
    assert effect(a, b) and effect(a, b) != effect(b, a) and effect(a, b) == frozenset({('+', ('judge', 'question'), 1), ('-', ('judge', 'quiet'), 1)})

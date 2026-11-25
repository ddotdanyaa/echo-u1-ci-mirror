"""Independent attack on the answer gate without «words instead of meaning» (v5_gate.py, ``v5_gate_same`` = answers).

Tests only, built by classes of variants: (a) the outcome must NOT change (fillers, a polite frame, a recogniser error, the same thing in other words, duplicate delivery, other timing, a restart),
(b) the outcome MUST change (a number, a date, a negation, a correction). A class test loops over its variants and fails with the count and the first examples: «N of M variants». Bounds on time and size are
«стартовое» (nothing is measured on the laptop). The pairs are the measurement's dev pairs (REVIEW_20261112_V6/semantics/data/dev_pairs.jsonl); without that file the pair classes are skipped.
"""
import builtins
import json
import logging
import random
import time
from pathlib import Path

import pytest

from echo_sync import v5_gate
from test_v5_answer_gate import Controller, Wire, cue
from test_v5_gate_same import CHANGED, Fast, job_gate

PAIRS = Path('/home/user/echo-u1-cloud/cloud_context/REVIEW_20261112_V6/semantics/data/dev_pairs.jsonl')
CAP = v5_gate.COSTS['hold_unknown_s']
ANSWER = 'Банк закрывается в шесть.'


def pairs(relation, cls):
    if not PAIRS.exists():
        pytest.skip('dev pairs not present')
    return [(r['a'], r['b']) for r in map(json.loads, PAIRS.read_text(encoding='utf-8').splitlines()) if r['relation'] == relation and r['cls'] == cls]


def verdict(old_q, now_q, old_a=ANSWER, new_a=ANSWER, over=True, mode='shadow', same='answers', turns=(), **kw):
    """The row the gate writes for a job answer ``old_a`` made for ``old_q`` while the question stands as ``now_q`` (``new_a``: the job on the present form, or None)."""
    c, gate, a, notes = job_gate(old_q, now_q, old_a, newer=None if new_a is None else (new_a, over), mode=mode, same=same, **kw)
    for i, text in enumerate(turns):
        c.ledger.turns.append({'id': f'u{i + 2}', 'role': 'user', 'valid': True, 'final': False, 'text': text})
    got = gate.handed(a, 101.0)
    return c, gate, got, notes[0][1]


def sweep(items, bad, what):
    """A class test: every variant must satisfy; fails with the count."""
    failed = [x for x in items if bad(x)]
    assert not failed, f'{what}: {len(failed)} of {len(items)} variants fail, e.g. {failed[:3]}'


# -- (a) the outcome must not change: the same question in other words (closed-class veto only; the answers agree) ------------------------------------------------------------

def test_a_true_repeat_is_never_refused_while_the_answers_agree():
    out = {}
    for cls in ('reword', 'filler', 'politeness', 'asr_error', 'two_parts', 'numerals_words_digits'):
        items = pairs('same', cls)
        failed = [p for p in items if verdict(*p)[3]['would_answers'] != 'pass']
        if failed:
            out[cls] = (len(failed), len(items), failed[0])
    assert not out, f'a true repeat with identical answers refused (failed, of, first): {out}'


def test_a_filler_said_after_the_question_does_not_revise_it():
    fillers = ['ну, не знаю', 'э-э, не', 'одну секунду', 'раз, два, подожди', 'не-не-не, подожди', 'ага, понятно']
    q = 'Во сколько завтра закрывается банк'
    sweep(fillers, lambda t: verdict(q, q, turns=[t])[3]['would_answers'] != 'pass', 'a filler after the question made the answer stale')


def test_the_question_delivered_twice_is_not_a_revision_of_itself():
    q = 'Почему не работает интернет'
    c, gate, got, row = verdict(q, q, turns=[q])
    assert row['would_answers'] == 'pass', row['code_answers']


def test_three_forms_in_quick_succession_the_last_one_equal_to_the_first_is_the_same_question():
    q = 'Сколько будет сорок на два'
    c, gate, got, row = verdict(q, q, turns=['а пятьдесят?', 'ой, всё, сорок'])
    assert row['would_answers'] == 'pass', f'the first and the last form are one question: {row["code_answers"]}'


# -- (b) the outcome must change ------------------------------------------------------------------------------------------------------------------------------------------

def test_a_changed_number_including_an_ordinal_is_refused_at_once():
    items = pairs('correction', 'number')
    sweep(items, lambda p: verdict(*p, new_a=None)[3]['would_answers'] != 'refuse', 'changed number not refused')


def test_a_changed_date_or_day_is_refused_at_once():
    items = pairs('correction', 'date_time')
    sweep(items, lambda p: verdict(*p, new_a=None)[3]['would_answers'] != 'refuse', 'changed date/time/day not refused')


def test_an_added_or_removed_negation_is_refused_at_once():
    items = pairs('correction', 'negation_added') + pairs('correction', 'negation_removed')
    sweep(items, lambda p: verdict(*p, new_a=None)[3]['would_answers'] != 'refuse', 'added/removed negation not refused')


@pytest.mark.parametrize('relation, cls', [('correction', 'entity'), ('correction', 'tense'), ('correction', 'roles_swapped'), ('correction', 'modality'), ('correction', 'quantifier_comparison'),
                                           ('refinement', 'condition_added'), ('refinement', 'condition_removed'), ('new', 'new_topic'), ('new', 'question_word'), ('unrelated', 'unrelated')])
def test_where_the_closed_classes_are_silent_a_newer_answer_that_differs_decides(relation, cls):
    items = pairs(relation, cls)
    sweep(items, lambda p: verdict(*p, old_a='Толстой.', new_a='Достоевский.')[3]['would_answers'] != 'refuse', f'{relation}/{cls} with a differing newer answer')
    sweep(items, lambda p: verdict(*p, old_a='Около 2 миллионов.', new_a='Около 3 миллионов.')[3]['would_answers'] != 'refuse', f'{relation}/{cls} with another number in the newer answer')


def test_the_remaining_risk_without_a_newer_answer_is_told_every_time_never_called_agreement():
    """Not a defect of the code: the count of the silent variants is the remaining risk (printed; see the note)."""
    silent = [p for rel, cls in [('correction', 'entity'), ('correction', 'tense'), ('correction', 'roles_swapped'), ('correction', 'modality'), ('refinement', 'condition_added'),
                                 ('refinement', 'condition_removed'), ('new', 'new_topic'), ('new', 'question_word')] for p in pairs(rel, cls)]
    rows = [verdict(*p, new_a=None)[3] for p in silent]
    passed = [r for r in rows if r['would_answers'] == 'pass']
    print(f'REMAINING RISK: {len(passed)} of {len(rows)} changed questions go with the old answer when no newer one is there ({round(100 * len(passed) / len(rows))} %)')
    assert all(r['code_answers'] in ('identity_unchecked', 'veto_number', 'veto_date', 'veto_negation', 'same_words') for r in rows)


# -- the answers compared ---------------------------------------------------------------------------------------------------------------------------------------------------

def agree(old, new, over=True):
    return verdict(*CHANGED, old_a=old, new_a=new, over=over)[3]['would_answers'] == 'pass'


def test_two_true_repeats_whose_answers_have_no_exact_thing_and_differ_in_wording_are_not_a_change():
    wordings = [('Толстой.', 'Это Лев Толстой.'), ('Париж.', 'Столица Франции Париж.'), ('Можно.', 'Да, конечно можно.'), ('Вода кипит при ста градусах.', 'Кипит она при ста градусах.'),
                ('Это в Москве.', 'Москва.'), ('Лев Толстой.', 'Написал Толстой.')]
    sweep(wordings, lambda p: not agree(*p), 'the same fact in other words, no number in it, refused as a changed answer')


def test_numerals_in_words_against_digits_are_one_number():
    cases = [('Две тысячи.', 'Это 2000.'), ('Двадцать пять.', '25.'), ('Сто.', 'Около 100.'), ('Два с половиной.', '2,5.'), ('Тысяча.', '1000.'), ('Две тысячи рублей.', 'Всего 2000 рублей.')]
    sweep(cases, lambda p: not agree(*p), 'words against digits called a changed answer')


def test_a_polarity_word_added_or_dropped_while_the_exact_things_stay_is_not_a_change():
    cases = [('Да, можно.', 'Можно.'), ('Да, около 2 миллионов.', 'Около 2 миллионов.'), ('Да, в шесть.', 'В шесть.'), ('Нет, не было.', 'Не было.'), ('Да, можно.', 'Конечно, можно.')]
    sweep(cases, lambda p: not agree(*p), 'polarity word added/dropped')


def test_a_double_negation_is_a_yes():
    cases = [('Нельзя не согласиться.', 'Да, согласен.'), ('Не могу не признать.', 'Да, признаю.'), ('Не без этого.', 'Да.')]
    sweep(cases, lambda p: not agree(*p), 'double negation read as a plain no')


def test_yes_and_no_and_not_was_are_a_change():
    for old, new in [('Да, было.', 'Нет, не было.'), ('Да.', 'Нет.'), ('Не было.', 'Было.'), ('Да, было.', 'Не было.')]:
        row = verdict(*CHANGED, old_a=old, new_a=new)[3]
        assert row['would_answers'] == 'refuse', (old, new, row['code_answers'])


def test_the_same_numbers_with_another_unit_or_in_another_place_are_a_change():
    cases = [('До вокзала 5 километров.', 'До вокзала 5 метров.'), ('Иван 180, Пётр 175.', 'Пётр 180, Иван 175.'), ('Бежать 10 минут.', 'Бежать 10 часов.'),
             ('Скидка 20 процентов.', 'Скидка 20 рублей.'), ('Ему 30, ей 25.', 'Ей 30, ему 25.')]
    sweep(cases, lambda p: agree(*p), 'same numbers, other unit or other holder, called the same answer')


def test_one_answer_with_a_number_and_one_without_is_never_called_agreement():
    for old, new in [('Через 5 минут.', 'Скоро.'), ('Скоро.', 'Через 5 минут.')]:
        assert not agree(old, new), (old, new)


def test_a_newer_answer_not_yet_far_enough_waits_and_a_conflict_at_once_does_not():
    assert verdict(*CHANGED, old_a='Около 2 миллионов.', new_a='Около', over=False)[3]['code_answers'] == 'identity_unchecked'
    assert verdict(*CHANGED, old_a='Около 2 миллионов.', new_a='Около 3', over=False)[3]['code_answers'] == 'answer_changed'


# -- the newer answer after the older one was handed; the hold and its cap -----------------------------------------------------------------------------------------------------

def test_the_gate_does_not_refuse_the_newer_answer_after_the_older_was_said_no_second_asking():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=None, mode='on')
    assert gate.handed(a, 101.0) is None
    newer = cue(revision=8, nonce='n2', text='Около 3 миллионов.')
    gate.wire.fast.looks[CHANGED[1]] = ('Около 3 миллионов.', True)
    assert gate.handed(newer, 102.0) is None and c.stale_calls == []


def test_a_refused_answer_whose_reasking_gives_nothing_back_is_not_swallowed():
    def boom(cue_, asked):
        raise RuntimeError('x')
    bad = []
    for name, ask in (('empty list', lambda cue_, asked: []), ('exception', boom)):
        c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 3 миллионов.', True), mode='on')
        c.v5_stale = ask
        if gate.handed(a, 101.0) == []:
            bad.append(name)      # the wire does «actions([]); continue»: neither the old answer is said nor a new one asked
    assert not bad, f'the cue is swallowed when the asking gives {bad}'


def test_the_hold_never_exceeds_the_cap_under_any_order_of_events():
    rng, bad = random.Random(6), []
    for seed in range(300):
        c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около', False), mode='on')
        looks, t, first = gate.wire.fast.looks, 100.0, None
        for _ in range(rng.randint(3, 12)):
            t += rng.choice([0.0, 0.3, 0.9, 1.4, 2.0])
            pick = rng.choice([None, ('Около', False), ('', False), ('Около 2', False), ('Около 2 миллионов.', True)])
            looks.pop(CHANGED[1], None)
            if pick:
                looks[CHANGED[1]] = pick
            until = gate.parks(a, t)
            if until is not None:
                first = t if first is None else first
                if until > first + CAP + 1e-9:
                    bad.append(seed)
                    break
    assert not bad, f'{len(bad)} of 300 random orders hold past the cap'


def test_a_restart_of_the_gate_object_in_the_middle_does_not_double_the_cap():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около', False), mode='on')
    assert gate.parks(a, 100.0) == 100.0 + CAP
    again = v5_gate.attach({'v5_answer_gate': 'on'}, c, gate.wire)
    got = again.parks(a, 102.9)
    assert got is None or got <= 100.0 + CAP, f'after the restart the hold ends at {got}: {round(got - 100.0, 1)} s from the first hold'


def test_a_restart_of_the_gate_object_does_not_give_one_question_a_second_reasking():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 3 миллионов.', True), mode='on')
    assert gate.handed(a, 101.0)
    again = v5_gate.attach({'v5_answer_gate': 'on'}, c, gate.wire)
    again.handed(a, 102.0)
    assert len(c.stale_calls) == 1, f'{len(c.stale_calls)} askings for one question (stale_refusals = {v5_gate.COSTS["stale_refusals"]})'


# -- timing, tempo, pauses ------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_outcome_does_not_depend_on_the_clock_origin_or_the_pause_before_the_cue():
    seen = set()
    for shift in (0.0, 3.7, 1e6, 86400.0 * 400):
        for pause in (0.0, 0.4, 2.9, 40.0):
            c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 3 миллионов.', True), mode='on')
            gate.asked({'qid': 'u1', 'question': CHANGED[0]}, shift)
            gate.handed(a, shift + pause)
            row = notes[0][1]
            seen.add((row['code_answers'], row['would'], row['did']))
    assert seen == {('answer_changed', 'refuse', 'refused')}, seen


# -- growth and cost over a call of 180 minutes -----------------------------------------------------------------------------------------------------------------------------------

def long_call(minutes=180, per_question=5):
    """A synthetic call: a question every 24 s, five turns per question, every answer refused once (the worst case for the state of the gate)."""
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 3 миллионов.', True), mode='on')
    c.v5_stale = lambda cue_, asked: [{'type': 'cancel', 'epoch': 2}]
    turns, t = [], 100.0
    for n in range(minutes * 60 // 24):
        qid = f'q{n}'
        turns += [{'id': f'{qid}-{k}', 'role': 'user' if k % 2 == 0 else 'assistant', 'valid': True, 'final': True, 'text': f'это реплика номер {n} {k} про разные дела и сроки'} for k in range(per_question)]
        turns[-per_question]['id'] = qid
        c.ledger.turns[:] = turns
        c.question_id, c.fast_turn, c.source_id = qid, 'fast-1', 'fast-1'
        c.question_text = c.fast_text = CHANGED[1]
        gate.wire.fast.asked[qid] = CHANGED[0]
        t += 24
        gate.parks(a, t)
        gate.handed(cue(nonce=f'n{n}', revision=n, text='Около 2 миллионов.'), t)
    return c, gate, turns


def test_the_state_of_the_gate_stays_bounded_over_a_call_of_180_minutes():
    c, gate, turns = long_call()
    sizes = {name: len(getattr(gate, name)) for name in ('releases', 'holds', 'refused', 'seen', 'parked')}
    limit = 2 * v5_gate._KEPT
    assert all(v <= limit for v in sizes.values()), f'{len(turns)} turns, state sizes {sizes}, limit {limit}'


def test_one_request_costs_bounded_time_with_a_ledger_of_a_whole_call():
    c, gate, turns = long_call()
    c.question_id = 'q0'      # an old question still open: the whole call lies after it
    c.ledger.turns[:] = [dict(t, text=t['text'] + ' не') if i % 3 == 0 else t for i, t in enumerate(turns)]
    start = time.perf_counter()
    gate.parks(cue(nonce='z', revision=999), 9999.0)
    gate.handed(cue(nonce='z', revision=999), 9999.0)
    spent = time.perf_counter() - start
    assert spent < 0.25, f'{round(spent, 3)} s for one parks+handed with {len(turns)} turns after the question (стартовое bound 0.25 s)'


# -- poison, exceptions, off, shadow, secrecy ------------------------------------------------------------------------------------------------------------------------------------

POISON_CUES = [{}, {'text': None}, {'text': 5, 'index': 0}, {'text': b'abc', 'index': 0}, {'text': ['a'], 'index': 'x'}, {'text': 'Да\x00\x1b[31m', 'index': 0, 'nonce': object()}, {'text': '😀' * 5000, 'index': 0}]
POISON_NOW = [None, float('nan'), float('inf'), -5.0, 'x', 10 ** 30]


@pytest.mark.parametrize('mode', ['shadow', 'on'])
def test_poison_never_raises_into_the_call_and_never_swallows_an_answer(mode):
    out = []
    for poison in POISON_CUES:
        for now in [101.0] + POISON_NOW:
            c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 3 миллионов.', True), mode=mode)
            c.v5_stale = lambda cue_, asked: [{'type': 'cancel', 'epoch': 2}]      # the asking itself is sound here: only the gate is attacked
            try:
                until = gate.parks(poison, now)
                got = gate.handed(poison, now)
            except Exception as error:      # noqa: BLE001
                out.append(('raised', type(error).__name__, repr(poison)[:30], now))
                continue
            if got == [] or (mode == 'shadow' and (got is not None or until is not None)):
                out.append(('bad result', got, repr(poison)[:30], now))
    assert not out, f'{len(out)} poison variants: {out[:3]}'


def test_poison_in_the_ledger_and_in_the_text_channel_degrades_to_the_old_behaviour():
    bad = []
    for ledger in (None, 5, [None, 5, 'x'], [{'id': 'u1', 'role': 'user', 'valid': True, 'text': None}], [{'id': 'u1'}, {'role': 'user', 'valid': True, 'text': 'не'}]):
        for prepared in (None, 5, 'ab', (None, None), [], ('x', 'y', 'z'), (5, 5)):
            c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=None, mode='on')
            c.v5_stale = lambda cue_, asked: [{'type': 'cancel', 'epoch': 2}]
            c.ledger = type('L', (), {'history': lambda self, v=ledger: v})()
            gate.wire.fast.prepared = lambda text, v=prepared: v
            try:
                gate.parks(a, 101.0)
                got = gate.handed(a, 101.0)
            except Exception as error:      # noqa: BLE001
                bad.append((type(error).__name__, repr(ledger)[:20], repr(prepared)))
                continue
            if got == []:
                bad.append(('swallowed', repr(ledger)[:20], repr(prepared)))
    assert not bad, f'{len(bad)} variants: {bad[:3]}'


class _Broken:
    @property
    def question_text(self):
        raise RuntimeError('boom')


def test_an_exception_inside_the_gate_leaves_a_trace_in_the_call_journal():
    notes, taps = [], []
    tap = type('T', (), {'note': lambda self, *a: taps.append(a)})()
    gate = v5_gate.attach({'v5_answer_gate': 'on'}, _Broken(), Wire(), tap=tap, note=lambda ev, **f: notes.append((ev, f)))
    assert gate.handed(cue(), 1.0) is None
    assert notes or taps, 'the gate failed and passed the cue, but the call journal (note / v5 record) knows nothing of it'


def test_an_exception_in_parks_leaves_a_trace_too(caplog):
    notes = []
    gate = v5_gate.attach({'v5_answer_gate': 'on'}, _Broken(), Wire(), note=lambda ev, **f: notes.append((ev, f)))
    with caplog.at_level(logging.DEBUG):
        assert gate.parks(cue(), 1.0) is None
    assert notes or caplog.records, 'parks swallows every exception without a line anywhere'


def test_off_builds_nothing_whatever_the_other_setting_and_the_wire_asks_nothing():
    for off in ('off', None, '', 'OFF', 0, False, 'nonsense'):
        for same in ('answers', 'words', None):
            assert v5_gate.attach({'v5_answer_gate': off, 'v5_gate_same': same}, object(), object()) is None
    assert v5_gate.attach({}, object(), object()) is None and v5_gate.attach(None, object(), object()) is None


def test_shadow_changes_nothing_the_model_or_the_owner_can_see():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около 3 миллионов.', True), mode='shadow')

    def snap():
        return repr(sorted((k, repr(v)) for k, v in vars(c).items() if k != 'ledger')), repr(c.ledger.turns), dict(gate.wire.fast.looks), dict(gate.wire.fast.asked)
    before = snap()
    results = [gate.parks(a, 100.0), gate.handed(a, 100.0), gate.handed(a, 100.5), gate.parks(cue(index=1), 101.0), gate.waits(a, 101.0), gate.held(a, 'speech_with_content', 101.0)]
    assert results == [None] * 6 and before == snap() and c.stale_calls == []


def test_the_words_value_reproduces_the_old_rule_on_every_pair_of_the_measurement():
    """«words» must decide exactly as the deployed rule did: rebuild the old verdict from compare() on the whole sample and compare with the row."""
    if not PAIRS.exists():
        pytest.skip('dev pairs not present')
    items = [(r['a'], r['b']) for r in map(json.loads, PAIRS.read_text(encoding='utf-8').splitlines())][:300]
    bad = []
    for old, new in items:
        row = verdict(old, new, same='words')[3]
        meaning, why = v5_gate.compare(v5_gate.fingerprint(old), v5_gate.fingerprint(new))
        if row['meaning'] != meaning or row['would'] != ('refuse' if meaning == 'stale' else 'pass') or (meaning == 'stale' and row['why'] != why):
            bad.append((old, new, row['meaning'], meaning))
    assert not bad, f'{len(bad)} of {len(items)}: {bad[:2]}'


def test_no_text_of_the_conversation_goes_anywhere_new(caplog):
    secret_q, secret_a = 'Сколько стоит аренда склада Зюзино', 'Склад Зюзино стоит 4000 рублей.'
    notes, taps = [], []
    tap = type('T', (), {'note': lambda self, *a: taps.append(a)})()
    c = Controller(question='Сколько стоит аренда склада Бутово', fast_turn='fast-1')
    c.source_id = 'fast-1'
    fast = Fast({'u1': secret_q}, {'Сколько стоит аренда склада Бутово': ('Склад Бутово стоит 5000 рублей.', True)})
    gate = v5_gate.attach({'v5_answer_gate': 'on'}, c, Wire(fast), tap=tap, note=lambda ev, **f: notes.append((ev, f)))
    with caplog.at_level(logging.DEBUG):
        gate.parks(cue(text=secret_a), 100.0)
        gate.handed(cue(text=secret_a), 100.0)
    blob = json.dumps([notes, taps], ensure_ascii=False, default=str) + ' '.join(r.getMessage() for r in caplog.records)
    for word in ('Зюзино', 'Бутово', 'склад', 'аренд', 'рублей', '4000', '5000'):
        assert word.lower() not in blob.lower(), word


def test_nothing_is_written_anywhere_by_the_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    real_open, writes = builtins.open, []

    def guard(file, mode='r', *args, **kw):
        if any(m in str(mode) for m in 'wax+'):
            writes.append(file)
        return real_open(file, mode, *args, **kw)
    monkeypatch.setattr(builtins, 'open', guard)
    verdict(*CHANGED, old_a='Около 2 миллионов.', new_a='Около 3 миллионов.', mode='on')
    long_call(minutes=10)
    assert not writes and not list(tmp_path.iterdir()), (writes, list(tmp_path.iterdir()))

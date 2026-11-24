"""U25-R2: the mutations hold their rule on synthetic rows; the matrix prints one table with a passport."""
import copy

from tools.replay import matrix, mutate

FIX = {
    'cloud': [[10.0, 'ustart', 'u1', ''], [12.0, 'user', 'u1', 'Сколько будет 15 процентов от 200 рублей'], [12.1, 'astart', 'a1', ''], [14.0, 'cloud', 'a1', 'Тридцать.'],
              [30.0, 'user', 'u2', 'Это можно сделать завтра утром'], [33.0, 'cloud', 'a2', 'Да.']],
    'ear': [[8.0, 11.0, 11.5, 'сколько будет 15 процентов от 200 рублей'], [26.0, 29.0, 29.5, 'это можно сделать завтра утром']],
    'cues': [[15.0, 'Тридцать', 'completed']],
    'jobs': [], 'decisions': [], 'profile': {},
}


def test_every_mutation_holds_its_rule():
    for name in mutate.MUTATIONS:
        if name == 'not':       # its rule is DIFFERS, which meaning_guard does not yet give: see test_not_expects_differs_and_reports_the_guard_gap
            continue
        for arg in mutate.ARGS[name]:
            got = mutate.apply(FIX, name, arg)
            assert got['status'] == 'correct', (name, arg, got)
            assert got['fixture'] is not FIX and FIX['cloud'][1][3].startswith('Сколько')   # the original is untouched


def test_number_changes_the_value_and_is_not_same():
    got = mutate.apply(FIX, 'number', 1)
    assert '15' not in got['fixture']['cloud'][1][3] and got['expect'] == 'differs'


def test_not_expects_differs_and_reports_the_guard_gap():
    """The design: an added or dropped «не» is DIFFERS. The status follows the real meaning_guard; while it says UNKNOWN the mutation is 'wrong' (a finding), never relaxed to pass."""
    from echo_sync.fast_text import meaning_guard
    for how in ('insert', 'delete'):
        base = FIX if how == 'insert' else mutate.apply(FIX, 'not', 'insert')['fixture']
        got = mutate.apply(base, 'not', how)
        old, new = base['cloud'][1][3], got['fixture']['cloud'][1][3]
        assert got['expect'] == 'differs' and (' не ' in new.casefold()) == (how == 'insert')
        assert got['status'] == ('correct' if meaning_guard(old, new) == 'differs' else 'wrong')


def test_pauses_scale_the_gaps_only():
    twice = mutate.apply(FIX, 'pauses', 2.0)['fixture']
    assert [row[3] for row in twice['ear']] == [row[3] for row in FIX['ear']]
    assert round(twice['ear'][1][0] - twice['ear'][0][2], 3) == round(2 * (FIX['ear'][1][0] - FIX['ear'][0][2]), 3)


def test_cloud_delay_moves_the_cloud_only():
    got = mutate.apply(FIX, 'cloud_delay', 3.0)['fixture']
    assert got['ear'] == FIX['ear'] and got['cloud'][1][0] == 15.0 and got['cloud'][1][3] == FIX['cloud'][1][3]


def test_language_leaves_no_cyrillic():
    got = mutate.apply(FIX, 'language', 'latin')['fixture']
    assert not any('а' <= ch.casefold() <= 'я' for row in got['cloud'] if row[1] == 'user' for ch in row[3])


def test_order_swap_flips_the_arrival_order():
    got = mutate.apply(FIX, 'order', 'swap')
    assert got['status'] == 'correct' and got['fixture']['cloud'][1][0] < FIX['ear'][0][2]


def test_not_applicable_is_invalid_not_dropped():
    bare = copy.deepcopy(FIX)
    bare['cloud'][1][3] = 'Это без цифр'
    assert mutate.apply(bare, 'number', 1)['status'] == 'invalid'


def test_denominator_is_full():
    got = matrix.denominator(['correct', 'wrong', 'missed', 'timeout', 'invalid', 'unjudged', 'weird'])
    assert list(got) == list(matrix.STATUSES) and got['invalid'] == 2 and sum(got.values()) == 7


def test_judge_statuses():
    ask = dict(text='сколько будет 15 процентов', expected='тридцать')
    assert matrix.judge(ask, 'тридцать', 2.0) == 'correct' and matrix.judge(ask, 'сорок', 2.0) == 'wrong'
    assert matrix.judge(ask, None, None) == 'missed' and matrix.judge(ask, 'тридцать', 99.0) == 'timeout'
    assert matrix.judge(dict(text='x', expected=None), 'что-то', 1.0) == 'unjudged' and matrix.judge(ask, 5, 1.0) == 'invalid'


def test_matrix_prints_one_table_with_passport():
    calls = {'c1': FIX, 'c2': FIX}

    def runner(fixture, flags):
        wrong = 1 if flags.get('words_per_portion') == 4 and flags.get('max_auto_repeats') == 2 else 0
        return ['wrong'] * wrong + ['correct'] * (2 - wrong)
    out = matrix.run(calls, runner=runner, manifest={'count': 2, 'sha256': 'abc', 'verifier_sha256': 'def'})
    assert len(out['rows']) == len(matrix.PAIRS) == 6
    row = next(r for r in out['rows'] if r['pair'] == ('portion', 'repeat'))
    assert row['interaction_wrong'] == 2 and row['n_calls'] == 2
    text = matrix.table(out)
    assert text.count('passport') == 1 and 'portion' in text and 'abc' in text


def test_every_set_of_every_pair_differs_from_the_base(monkeypatch):
    import pytest
    matrix.check_axes()                                  # no axis is clamped back to the default by the resolver
    monkeypatch.setitem(matrix.FLAGS, 'cover', {'repeat_cover': 0.8})        # the default value: the set equals the base
    with pytest.raises(ValueError):
        matrix.check_axes((('cover', 'repeat'),))


def test_the_axes_are_numbers_only():
    from echo_sync.settings import DEFAULTS
    for name, setting in matrix.FLAGS.items():
        for key, value in setting.items():
            assert key in DEFAULTS and isinstance(value, (int, float)) and not isinstance(value, bool), (name, key, value)


def test_without_a_runner_the_passport_says_partial():
    out = matrix.run({'c1': FIX})
    assert out['passport']['status'].startswith('PARTIAL') and out['passport']['runner'].startswith('none')
    assert all(row['den']['base']['unjudged'] == row['asked'] and row['interaction_wrong'] == 0 for row in out['rows'])

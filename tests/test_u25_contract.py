"""U25-R1: closed against open replay."""
from tools.replay import contract

JOURNAL = [[1.0, 'Первый ответ', None], [5.0, 'Второй ответ', None], [9.0, 'Третий ответ', None]]
METRICS = [{'t': 2.0, 'name': 'a'}, {'t': 5.5, 'name': 'b'}, {'t': 9.5, 'name': 'c'}]


def test_same_cues_is_closed():
    replay = [(1.0, 'первый ответ!', None), (5.0, 'Второй ответ', None), (9.0, 'Третий ответ', None)]
    assert contract.divergence(JOURNAL, replay) is None
    got = contract.run({'cues': JOURNAL}, replay, METRICS)
    assert got['closed'] and not any(row['open_replay'] for row in got['metrics'])


def test_one_changed_cue_moves_the_point():
    middle = [(1.0, 'Первый ответ', None), (5.2, 'Другой ответ', None), (9.0, 'Третий ответ', None)]
    last = [(1.0, 'Первый ответ', None), (5.0, 'Второй ответ', None), (9.0, 'Иной ответ', None)]
    p1, p2 = contract.divergence(JOURNAL, middle), contract.divergence(JOURNAL, last)
    assert (p1['index'], p1['at']) == (1, 5.0) and (p2['index'], p2['at']) == (2, 9.0)
    assert [r['open_replay'] for r in contract.mark(METRICS, p1)] == [False, True, True]
    assert [r['open_replay'] for r in contract.mark(METRICS, p2)] == [False, False, True]
    assert contract.mark(METRICS, p1)[1]['bound'] == contract.BORDER


def test_missing_and_extra_cue_diverge():
    assert contract.divergence(JOURNAL, JOURNAL[:2])['index'] == 2
    extra = JOURNAL + [[12.0, 'Лишний', None]]
    assert contract.divergence(JOURNAL, extra) == {'index': 3, 'at': 12.0, 'journal': None, 'replay': 'лишний'}


def test_corpus_manifest_names_the_verifier(tmp_path):
    (tmp_path / 'a.json').write_text('{}', encoding='utf-8')
    got = contract.corpus(tmp_path)
    assert got['count'] == 1 and len(got['verifier_sha256']) == 64 and got['sha256']

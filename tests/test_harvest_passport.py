"""U06-S6: the latency passport of ``tools.harvest.passport``: two numbers, ``latency_proxy`` and ``latency_ref``, never merged, each with its own n of N. Synthetic
journals only; no network, no model, no replay."""
import json

from tools import harvest as H

ASK = 'объясни что такое абсолютная ссылка'


def journal(*rows):
    return H.read_rows([{'t': 0, 'ev': 'call_open', 'source': 'phone', 'max_auto_repeats': 3}] + [{'t': t, 'ev': ev, **fields} for t, ev, fields in rows])


def ear(t, text, kind='question'):
    return (t, 'ear_final', {'text': text, 'kind': kind, 'speech_ms': 900, 'lag_ms': 100})


def cue(t, text):
    return (t, 'cue', {'text': text})


def got(rows, **kw):
    return H.passport(H.events(rows), rows, **kw)


def timed(one):
    return H._timed(one, one['text'])


def test_the_two_piece_question_is_timed_from_its_last_piece():
    rows = journal(ear(1000, 'объясни что такое'), ear(3000, 'абсолютная ссылка', kind='speech'), cue(5500, 'Абсолютная ссылка закрепляет адрес ячейки'))
    (one,) = H.latency_asks(rows)
    assert one['t0'] == 3.0 and timed(one) == ('none', 2.5)


def test_a_diagnostic_is_not_a_useful_cue():
    rows = journal(ear(1000, ASK), cue(2000, sorted(H.FAILURES)[0]))
    (one,) = H.latency_asks(rows)
    assert timed(one) == ('no_cue', None)
    rows = journal(ear(1000, ASK), cue(2000, sorted(H.FAILURES)[0]), cue(4000, 'Ссылка с долларами не сдвигается'))
    assert timed(H.latency_asks(rows)[0]) == ('none', 3.0)


def test_a_cue_before_the_last_piece_is_premature_and_out_of_the_numbers():
    rows = journal(ear(1000, 'объясни что такое'), cue(2000, 'Что-то про ссылку и адрес'), ear(3000, 'абсолютная ссылка', kind='speech'))
    (one,) = H.latency_asks(rows)
    assert timed(one) == ('premature', None)
    made = got(rows)
    assert made['latency_proxy']['N'] == 1 and made['latency_proxy']['n'] == 0


def test_a_cue_with_no_shared_word_is_unanchored_and_a_slow_one_is_late():
    assert timed(H.latency_asks(journal(ear(1000, ASK), cue(2000, 'Погода хорошая')))[0]) == ('unanchored', None)
    (one,) = H.latency_asks(journal(ear(1000, ASK), cue(1000 + 20000, 'Абсолютная ссылка не меняется')))
    assert timed(one) == ('late', 20.0)


def test_p95_is_absent_below_twenty_and_present_at_twenty():
    def many(n):
        rows = []
        for i in range(n):
            rows += [ear(i * 30000 + 1000, ASK), cue(i * 30000 + 2000 + i * 10, 'Абсолютная ссылка')]
        return journal(*rows)
    low = got(many(19))['latency_proxy']
    assert (low['n'], low['N']) == (19, 19) and 'p95_s' not in low and low['median_s'] > 0
    assert 'p95_s' in got(many(20))['latency_proxy']


def test_within_counts_are_over_n_and_header_has_the_hashes():
    rows = journal(ear(1000, ASK), cue(3500, 'Абсолютная ссылка'), ear(40000, ASK), cue(47000, 'Абсолютная ссылка'))
    made = got(rows, manifest_sha='abc')
    one = made['latency_proxy']
    assert (one['within_3'], one['within_5'], one['within_8'], one['n'], one['N']) == (1, 1, 2, 2, 2)
    assert made['manifest_sha256'] == 'abc' and len(made['checker_sha256']) == 64


def test_the_reference_gives_latency_ref_apart_from_the_proxy(tmp_path):
    path = tmp_path / 'scenes.json'
    path.write_text(json.dumps({'scenes': [{'id': 'S06', 'text': ASK, 'expected': 'Закрепляет адрес знаком доллара'}, {'id': 'S07', 'text': 'другое'}]}), encoding='utf-8')
    refs = H.scene_refs(path)
    assert len(refs) == 1 and refs[0]['id'] == 'S06'
    rows = journal(ear(1000, ASK), cue(3000, 'Абсолютная ссылка'), ear(40000, 'расскажи про сводные таблицы'), cue(43000, 'Сводные таблицы собирают данные'))
    made = got(rows, refs=refs)
    assert (made['latency_proxy']['n'], made['latency_proxy']['N']) == (2, 2)
    assert (made['latency_ref']['N'], made['latency_ref']['n']) == (1, 0)      # the cue shares a word with the question, not with the expected answer
    rows = journal(ear(1000, ASK), cue(3000, 'Адрес закрепляется знаком'))
    assert got(rows, refs=refs)['latency_ref']['n'] == 1
    assert got(rows)['latency_ref'] == {'n': 0, 'N': 0}

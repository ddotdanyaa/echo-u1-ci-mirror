"""U06-S5: ``tools.harvest.events`` and ``passport``. The journals here are synthetic (one test per label); the two real ones (120135, 074253) are read only
where the laptop has them, and skip elsewhere. No network, no model, no replay."""
import os
from pathlib import Path

import pytest

from tools import harvest as H

CALLS = Path(os.environ.get('ECHO_CALLS_DIR') or Path(os.environ.get('LOCALAPPDATA', '')) / 'hermes-echo' / 'home' / 'profiles' / 'echo-sync' / 'logs' / 'echo_calls')
ASK = 'объясни что такое счёт пятьдесят один подробнее'


def journal(*rows, cap=3):
    return H.read_rows([{'t': 0, 'ev': 'call_open', 'source': 'phone', 'max_auto_repeats': cap}] + [{'t': t, 'ev': ev, **fields} for t, ev, fields in rows])


def ear(t, text, kind='question', speech_ms=900):
    return (t, 'ear_final', {'text': text, 'kind': kind, 'speech_ms': speech_ms, 'lag_ms': 100})


def refused(t, job=1, rule='words', asked=ASK):
    return (t, 'fast_refused', {'job': job, 'rule': rule, 'on': 'ear', 'heard': asked, 'asked': asked, 'ms': 10})


def job(t=1100):
    return (t, 'fast_job', {'job': 1, 'outcome': 'ok'})


def of(rows, label):
    return [event for event in H.events(rows) if event['label'] == label]


def verdicts(rows):
    return [event['verdict'] for event in of(rows, 'refusal')]


def test_loop_run_counts_plays_over_one_plus_the_cap():
    plays = lambda n, gap=4000: journal(*[(1000 + gap * i, 'cue', {'text': 'Термин возник давно'}) for i in range(n)])
    assert len(of(plays(4), 'loop_run')) == 0
    got = of(plays(5), 'loop_run')
    assert [(event['plays'], event['cap'], event['cap_source']) for event in got] == [(5, 3, 'reconstructed')]
    assert not of(plays(8, gap=20000), 'loop_run'), 'plays more than the window apart are not a run'


def test_over_cap_is_against_the_logged_cap_and_reconstructed_without_it():
    repeats = lambda **extra: journal(*[(1000 * n, 'decision', {'kind': 'replay', 'reason': 'ear_tempo', 'repeats': n, 'revision': 1, **extra}) for n in range(1, 6)])
    old = repeats()
    assert [(event['repeats'], event['cap_source']) for event in of(old, 'over_cap')] == [(4, 'reconstructed'), (5, 'reconstructed')]
    assert H.passport(H.events(old), old)['over_cap_reconstructed'] == 2
    new = repeats(cap=5)
    assert not of(new, 'over_cap'), 'the cap the controller logged is the cap: five repeats under cap=5 are fine'
    got = H.passport(H.events(new), new)
    assert (got['over_cap'], got['over_cap_reconstructed'], got['over_user_cap']) == (0, 0, 2), 'over_user_cap is a column: more than the owner set, not a defect'


def test_refusal_wrong_is_a_question_by_both_signs_taken_a_little_later():
    rows = journal(ear(1000, ASK), job(), refused(2000), (5000, 'decision', {'kind': 'question', 'reason': 'cloud_admitted'}))
    assert verdicts(rows) == ['wrong']


def test_refusal_unanswered_is_a_question_by_both_signs_never_taken():
    rows = journal(ear(1000, ASK), job(), refused(2000), (40000, 'decision', {'kind': 'question', 'reason': 'cloud_admitted'}))
    assert verdicts(rows) == ['unanswered']


def test_refusal_abstain_is_no_question_by_either_sign():
    chat = 'ну да в общем привет сижу вот здесь'
    rows = journal(ear(1000, chat, kind='silent'), job(), refused(2000, asked=chat))
    assert verdicts(rows) == ['abstain']


def test_refusal_unclear_is_the_signs_apart():
    assert verdicts(journal(ear(1000, ASK, kind='silent'), job(), refused(2000))) == ['unclear']
    assert verdicts(journal(ear(1000, ASK), job(), refused(9000))) == ['unclear'], 'the ear named the question long before: it does not stand for it'
    assert verdicts(journal(refused(2000))) == ['unclear'], 'a refusal of a job with no text of its own'


def test_refusal_service_is_not_a_verdict_on_the_rules():
    assert verdicts(journal(ear(1000, ASK), job(), refused(2000, rule='released'))) == ['service']


def test_refusal_takes_t0_from_the_first_note_and_the_end_from_the_sum():
    total = (9000, 'fast_refused_sum', {'job': 1, 'rules': {'words': 6}, 'last_t': 2010, 'last_asked': ASK})
    rows = journal(ear(3000, ASK), job(), refused(2000, asked='ну да'), refused(2100, asked='ну да'), refused(2200, asked='ну да'), total,
                   (7000, 'decision', {'kind': 'question', 'reason': 'cloud_admitted'}))
    (one,) = of(rows, 'refusal')
    assert (one['t'], one['t1'], one['raw'], one['rules']) == (2.0, 4.0, 9, {'words': 9})
    assert one['verdict'] == 'wrong', 'the ear final of 3 s stands for the question asked last (4 s), not the one of the first note'
    assert H.passport(H.events(rows), rows)['refusal_raw'] == 9


def test_the_sum_adds_to_the_notes_and_keeps_a_service_verdict():
    total = (130000, 'fast_refused_sum', {'job': 1, 'rules': {'words': 7}, 'last_t': 30000, 'last_asked': ASK})
    rows = journal(ear(99000, ASK), job(100100), refused(100000, rule='released'), refused(101000, rule='released'), refused(102000, rule='released'), total)
    (one,) = of(rows, 'refusal')
    assert one['raw'] == 10 and one['rules'] == {'released': 3, 'words': 7} and one['t1'] == pytest.approx(130.0 - 0.01, abs=0.02)


def test_false_cue_broad_is_no_final_of_the_ear_and_strict_no_question_word_either():
    (one,) = of(journal(ear(1000, 'ну да вот так', kind='silent'), (5000, 'cue', {'text': 'Новая подсказка'})), 'false_cue')
    assert one['strict'] is True
    asked = journal(ear(1000, 'почему так', kind='silent'), (5000, 'cue', {'text': 'Новая подсказка'}))
    assert [event['strict'] for event in of(asked, 'false_cue')] == [False]
    assert not of(journal(ear(1000, ASK), (5000, 'cue', {'text': 'Новая подсказка'})), 'false_cue')
    repeat = journal((1000, 'cue', {'text': 'Новая подсказка'}), (30000, 'cue', {'text': 'Новая подсказка'}))
    assert len(of(repeat, 'false_cue')) == 1, 'a text said before is not new'
    tempo = journal((5000, 'decision', {'kind': 'replay', 'reason': 'ear_tempo', 'repeats': 1}), (5005, 'cue', {'text': 'Новая подсказка'}))
    assert not of(tempo, 'false_cue')


def test_missed_question_is_a_question_of_the_ear_with_no_cue_after_it():
    (one,) = of(journal(ear(1000, ASK), (3000, 'user_final', {'text': ASK})), 'missed_question')
    assert one['confirmed'] is True
    assert not of(journal(ear(1000, ASK), (3000, 'cue', {'text': 'Ответ'})), 'missed_question')
    assert [e['confirmed'] for e in of(journal(ear(1000, ASK)), 'missed_question')] == [False]
    assert len(of(journal(ear(1000, ASK), ear(3000, ASK)), 'missed_question')) == 1, 'the same utterance twice within 6 s is one'


def test_no_text_speech_is_a_final_with_no_words_and_a_speech_over_the_floor():
    assert len(of(journal(ear(1000, '', kind='silent', speech_ms=800)), 'no_text_speech')) == 1
    assert not of(journal(ear(1000, '', kind='silent', speech_ms=700)), 'no_text_speech')


def test_wrong_repeat_is_a_decision_by_that_reason():
    assert len(of(journal((1000, 'decision', {'kind': 'replay', 'reason': 'wrong_repeat', 'revision': 1})), 'wrong_repeat')) == 1


def test_the_fixture_holds_the_new_keys():
    rows = journal(ear(1000, ASK), (1100, 'fast_job', {'job': 1, 'outcome': 'ok', 'first': 'Ответ'}), refused(2000),
                   (9000, 'fast_refused_sum', {'job': 1, 'rules': {'words': 3}, 'last_t': 2500, 'last_asked': ASK}))
    got = H.fixture(rows)
    assert got['ear_kind'] == [['question', None]]
    assert [row['job'] for row in got['refused']] == [1, 1] and got['refused'][-1]['last_t'] == 2500
    assert got['jobs_meta'][0][1] == 1 and got['header']['max_auto_repeats'] == 3
    assert got['events'] == H.events(rows) and got['passport'] == H.passport(got['events'], rows)
    assert got['passport']['events_total'] == len(got['events'])


def real(name):
    path = CALLS / (name + '.jsonl')
    if not path.exists():
        pytest.skip('no journal of this call on this machine')
    rows = H.read(path)
    return H.events(rows), rows


def test_real_120135_over_cap_and_loops():
    made, rows = real('20261108-120135-6dc9eed08e9b')
    got = H.passport(made, rows)
    assert (got['over_cap_reconstructed'], got['loops_run'], got['cap_source']) == (6, 2, 'reconstructed')
    assert (got['refusal_wrong'], got['refusal_unclear']) == (1, 1)


def test_real_074253_labels_match_u06_1():
    made, rows = real('20261106-074253-65f46fe91e81')
    got = H.passport(made, rows)
    assert (got['refusal_wrong'], got['refusal_unanswered'], got['refusal_abstain'], got['refusal_unclear'], got['refusal_service']) == (4, 0, 5, 4, 2)
    assert got['refusal_raw'] == 22 and (got['missed_question'], got['no_text_speech'], got['wrong_repeat']) == (1, 4, 0)
    assert got['false_cue'] == 6      # U06.1: 6 broad; strict differs by one (U06.1: 3, here 4: the cue at 130.352 s, after a cloud final with no question word)

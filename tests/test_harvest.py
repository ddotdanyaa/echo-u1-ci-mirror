"""G34: every real call becomes a test. ``tools.harvest`` reads the journal of a call (``logs/echo_calls/*.jsonl``, ``call_trace``) and makes of it a
fixture of the form of ``fixtures/call_1027_replay.json`` (the cloud's turns, the ear's utterances, the jobs' texts, the cues), plus the checks the
journal shows by itself. Here: the journal is synthetic or rebuilt from the fixture already in the repo; no text of a call is added. On the laptop
``ECHO_HARVEST_DIR`` points at the harvested fixtures, and each is replayed through the controller on the injected clock, with no network and no model.
"""
import json
import logging
import os
from pathlib import Path

import pytest

from echo_sync.call_trace import CallTrace
from echo_sync.diagnostics import PHRASES
from tools import harvest as H

import test_h3_tempo as T3
from test_h7 import job_of_1027
from test_h3_tempo import call, the_whole_call       # noqa: F401 - call is the fixture

FIXTURES = Path(__file__).parent / 'fixtures'
CALL_1027 = json.loads((FIXTURES / 'call_1027_replay.json').read_text(encoding='utf-8'))


def journal_of(fixture):
    """The journal ``call_trace`` would have written for a fixture: ms since the call opened, the ear's utterance at the moment its text came."""
    rows = [{'t': 0, 'ev': 'call_open', 'source': 'phone', 'max_auto_repeats': 3, 'repeat_seconds': 6.0}]
    names = {'ustart': 'user_start', 'user': 'user_final', 'astart': 'assistant_start', 'cloud': 'assistant_final'}
    for at, kind, key, text in fixture['cloud']:
        row = {'t': round(at * 1000), 'ev': names[kind], 'id': key}
        if kind in ('user', 'cloud'):
            row.update(text=text, chars=len(text))
        rows.append(row)
    for onset, offset, at, text in fixture['ear']:
        rows.append({'t': round(at * 1000), 'ev': 'ear_final', 'uid': 'e', 'text': text, 'kind': 'x', 'speech_ms': round((offset - onset) * 1000), 'lag_ms': round((at - offset) * 1000)})
    return sorted(rows, key=lambda row: row['t'])


def write(tmp_path, rows, name='20261107-101500-c1.jsonl'):
    path = tmp_path / name
    path.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows) + 'not json\n', encoding='utf-8')
    return path


# -- the fixture -----------------------------------------------------------------------------------------------------------------------

def test_the_journal_of_1027_gives_back_its_fixture(tmp_path):
    got = H.fixture(H.read(write(tmp_path, journal_of(CALL_1027))))
    keys = {}
    assert [(at, kind, text) for at, kind, _, text in got['cloud']] == [(at, kind, text) for at, kind, _, text in CALL_1027['cloud']]
    for (_, _, key, _), (_, _, mine, _) in zip(CALL_1027['cloud'], got['cloud']):
        assert keys.setdefault(key, mine) == mine, 'one turn keeps one id'
    assert [row[3] for row in got['ear']] == [row[3] for row in CALL_1027['ear']]
    for mine, theirs in zip(got['ear'], CALL_1027['ear']):
        assert mine[:3] == pytest.approx(theirs[:3], abs=0.0015)


def test_the_ids_of_the_provider_are_not_kept(tmp_path):
    got = H.fixture(H.read(write(tmp_path, journal_of(CALL_1027))))
    assert not {key for _, _, key, _ in got['cloud']} & {key for _, _, key, _ in CALL_1027['cloud']}


def test_jobs_cues_and_decisions_are_harvested(tmp_path):
    rows = [{'t': 0, 'ev': 'call_open'}, {'t': 1000, 'ev': 'user_final', 'id': 'X', 'text': 'что такое инерция'},
            {'t': 1100, 'ev': 'decision', 'kind': 'answer', 'reason': 'fast', 'revision': 1, 'index': 0},
            {'t': 1500, 'ev': 'fast_job', 'job': 0, 'on': 'final', 'ttft_ms': 400, 'first': 'Инерция — свойство тела.', 'outcome': 'ok'},
            {'t': 1600, 'ev': 'cue', 'text': 'Инерция — свойство тела.'}, {'t': 2900, 'ev': 'cue_end', 'status': 'completed'}]
    got = H.fixture(H.read(write(tmp_path, rows)))
    assert got['jobs'] == [[1.5, 'final', 400, 'Инерция — свойство тела.', 'ok']]
    assert got['cues'] == [[1.6, 'Инерция — свойство тела.', 'completed']]
    assert got['decisions'] == [[1.1, 'answer', 'fast', 1, 0]]


def test_a_job_answers_with_the_journals_text_for_the_final_it_heard():
    fixture = {'cloud': [[1.0, 'ustart', 'u1', ''], [2.0, 'user', 'u1', 'что такое инерция'], [4.0, 'cloud', 'a1', 'Облако про инерцию.'],
                         [5.0, 'ustart', 'u2', ''], [6.0, 'user', 'u2', 'в каком году была битва при калке'], [9.0, 'cloud', 'a2', 'Облако про Калку.']],
               'jobs': [[2.6, 'final', 300, 'Работа про инерцию.', 'ok'], [6.4, 'final', 300, '', 'failed']]}
    assert H.answer_for(fixture, 'что такое инерция') == 'Работа про инерцию.'
    assert H.answer_for(fixture, 'битва при калке') == 'Облако про Калку.', 'a failed job has no text: the cloud answered'
    assert H.answer_for(fixture, 'сколько планет') == '—'


def test_a_replayed_job_takes_the_text_of_the_job_that_ended_next_in_the_call():
    fixture = {'cloud': [], 'jobs': [[2.6, 'ear', 300, 'Первая.', 'ok'], [7.0, 'final', 300, '', 'failed'], [7.5, 'final', 300, 'Вторая.', 'ok']]}
    assert H.answer_for(fixture, 'что угодно', at=2.3) == 'Первая.'
    assert H.answer_for(fixture, 'что угодно', at=6.0) == 'Вторая.'
    assert H.answer_for(fixture, 'что угодно', at=20.0) == '—'


def test_a_journal_written_by_call_trace_itself(tmp_path):
    """The format is the module's own: the records of a real CallTrace, not rows written here by hand."""
    now = [100.0]
    trace = CallTrace(tmp_path, 'c1', clock=lambda: now[0])
    trace.open(source='phone', max_auto_repeats=1, repeat_seconds=6.0)

    def at(second, act):
        now[0] = 100.0 + second
        act()
    at(1.0, lambda: trace.provider({'type': 'turn.created', 'turn': {'id': 'item_AbC', 'role': 'user'}}))
    at(2.0, lambda: trace.provider({'type': 'turn.done', 'turn': {'id': 'item_AbC', 'role': 'user', 'transcript': 'что такое инерция'}}))
    at(2.1, lambda: trace.note('ear_final', uid=7, text='что такое инерция', kind='question', speech_ms=1200, lag_ms=150))
    at(2.2, lambda: trace.decision('echo-sync decision kind=answer reason=fast_text_owns revision=1 index=0'))
    at(2.5, lambda: trace.note('fast_job', job=0, on='final', ttft_ms=300, first=A1, outcome='ok'))
    at(2.6, lambda: trace.frame({'type': 'response.created'}))
    at(2.6, lambda: trace.frame({'type': 'response.audio_transcript.delta', 'delta': A1}))
    at(2.62, lambda: trace.frame({'type': 'response.audio.delta', 'delta': 'AAAA'}))
    at(3.9, lambda: trace.frame({'type': 'response.done', 'response': {'id': 'r1', 'status': 'completed'}}))
    at(4.0, lambda: trace.provider({'type': 'turn.created', 'turn': {'id': 'item_DeF', 'role': 'assistant'}}))
    at(5.0, lambda: trace.provider({'type': 'turn.done', 'turn': {'id': 'item_DeF', 'role': 'assistant', 'transcript': 'Облако.'}}))
    at(6.0, trace.close)
    got = H.fixture(H.read(trace.path))
    assert got['profile'] == {'max_auto_repeats': 1, 'repeat_seconds': 6.0}
    assert got['cloud'] == [[1.0, 'ustart', 'u1', ''], [2.0, 'user', 'u1', 'что такое инерция'], [4.0, 'astart', 'a1', ''], [5.0, 'cloud', 'a1', 'Облако.']]
    assert got['ear'] == [[0.75, 1.95, 2.1, 'что такое инерция']]
    assert got['jobs'] == [[2.5, 'final', 300, A1, 'ok']] and got['decisions'] == [[2.2, 'answer', 'fast_text_owns', 1, 0]]
    assert got['cues'] == [[2.6, A1, 'completed']]
    assert H.findings(got['checks']) == {} and got['checks']['questions'] == 1


def test_a_broken_line_or_a_record_with_no_time_is_skipped(tmp_path):
    path = write(tmp_path, [{'t': 0, 'ev': 'call_open'}, {'ev': 'cue', 'text': 'x'}, {'t': 'a', 'ev': 'cue'}, {'t': 5, 'ev': 'cue', 'text': 'Да.'}])
    assert [row['ev'] for row in H.read(path)] == ['call_open', 'cue']


# -- the checks the journal shows by itself ----------------------------------------------------------------------------------------

def stream(*events, repeats=None):
    rows, t = [{'t': 0, 'ev': 'call_open', **({} if repeats is None else {'max_auto_repeats': repeats})}], 0
    for event in events:
        t += 1000
        kind, *rest = event
        if kind == 'q':
            rows.append({'t': t, 'ev': 'user_final', 'id': 'u', 'text': rest[0]})
        elif kind == 'rev':
            rows.append({'t': t, 'ev': 'decision', 'kind': 'answer', 'reason': 'r', 'revision': rest[0], 'index': 0})
        elif kind == 'retire':
            rows.append({'t': t, 'ev': 'decision', 'kind': 'retire', 'reason': 'new_question', 'revision': rest[0], 'index': 0})
        elif kind == 'next':
            rows.append({'t': t, 'ev': 'decision', 'kind': 'next', 'reason': 'a_try_counts', 'revision': rest[0], 'index': 1})
        elif kind == 'cue':
            rows += [{'t': t, 'ev': 'cue', 'text': rest[0]}, {'t': t + 500, 'ev': 'cue_end', 'status': 'completed'}]
        elif kind == 'ear':
            rows.append({'t': t, 'ev': 'ear_final', 'text': rest[0], 'speech_ms': 800, 'lag_ms': 100})
        elif kind == 'say':
            rows.append({'t': t, 'ev': 'user_final', 'id': 'u', 'text': rest[0]})
        elif kind == 'timeout':
            rows.append({'t': t, 'ev': 'decision', 'kind': 'silent', 'reason': 'answer_timeout'})
    return H.read_rows(rows)


A1, A2 = 'Инерция — это свойство тела', 'сохранять свою скорость неизменной.'
B1 = 'Битва на Калке была в 1223 году.'


def test_a_clean_call_has_no_finding():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('say', 'инерция это свойство тела'), ('cue', A2),
                          ('q', 'в каком году была битва при калке'), ('rev', 2), ('cue', B1)))
    assert got['questions'] == 2 and got['cues'] == 3 and got['repeats'] == 1
    assert H.findings(got) == {}


def test_a_cue_said_round_and_round():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('cue', A1), ('cue', A1)))
    assert H.findings(got) == {'loops': 1}


def test_the_auto_repeats_of_the_call_are_no_loop():
    assert H.findings(H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('cue', A1), ('cue', A1), ('cue', A1), repeats=3))) == {}
    assert H.findings(H.checks(stream(('q', 'что такое инерция'), ('rev', 1), *[('cue', A1)] * 5, repeats=3))) == {'loops': 1}
    assert H.findings(H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('cue', A1), repeats=0))) == {'loops': 1}


def test_one_repeat_of_a_cue_is_no_loop():
    assert H.findings(H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('cue', A1), ('cue', A2)))) == {}


def test_an_old_answer_after_a_new_question():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('q', 'в каком году была битва при калке'), ('rev', 2), ('next', 1), ('cue', A2), ('rev', 2), ('cue', B1)))
    assert H.findings(got) == {'stale': 1}


def test_an_old_cue_said_again_after_a_new_question():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('q', 'в каком году была битва при калке'), ('rev', 2), ('cue', A1), ('cue', B1)))
    assert H.findings(got) == {'stale': 1}


def test_the_same_question_in_other_words_may_get_the_same_answer():
    got = H.checks(stream(('q', '55 статья налогового кодекса'), ('rev', 1), ('cue', 'Статья 55 Налогового кодекса — налоговый период.'),
                          ('q', 'он не дал ответа, значит что такое 55 статья налогового кодекса'), ('rev', 2), ('cue', 'Статья 55 Налогового кодекса — налоговый период.')))
    assert got['questions'] == 2 and H.findings(got) == {}


def test_a_retired_question_opens_one_question_with_the_next_revision():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('ear', 'в каком году была битва при калке'), ('retire', 2), ('rev', 3), ('cue', B1)))
    assert got['questions'] == 2 and H.findings(got) == {}


def test_a_cue_after_its_question_is_admitted_is_of_that_question():
    rows = stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('q', 'в каком году была битва при калке'), ('retire', 2), ('cue', B1))
    rows.insert(-1, {'t': rows[-1]['t'], 'ev': 'decision', 'kind': 'question', 'reason': 'local_reference', 'revision': 3, 'index': 0})
    assert H.findings(H.checks(rows)) == {}


def test_two_revisions_of_one_question_are_one_question():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('rev', 2), ('next', 1), ('cue', A1), ('next', 2), ('cue', A2)))
    assert got['questions'] == 1 and H.findings(got) == {}


def test_a_correction_of_the_same_question_is_no_new_question():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('rev', 2), ('cue', A2)))
    assert got['questions'] == 1 and H.findings(got) == {}


def test_the_same_question_asked_again_may_get_the_same_answer():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('q', 'Что такое инерция?'), ('rev', 2), ('cue', A1)))
    assert H.findings(got) == {}


@pytest.mark.parametrize('phrase', sorted(PHRASES.values()))
def test_a_spoken_failure(phrase):
    assert H.findings(H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', phrase)))) == {'failures': 1, 'silent': 1}


def test_a_question_with_no_sound():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('q', 'в каком году была битва при калке'), ('rev', 2), ('cue', B1)))
    assert H.findings(got) == {'silent': 1}


def test_a_question_that_timed_out_is_silent_too():
    assert H.findings(H.checks(stream(('q', 'что такое инерция'), ('timeout',)))) == {'silent': 1, 'timeouts': 1}


@pytest.mark.parametrize('heard', ['инерция это свойство тела', 'инерцией это свойство тело', 'Инерция — это свойство тела'])
def test_the_owner_repeats_and_the_same_cue_comes_again(heard):
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('ear', heard), ('cue', A1), ('cue', A2)))
    assert got['repeats'] == 1 and H.findings(got) == {'stuck': 1}


INFLATION, REST = 'Инфляция — это устойчивый рост общего уровня цен.', 'рост общего уровня цен.'


def test_the_place_jumps_back_to_the_head_of_the_portion():
    """The call of 10:27, 8:00: «устойчивый», the rest of the portion, «устойчивый» again, and the whole portion from its head."""
    got = H.checks(stream(('q', 'что такое инфляция'), ('rev', 1), ('cue', INFLATION), ('ear', 'цвета устойчивый'), ('cue', REST), ('ear', 'устойчивый'),
                          ('cue', INFLATION), repeats=3))
    assert H.findings(got) == {'back': 1}


def test_the_rest_said_again_is_no_jump_back():
    got = H.checks(stream(('q', 'что такое инфляция'), ('rev', 1), ('cue', INFLATION), ('ear', 'устойчивый'), ('cue', REST), ('cue', REST), repeats=3))
    assert H.findings(got) == {}


def test_the_same_portion_for_a_new_question_is_no_jump_back():
    got = H.checks(stream(('q', 'что такое инфляция'), ('rev', 1), ('cue', INFLATION), ('cue', REST), ('q', 'Что такое инфляция?'), ('rev', 2), ('cue', INFLATION)))
    assert H.findings(got) == {}


def test_a_remark_that_is_no_repeat_does_not_count():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('ear', 'подожди я не понял'), ('cue', A1), ('cue', A2)))
    assert got['repeats'] == 0 and H.findings(got) == {}


def test_the_ear_and_the_cloud_hearing_one_repeat_count_once():
    got = H.checks(stream(('q', 'что такое инерция'), ('rev', 1), ('cue', A1), ('ear', 'инерция это свойство тела'), ('say', 'инерция это свойство тела'), ('cue', A2)))
    assert got['repeats'] == 1 and H.findings(got) == {}


def test_the_counters_hold_numbers_only(tmp_path):
    got = H.checks(H.read(write(tmp_path, journal_of(CALL_1027))))
    assert got and all(isinstance(value, int) for value in got.values())
    assert got['finals'] == 20 and got['ear'] == 130


# -- the command, on the laptop ----------------------------------------------------------------------------------------------------

def test_the_command_writes_a_fixture_per_journal_and_prints_numbers(tmp_path, capsys):
    calls, out = tmp_path / 'echo_calls', tmp_path / 'harvest'
    calls.mkdir()
    write(calls, journal_of(CALL_1027), '20261105-102700-a.jsonl')
    write(calls, journal_of(CALL_1027), '20261105-102700-a.report.json')
    assert H.main([str(calls), '--out', str(out)]) == 0
    made = sorted(path.name for path in out.iterdir())
    assert made == ['20261105-102700-a.json', 'counters.json']
    printed = capsys.readouterr().out
    assert 'Привет' not in printed and 'finals=20' in printed
    counters = json.loads((out / 'counters.json').read_text(encoding='utf-8'))
    assert counters['calls'] == 1 and all(isinstance(value, int) for row in counters['by_call'] for value in row.values() if not isinstance(value, str))
    assert not any(isinstance(value, str) and len(value) > 40 for row in counters['by_call'] for value in row.values())
    kept = json.loads((out / '20261105-102700-a.json').read_text(encoding='utf-8'))['passport']
    assert counters['events_total'] == kept['events_total'] == counters['passport_total']['events_total']       # U07-S8: the baseline against U06.1
    assert counters['passport_total']['refusal_raw'] == kept['refusal_raw'] and counters['passport_total']['latency_proxy_N'] == kept['latency_proxy']['N']
    assert all(isinstance(value, int) for value in counters['passport_total'].values())


def test_with_no_argument_it_reads_the_folder_of_echo_calls(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('ECHO_CALLS_DIR', str(tmp_path / 'none'))
    assert H.main(['--out', str(tmp_path / 'harvest')]) == 1 and 'no call journal' in capsys.readouterr().err
    (tmp_path / 'none').mkdir()
    write(tmp_path / 'none', journal_of(CALL_1027), '20261105-102700-a.jsonl')
    assert H.main(['--out', str(tmp_path / 'harvest')]) == 0


def test_a_harvested_fixture_is_not_written_twice(tmp_path):
    calls, out = tmp_path / 'echo_calls', tmp_path / 'harvest'
    calls.mkdir()
    write(calls, journal_of(CALL_1027), '20261105-102700-a.jsonl')
    H.main([str(calls), '--out', str(out)])
    stamp = (out / '20261105-102700-a.json').stat().st_mtime_ns
    H.main([str(calls), '--out', str(out)])
    assert (out / '20261105-102700-a.json').stat().st_mtime_ns == stamp


def test_the_harvest_folder_is_ignored_by_git():
    ignored = (Path(__file__).parents[1] / '.gitignore').read_text(encoding='utf-8').split()
    assert 'tests/fixtures/harvest/' in ignored


# -- the replay: a harvested fixture through the controller ------------------------------------------------------------------------

def harvested():
    folder = Path(os.environ.get('ECHO_HARVEST_DIR') or FIXTURES / 'harvest')
    found = sorted(folder.glob('*.json')) if folder.is_dir() else []
    return [path for path in found if path.stem not in H.NOT_JOURNALS] or [None]


def replay(rig, monkeypatch, fixture, *, late=1.2, job=None):
    """Every event at its time; a job answers with the call's own text for that moment (``H.answer_for``), or with ``job`` when the test has its own."""
    monkeypatch.setattr(T3, 'CALL_2034', [tuple(row) for row in fixture['cloud']])
    monkeypatch.setattr(T3, 'CALL_EAR', [tuple(row) for row in fixture['ear']])
    zero = rig.w.clock.now() - 20.0

    def own(question):
        return H.answer_for(fixture, question.rsplit('Сейчас прозвучало: ', 1)[-1], at=rig.w.clock.now() - zero)
    end = max([row[0] for row in fixture['cloud']] + [row[2] for row in fixture['ear']] + [0.0]) + 15.0
    cues = the_whole_call(rig, job=job or own, late=late, until=end)
    rig.fast.close()
    return cues


class Decisions(logging.Handler):
    def __init__(self, clock):
        super().__init__(logging.INFO)
        self.clock, self.rows = clock, []

    def emit(self, record):
        message = record.getMessage()
        if message.startswith('echo-sync decision '):
            self.rows.append((self.clock(), message))


def replayed_checks(rig, monkeypatch, fixture, job=None, rows=None):
    seen = Decisions(rig.w.clock.now)
    logger = logging.getLogger('echo-sync')
    logger.addHandler(seen)
    level = logger.level
    logger.setLevel(logging.INFO)
    try:
        zero = rig.w.clock.now() - 20.0
        cues = replay(rig, monkeypatch, fixture, job=job)
    finally:
        logger.removeHandler(seen)
        logger.setLevel(level)
    made = H.replay_rows(fixture, cues, [(at - zero, message) for at, message in seen.rows])
    if rows is not None:
        rows += made
    return H.checks(made)



RULES = ('loops', 'stale', 'failures', 'stuck', 'back')


def replayed_1027(call, monkeypatch, rows=None):
    """The call of 10:27 with the candidate's tempo (the call itself ran with it off) and the jobs answering with the owner's sample (c14 kept no text of them)."""
    rig = call(fast_text='on', max_auto_repeats=3)
    got = replayed_checks(rig, monkeypatch, H.fixture(H.read_rows(journal_of(CALL_1027))), job=job_of_1027, rows=rows)
    print(f'\n[G34] 10:27 replay {H.line(got)}')
    assert got['cues'] > 0 and got['questions'] > 0
    return got


def test_the_replay_of_1027_says_nothing_old_and_no_failure(call, monkeypatch):
    got = replayed_1027(call, monkeypatch)
    assert {key: got[key] for key in ('stale', 'failures', 'stuck')} == {'stale': 0, 'failures': 0, 'stuck': 0}


@pytest.mark.xfail(strict=True, reason='G34 finding, controlled_media.py (the coordinator\'s): 8:00 of 10:27, the tail «рост общего уровня цен.» was cued, the owner said '
                   '«устойчивый» again (the ear, 488.0), and the timer said the whole portion from its head: _missing_part reads no start in the word before the tail, '
                   'and the ear dropped it as what the last final said. back=2, loops=1. The patch: g34-harvest_controlled_media.diff')
def test_the_replay_of_1027_keeps_its_place(call, monkeypatch):
    rows = []
    got = replayed_1027(call, monkeypatch, rows)
    after = [row['text'] for row in rows if row['ev'] == 'cue' and 488000 < row['t'] < 499000]
    assert after == ['рост общего уровня цен.'] and got['loops'] == 0


@pytest.mark.parametrize('path', harvested(), ids=lambda path: path.stem if path else 'none')
def test_every_harvested_call_replays_with_no_finding(call, monkeypatch, path, capsys):
    if path is None:
        pytest.skip('no harvested call here: on the laptop, python -m tools.harvest, then ECHO_HARVEST_DIR')
    fixture = json.loads(path.read_text(encoding='utf-8'))
    rig = call(fast_text='on', max_auto_repeats=fixture.get('profile', {}).get('max_auto_repeats', 1))
    got = replayed_checks(rig, monkeypatch, fixture)
    with capsys.disabled():
        print(f'\n[G34] {path.stem} journal {H.line(fixture["checks"])} | replay {H.line(got)}')
    assert {key: got[key] for key in RULES} == dict.fromkeys(RULES, 0)


# -- U17-S6 (for P11): the microphone second is a fixture row, numbers only -------------------------------------------------------------------

def test_mic_rows_become_numbers_and_a_row_with_text_is_dropped():
    rows = [{'t': 0, 'ev': 'call_open'},
            {'t': 1000, 'ev': 'mic', 'first_ms': 1000, 'last_ms': 1990, 'n': 50, 'bytes': 32000, 'text': 'private words'},
            {'t': 2000, 'ev': 'mic', 'first_ms': 2000, 'last_ms': None, 'n': 3, 'bytes': 10}]
    made = H.fixture(rows)
    assert made['mic'] == [[1.0, 1.99, 50, 32000]], made.get('mic')
    assert 'private words' not in json.dumps(made, ensure_ascii=False)
    assert 'mic' not in H.fixture([{'t': 0, 'ev': 'call_open'}]), 'a journal with no mic rows keeps its old fixture'

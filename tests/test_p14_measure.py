"""P14: tools/harvest/measure.py. A real call through the host is classified (U167); the rest are journals invented for the case (numbers and labels only)."""
import json
import logging
import subprocess
from pathlib import Path

import pytest

from helpers_spoken_diagnostics import run_host
from tools import harvest as H
from tools.harvest import measure as M


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')


def ear(t, text, lag=100, kind='question'):
    return {'t': t, 'ev': 'ear_final', 'kind': kind, 'text': text, 'lag_ms': lag, 'speech_ms': 1500}


def cue(t, text):
    return {'t': t, 'ev': 'cue', 'text': text}


def dec(t, kind='answer'):
    return {'t': t, 'ev': 'decision', 'kind': kind, 'reason': 'r'}


# -- U167 ------------------------------------------------------------------------------------------------------------------------------

def test_a_real_call_gives_each_question_one_class_with_its_number(tmp_path, monkeypatch):
    seen = {}

    async def body(host):
        for n, (ask, answer) in enumerate((('Почему небо голубое днём?', 'Воздух сильнее рассеивает синий свет, поэтому небо кажется голубым.'),
                                           ('Сколько будет двадцать плюс двадцать два?', 'Сорок два.')), 1):
            await host.ask(ask, tid=f'u{n}')
            await host.answer(answer, tid=f'a{n}')
            await host.advance(25)
        seen['path'] = next(f for f in (Path(host.home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name)
    run_host(tmp_path / 'call', monkeypatch, body)
    rows = H.read(seen['path'])
    finals = [row for row in rows if row['ev'] == 'user_final']
    assert len(finals) == 2
    rows = sorted(rows + [ear(row['t'] - 300, row['text']) for row in finals], key=lambda row: row['t'])      # the ear row the phone adds before the cloud's final
    split = M.latency_split(rows)
    assert [one['qid'] for one in split] == [1, 2] and all(one['class'] in ('right', 'premature', 'stale', 'none') for one in split)
    counts = M.split_counts(split)
    assert counts['N'] == 2 and counts['right'] + counts['premature'] + counts['stale'] + counts['none'] == 2
    assert counts['right'] >= 1, split


def test_each_class_is_told_apart():
    rows = [{'t': 0, 'ev': 'call_open'},
            ear(1000, 'Сколько стоит доллар', kind='question'), cue(2000, 'Доллар стоит девяносто рублей.'), ear(3000, 'в рублях сегодня', kind='statement'),   # q1: a cue while the question is still being said: premature
            ear(20000, 'Какая высота горы Эверест'), cue(23000, 'Высота горы Эверест восемь тысяч метров.'),                                             # q2: right
            ear(40000, 'Что такое инерция вообще'), cue(43000, 'Высота горы Эверест восемь тысяч метров.'),                                              # q3: the old answer again: stale
            ear(60000, 'Кто написал роман Идиот')]                                                                                                        # q4: no cue at all
    split = M.latency_split(rows)
    assert [one['class'] for one in split] == ['premature', 'right', 'stale', 'none'], split
    assert split[1]['latency_s'] == 3.0 and split[0]['latency_s'] is None


def test_the_job_that_gave_a_right_cue_is_named():
    rows = [{'t': 0, 'ev': 'call_open'}, ear(1000, 'Какая высота горы Эверест'), {'t': 1500, 'ev': 'fast_adopted', 'job': 7, 'on': 'ear', 'ms': 400, 'ready_ms': 10},
            cue(2200, 'Высота горы Эверест восемь тысяч метров.')]
    assert M.latency_split(rows)[0] == {'qid': 1, 'job': 7, 'class': 'right', 'latency_s': 1.2}


# -- U168 ------------------------------------------------------------------------------------------------------------------------------

def test_a_pin_names_the_sha_and_changes_with_each_of_the_three_files(tmp_path):
    def git(*args):
        subprocess.run(['git', *args], cwd=tmp_path, check=True, capture_output=True)
    git('init', '-q')
    git('config', 'user.email', 'a@b.c')
    git('config', 'user.name', 'n')
    (tmp_path / 'echo_sync').mkdir()
    (tmp_path / 'tools').mkdir()
    brain, measurer = tmp_path / 'echo_sync' / 'brain_rules.py', tmp_path / 'tools' / 'm.py'
    brain.write_text('A = 1\n')
    measurer.write_text('B = 1\n')
    git('add', '-A')
    git('commit', '-q', '-m', 'x')
    one = M.pin(measurer, {'k': 1}, root=tmp_path)
    assert one['sha'] and not one['dirty'] and M.one_pin([one, M.pin(measurer, {'k': 1}, root=tmp_path)]) == {'status': 'ONE', 'differs': []}
    assert M.pin(measurer, {'k': 2}, root=tmp_path)['profile'] != one['profile']
    brain.write_text('A = 2\n')
    changed = M.pin(measurer, {'k': 1}, root=tmp_path)
    assert changed['brain'] != one['brain'] and changed['dirty']
    mixed = M.one_pin([one, changed])
    assert mixed['status'] == 'MIXED' and 'brain' in mixed['differs'] and 'dirty' in mixed['differs']
    assert M.one_pin([])['status'] == 'NONE'


# -- U133 / U132 -----------------------------------------------------------------------------------------------------------------------

def call_rows(base, search=False, voice=100):
    """One answered question: the ear's final at base (lag 100), a job that starts 150 ms after the speech ended and thinks 400 ms, a decision, a cue."""
    rows = [{'t': 0, 'ev': 'call_open'}, ear(base, 'Какая высота горы Эверест', lag=100)]
    first = base - 100 + 150 + 400
    if search:
        rows += [{'t': base + 30, 'ev': 'stage', 'name': 'lookup_start'}, {'t': base + 330, 'ev': 'stage', 'name': 'lookup_end'}]
        first = base + 330 + 100
    rows += [{'t': first + 20, 'ev': 'fast_job', 'job': 1, 'after_ear_ms': 150, 'ttft_ms': 400, 'chars': 20, 'outcome': 'ok', 'first': 'x'}] if not search else []
    rows += [dec(first + 50), cue(first + 50 + voice, 'Высота горы Эверест.')]
    return rows


def test_the_stages_are_measured_per_path_and_add_up_to_the_whole():
    plain = [call_rows(10000 + 1000 * n) for n in range(21)]
    table = M.stage_table(plain)
    row = table['paths']['plain']
    assert row['episodes'] == 21 and row['closure_bad'] == 0
    assert row['stages']['pause']['median'] == 300 and row['stages']['ear']['median'] == 100 and row['stages']['model']['median'] > 0
    assert table['passport']['meets_20'] and table['passport']['calls'] == 21
    assert table['paths']['search']['episodes'] == 0


def test_a_search_path_has_its_own_row_and_few_calls_do_not_meet_the_count():
    table = M.stage_table([call_rows(10000, search=True), call_rows(30000)])
    assert table['paths']['search']['episodes'] == 1 and table['paths']['search']['stages']['search']['median'] == 300
    assert table['paths']['plain']['episodes'] == 1 and not table['passport']['meets_20']


def test_the_target_is_read_from_the_end_of_speech():
    table = M.stage_table([call_rows(10000 + 1000 * n) for n in range(5)])
    report = M.target_report(table)
    assert report['paths']['plain']['median_s'] == 1.0 and report['paths']['plain']['met'] is False       # 300 pause + 100 ear + 50 start + 400 model + 50 pick + 100 voice ms; over the 0.6 s target
    assert report['paths']['search']['met'] is None and report['paths']['plain']['target_s'] == [0.3, 0.6]


# -- U106 / U121 -----------------------------------------------------------------------------------------------------------------------

def test_a_build_is_faster_only_when_median_and_tail_fall_on_the_same_scenes():
    old = M.build_numbers([call_rows(10000 + 1000 * n, voice=400) for n in range(6)])
    new = M.build_numbers([call_rows(10000 + 1000 * n, voice=100) for n in range(6)])
    assert M.compare(old, new)['faster'] is True
    worse_errors = M.build_numbers([call_rows(10000 + 1000 * n, voice=100) + [{'t': 99999, 'ev': 'error', 'code': 'x'}] for n in range(6)])
    assert M.compare(old, worse_errors)['faster'] is False
    fewer = M.build_numbers([call_rows(10000, voice=100)])
    assert M.compare(old, fewer)['faster'] is False and M.compare(old, fewer)['same_scenes'] is False
    assert M.compare(old, new)['verdict']['median_ms'] == 'better' and M.compare(new, old)['verdict']['median_ms'] == 'worse'


# -- U137 / U25 ------------------------------------------------------------------------------------------------------------------------

def test_an_open_set_needs_licences_size_and_sources():
    good = {'sources': [{'id': f's{n}', 'licence': 'CC-BY-4.0', 'utterances': 50} for n in range(5)]}
    assert M.open_set(good) == []
    bad = {'sources': [{'id': 'a', 'licence': 'all-rights-reserved', 'utterances': 10}, {'id': 'b', 'licence': 'MIT', 'utterances': 10}]}
    found = M.open_set(bad)
    assert any('all-rights-reserved' in item for item in found) and any('utterances' in item for item in found) and any('sources' in item for item in found)


def test_the_holdout_is_read_once_per_checker(tmp_path):
    ledger = tmp_path / 'ledger.json'
    M.holdout_once(ledger, 'a' * 64, ['h2', 'h1'])
    with pytest.raises(RuntimeError):
        M.holdout_once(ledger, 'a' * 64, ['h1'])
    assert json.loads(ledger.read_text(encoding='utf-8')) == {'a' * 64: ['h1', 'h2']}
    M.holdout_once(ledger, 'b' * 64, ['h1'])                       # another checker is another blind reading


# -- the baseline of a set of journals: counts only ------------------------------------------------------------------------------------

def test_the_baseline_of_a_real_host_call_is_counts_only_with_a_passport(tmp_path, monkeypatch):
    seen = {}

    async def body(host):
        await host.ask('Почему небо голубое днём?', tid='u1')
        await host.answer('Воздух сильнее рассеивает синий свет, поэтому небо кажется голубым.', tid='a1')
        await host.advance(3)
        seen['path'] = next(f for f in (Path(host.home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name)
    run_host(tmp_path / 'call', monkeypatch, body)
    got = M.baseline([seen['path']])
    assert got['passport']['set'].startswith('1 call journals') and 'n=1 of N=1' in got['passport']['set'] and got['passport']['load'].startswith('none')
    assert len(got['calls']) == 1 and got['calls'][0]['counters']['cues'] >= 1 and got['total']['cues'] >= 1
    assert 'Воздух' not in json.dumps(got, ensure_ascii=False) and 'голуб' not in json.dumps(got, ensure_ascii=False)
    assert M.one_pin([got['passport']['pin']])['status'] in ('ONE', 'MIXED')


def test_the_baseline_fixture_of_the_laptop_journals_is_counts_only_and_adds_up():
    one = json.loads((Path(__file__).parent / 'fixtures' / 'baseline_p14_journals.json').read_text(encoding='utf-8'))
    assert set(one['passport']) >= {'set', 'profile', 'checker', 'load', 'clock', 'pin'} and one['passport']['pin']['dirty'] is False
    assert one['split']['right'] + one['split']['premature'] + one['split']['stale'] + one['split']['none'] == one['split']['N']
    assert sum(one['corpus'].values()) == len(one['calls'])
    assert one['total']['questions'] == sum(call['counters']['questions'] for call in one['calls'])

    def leaves(value):
        for item in (value.values() if isinstance(value, dict) else value):
            yield from leaves(item) if isinstance(item, (dict, list)) else [item]
    strings = [x for call in one['calls'] for x in leaves(call) if isinstance(x, str)]
    assert all(len(x) <= 32 for x in strings), 'a long string is text, not a count'


def test_the_fuzz_baseline_fixture_has_a_passport_and_the_counts_of_every_invariant():
    one = json.loads((Path(__file__).parent / 'fixtures' / 'fuzz_baseline_446237b.json').read_text(encoding='utf-8'))
    assert set(one['passport']) >= {'set', 'profile', 'checker', 'load', 'sha'} and one['seeds'] == 2000 and one['passport']['crashes'] == []
    assert set(one['seeds_with']) == {g['invariant'] for g in one['groups']} and all(0 < n <= 2000 for n in one['seeds_with'].values())
    assert one['seeds_with']['A2'] < one['reference']['227f594']['A2'], 'A2 is lower than the 218 seeds of 227f594'
    assert all(len(g['first_seeds']) <= 6 and g['min_seed'] == g['first_seeds'][0] for g in one['groups'])

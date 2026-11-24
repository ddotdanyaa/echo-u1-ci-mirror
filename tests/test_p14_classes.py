"""U57 (P14): the loss classes of a call journal as counts (tools/harvest/classes.py, from call_class_meter) and the baseline of 11.11 as a counts-only fixture.
A real call through the host (HostRig, virtual time) is measured; the classes are checked on journals invented for each of them."""
import json
import logging
from pathlib import Path

import pytest

from helpers_spoken_diagnostics import run_host
from tools.harvest import classes as C

FIXTURE = Path(__file__).parent / 'fixtures' / 'baseline_classes_1111.json'


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')


def rows(*items):
    return [{'t': 0, 'ev': 'call_open', 'source': 'phone'}, *items]


def dec(t, kind, reason='r', **more):
    return {'t': t, 'ev': 'decision', 'kind': kind, 'reason': reason, **more}


def cue(t, text, end=None):
    return [{'t': t, 'ev': 'cue', 'text': text}] + ([{'t': end, 'ev': 'cue_end', 'status': 'completed'}] if end else [])


def test_a_real_call_gives_counts_of_its_own_journal(tmp_path, monkeypatch):
    seen = {}

    async def body(host):
        await host.ask('Почему небо голубое днём?', tid='u1')
        await host.answer('Воздух сильнее рассеивает синий свет, поэтому небо кажется голубым.', tid='a1')
        await host.advance(3)
        seen['spoken'] = host.spoken()
        seen['path'] = next(f for f in (Path(host.home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name)
    run_host(tmp_path / 'call', monkeypatch, body)
    got = C.measure_file(seen['path'])
    assert got['cues'] == len(seen['spoken']) >= 1
    assert got['portion_loop']['n'] == 0 and got['stale_cue']['n'] == 0 and got['long_segment']['n'] == 0
    assert all(isinstance(value, (int, float, str, dict, type(None))) for value in got.values())
    assert 'Воздух' not in json.dumps(got, ensure_ascii=False), 'counts and labels only, no words of the call'


def test_hold_is_the_wait_from_a_ready_text_to_the_sound():
    ev = rows({'t': 1000, 'ev': 'fast_job', 'outcome': 'ok', 'first': 'Сорок два.', 'chars': 10}, dec(1100, 'answer', 'fast_text_owns'), *cue(9600, 'Сорок два.', 11000))
    got = C.measure(ev)
    assert got['hold']['n'] == 1 and got['hold']['max_s'] == 8.6 and got['hold']['linked'] == 1


def test_a_cue_inside_one_and_a_half_seconds_is_no_hold():
    ev = rows({'t': 1000, 'ev': 'fast_job', 'outcome': 'ok', 'first': 'Сорок два.', 'chars': 10}, dec(1100, 'answer'), *cue(1900, 'Сорок два.', 2500))
    assert C.measure(ev)['hold']['n'] == 0


def test_a_retired_plan_with_nothing_after_it_is_a_false_question():
    ev = rows(dec(1000, 'retire', 'new_question'), {'t': 40000, 'ev': 'call_close', 'elapsed_ms': 40000})
    got = C.measure(ev)['false_question']
    assert got['n'] == 1 and got['of_retire_new_question'] == 1
    answered = rows(dec(1000, 'retire', 'new_question'), dec(3000, 'answer'), *cue(3500, 'Ответ.', 4000), {'t': 40000, 'ev': 'call_close', 'elapsed_ms': 40000})
    assert C.measure(answered)['false_question']['n'] == 0


def test_the_same_portion_said_three_times_by_the_timer_is_a_loop():
    ev = rows(dec(1000, 'answer', index=0), *cue(1100, 'Инерция — это свойство.', 2000), dec(4000, 'replay', 'ear_tempo', index=0), *cue(4100, 'Инерция — это свойство.', 5000),
              dec(7000, 'replay', 'ear_tempo', index=0), *cue(7100, 'Инерция — это свойство.', 8000))
    got = C.measure(ev)['portion_loop']
    assert got['n'] == 1 and got['sec'] == 6.9
    two = rows(dec(1000, 'answer', index=0), *cue(1100, 'Инерция.', 2000), dec(4000, 'replay', 'ear_tempo', index=0), *cue(4100, 'Инерция.', 5000))
    assert C.measure(two)['portion_loop']['n'] == 0


def test_questions_without_a_cue_in_5_15_30_seconds_are_counted_by_window():
    ev = rows({'t': 2000, 'ev': 'ear_final', 'kind': 'question', 'text': 'что это', 'speech_ms': 900}, {'t': 50000, 'ev': 'ear_final', 'kind': 'question', 'text': 'а это', 'speech_ms': 900},
              *cue(12000, 'Ответ первому.', 13000))
    got = C.measure(ev)['unanswered']
    assert (got['n'], got['s5'], got['s15'], got['s30']) == (2, 1 + 1, 1, 1)


def test_a_repeat_started_before_the_gap_after_the_previous_cue_is_over_speech():
    ev = rows(dec(1000, 'answer'), *cue(1100, 'Первая порция.', 3000), dec(3300, 'replay', 'ear_tempo'), *cue(3400, 'Первая порция.', 4500))
    assert C.measure(ev)['repeat_over_speech'] == {'n': 1, 'of_replay': 1}


def test_an_empty_final_of_real_speech_and_a_long_segment_are_counted():
    ev = rows({'t': 1000, 'ev': 'ear_final', 'text': '', 'speech_ms': 900}, {'t': 2000, 'ev': 'ear_final', 'text': '', 'speech_ms': 300},
              {'t': 20000, 'ev': 'ear_final', 'text': 'длинный кусок речи', 'speech_ms': 14000})
    got = C.measure(ev)
    assert got['empty_ear']['n'] == 1 and got['empty_ear']['n_any'] == 2 and got['long_segment']['n'] == 1


def test_an_answer_that_repeats_what_the_ear_heard_before_is_a_stale_cue_lower_bound():
    ev = rows({'t': 1000, 'ev': 'ear_final', 'kind': 'statement', 'text': 'вода кипит при ста градусах цельсия', 'speech_ms': 2000},
              dec(5000, 'answer'), *cue(5100, 'Вода кипит при ста градусах цельсия.', 7000))
    assert C.measure(ev)['stale_cue']['n'] == 1


def test_the_baseline_of_1111_is_counts_only_and_has_a_passport():
    one = json.loads(FIXTURE.read_text(encoding='utf-8'))
    assert set(one['passport']) >= {'set', 'profile', 'checker', 'load'} and len(one['calls']) == 5

    def leaves(value):
        for item in (value.values() if isinstance(value, dict) else value if isinstance(value, list) else [value]):
            yield from leaves(item) if isinstance(item, (dict, list)) else [item]
    assert all(isinstance(x, (int, float, type(None))) or (isinstance(x, str) and len(x) <= 24) for call in one['calls'] for x in leaves(call)), 'a long string is text, not a count'
    for call in one['calls']:
        un = call['unanswered']
        assert un['s30'] <= un['s15'] <= un['s5'] <= un['n'], call['call']
        assert call['repeat_over_speech']['n'] <= call['repeat_over_speech']['of_replay'] <= call['cues']
    assert sum(call['unanswered']['n'] for call in one['calls']) == 33 and sum(call['long_segment']['n'] for call in one['calls']) == 17

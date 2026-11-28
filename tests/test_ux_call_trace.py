"""UX-trace, part 1 (the recorder): a LOCAL, bounded, never-failing trace of one phone call, one JSONL file per call.

These tests drive echo_sync.call_trace.CallTrace on its own (a fake monotonic clock, a temporary folder). The same recorder inside the
real controlled_host.serve is tested in tests/test_ux_call_trace_host.py.
"""
import ast
import contextvars
import json
import logging
import os
import re
from pathlib import Path

import pytest

from echo_sync import call_trace
from echo_sync.call_trace import CallTrace, KEEP_FILES, MAX_FILE_BYTES, MAX_TEXT_CHARS

CALL = '0123456789ab'
NAME = re.compile(r'^\d{8}-\d{6}-[0-9a-f]{12}\.jsonl$')


class Clock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now


def folder(tmp_path):
    return tmp_path / 'home' / 'logs' / 'echo_calls'


def make(tmp_path, call_id=CALL, **keywords):
    clock = Clock()
    return CallTrace(folder(tmp_path), call_id, clock=clock, **keywords), clock


def records(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines()]


def user_final(text, tid='u1', **more):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': 'user', 'transcript': text, **more}}


def assistant_final(text, tid='a1'):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': 'assistant', 'transcript': text}}


# --- the file ---------------------------------------------------------------------------------------------------------------

def test_one_file_per_call_named_by_the_time_and_the_call_id(tmp_path):
    """Break: a name that does not tell the call (the owner cannot find «that» call), or one file for every call."""
    trace, _ = make(tmp_path)
    assert trace.open(source='phone') is True and trace.active
    names = [p.name for p in folder(tmp_path).iterdir()]
    assert len(names) == 1 and NAME.match(names[0]) and names[0].endswith(f'-{CALL}.jsonl')
    assert trace.path == folder(tmp_path) / names[0]
    trace.close()


def test_the_first_line_is_a_header_with_the_call_and_what_the_caller_says(tmp_path):
    trace, _ = make(tmp_path)
    trace.open(source='phone', policy='answer-v2.1', repeat_seconds=6.0, max_auto_repeats=1)
    trace.close()
    head = records(trace.path)[0]
    assert head['ev'] == 'call_open' and head['t'] == 0 and head['call'] == CALL
    assert (head['source'], head['policy'], head['repeat_seconds'], head['max_auto_repeats']) == ('phone', 'answer-v2.1', 6.0, 1)
    assert re.match(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d[+-]\d\d:\d\d$', head['wall']) and isinstance(head['mono_ms'], int)


def test_every_record_carries_monotonic_milliseconds_since_the_call_opened(tmp_path):
    trace, clock = make(tmp_path)
    trace.open()
    clock.now += 1.5
    trace.note('first')
    clock.now += 0.25
    trace.note('second')
    trace.close()
    assert [(r['ev'], r['t']) for r in records(trace.path)] == [('call_open', 0), ('first', 1500), ('second', 1750), ('duplex', 1750), ('call_close', 1750)]


def test_the_call_id_cannot_climb_out_of_the_folder(tmp_path):
    trace, _ = make(tmp_path, call_id='..\\..\\evil/../x')
    trace.open()
    trace.close()
    assert trace.path.parent == folder(tmp_path) and '..' not in trace.path.name and '/' not in trace.path.name


# --- what is recorded: the cloud's turns, as it sent them --------------------------------------------------------------------

def test_a_user_final_and_an_assistant_text_are_recorded_as_the_provider_sent_them(tmp_path):
    """The two things the owner's call could not show: what the cloud HEARD, and what it SAID (the cut answer and its restart)."""
    trace, clock = make(tmp_path)
    trace.open()
    clock.now += 2
    trace.provider(user_final('Что такое сублимация', start_ms=1200, end_ms=6200))
    clock.now += 1
    cut = 'Есть два основных значения. В психологии — когда сильные импульсы перенаправляются в социально приемлемые'
    trace.provider(assistant_final(cut))
    trace.close()
    said, answered = records(trace.path)[1:3]
    assert said == {'t': 2000, 'ev': 'user_final', 'id': 'u1', 'text': 'Что такое сублимация', 'chars': 20, 'start_ms': 1200, 'end_ms': 6200, 'lang': 'ru'}
    assert answered == {'t': 3000, 'ev': 'assistant_final', 'id': 'a1', 'text': cut, 'chars': len(cut)}


def test_the_start_of_a_turn_is_recorded_without_text_and_the_delta_stream_not_at_all(tmp_path):
    trace, _ = make(tmp_path)
    trace.open()
    trace.provider({'type': 'turn.created', 'turn': {'id': 'u1', 'role': 'user', 'transcript': 'Что'}})
    trace.provider({'type': 'turn.created', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': 'Сублимация'}})
    for n in range(50):
        trace.provider({'type': 'turn.delta', 'turn_id': 'a1', 'delta': ' слово', 'start_ms': n, 'end_ms': n + 1})
    trace.close()
    middle = records(trace.path)[1:-2]              # between the header and the summary + closing line
    assert [(r['ev'], r['id']) for r in middle] == [('user_start', 'u1'), ('assistant_start', 'a1')]
    assert not any('text' in r for r in middle)


def test_other_provider_events_are_recorded_by_their_type(tmp_path):
    trace, _ = make(tmp_path)
    trace.open()
    trace.provider({'type': 'input_audio_buffer.speech_started'})
    trace.provider({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'content': ['private']}})
    trace.close()
    middle = records(trace.path)[1:-2]
    assert middle[0]['ev'] == 'provider' and middle[0]['type'] == 'input_audio_buffer.speech_started'
    assert middle[1]['ev'] == 'provider' and middle[1]['type'] == 'delegation.created' and middle[1]['id'] == 'd1'
    assert middle[1]['for_turn'] == 'u1' and 'private' not in json.dumps(middle[1])


@pytest.mark.parametrize('event', [None, 7, 'text', [], {}, {'type': None}, {'type': 'turn.done', 'turn': 'x'},
                                   {'type': 'turn.done', 'turn': {'role': 'user'}}])
def test_a_malformed_event_never_raises(tmp_path, event):
    trace, _ = make(tmp_path)
    trace.open()
    trace.provider(event)
    trace.close()
    assert records(trace.path)[-1]['ev'] == 'call_close'


# --- what is recorded: what the phone is given -------------------------------------------------------------------------------

def test_a_cue_its_end_and_its_cut_are_recorded(tmp_path):
    trace, clock = make(tmp_path)
    trace.open()
    clock.now += 1
    trace.frame({'type': 'response.created', 'response': {'id': 'r1'}})
    trace.frame({'type': 'response.audio_transcript.delta', 'response_id': 'r1', 'delta': 'свойство тела'})
    for _ in range(100):
        trace.frame({'type': 'response.audio.delta', 'response_id': 'r1', 'delta': 'AAAA'})
    clock.now += 0.5
    trace.frame({'type': 'response.done', 'response': {'id': 'r1', 'status': 'completed'}})
    clock.now += 5
    trace.frame({'type': 'output_audio_buffer.clear'})
    trace.close()
    middle = records(trace.path)[1:-2]
    assert [(r['ev'], r['t']) for r in middle] == [('cue', 1000), ('cue_end', 1500), ('cue_cut', 6500)]
    assert middle[0]['text'] == 'свойство тела' and middle[1]['status'] == 'completed'


def test_the_ready_marker_of_the_handshake_is_no_cue_end_but_the_ready_record(tmp_path):
    trace, _ = make(tmp_path)
    trace.open()
    trace.frame({'type': 'response.done', 'response': {'status': 'completed', 'output': []}})
    trace.close()
    assert [r['ev'] for r in records(trace.path)] == ['call_open', 'ready', 'duplex', 'call_close']


def test_an_error_frame_is_recorded_by_its_code_only(tmp_path):
    trace, _ = make(tmp_path)
    trace.open()
    trace.frame({'type': 'error', 'error': {'code': 'controlled_answer_timeout', 'message': 'controlled_answer_timeout'}})
    trace.frame({'type': 'error', 'error': {'code': 'has spaces and a secret token abc', 'message': 'x'}})
    trace.close()
    first, second = records(trace.path)[1:3]
    assert first['ev'] == 'error' and first['code'] == 'controlled_answer_timeout'
    assert second['code'] == 'redacted_error' and 'secret' not in json.dumps(second)


# --- decisions --------------------------------------------------------------------------------------------------------------

def decide(message):
    logging.getLogger('echo-sync').info(message)


def test_the_decisions_of_the_controller_are_recorded_from_its_log_lines(tmp_path, caplog):
    """«kind/reason/revision/index» are exactly what the engine already logs; the trace puts them next to the words that caused them."""
    trace, clock = make(tmp_path)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        trace.open()
        clock.now += 4
        decide('echo-sync decision kind=ack reason=stable_partial revision=3 index=1')
        decide('echo-sync decision kind=silent reason=auto_repeat_cap repeats=1 revision=3 index=1')
        decide('echo-sync decision kind=silent reason=own_voice evidence=speech_start announced_after_first_audio=1.25 revision=3 index=1')
        decide('echo-sync decision kind=ack reason=x revision=None')
        decide('echo-sync classify kind=ack reason=not_a_decision')
        decide('Controlled call opened call=abc source=phone')
        trace.close()
    decisions = [r for r in records(trace.path) if r['ev'] == 'decision']
    assert decisions[0] == {'t': 4000, 'ev': 'decision', 'kind': 'ack', 'reason': 'stable_partial', 'revision': 3, 'index': 1}
    assert decisions[1]['reason'] == 'auto_repeat_cap' and decisions[1]['repeats'] == 1
    assert decisions[2]['evidence'] == 'speech_start' and decisions[2]['announced_after_first_audio'] == 1.25
    assert decisions[3]['revision'] is None
    assert len(decisions) == 4


def test_a_decision_token_cannot_overwrite_the_time_or_the_kind_of_record(tmp_path, caplog):
    trace, clock = make(tmp_path)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        trace.open()
        clock.now += 1
        decide('echo-sync decision kind=ack reason=x t=999999 ev=hacked')
        trace.close()
    record = [r for r in records(trace.path) if r['ev'] == 'decision'][0]
    assert record['t'] == 1000 and record['ev'] == 'decision'


def test_a_decision_of_another_call_is_not_recorded(tmp_path, caplog):
    """Two calls (or a probe next to a phone call) share one process and one logger; each trace keeps ITS OWN call's decisions."""
    one, clock_one = make(tmp_path / 'one', call_id='aaaaaaaaaaaa')
    two, clock_two = make(tmp_path / 'two', call_id='bbbbbbbbbbbb')
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        ctx_one, ctx_two = contextvars.copy_context(), contextvars.copy_context()
        ctx_one.run(one.open)
        ctx_two.run(two.open)
        ctx_one.run(decide, 'echo-sync decision kind=ack reason=from_one')
        ctx_two.run(decide, 'echo-sync decision kind=silent reason=from_two')
        decide('echo-sync decision kind=question reason=from_nobody')           # neither call's context
        ctx_one.run(one.close)
        ctx_two.run(two.close)
    assert [r['reason'] for r in records(one.path) if r['ev'] == 'decision'] == ['from_one']
    assert [r['reason'] for r in records(two.path) if r['ev'] == 'decision'] == ['from_two']


def test_after_close_the_tap_is_gone_and_nothing_more_is_recorded(tmp_path, caplog):
    trace, _ = make(tmp_path)
    handlers = list(logging.getLogger('echo-sync').handlers)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        trace.open()
        trace.close()
        decide('echo-sync decision kind=ack reason=late')
    assert logging.getLogger('echo-sync').handlers == handlers
    assert all(r['ev'] != 'decision' for r in records(trace.path))


def test_the_header_says_whether_the_decisions_can_be_seen(tmp_path):
    """If the logger is switched below INFO the decision lines never exist: the file must say so instead of looking decision-free."""
    log = logging.getLogger('echo-sync')
    before = log.level
    try:
        log.setLevel(logging.WARNING)
        quiet, _ = make(tmp_path / 'a', call_id='aaaaaaaaaaaa')
        quiet.open()
        quiet.close()
        log.setLevel(logging.INFO)
        loud, _ = make(tmp_path / 'b', call_id='bbbbbbbbbbbb')
        loud.open()
        loud.close()
    finally:
        log.setLevel(before)
    assert records(quiet.path)[0]['decisions'] is False and records(loud.path)[0]['decisions'] is True


# --- bounded ----------------------------------------------------------------------------------------------------------------

def test_a_long_text_is_cut_and_says_how_long_it_was(tmp_path):
    trace, _ = make(tmp_path)
    trace.open()
    trace.provider(assistant_final('слово ' * 3000))
    trace.close()
    record = records(trace.path)[1]
    assert len(record['text']) == MAX_TEXT_CHARS and record['chars'] == 18000 and record['truncated'] is True


def test_the_file_stops_growing_at_its_cap_and_still_ends_with_a_close_line(tmp_path):
    """Break: a three-hour lecture fills the disk, or the cap cuts the file off without its closing line."""
    trace, clock = make(tmp_path, max_bytes=6000)
    trace.open()
    for n in range(500):
        clock.now += 0.1
        trace.provider(user_final(f'повтор номер {n} ' * 4, tid=f'u{n}'))
    trace.close(elapsed_ms=1)
    lines = records(trace.path)
    assert os.path.getsize(trace.path) <= 6000
    assert [r['ev'] for r in lines].count('trace_full') == 1 and lines[-1]['ev'] == 'call_close' and lines[-1]['elapsed_ms'] == 1
    assert 5 < len(lines) < 100


def test_the_product_caps_are_the_documented_ones():
    assert KEEP_FILES == 400 and MAX_FILE_BYTES == 8_000_000 and MAX_TEXT_CHARS == 2000   # 13.11: 50 files and 1 MB did not hold a three-hour call with the facts journal, nor the owner's calls next to the probes


def test_only_the_newest_files_are_kept_and_nothing_else_is_touched(tmp_path):
    """Break: the folder grows for ever - or the pruning deletes something the owner put there."""
    directory = folder(tmp_path)
    directory.mkdir(parents=True)
    old = []
    for n in range(KEEP_FILES + 5):
        path = directory / f'20261101-{n:06d}-{n:012x}.jsonl'
        path.write_text('{}\n', encoding='utf-8')
        os.utime(path, (1_000_000 + n, 1_000_000 + n))
        old.append(path)
    foreign = [directory / 'notes.txt', directory / '20261101-000000-xyz.jsonl.bak', directory / 'agent.jsonl']
    for path in foreign:
        path.write_text('keep me', encoding='utf-8')
        os.utime(path, (1, 1))
    trace, _ = make(tmp_path)
    trace.open()
    trace.close()
    remaining = sorted(p.name for p in directory.iterdir() if NAME.match(p.name))
    assert len(remaining) == KEEP_FILES
    assert trace.path.name in remaining
    assert all(not p.exists() for p in old[:6]) and all(p.exists() for p in old[6:])      # KEEP_FILES + 5 and the new one, less KEEP_FILES: the 6 oldest go
    assert all(p.exists() for p in foreign)


def test_a_smaller_keep_is_honoured(tmp_path):
    directory = folder(tmp_path)
    directory.mkdir(parents=True)
    for n in range(5):
        path = directory / f'20261101-0000{n:02d}-{n:012x}.jsonl'
        path.write_text('{}\n', encoding='utf-8')
        os.utime(path, (1_000_000 + n, 1_000_000 + n))
    trace, _ = make(tmp_path, keep=3)
    trace.open()
    trace.close()
    assert len([p for p in directory.iterdir() if NAME.match(p.name)]) == 3


# --- a failure never reaches the call ----------------------------------------------------------------------------------------

def test_a_folder_that_cannot_be_made_means_no_trace_and_no_exception(tmp_path, caplog):
    (tmp_path / 'home').mkdir()
    (tmp_path / 'home' / 'logs').write_text('a file where the folder should be', encoding='utf-8')
    trace, _ = make(tmp_path)
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        assert trace.open() is False
        trace.provider(user_final('слова'))
        trace.frame({'type': 'response.audio_transcript.delta', 'delta': 'порция'})
        trace.note('x')
        trace.close()
    assert not trace.active and trace.failure
    text = caplog.text
    assert 'call trace' in text and str(tmp_path) not in text, 'the warning names the type of the failure, never the path'


def test_a_write_that_fails_stops_the_trace_quietly_and_keeps_what_was_written(tmp_path, monkeypatch, caplog):
    trace, _ = make(tmp_path)
    trace.open()
    trace.provider(user_final('первая'))
    real = CallTrace._write_line
    seen = []

    def failing(self, line):
        seen.append(line)
        raise OSError(28, 'No space left on device: C:\\secret\\path')
    monkeypatch.setattr(CallTrace, '_write_line', failing)
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        trace.provider(user_final('вторая'))                 # the failing write
        monkeypatch.setattr(CallTrace, '_write_line', real)
        trace.provider(user_final('третья'))                 # the trace is dead: not even tried again
        trace.close()
    assert len(seen) == 1 and not trace.active and trace.failure == 'OSError'
    assert [r.get('text') for r in records(trace.path) if r['ev'] == 'user_final'] == ['первая']
    assert 'secret' not in caplog.text and caplog.text.count('call trace') == 1
    assert str(tmp_path) not in caplog.text and trace.path.name not in caplog.text, 'the warning names the type, never the path'


def test_a_bug_inside_close_never_escapes_it(tmp_path, monkeypatch):
    """close() runs in the host's finally, before the cleanup of the call: whatever goes wrong in it, the cleanup must still run."""
    trace, _ = make(tmp_path)
    trace.open()

    def broken(self):
        raise RuntimeError('bug in the recorder')
    monkeypatch.setattr(CallTrace, '_unlisten', broken)
    assert isinstance(trace.close(), dict)
    assert isinstance(trace.close(), dict) and not trace.active


def test_a_value_that_cannot_be_serialised_costs_one_record_not_the_trace(tmp_path):
    trace, _ = make(tmp_path)
    trace.open()
    loop = []
    loop.append(loop)
    trace.note('bad', value=loop)
    trace.note('good')
    trace.close()
    events = [r['ev'] for r in records(trace.path)]
    assert 'good' in events and trace.failure is None


def test_a_lone_surrogate_in_a_transcript_is_written_not_fatal(tmp_path):
    trace, _ = make(tmp_path)
    trace.open()
    trace.provider(user_final('до \ud800 после'))
    trace.provider(user_final('следующая'))
    trace.close()
    texts = [r['text'] for r in records(trace.path) if r['ev'] == 'user_final']
    assert len(texts) == 2 and texts[1] == 'следующая' and trace.failure is None


def test_nothing_is_written_after_close_and_close_can_be_repeated(tmp_path):
    trace, _ = make(tmp_path)
    trace.open()
    trace.close()
    trace.close()
    trace.provider(user_final('поздно'))
    assert [r['ev'] for r in records(trace.path)] == ['call_open', 'duplex', 'call_close']


def test_a_trace_with_no_folder_is_inert(tmp_path):
    """The setting is off, or this is a probe: every hook stays in the host and costs nothing."""
    trace = CallTrace(None, CALL)
    assert trace.open() is False and not trace.active
    trace.provider(user_final('слова'))
    trace.frame({'type': 'error', 'error': {'code': 'x'}})
    trace.note('x')
    trace.close()
    assert trace.path is None and trace.failure is None


# --- local only ---------------------------------------------------------------------------------------------------------------

def test_the_recorder_has_no_way_to_send_anything_anywhere():
    """«Local file only, never sent anywhere»: the module imports nothing that talks to a network or starts a program."""
    tree = ast.parse(Path(call_trace.__file__).read_text(encoding='utf-8'))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split('.')[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imported.add((node.module or '').split('.')[0])
    forbidden = {'socket', 'ssl', 'http', 'urllib', 'requests', 'aiohttp', 'httpx', 'websockets', 'smtplib', 'ftplib', 'subprocess',
                 'asyncio', 'multiprocessing', 'webbrowser', 'xmlrpc', 'telnetlib', 'shutil'}
    assert not imported & forbidden, imported & forbidden


def test_the_judge_lines_are_recorded_as_judge_records(tmp_path, caplog):
    """U15-S2: ``echo-sync judge rule=... chain=... analyses=...`` becomes one ``judge`` record; a decision line stays a decision."""
    trace, clock = make(tmp_path)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        trace.open()
        clock.now += 2
        decide('echo-sync judge tid=u3 rule=question chain=recall>question analyses=2 t=999 ev=hacked')
        decide('echo-sync decision kind=ack reason=x revision=1')
        trace.close()
    rows = records(trace.path)
    judged = [r for r in rows if r['ev'] == 'judge']
    assert len(judged) == 1 and judged[0]['t'] == 2000
    assert judged[0]['rule'] == 'question' and judged[0]['chain'] == 'recall>question' and judged[0]['analyses'] == 2 and judged[0]['tid'] == 'u3'
    assert len([r for r in rows if r['ev'] == 'decision']) == 1

"""UX-trace, part 1 through controlled_host.serve: a phone call leaves a LOCAL trace, and the trace changes nothing the phone sees.

The real serve() with a fake phone, a fake cloud helper and a fake SAPI worker, on virtual time (helpers_s6_fault.HostRig). The trace is
read back from <profile home>/logs/echo_calls/ the way the owner (or the next task) will read it.
"""
import json
import logging
from pathlib import Path

import pytest

import helpers_s6_fault as F
from echo_sync import controlled_host
from echo_sync.call_trace import CallTrace
from echo_sync.content_policy import POLICY_VERSION
from helpers_spoken_diagnostics import run_host


def trace_dir(home):
    return Path(home) / 'logs' / 'echo_calls'


def trace_files(home):
    folder = trace_dir(home)
    return sorted((f for f in folder.glob('*.jsonl') if '.v5tap' not in f.name)) if folder.is_dir() else []


def read_trace(home):
    """The records of the only trace file of the profile (the call may still be open: every line is flushed)."""
    files = trace_files(home)
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def settings_file(home, **values):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(values), encoding='utf-8')


# c23: since c22-merge a portion holds up to 9 words, and the body of F.DIRECT_ANSWER («свойство тела … движения.», 9 words) is ONE portion:
# the dictation needs an answer of two portions, the longer twin of the same answer.
LONG_ANSWER = F.DIRECT_ANSWER[:-1] + ', пока на него не действуют другие тела или силы.'


async def dictation(host):
    """A question, the cloud's answer, the first portion spoken, the listener repeats it, the second portion is spoken."""
    await host.ask(F.DIRECT_QUESTION, tid='u1')
    await host.answer(LONG_ANSWER, tid='a1')
    await host.advance(1)
    first = host.spoken()[0]
    host.cloud(F.created('r1', 'user', first.split()[0]))
    host.cloud(F.done('r1', 'user', first))
    await host.advance(1)
    return first


def what_the_phone_saw(host):
    """The phone-visible output of a call without ids and times: the type of every frame, the spoken text, the error code."""
    seen = []
    for frame in host.ws.frames:
        data = frame.data
        if data.get('type') == 'response.audio.delta':
            seen.append(('audio',))
        else:
            seen.append((data.get('type'), data.get('delta'), (data.get('error') or {}).get('code'), data.get('transcript')))
    return seen


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    """The product logs the controller's decisions at INFO (the owner's server does); the trace listens to that log."""
    caplog.set_level(logging.INFO, logger='echo-sync')


# --- what the trace holds -----------------------------------------------------------------------------------------------------

def test_a_phone_call_leaves_the_chain_words_then_decision_then_cue(tmp_path, monkeypatch):
    """The point of the trace: what was said, what the cloud answered, what the controller decided, and what was spoken - in order."""
    async def body(host):
        first = await dictation(host)
        rows = read_trace(host.home)
        assert rows[0]['ev'] == 'call_open'
        assert [r['text'] for r in rows if r['ev'] == 'user_final'] == [F.DIRECT_QUESTION, first]
        assert [r['text'] for r in rows if r['ev'] == 'assistant_final'] == [LONG_ANSWER]
        assert [(r['kind'], r['reason'], r['revision']) for r in rows if r['ev'] == 'decision'] == [
            ('question', 'question_mark', 1), ('ack', 'ack_ru_canonical', 1)]
        assert [r['text'] for r in rows if r['ev'] == 'cue'] == host.spoken() and len(host.spoken()) == 2
        chain = [r['ev'] for r in rows if r['ev'] in {'user_final', 'decision', 'assistant_final', 'cue'}]
        # the longer answer streams: its first portion is a closed clause and is cued before the cloud's final (the order a stream has)
        assert chain == ['user_final', 'decision', 'cue', 'assistant_final', 'user_final', 'decision', 'cue']
    run_host(tmp_path, monkeypatch, body)


def test_the_header_names_the_policy_and_the_settings_the_call_runs_with(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            settings_file(host.home, repeat_seconds=4, max_auto_repeats=2)
            await host.handshake()
            head = read_trace(host.home)[0]
            assert head['ev'] == 'call_open' and head['source'] == 'phone' and head['policy'] == POLICY_VERSION
            assert (head['repeat_seconds'], head['max_auto_repeats']) == (4, 2)
            assert head['decisions'] is True
    F.run(main)


def test_call_open_names_build_code_and_flags(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
            head = read_trace(host.home)[0]
            assert head['ev'] == 'call_open'
            for key in ('build', 'code', 'flags'):
                assert isinstance(head.get(key), str) and head[key], key
    F.run(main)


class WebSocketDisconnect(Exception):
    """The shape of the framework's disconnect: it carries the code."""
    def __init__(self, code):
        super().__init__('disconnect')
        self.code = code


def test_a_close_before_ready_writes_close_code_closer_and_stages(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.advance(0.5)
            host.ws.inbox.put_nowait(WebSocketDisconnect(1006))
            await host.advance(1)
        rows = read_trace(host.home)
        last = rows[-1]
        assert last['ev'] == 'call_close' and last['ready'] is False
        assert (last['closer'], last['close_code']) == ('phone', 1006)
        stages = [r for r in rows if r['ev'] == 'stage']
        assert [r['name'] for r in stages] == ['trace_open'] and all(isinstance(r['ms'], int) for r in stages)
    F.run(main)


def test_a_call_that_reached_ready_names_its_stages_in_order(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
        rows = read_trace(host.home)
        names = [r['name'] for r in rows if r['ev'] == 'stage']
        assert names[0] == 'trace_open' and names[-1] == 'ready' and len(names) == len(set(names))
        assert [r for r in rows if r['ev'] == 'call_close'][0]['closer'] == 'phone'      # the rig's teardown is the phone ending the read
    F.run(main)


def test_the_times_are_the_calls_own_monotonic_clock(tmp_path, monkeypatch):
    """Break: the trace cannot show the timer the owner complained about. Here: the silence auto-repeat, in milliseconds."""
    async def body(host):
        await host.ask(F.DIRECT_QUESTION, tid='u1')
        await host.answer(F.DIRECT_ANSWER, tid='a1')
        await host.advance(30)
        rows = read_trace(host.home)
        cues = [r for r in rows if r['ev'] == 'cue']
        assert len(cues) == 2 and cues[0]['text'] == cues[1]['text']
        assert 6000 <= cues[1]['t'] - cues[0]['t'] <= 7000                          # the calm timer: ~6 s of silence after the portion
        assert all(a['t'] <= b['t'] for a, b in zip(rows, rows[1:]))
        assert any(r['ev'] == 'decision' and r['reason'] == 'auto_repeat_cap' for r in rows)
    run_host(tmp_path, monkeypatch, body)


def test_the_end_of_the_call_is_the_last_line_with_the_counters(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
            await dictation(host)
            host.phone_audio(3)
            await host.advance(1)
        rows = read_trace(host.home)
        last = rows[-1]
        assert last['ev'] == 'call_close' and last['elapsed_ms'] > 0 and last['counters']['input_pcm_packets'] == 3
        assert last['counters']['user_finals'] == 2
        assert [r['ev'] for r in rows].count('call_close') == 1
    F.run(main)


def test_a_provider_error_and_the_spoken_diagnostic_are_in_the_trace(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            await host.handshake()
            host.cloud({'type': 'error', 'error': {'code': 'boom'}})
            await host.advance(5)
            rows = read_trace(host.home)
            assert any(r['ev'] == 'provider' and r['type'] == 'error' for r in rows)
            assert any(r['ev'] == 'error' and r['code'] == 'controlled_upstream_closed' for r in rows)
            assert any(r['ev'] == 'cue' and 'Облако недоступно' in r['text'] for r in rows)
            assert 'boom' not in json.dumps(rows), 'the provider\'s own error text is not copied'
    F.run(main)


def test_every_call_has_its_own_file(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        for _ in range(2):
            async with F.HostRig(tmp_path, monkeypatch) as host:
                await host.handshake()
        names = [p.name for p in trace_files(host.home)]
        assert len(names) == 2 and len(set(names)) == 2
    F.run(main)


# --- the switches --------------------------------------------------------------------------------------------------------------

def trace_off(monkeypatch):
    """What the owner's old ``call_trace: off`` was: a recorder with no folder (the key is gone, a phone call always traces; this is the baseline the guards compare with)."""
    real = CallTrace
    monkeypatch.setattr(controlled_host, 'CallTrace', lambda directory, *args, **keywords: real(None, *args, **keywords))


def test_a_phone_call_always_writes_its_trace_and_no_key_can_switch_it_off(tmp_path, monkeypatch):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            settings_file(host.home, call_trace='off')      # a profile that still names the old key: ignored
            await host.handshake()
        assert len(trace_files(host.home)) == 1
    F.run(main)


def test_a_probe_call_writes_no_trace_file(tmp_path, monkeypatch):
    """A probe (echo_trace=1) already streams its observations to its own client; its calls must not push the owner's calls out of the 50."""
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch, query={'echo_trace': '1'}) as host:
            await host.handshake()
            await host.ask(F.DIRECT_QUESTION)
            await host.answer(F.DIRECT_ANSWER)
            await host.advance(2)
        assert not (host.home / 'logs').exists()
    F.run(main)


# --- it never touches the call -------------------------------------------------------------------------------------------------

def normal_end(outcome):
    """serve() ends when the phone goes away: it returns cleanly, or (as a real websocket raises WebSocketDisconnect) it raises the rig's teardown WSClosed."""
    return outcome == 'returned' or (isinstance(outcome, F.WSClosed) and str(outcome) == 'test teardown')


def phone_run(tmp_path, monkeypatch, prepare=None, **rig):
    """One whole call; returns (what the phone saw, how serve ended, the rig's home)."""
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch, **rig) as host:
            if prepare:
                prepare(host)
            await host.handshake()
            await dictation(host)
            await host.advance(20)
        return what_the_phone_saw(host), host.outcome, host.home
    return F.run(main)


def test_the_phone_sees_exactly_the_same_with_the_trace_on_and_off(tmp_path, monkeypatch):
    """Break: the trace adds a frame, a delay or a reordering to a live call. The same scenario, twice, frame for frame."""
    on, outcome_on, _ = phone_run(tmp_path / 'on', monkeypatch)
    off, outcome_off, _ = phone_run(tmp_path / 'off', monkeypatch, prepare=lambda host: trace_off(monkeypatch))
    assert on == off and len(on) > 10
    assert normal_end(outcome_on) and normal_end(outcome_off)
    assert not any(str(frame[0]).startswith('conduit.echo') for frame in on), 'a trace is never a frame to the phone'


def test_a_folder_that_cannot_be_made_costs_the_call_nothing(tmp_path, monkeypatch, caplog):
    """The profile's logs folder is a FILE: the trace cannot start. The call goes on as if it were off."""
    def block(host):
        (host.home / 'logs').write_text('in the way', encoding='utf-8')
    blocked, outcome, home = phone_run(tmp_path / 'blocked', monkeypatch, prepare=block)
    free, _, _ = phone_run(tmp_path / 'free', monkeypatch, prepare=lambda host: trace_off(monkeypatch))
    assert blocked == free and normal_end(outcome)
    assert (home / 'logs').read_text(encoding='utf-8') == 'in the way'
    assert caplog.text.count('call trace stopped type=') == 1 and str(tmp_path) not in caplog.text


def test_a_disk_that_fails_in_the_middle_of_a_call_costs_the_call_nothing(tmp_path, monkeypatch, caplog):
    real = CallTrace._write_line
    written = []

    def dies_after_five_lines(self, line):
        if len(written) >= 5:
            raise OSError(28, 'No space left on device')
        written.append(line)
        real(self, line)
    with monkeypatch.context() as patched:
        patched.setattr(CallTrace, '_write_line', dies_after_five_lines)
        broken, outcome, home = phone_run(tmp_path / 'broken', patched)
    free, _, _ = phone_run(tmp_path / 'free', monkeypatch, prepare=lambda host: trace_off(monkeypatch))
    assert broken == free and normal_end(outcome)
    assert len(written) == 5 and len(read_trace(home)) == 5
    assert caplog.text.count('call trace stopped type=OSError') == 1


def test_a_bug_in_the_recorder_costs_the_call_nothing(tmp_path, monkeypatch):
    """Even an exception the recorder did not foresee (here: in its own record builder) stays inside it."""
    def explode(self, ev, fields, **keywords):
        raise RuntimeError('bug in the recorder')
    with monkeypatch.context() as patched:
        patched.setattr(CallTrace, '_emit', explode)
        broken, outcome, _ = phone_run(tmp_path / 'broken', patched)
    free, _, _ = phone_run(tmp_path / 'free', monkeypatch, prepare=lambda host: trace_off(monkeypatch))
    assert broken == free and normal_end(outcome)

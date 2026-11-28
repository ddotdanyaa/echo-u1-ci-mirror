"""V5 step 0, facts in the journal: every new behaviour is behind a setting whose default is today's behaviour.

(a) mic_gap / mic_back and the arrival stamps of the microphone packets (CallTrace, ``facts_journal``), (b) the rule or timer behind a hold or a
drop (``why`` records), (c) the recording cap per call (``pcm_record_call_mb``), (d) one readiness verdict after the first cue of a call.
"""
import base64
import json
from pathlib import Path

import pytest

import helpers_s6_fault as F
from echo_sync import call_audio, call_trace, settings as cfg
from echo_sync.call_trace import CallTrace

PACKET = base64.b64encode(bytes(4800)).decode()      # 2400 samples = 100 ms
APPEND = {'type': 'input_audio_buffer.append', 'audio': PACKET}


class Clock:
    def __init__(self):
        self.now = 5000.0

    def __call__(self):
        return self.now


def make(tmp_path, **keywords):
    clock = Clock()
    trace = CallTrace(tmp_path / 'echo_calls', 'abc', clock=clock, **keywords)
    assert trace.open(source='phone')
    return trace, clock


def records(trace):
    return [json.loads(line) for line in Path(trace.path).read_text(encoding='utf-8').splitlines()]


def kinds(trace, ev):
    return [r for r in records(trace) if r['ev'] == ev]


def feed(trace, clock, count, step=0.1):
    for _ in range(count):
        clock.now += step
        trace.mic(APPEND)


# --- settings: today's behaviour is the default --------------------------------------------------------------------------------

def test_the_new_settings_default_to_todays_behaviour():
    d = cfg.DEFAULTS
    assert 'facts_journal' not in d and (d['mic_gap_ms'], d['mic_ring_s'], d['pcm_record_call_mb']) == (1500, 60, 200)
    assert cfg.resolve({})['pcm_record_call_mb'] == 200
    r = cfg.resolve({'mic_gap_ms': 10, 'pcm_record_call_mb': 99999, 'mic_ring_s': 99999})      # out of range: the default, like every number here
    assert (r['mic_gap_ms'], r['pcm_record_call_mb'], r['mic_ring_s']) == (1500, 200, 60)
    r = cfg.resolve({'mic_gap_ms': 3000, 'pcm_record_call_mb': 500, 'mic_ring_s': 120})
    assert (r['mic_gap_ms'], r['pcm_record_call_mb'], r['mic_ring_s']) == (3000, 500, 120)


# --- (a) microphone facts ------------------------------------------------------------------------------------------------------

def test_off_writes_no_microphone_facts(tmp_path):
    trace, clock = make(tmp_path)
    feed(trace, clock, 3)
    clock.now += 30
    feed(trace, clock, 1)
    trace.close()
    assert not [r for r in records(trace) if r['ev'] in ('mic_gap', 'mic_back', 'mic_facts')]


def test_a_gap_is_written_when_the_audio_comes_back_and_is_never_called_silence(tmp_path):
    trace, clock = make(tmp_path, facts=True, mic_gap_ms=1500)
    feed(trace, clock, 5)
    start_ms = round((clock.now - 5000.0) * 1000)
    clock.now += 4.0
    trace.mic(APPEND)
    gap, back = kinds(trace, 'mic_gap'), kinds(trace, 'mic_back')
    assert len(gap) == 1 and len(back) == 1
    g = gap[0]
    assert g['cause'] == 'unknown' and g['start_ms'] == start_ms and g['end_ms'] == start_ms + 4000 and g['seq_before'] == 5 and g['seq_after'] == 6
    assert 'silence' not in json.dumps(records(trace)).replace('"cause":"unknown"', '')
    assert back[0]['gap_ms'] == 4000


def test_a_gap_shorter_than_the_tolerance_is_not_a_gap(tmp_path):
    trace, clock = make(tmp_path, facts=True, mic_gap_ms=1500)
    feed(trace, clock, 3)
    clock.now += 1.2
    trace.mic(APPEND)
    assert not kinds(trace, 'mic_gap')


def test_a_gap_is_seen_while_it_lasts_by_the_watch_and_reported_once(tmp_path):
    trace, clock = make(tmp_path, facts=True, mic_gap_ms=1500)
    feed(trace, clock, 3)
    clock.now += 1.0
    trace.mic_watch()
    assert not kinds(trace, 'mic_gap')
    clock.now += 1.0
    trace.mic_watch()
    trace.mic_watch()
    gap = kinds(trace, 'mic_gap')
    assert len(gap) == 1 and gap[0]['cause'] == 'unknown' and gap[0]['open'] is True
    clock.now += 3.0
    trace.mic(APPEND)
    assert len(kinds(trace, 'mic_gap')) == 1 and kinds(trace, 'mic_back')[0]['gap_ms'] >= 5000


def test_a_gap_before_the_first_packet_is_not_invented(tmp_path):
    trace, clock = make(tmp_path, facts=True)
    clock.now += 60
    trace.mic_watch()
    assert not kinds(trace, 'mic_gap')


def test_the_close_names_the_counts_and_an_open_gap(tmp_path):
    trace, clock = make(tmp_path, facts=True, mic_gap_ms=1500)
    feed(trace, clock, 4)
    clock.now += 9.0
    trace.close()
    facts = kinds(trace, 'mic_facts')[0]
    assert facts['appends'] == 4 and facts['samples'] == 4 * 2400 and facts['gaps'] == 1
    assert kinds(trace, 'mic_gap')[0]['open'] is True and not kinds(trace, 'mic_back')


def test_the_microphone_budget_becomes_a_ring_of_the_last_seconds(tmp_path, monkeypatch):
    monkeypatch.setattr(call_trace, 'MIC_BUDGET_BYTES', 20_000)      # the real budget holds a three-hour call (u89); the rule here is what happens when it is spent
    trace, clock = make(tmp_path, facts=True, mic_ring_s=5)
    for _ in range(400):
        feed(trace, clock, 1, step=1.0)
    trace.close()
    rs = records(trace)
    assert any(r['ev'] == 'mic_full' for r in rs)
    tail = [r for r in rs if r['ev'] == 'mic_tail'][0]
    assert len(tail['secs']) == 5 and tail['secs'][-1][0] > tail['secs'][0][0] and rs[-1]['ev'] == 'call_close'


def test_without_the_switch_the_budget_still_ends_in_mic_full_and_nothing_more(tmp_path, monkeypatch):
    monkeypatch.setattr(call_trace, 'MIC_BUDGET_BYTES', 20_000)      # as above: the budget is the thing under test, not its size
    trace, clock = make(tmp_path)
    for _ in range(400):
        feed(trace, clock, 1, step=1.0)
    trace.close()
    assert any(r['ev'] == 'mic_full' for r in records(trace)) and not kinds(trace, 'mic_tail')


# --- (c) the recording cap ------------------------------------------------------------------------------------------------------

def test_the_call_recorder_gets_the_configured_cap(tmp_path, monkeypatch):
    seen = []
    real = call_audio.CallAudio
    monkeypatch.setattr(call_audio, 'CallAudio', lambda root, call_id, **k: (seen.append(k), real(root, call_id, **k))[1])
    import test_u07_call_audio_host as H
    from test_ux_call_trace_host import settings_file
    H.run_call(tmp_path / 'a', monkeypatch, prepare=lambda h: settings_file(h.home))
    H.run_call(tmp_path / 'b', monkeypatch, prepare=lambda h: settings_file(h.home, pcm_record_call_mb=500))
    assert [k['cap_mb'] for k in seen] == [200, 500]


def test_the_minutes_the_cap_gives_are_told():
    assert call_audio.minutes(200) == pytest.approx(72.8, abs=0.1) and call_audio.minutes(200, channels=2) == pytest.approx(36.4, abs=0.1)


# --- (d) the readiness verdict after the first cue ---------------------------------------------------------------------------

def cue(trace, clock, seconds, packets_every=0.1):
    trace.frame({'type': 'response.created'})
    steps = int(seconds / 0.02)
    for i in range(steps):
        clock.now += 0.02
        trace.frame({'type': 'response.audio.delta', 'delta': 'AAAA'})
        if packets_every and i % int(round(packets_every / 0.02)) == 0:
            trace.mic(APPEND)
    trace.frame({'type': 'response.done', 'response': {'id': 'r1', 'status': 'completed'}})


def test_the_verdict_says_the_microphone_kept_arriving(tmp_path):
    trace, clock = make(tmp_path, facts=True)
    feed(trace, clock, 20)
    cue(trace, clock, 3.0)
    v = kinds(trace, 'ready_verdict')
    assert len(v) == 1 and v[0]['mic_kept'] is True and v[0]['reason'] == 'packets_kept_arriving' and v[0]['coverage'] >= 0.75


def test_the_verdict_says_plainly_when_the_packets_stopped_and_comes_once(tmp_path):
    trace, clock = make(tmp_path, facts=True)
    feed(trace, clock, 20)
    cue(trace, clock, 3.0, packets_every=0)
    cue(trace, clock, 3.0)
    v = kinds(trace, 'ready_verdict')
    assert len(v) == 1 and v[0]['mic_kept'] is False and v[0]['reason'].startswith('no_packets_while_the_cue_played')


def test_no_verdict_when_the_switch_is_off(tmp_path):
    trace, clock = make(tmp_path)
    feed(trace, clock, 20)
    cue(trace, clock, 3.0)
    assert not kinds(trace, 'ready_verdict')


# --- the host wires the switches ---------------------------------------------------------------------------------------------

def host_trace(tmp_path, monkeypatch, **values):
    import test_u07_call_audio_host as H
    from test_ux_call_trace_host import read_trace, settings_file
    host = H.run_call(tmp_path, monkeypatch, prepare=lambda h: settings_file(h.home, **values) if values else None)
    return read_trace(host.home)


def test_in_a_real_call_the_facts_are_always_written(tmp_path, monkeypatch):
    rs = host_trace(tmp_path, monkeypatch)
    facts = [r for r in rs if r['ev'] == 'mic_facts']
    assert len(facts) == 1 and facts[0]['appends'] == 5 and facts[0]['samples'] == 5 * 512
    assert [r for r in rs if r['ev'] == 'mic_gap'], 'the virtual 20 s after the last packet is a gap'
    assert all(r['cause'] == 'unknown' for r in rs if r['ev'] == 'mic_gap')


# --- (b) the rule or timer behind a hold or a drop ---------------------------------------------------------------------------

def controller(tmp_path, on, name='why'):
    import helpers_s6_ack as H
    from echo_sync.controlled_media import ControlledMedia
    c = ControlledMedia(tmp_path / (name + '.sqlite3'), session_id=H.SESSION, clock=H.FakeClock(), **H.HOST_KWARGS)
    if on:
        c.facts_why = True
    return c


from echo_sync.cm_question import CLOSE, Fate      # noqa: E402


def why_lines(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith('echo-sync why ')]


def test_a_drop_names_the_site_and_the_constant_behind_it(tmp_path, caplog):
    caplog.set_level('INFO', logger='echo-sync')
    c = controller(tmp_path, True)
    c._drop_question()
    c._end_question(Fate(CLOSE, 'abandon'), {})
    lines = why_lines(caplog)
    assert any('kind=drop' in l and 'subject=question' in l and 'rule=drop_question' in l and 'by=' in l for l in lines), lines
    assert any('rule=abandon' in l and 'const=ABANDON_SECONDS' in l for l in lines), lines


def test_the_watchdog_drop_names_the_answer_wait_constants(tmp_path, caplog):
    from echo_sync import why_journal
    caplog.set_level('INFO', logger='echo-sync')
    c = controller(tmp_path, True)

    def _answer_watchdog():
        c._drop_question()
    _answer_watchdog()
    line = why_lines(caplog)[0]
    assert 'by=_answer_watchdog' in line and 'const=ANSWER_WAIT_SECONDS' in line and 'seconds=8.0' in line
    assert why_journal.SITES['_answer_watchdog'][0] == 'ANSWER_WAIT_SECONDS'


def test_without_the_switch_nothing_is_logged_and_the_state_is_the_same(tmp_path, caplog):
    caplog.set_level('INFO', logger='echo-sync')
    off = controller(tmp_path, False, 'off')
    for c in (off,):
        c._drop_question()
        c._new_epoch('abandon')
    facts = lambda: [line for line in why_lines(caplog) if ' kind=act ' not in line + ' ']        # 3.01 act_gate always on (dc839fb8): the gate writes its own kind=act line, which facts_why does not switch
    assert not facts()
    on = controller(tmp_path, True, 'on')
    on._drop_question()
    on._new_epoch('abandon')
    assert off.epoch == on.epoch and len(facts()) == 2


def test_a_hold_is_written_when_it_begins_or_changes_and_not_on_every_tick(tmp_path, caplog):
    from echo_sync import why_journal
    caplog.set_level('INFO', logger='echo-sync')
    c = controller(tmp_path, True)
    for _ in range(50):
        why_journal.why(c, 'hold', 'first_cue', 'speech_with_content', 'FIRST_HOLD_SECONDS', ident=3)
    why_journal.why(c, 'hold', 'first_cue', 'ear_text_awaited', 'TEMPO_TEXT_SECONDS', ident=3)
    why_journal.why(c, 'hold', 'first_cue', 'speech_with_content', 'FIRST_HOLD_SECONDS', ident=4)
    assert len(why_lines(caplog)) == 3 and 'seconds=8.0' in why_lines(caplog)[0]


def test_the_tap_turns_a_why_line_into_a_why_record(tmp_path):
    trace, _ = make(tmp_path, facts=True)
    import logging
    from echo_sync import call_trace
    logging.getLogger('echo-sync').setLevel(logging.INFO)
    logging.getLogger('echo-sync').info('echo-sync why kind=hold subject=first_cue rule=speech_with_content const=FIRST_HOLD_SECONDS id=3 seconds=8.0')
    w = kinds(trace, 'why')
    assert len(w) == 1 and w[0]['rule'] == 'speech_with_content' and w[0]['seconds'] == 8.0 and w[0]['const'] == 'FIRST_HOLD_SECONDS'
    trace.close()


def test_a_real_hold_of_the_first_cue_is_named_and_decides_the_same(tmp_path, caplog):
    caplog.set_level('INFO', logger='echo-sync')
    results = {}
    for on in (False, True):
        c = controller(tmp_path, on, 'h%d' % on)
        c.tempo_live, c.tempo_awaits, c.tempo_ended = True, 'text', c.clock() - 0.1
        results[on] = [c.first_cue_hold() is not None for _ in range(5)]
    assert results[False] == results[True] == [True] * 5
    lines = why_lines(caplog)
    assert len(lines) == 1 and 'kind=hold subject=first_cue rule=ear_text_awaited const=TEMPO_TEXT_SECONDS' in lines[0] and 'seconds=' in lines[0]


def test_a_cue_held_by_the_cloud_hearing_the_listener_is_named(tmp_path, caplog):
    caplog.set_level('INFO', logger='echo-sync')
    from echo_sync import why_journal

    class Owner:
        facts_why = True
    why_journal.why(Owner(), 'hold', 'cue', 'cloud_hears_listener', 'HEARING_SECONDS', 1, by='hold', first=0)
    assert 'rule=cloud_hears_listener const=HEARING_SECONDS' in why_lines(caplog)[0]

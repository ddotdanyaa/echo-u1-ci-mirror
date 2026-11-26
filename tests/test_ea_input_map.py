"""E07.2 / U71 (package EA): the map of the paths of the input is data (``call_trace.INPUT_PATHS``) and it is held to the code.

  * every owner of a path is a real ``module:Symbol`` and every proof a real test file: a path that is not in the code, or a reader that is not in the map, fails here;
  * the switches the map names are the profile's own keys;
  * ONE phone stream through the real ControlledMedia + NativeMediaSocket stand reaches each reader of the map once (cloud, clock, trace, ear) - several readers of the same
    packets are not several sources - and the recognizers of a call are the two the map lists (U71): the cloud and the local ear.
"""
import base64
import importlib
from pathlib import Path

import pytest

import helpers_night_memory as N
from echo_sync import call_trace, settings as cfg
from echo_sync.settings import resolve
from test_ear_shadow import ScriptedDetector
from test_s5_ear_part import LIVE, Toy, build, settle, tagged

TESTS = Path(__file__).resolve().parent
PACKETS = 6


def _resolve(anchor):
    module, symbol = anchor.split(':')
    found = importlib.import_module('echo_sync.' + module)
    for part in symbol.split('.'):
        found = getattr(found, part)
    return found


def test_every_owner_in_the_map_is_in_the_code_and_every_proof_is_a_test():
    ids = [row[0] for row in call_trace.INPUT_PATHS]
    assert len(ids) == len(set(ids)) and {'wire', 'cloud', 'ear', 'trace', 'record'} <= set(ids)
    for row in call_trace.INPUT_PATHS:
        assert len(row) == 8 and all(isinstance(field, (str, tuple)) and field for field in row), row[0]
        for anchor in row[3]:
            assert _resolve(anchor) is not None, (row[0], anchor)
        assert (TESTS / row[6]).is_file(), (row[0], row[6])


def test_the_switches_the_map_names_are_keys_of_the_profile_and_the_ear_is_off_by_default():
    named = {key for row in call_trace.INPUT_PATHS for key in cfg.DEFAULTS if key in row[2].replace('|', ' ').replace(';', ' ').replace(',', ' ').split()}
    assert {'local_ear'} <= named
    assert resolve({})['local_ear'] == 'off'


def test_one_phone_stream_reaches_each_reader_of_the_map_once_and_two_recognizers_hear_it(tmp_path, caplog):
    toy = Toy()
    call = build(tmp_path, caplog, ScriptedDetector(['onset'] + ['speech'] * (PACKETS - 2) + ['end']), toy)
    try:
        for i in range(PACKETS):
            pcm = tagged(i)
            event = {'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode('ascii')}
            call.trace.mic(event)                        # the host's own order: the trace counts the packet, then the wire hands it on
            call.w.client(event)
            call.w.advance(0.1)
        settle(call, 1)
        sent = [payload for kind, payload in call.w.source.frames if kind == 'P']
        assert len(sent) == PACKETS, 'the cloud reader: every packet once'
        assert call.trace.meter.packets == PACKETS, 'the trace reader: every packet once'
        assert call.w.wire.input_ms() == pytest.approx(PACKETS * 100, abs=1), 'the clock reader: the sound forwarded'
        finals = call.finals()
        assert finals and finals[0].get('text'), 'the ear reader: an utterance of text'
        assert len(toy.started) >= 1
    finally:
        call.close()
    assert call_trace.RECOGNIZERS == ('cloud', 'ear') and {row[0] for row in call_trace.INPUT_PATHS} >= set(call_trace.RECOGNIZERS)


def test_the_trace_of_the_call_reads_the_map_and_says_which_recognizers_heard_it(tmp_path, caplog):
    """E07.2 / U71 through the real ControlledMedia stand: the opening line of the call's journal carries the paths of the map, and the live ear says that it is the second recognizer."""
    toy = Toy()
    call = build(tmp_path, caplog, ScriptedDetector(['onset', 'speech', 'speech', 'end']), toy)
    try:
        for i in range(4):
            call.w.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(tagged(i)).decode('ascii')})
            call.w.advance(0.1)
        settle(call, 1)
        journal = call.journal()
        opened = [r for r in journal if r['ev'] == 'call_open']
        assert opened and opened[0]['input_paths'] == [row[0] for row in call_trace.INPUT_PATHS]
        told = [r for r in journal if r['ev'] == 'input_readers']
        assert told and told[0]['recognizers'] == ['cloud', 'ear'] and told[0]['ear'] in ('shadow', 'act')
    finally:
        call.close()

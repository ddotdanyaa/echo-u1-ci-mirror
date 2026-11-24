"""Registry 5.08 «Служебные фразы при сбое: телефон не остаётся в тишине» - state per registry: РАБОТАЕТ НА СЕРВЕРЕ, always on, no key.

Proved through the real controlled_host.serve() (HostRig: fake phone, cloud helper, SAPI and lookup on virtual time): on each
failure the phone receives ONE short spoken phrase as an ordinary paced response (created -> transcript -> audio -> done),
never silence, and the call journal (<home>/logs/echo_calls) records the failure code and the phrase as a cue. Failures:
no answer in time, cue synthesis (twice), lookup, upstream channel. A healthy call says no phrase. Dummy check (private copy):
the single entry point NativeMediaSocket that starts a failure phrase stubbed to do nothing - the failure tests go red, the healthy one stays green.
"""
import json
import logging

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import ANSWER, CHANNEL, EVERY_PHRASE, LOOKUP_EMPTY, SYNTHESIS, responses, run_host


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')   # the journal listens to the product log, as on the owner's server


def journal(host):
    """The call journal records of the only call of the profile, read back from disk."""
    files = sorted((f for f in (host.home / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def assert_spoken_not_silent(host, phrase, code, *, frame=True):
    """One phrase, as a whole normal spoken response with real audio; the journal has code and cue. The error frame reaches the phone (``frame``) except for a failure the listener hears told and the call goes on
    with (P20, class 'lookup'): the frame is the journal's and the log's, the phone gets the phrase only."""
    heard = responses(host.ws.frames)
    assert [r['text'] for r in heard] == [phrase], host.ws.frames
    assert heard[0]['status'] == 'completed' and heard[0]['pcm'], 'the phrase must be played, not just announced'
    assert host.errors() == ([code] if frame else [])
    events = journal(host)
    assert [r['code'] for r in events if r['ev'] == 'error'] == [code]
    assert [r['text'] for r in events if r['ev'] == 'cue'] == [phrase], 'the phrase is a cue of the call journal'


def test_no_answer_in_time_is_spoken_and_journaled(tmp_path, monkeypatch):
    async def body(host):
        await host.ask(F.DIRECT_QUESTION)             # the cloud takes the question and never answers
        await host.advance(14)
        assert_spoken_not_silent(host, ANSWER, 'controlled_answer_timeout')
        assert ('decision', 'silent', 'answer_timeout') in [(r['ev'], r.get('kind'), r.get('reason')) for r in journal(host)]
        assert not host.finished, 'the call goes on'
    run_host(tmp_path, monkeypatch, body)


def test_a_cue_that_cannot_be_synthesized_is_replaced_by_the_synthesis_phrase(tmp_path, monkeypatch):
    async def body(host):
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(10)
        assert_spoken_not_silent(host, SYNTHESIS, 'controlled_synthesis_failed')
    run_host(tmp_path, monkeypatch, body, synth=['raise'])


def test_a_failed_lookup_ends_in_a_spoken_phrase_not_silence(tmp_path, monkeypatch):
    async def body(host):
        await host.ask(F.LOOKUP_QUESTION)
        await host.advance(22)
        assert_spoken_not_silent(host, LOOKUP_EMPTY, 'controlled_sources_unavailable', frame=False)
    run_host(tmp_path, monkeypatch, body, lookup=['raise'])


def test_a_closed_upstream_channel_is_spoken_before_the_call_ends(tmp_path, monkeypatch):
    async def body(host):
        host.bridge.push('X', b'')                    # the helper pipe reports that the cloud channel closed
        await host.advance(8)
        assert_spoken_not_silent(host, CHANNEL, 'controlled_upstream_closed')
        assert 'call_close' in [r['ev'] for r in journal(host)]
    run_host(tmp_path, monkeypatch, body)


def test_a_healthy_answer_is_not_followed_by_any_service_phrase(tmp_path, monkeypatch):
    async def body(host):
        await host.ask(F.DIRECT_QUESTION)
        await host.answer(F.DIRECT_ANSWER)
        await host.advance(14)
        heard = [r['text'] for r in responses(host.ws.frames)]
        assert heard and not set(heard) & set(EVERY_PHRASE), heard
        assert not host.errors() and 'error' not in [r['ev'] for r in journal(host)]
    run_host(tmp_path, monkeypatch, body)

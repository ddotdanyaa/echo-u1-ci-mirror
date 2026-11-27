"""Registry 5.01d «Падение голоса в конце ответа» (state per registry: ВЫКЛЮЧЕНО, key end_intonation, code default off).

Goal described here (xfail strict until the key is on by default / switched on at deployment): through the real controlled_host.serve()
(helpers_s6_fault.HostRig: real controller, NativeMediaSocket, virtual time; fake phone / cloud pipe / SAPI worker) the owner asks, the cloud
answers in several portions, the owner repeats each portion aloud. The phone is shown the portions in order, and the synthesizer (the fake SAPI
worker) receives the end mark ('fall') for the LAST portion only; middle portions are voiced plain. The profile file does NOT set end_intonation:
the engine default, read at run time, acts (as of now off -> no portion carries the mark).
Boundary note: helpers_s6_fault.FakeWorker.synthesize(text, path) has no ``end`` parameter, so the test wraps that fake (not the engine) to record it.
Mutation check (private copy): the default of end_intonation in echo_sync/settings.py switched off -> fall: the test passes under --runxfail; off: fails.
"""
import json
import re

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

pytestmark = pytest.mark.xfail(strict=True, reason='реестр 5.01d: ВЫКЛЮЧЕНО (end_intonation=off по умолчанию, в синтез не уходит пометка конца ответа)')
ANSWER = ('Фотосинтез — это процесс образования органических веществ на свету. Он идёт в хлоропластах клеток зелёных растений, '
          'где поглощается углекислый газ и выделяется кислород.')


def put_settings(host):
    folder = host.home / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps({'preset': 'meaning'}), encoding='utf-8')      # live preset (portions by meaning); end_intonation left to the default


def key(text):
    return re.sub(r'\W+', ' ', text).strip().lower()


def test_only_the_last_portion_is_sent_to_the_voice_with_the_end_mark(tmp_path, monkeypatch):
    async def body(host):
        sent, plain = [], host.worker.synthesize
        def recording(text, path, end=None):      # the fake worker gets what the real SAPI worker would: text and the end style
            sent.append((key(text), end))
            return plain(text, path)
        host.worker.synthesize = recording
        put_settings(host)
        await host.handshake()
        await host.ask(F.DIRECT_QUESTION, tid='u1')
        await host.answer(ANSWER, tid='a1')
        await host.advance(1)
        for n in range(8):                                      # the owner repeats every portion as it comes
            before = len(host.spoken())
            host.cloud(F.created('r%d' % n, 'user', host.spoken()[-1].split()[0]))
            host.cloud(F.done('r%d' % n, 'user', host.spoken()[-1]))
            await host.advance(1)
            if len(host.spoken()) == before:
                break
        portions = [key(p) for p in host.spoken()]
        assert len(portions) >= 3, portions                      # an answer in several portions, in order
        first_time = {}
        for text, end in sent:                                   # the first synthesis of each portion
            first_time.setdefault(text, end)
        marks = [first_time.get(p) for p in portions]
        assert all(p in first_time for p in portions), (portions, sent)      # every portion reached the synthesizer
        assert marks[:-1] == [None] * (len(portions) - 1), marks             # middle portions are voiced as before
        assert marks[-1] == 'fall', marks                                    # the last portion carries the end mark
    run_host(tmp_path, monkeypatch, body, handshake=False)

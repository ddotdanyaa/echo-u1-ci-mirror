"""Registry 5.04 «Диктовка порциями»; state by the registry: РАБОТАЕТ НА СЕРВЕРЕ, `portion_sense` ВЫКЛЮЧЕНО.

Proved through the real controlled_host.serve (helpers_s6_fault.HostRig: real controller, NativeMediaSocket and engine; fake phone, cloud
pipe, SAPI, lookup, virtual time). The owner asks, the cloud answers, the fake phone «hears» the owner repeat each portion; read back only
what the phone is told to say, what goes to SAPI, and the call journal (logs/echo_calls). Cloud stand on virtual time, not a device.
 1 meaning portions: every portion is within the preset sizes (<= 9 words, <= 26 syllables), the first one is a whole sentence of 5+ words
   (not a 3-word cut), the portions in order are the text of the answer (only the lead-in the owner heard may be missing)
 2 dictation on the LIVE combination (repeat_seconds=2.0): after 3 s of silence the auto-repeat has said the SAME portion again (the code default
   6.0 s would not have), after 8 s still never the NEXT one; a repeat aloud brings exactly the next portion; SAPI gets the portion texts; the journal holds
   a question decision, then an ack decision per repeat
 3 portion_sense (OFF by registry; xfail strict): a list marker «2)» must not be cut off from its item
 4 the profile file acts on portions: preset=slow in the file gives 6+ portions of <= 4 words (CALL_SETTINGS stays meaning)
Settings: the profile file gets preset=meaning and repeat_seconds=2.0 (live: prompt_tempo=ear + local_ear=act derive 2.0, the code
default is 6.0; the file here states it outright); the call's CALL_SETTINGS holds preset=meaning too; portion_sense is NOT set - the code
default acts. The file's preset reaches the call (test 4: preset=slow in the file gives short portions); min_words is not pinned by a test.
Dummy check (private copy): CALL_SETTINGS preset -> None AND no preset in the file kills 1 and 2; the file without repeat_seconds kills 2;
the idle timer saying the NEXT portion (engine.current) kills 2; the file's portion keys not passed to the call kills 4; DEFAULTS
portion_sense=on turns 3 green (with --runxfail)."""
import json
import logging
import re

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

QUESTION = 'Что такое фотосинтез?'
ANSWER = ('Фотосинтез — это процесс образования органических веществ на свету. Он идёт в хлоропластах клеток зелёных растений, '
          'где поглощается углекислый газ и выделяется кислород.')
LISTING = 'Список покупок такой: 1) хлеб и молоко, 2) яйца и сыр, 3) яблоки и бананы для всей семьи.'


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')   # the journal listens to the controller's INFO log


def words(text):
    return re.findall(r'\w+', text.lower())


def syllables(text):
    return len(re.findall('[аеёиоуыэюя]', text.lower()))


def put_settings(host, **keys):
    folder = host.home / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps({'preset': 'meaning', 'repeat_seconds': 2.0, **keys}), encoding='utf-8')


def journal(host):
    (path,) = list((f for f in (host.home / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]


async def say_back(host, n, text):
    """The owner repeats the portion aloud: the cloud sends the transcription of the owner's voice."""
    host.cloud(F.created('r%d' % n, 'user', text.split()[0]))
    host.cloud(F.done('r%d' % n, 'user', text))
    await host.advance(1)


async def dictate(host, answer, question=QUESTION, **keys):
    """Ask, answer, repeat every portion as it comes. -> the portions in order of speaking."""
    put_settings(host, **keys)
    await host.handshake()
    await host.ask(question, tid='u1')
    await host.answer(answer, tid='a1')
    await host.advance(1)
    for n in range(8):
        before = len(host.spoken())
        await say_back(host, n, host.spoken()[-1])
        if len(host.spoken()) == before:
            break
    return host.spoken()


def test_portions_are_by_meaning_and_in_order(tmp_path, monkeypatch):
    async def body(host):
        cues = await dictate(host, ANSWER)
        assert len(cues) >= 3, cues
        assert all(len(words(c)) <= 9 and syllables(c) <= 26 for c in cues), cues       # preset meaning: max_words 9, max_syllables 26
        assert len(words(cues[0])) >= 5 and cues[0].endswith('.'), cues[0]               # the whole first sentence, not a 3-word cut
        said, full = words(' '.join(cues)), words(ANSWER)
        assert full[-len(said):] == said and len(full) - len(said) <= 3, (said, full)   # in order, whole; only the heard lead-in may go
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_next_portion_waits_for_the_repeat_at_live_timer_and_is_journalled(tmp_path, monkeypatch):
    async def body(host):
        put_settings(host)
        await host.handshake()
        await host.ask(QUESTION, tid='u1')
        await host.answer(ANSWER, tid='a1')
        await host.advance(1)
        first = host.spoken()
        assert len(first) == 1 and len(words(first[0])) >= 5, first                    # one portion, by meaning (5+ words)
        await host.advance(3)                                                           # live timer 2.0 s has fired, the code default 6.0 s has not
        assert host.spoken() == first * 2, host.spoken()                                # the auto-repeat says the SAME portion again
        await host.advance(5)                                                           # more silence: still never the NEXT portion
        assert set(host.spoken()) == set(first), host.spoken()
        n = len(host.spoken())
        await say_back(host, 0, first[0])
        assert len(host.spoken()) == n + 1 and host.spoken()[n] not in first, host.spoken()   # the owner's voice brings exactly the next one
        await say_back(host, 1, host.spoken()[n])
        spoken = host.spoken()
        assert len(spoken) == n + 2 and spoken[n + 1] not in spoken[:n + 1], spoken
        sapi = [text for _, text in host.synth_plan.calls]
        assert all(any(c.rstrip('.,') in s for s in sapi) for c in spoken), (spoken, sapi)   # the portions went to SAPI
        rows = journal(host)
        assert [r['text'] for r in rows if r['ev'] == 'cue'] == spoken                  # the journal holds what was cued, in order
        assert [(r['kind'], r['reason']) for r in rows if r['ev'] == 'decision' and r['kind'] != 'silent'] == [
            ('question', 'question_mark'), ('ack', 'ack_ru_canonical'), ('ack', 'ack_ru_canonical')]
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_profile_file_preset_changes_the_portions(tmp_path, monkeypatch):
    async def body(host):
        cues = await dictate(host, ANSWER, preset='slow')                                # the file's preset, against the call's own meaning
        assert len(cues) >= 6 and all(len(words(c)) <= 4 for c in cues), cues          # file acts: short slow portions, not sentences
    run_host(tmp_path, monkeypatch, body, handshake=False)


@pytest.mark.xfail(strict=True, reason="реестр 5.04: portion_sense ВЫКЛЮЧЕНО (off): маркер списка «2)» остаётся в конце порции, отрываясь от пункта")
def test_portion_sense_keeps_a_list_marker_with_its_item(tmp_path, monkeypatch):
    async def body(host):
        cues = await dictate(host, LISTING, 'Что купить?')
        assert len(cues) >= 3, cues
        assert not any(re.search(r'\d\)$', c) for c in cues), cues                      # no portion ends on a bare list marker
    run_host(tmp_path, monkeypatch, body, handshake=False)

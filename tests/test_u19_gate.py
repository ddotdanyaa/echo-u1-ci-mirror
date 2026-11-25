"""U19-S3: the controller's language field (``turn_lang``) and the ear gate ``_ear_lang_gate``, in front of the input meter (U17) in each ear entry.
(1) a gated record holds ``tempo_hold`` and reaches the meter as pending_asr for the hold; (2) a Russian record is never gated (the flag lang_turn is deleted, the gate is always on); (3) the cloud's final sets the language and
the Russian ear's Cyrillic over an English turn is gated (always, no key). Injected clock."""
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync.controlled_media import TEMPO_HOLD_SECONDS      # noqa: E402
from echo_sync.input_state import PENDING_ASR      # noqa: E402
from test_h3_tempo import call       # noqa: E402,F401 - call is the fixture
from test_x_tick_order import armed      # noqa: E402

LOG = 'echo-sync'
PACKET = b'\x10\x00' * 480
ENGLISH = 'what is the formula of the tax'
RUSSIAN = 'что такое налоговая база'


def feed(c, now, n=25):
    for i in range(n):
        c.mic_packet(len(PACKET), -30.0, now=now - 1.0 + i * 0.02)


def said(c, state, uid, text, now, **extra):
    c.tempo_spans[uid] = (now - 1.0, c._position(state))
    return {'uid': uid, 'text': text, 'offset': now, 'kind': 'final', 'speech_ms': 900, **extra}


def test_a_gated_record_holds_and_the_meter_says_pending_asr(call):
    rig, c, state = armed(call)
    now = c.clock()
    feed(c, now)
    c.repeat_at = now + 3
    c.tempo_heard(said(c, state, 7, ENGLISH, now))
    assert c.tempo_hold == (c._position(state), now) and c.repeat_at is None
    assert c.lang_gated == 1
    assert c.input_probe.state(now + 0.1) == PENDING_ASR
    for t in (TEMPO_HOLD_SECONDS - 0.1, TEMPO_HOLD_SECONDS + 0.1):      # the microphone goes on: a packet every 20 ms
        feed(c, now + t, n=50)
        assert (c.input_probe.state(now + t) == PENDING_ASR) == (t < TEMPO_HOLD_SECONDS)
    assert c._repeat_gate(state, now + 0.5) == 'tempo_hold'
    assert not c.tempo_unjudged, 'the words of another language are judged by nobody'


def test_a_russian_record_is_never_gated(call):
    """f84a05a9: ``lang_turn`` is deleted, the gate is the owner's rule always: the Russian record under the Russian turn passes as it did with the flag off."""
    rig, c, state = armed(call)
    now = c.clock()
    feed(c, now)
    c.tempo_heard(said(c, state, 3, RUSSIAN, now))
    assert c.lang_gated == 0 and c.input_probe.heard_at is not None


def test_the_gate_logs_numbers_and_labels_only(call, caplog):
    """Replaces the off/shadow test: the modes are gone, a foreign record is always gated, and the line the gate leaves holds numbers and labels, never the words."""
    rig, c, state = armed(call)
    now = c.clock()
    feed(c, now)
    record = said(c, state, 5, ENGLISH, now)
    with caplog.at_level(logging.INFO, logger=LOG):
        seen, gated = c._ear_lang_gate(record)
    assert gated and seen['text'] is None and c.lang_gated == 1
    assert any('lang_gate mode=on' in r.getMessage() for r in caplog.records)
    assert not any(ENGLISH in r.getMessage() for r in caplog.records), 'numbers and labels only'


def test_the_ear_entries_get_no_text_of_a_gated_record(call):
    rig, c, state = armed(call)
    got = []
    c._ear_heard = lambda record: got.append(record) or []
    assert c.ear_heard({'uid': 1, 'text': ENGLISH, 'offset': c.clock(), 'kind': 'question'}) == []
    assert got and got[0]['text'] is None and got[0]['reason'] == 'ear_other_language'
    got.clear()
    c.ear_heard({'uid': 2, 'text': RUSSIAN, 'offset': c.clock(), 'kind': 'final'})
    assert got and got[0]['text'] == RUSSIAN
    c.instant = type('I', (), {'_uid': None, 'hit': None, 'cut': False, 'feed': staticmethod(lambda *a, **k: pytest.fail('a gated partial reaches the bank'))})()
    assert c.ear_partial({'uid': 3, 'text': ENGLISH}) == []


def test_the_clouds_final_sets_the_language_and_the_russian_ear_is_gated_over_english(call):
    rig, c, state = armed(call)
    assert c.turn_lang.lang == 'ru'
    c._lang_observe({'id': 'u9', 'text': ENGLISH, 'final': True})
    c._lang_observe({'id': 'u9', 'text': RUSSIAN, 'final': True})      # one vote for each turn
    assert c.turn_lang.lang == 'en'
    seen, gated = c._ear_lang_gate({'uid': 1, 'text': 'что наводит финансия', 'offset': 0.0})
    assert gated and seen['text'] is None
    again, gated = c._ear_lang_gate({'uid': 2, 'text': 'what is the formula', 'offset': 0.0})
    assert gated and again['text'] is None      # no English ear key: the Russian ear's text stays no evidence over an English turn


def test_a_gate_that_fails_costs_nothing(call):
    rig, c, state = armed(call)
    c.ear_lexicon = 5      # not callable, not a container: the gate raises inside
    record = {'uid': 1, 'text': RUSSIAN, 'offset': 0.0}
    assert c._ear_lang_gate(record) == (record, False)


import pytest as _pytest_mic  # noqa: E402


@_pytest_mic.fixture(autouse=True)
def _own_microphone(monkeypatch):
    """This file feeds its own microphone packets (or none: a lost line): the live line of the world stays off (helpers_live_line)."""
    import helpers_s6_state
    monkeypatch.setattr(helpers_s6_state.World, 'mic_stream', False)

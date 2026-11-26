"""E43 / U54 (package T): every hold has a bound and a reason in one table; EAR_ASK_HOLD_SECONDS has one definition."""
import re
from pathlib import Path

from echo_sync import cm_base, cm_question, controlled_media, timer_policy as tp

SRC = Path(tp.__file__).resolve().parent


def test_every_hold_of_the_controller_is_named_bounded_and_explained():
    assert tp.holds_unexplained() == []
    assert tp.validate_waits() == []


def test_a_new_hold_without_its_row_is_caught(monkeypatch):
    monkeypatch.setitem(controlled_media.HOLD_BOUNDS, 'toy_hold', (3.0, 'a hold nobody wrote down'))
    assert [name for name, _ in tp.holds_unexplained()] == ['toy_hold']


def test_a_hold_beyond_the_wait_for_an_answer_is_caught(monkeypatch):
    monkeypatch.setitem(controlled_media.HOLD_BOUNDS, 'first_cue', (tp.ANSWER_WAIT_SECONDS + 1, 'too long'))
    assert [name for name, _ in tp.holds_unexplained()] == ['first_cue']


def test_a_stale_name_is_caught(monkeypatch):
    monkeypatch.delitem(controlled_media.HOLD_BOUNDS, 'record_pause')
    assert [name for name, _ in tp.holds_unexplained()] == ['record_pause']


def test_ear_ask_hold_has_one_definition_and_one_registry_row():
    assert 'timer_policy.EAR_ASK_HOLD_SECONDS' in tp.TIMERS and 'controlled_media.EAR_ASK_HOLD_SECONDS' not in tp.TIMERS
    assert 'timer_policy.EAR_ASK_HOLD_SECONDS' in tp.WAITS
    assert cm_base.EAR_ASK_HOLD_SECONDS is tp.EAR_ASK_HOLD_SECONDS is cm_question.EAR_ASK_HOLD_SECONDS is controlled_media.EAR_ASK_HOLD_SECONDS
    defined = [p.name for p in SRC.glob('*.py') if re.search(r'^EAR_ASK_HOLD_SECONDS\s*=', p.read_text(encoding='utf-8'), re.M)]
    assert defined == ['timer_policy.py'], defined


def test_u54_the_stable_partial_wait_keeps_the_owners_second():
    """U54: the next portion comes ~ the ear's end-of-speech pause + 0.2-0.3 s; the part this table owns is the wait of the stable partial: well under the owner's one second. The measured before/after pair is a cloud/phone job, not a number here."""
    assert tp.ACK_STABLE_SECONDS <= 0.3
    assert tp.ACK_STABLE_SECONDS + tp.CUE_TAIL_SECONDS < 1.0

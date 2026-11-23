"""c24-a1 (P13, fuzz A6o seed 33): the cloud's final of «Повтори.» came 4 s late (44.54), when the listener had begun the next question (43.84-46.00); the repeat of the
last portion it gave held ONSET_HOLD_MAX_S of the ear alone and began at 45.54 inside that question. What a final of speech that ended before the speech going on
now gives waits for that speech as a first cue does (``first_cue_hold``)."""
CS = 'prepare_wide=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,stumble_place=on'


import pytest


@pytest.mark.xfail(strict=True, reason='c24-a1 OPEN: the hold as a first cue (a680c89) was taken back: the held repeat then sounded after the new question was known '
                                       '(f6_stress Р104-4, old_answer). Needs: a cue held so is dropped, not played, when the speech it waited for turns out a question')
def test_the_late_repeat_is_not_said_over_the_next_question(monkeypatch):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    out = stand.run(33)
    assert [v for v in out.violations if v[0] in ('A6', 'A6o') and abs(v[1] - 45.54) < 0.05] == []

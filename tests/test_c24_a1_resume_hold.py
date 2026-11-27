"""c24-a1 (P13, fuzz A6o seed 1): the plan taken back on «Продолжай» (``_take_back``, resume) is the first cue of that plan again: while the listener is in the middle of
the next utterance it waits as a first cue waits (``first_cue_held``), not ONSET_HOLD_MAX_S of the ear alone. «Статья 19 …» began at 46.32 inside «Сколько будет 8
умножить на 5?» (44.32-46.80)."""
CS = 'two_witnesses=on,prepare_wide=on,ear_release=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,repeat_rule=on,stumble_place=on,local_fallback=on'


def test_a_plan_taken_back_is_not_said_over_the_next_utterance(monkeypatch):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    out = stand.run(1)
    assert [v for v in out.violations if v[0] in ('A6', 'A6o') and abs(v[1] - 46.32) < 0.05] == []

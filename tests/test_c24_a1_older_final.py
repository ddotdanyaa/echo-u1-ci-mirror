"""c24-a1: the cloud's final of an utterance that ended before the speech of the question the ear has opened (and answered) began is an older question the
listener has gone past: it opens nothing and retires nothing. Fuzz seed 411: «Сколько будет 5 умножить на 6?» (4.50-6.42) and «В каком году был полёт Гагарина?»
(7.50-9.61); the ear opened the second at 10.8 and «Гагарин полетел в 1961 году.» was cued, the cloud's final of the first came at 11.38, retired that plan and
«30. Это 5 раз по 6.» was cued at 14.48 (A2; the OPEN case Р057 of g23: «late final of the older question retires the newer plan»)."""
CS = 'prepare_wide=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,stumble_place=on'


def test_the_late_final_of_an_older_question_retires_nothing(monkeypatch):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    out = stand.run(411)
    assert [v for v in out.violations if v[0] in ('A2', 'A2e') and v[1] < 20] == []

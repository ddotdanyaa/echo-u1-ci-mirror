"""c24-a1: the ear's text that the cloud's open turn contradicts (``no_final_the_ear_is_contradicted``) has not been judged: it is still speech nobody judged, and the
first cue of the older answer waits for that final as it waited before (``first_cue_hold``), up to the same bound (TEMPO_HOLD_SECONDS). Fuzz seed 48: «Нет, не 40, а 60.»
heard by the ear, the cloud's words not yet the same, and «Осталось 40 рублей.» of the question before was said 0.1 s later (A2, a dangerous number)."""
import pytest

CS = 'prepare_wide=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = CS + ',stop_in_flight=on,stumble_place=on'


@pytest.mark.parametrize("seed,at", [(48, 28.6)])
def test_a_contradicted_ear_still_holds_the_old_first_cue(monkeypatch, seed, at):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", PROFILE)
    from tools.replay import stand
    out = stand.run(seed)
    assert [v for v in out.violations if v[0] in ('A2', 'A2e') and abs(v[1] - at) < 0.05] == []


def test_a_contradicted_remark_holds_nothing():
    """Ladder L4 seed 8: «В Москве сегодня до двадцати трёх градусов тепла, местами дожди.» of somebody else, the cloud 11 s late and its open words other than the
    ear's: a remark nobody asked, it holds the answer of question 1 no longer than before (it was cued at 22.5, not «missed»)."""
    from tools.ladder import scenes as L
    flags = dict(kv.split('=') for kv in PROFILE.split(','))
    out = L._play(L.Scene('L4', 8, flags=flags))
    assert [f for f in L.verdict(out) if f[0] == 'missed' and 'question 1 ' in f[2]] == []

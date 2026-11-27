"""c23-final: with ``repeat_rule`` on, the late cloud final of a repeat of the cue BEFORE («Осталось 20 рублей.», said before «Не хватает 20 рублей.»
was cued) is no «last word said» of the new cue: the cursor does not advance with nobody speaking (fuzz seed 286, A3; P03 of c22-break)."""
import os

import pytest

CS = 'two_witnesses=on,prepare_wide=on,ear_release=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'


@pytest.mark.parametrize("flags", ["", ",repeat_rule=on"])
def test_a_late_final_of_the_cue_before_does_not_advance_under_the_rule(monkeypatch, flags):
    monkeypatch.setenv("ECHO_REPLAY_FLAGS", CS + flags)
    from tools.replay import stand
    assert [v for v in stand.run(286).violations if v[0] == 'A3'] == []

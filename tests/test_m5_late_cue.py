"""U57 (M5): a first cue that comes more than LATE_CUE_S after its decision writes one decision row naming the hold that kept it and its seconds (the harvest: 8 s holds nobody could explain)."""
import logging

import helpers_s6_state as S
from echo_sync import timer_policy as tp
from test_h3_tempo import call      # noqa: F401 - the fixture



def answered(rig, question='Сколько будет сорок на два', answer='Восемьдесят. Это ответ.'):
    rig.w.feed(S.turn_created('u1', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('u1', 'user', question))
    rig.w.feed(S.turn_done('a1', 'assistant', answer))
    return rig.c


# --- U57: a late first cue names the hold ---------------------------------------------------------------------------------------------------

def _late_rows(caplog):
    return [r.getMessage() for r in caplog.records if 'kind=cue_late' in r.getMessage()]


def test_a_first_cue_released_after_a_hold_writes_the_cause_and_its_seconds(call, caplog):
    rig = call()
    c = answered(rig)
    c.tempo_live, c.first_hold_from = True, None
    c.handed_asks = (c.clock(), (c.state() or {}).get('revision'))
    c._cue('Восемьдесят.', first=True)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        assert c.first_cue_held() is True
        assert _late_rows(caplog) == []
        rig.w.clock.t += 3.0
        c.cloud_up = False      # U58: nobody will confirm: the hold ends
        assert c.first_cue_held() is False
        assert c.first_cue_held() is False
    rows = _late_rows(caplog)
    assert len(rows) == 1, rows
    assert 'reason=handed_back_to_cloud' in rows[0] and 'const=ANSWER_WAIT_SECONDS' in rows[0] and 'seconds=8.0' in rows[0] and 'lag_s=3.0' in rows[0]


def test_a_first_cue_that_comes_within_the_limit_writes_no_row(call, caplog):
    rig = call()
    c = answered(rig)
    c.tempo_live, c.first_hold_from = True, None
    c.handed_asks = (c.clock(), (c.state() or {}).get('revision'))
    c._cue('Восемьдесят.', first=True)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        assert c.first_cue_held() is True
        rig.w.clock.t += tp.LATE_CUE_S - 0.1
        c.cloud_up = False
        assert c.first_cue_held() is False
    assert _late_rows(caplog) == []

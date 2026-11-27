"""c24-a1: speech the job prepared on the ear's text has declined («—»: no question for the prompter) is judged, as the cloud's final of it would be (``fast_text_declined``):
it holds the first cue of the owner's answer no longer. Ladder L4 seed 29: «Курс доллара на торгах …», «Маша, подай ручку.», «Закрой окно, дует.» of others held the
answer of question 1 until the cloud's late finals (16.4 s), the owner asked the next question meanwhile: «missed»."""
from tools.ladder import scenes as L

CS = 'two_witnesses=on,prepare_wide=on,ear_release=on,gate_text=on,instant=on,spare_helper=on,open_overlap=on,warm_start=on'
PROFILE = dict(kv.split('=') for kv in (CS + ',stop_in_flight=on,repeat_rule=on,stumble_place=on,local_fallback=on').split(','))


def test_others_whose_job_declined_do_not_hold_the_answer():
    out = L._play(L.Scene('L4', 29, flags=PROFILE))
    assert [f for f in L.verdict(out) if f[0] == 'missed' and "question 1 " in f[2]] == []
    assert any('reason=ear_job_declined' in line for _, line in out.ctl)

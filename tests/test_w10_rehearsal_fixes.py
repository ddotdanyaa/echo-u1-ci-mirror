"""w10 item 2: what the rehearsal board (tools/rehearsal) showed red on the real controller, one failing replay per first cause, then the fix."""
from tools.rehearsal import score, sim


def episodes(name, seed, kind, flags=None):
    out = sim.play(sim.Spec(name), seed, flags=flags)
    return [e for e in score.board(out)[1] if e['kind'] == kind]


def test_r10_1_a_hold_of_a_question_the_ear_heard_does_not_end_in_a_replay_of_the_old_portion():
    """Р041 seed 2 (prompt_tempo ear, local_ear act, fast_text on): the friend asks «Сколько часов в неделе?» over the plan, the cloud's final is lost,
    the ear's text is contradicted by the cloud's open turn; the hold of that speech ended by itself (TEMPO_HOLD_SECONDS) and the timer said the old
    portion again 10 s after the new question («Да, при таком давлении жидкость нужно охлаждать»). A question the ear heard is no try of the portion."""
    assert episodes('Р041', 2, 'old_answer') == []


def test_r10_2_a_question_whose_job_failed_does_not_give_the_old_plan_back_on_the_clouds_backchannel():
    """Р051 seed 1: «В каком году была Куликовская битва?» after «В неделе 168 часов»: the job failed twice and was handed back to the cloud, the cloud
    said nothing of substance, and the plan went on with «В неделе 168 часов.» - an answer to the older question said after the new one. The job's
    failure is no verdict that the question was talk: the watchdog's honest phrase, not the old plan."""
    assert episodes('Р051', 1, 'old_answer') == []

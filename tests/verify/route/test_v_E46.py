"""V6 E46: «the safety catch of the fast_text channel: it can put the channel out for the whole call» (R5: it works twice as fast; R8: ``_first_new`` can fail and put it out). On the base the breaker is
gone (fast_text.py: «the roads own the verdict on a road; no breaker», 6535dd98): a job that is silent does not count against the channel. Three questions in a row whose job never says a word, then a
fourth: it gets its job and its answer. Real ControlledMedia and wire (rig ``call``). No network, no phone: the stalls of a real network (8-12 s) stay with the owner's call."""
from route_kit import BAPTISM, LIVE, RIGHT, TICK, answer_with_job, asked, call, texts      # noqa: F401
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS

QUESTIONS = ['В каком году было крещение Руси', 'Кто написал Войну и мир', 'Какая столица Австралии вообще']


def test_three_questions_whose_job_never_speaks_do_not_put_the_channel_out_for_the_call(call):
    rig = call(**LIVE)
    for n, text in enumerate(QUESTIONS):
        asked(rig, text, uid=f'u{n}')
        rig.pump(ANSWER_WAIT_SECONDS + 4.0)          # the job is silent for all of it: the stall of the net, not a failure
    before = len(rig.fake.runs)
    answer_with_job(rig, 'В каком году было крещение Руси ещё раз', RIGHT, 'u9')
    assert len(rig.fake.runs) > before, 'the channel is still asked after three silent questions'
    assert any('988' in t for t in texts(rig)), texts(rig)

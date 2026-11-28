"""V3 E47: a controlled refusal of the job on the final: the failures of the scripted tests (№2, 3, 4, 7, 9, 10, 11 of the review) held on one real call, and the old claim «three failures in a row switch the channel off for the
call» (T2R) is gone with the breaker (6535dd98: ONE road): a fourth question is still asked of the job and answered.

Real ControlledMedia and wire (rig ``call``). The job's channel breaks on every ask of three questions (two asks each: one more before the cloud), then a fourth question gets its job and its answer. Real server and phone
are not here: «на сервере вызван отказ» stays with the owner's call. Not run on the laptop."""
from answer_kit import LIVE, RIGHT, TICK, asked, call, fail_open_jobs, texts      # noqa: F401
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS

QUESTIONS = ['В каком году было крещение Руси', 'Кто написал Войну и мир', 'Какая столица Австралии вообще']


def test_a_channel_that_failed_three_questions_is_asked_the_fourth(call):
    rig = call(**LIVE)
    for n, text in enumerate(QUESTIONS):
        since = len(rig.fake.runs)
        asked(rig, text, uid=f'u{n}')
        fail_open_jobs(rig, since)
        rig.pump(ANSWER_WAIT_SECONDS + 2.0)
    before = len(rig.fake.runs)
    asked(rig, 'В каком году было крещение Руси ещё раз', uid='u9')
    rig.pump(TICK * 3)
    assert len(rig.fake.runs) > before, 'the channel is not off for the rest of the call'
    rig.job_says(before, RIGHT)
    rig.job_ends(before)
    rig.pump(TICK * 4)
    assert any('988' in t for t in texts(rig)), texts(rig)

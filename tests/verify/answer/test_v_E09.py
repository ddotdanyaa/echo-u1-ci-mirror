"""V3 E09: the right to sound is apart from the preparation: an unconfirmed cloud answer and a source that lost never reach the output queue (the holds of H5.2/H6 ``_fast_holds``).

Real ControlledMedia and wire (rig ``call``). Three rows of the invariant «preparing is not releasing»: the cloud's answer while the job is open; the job's answer, then the cloud's other one; the cloud's
answer after the job's. Red = a card for A (``cm_answer``) / P. Not run on the laptop."""
from answer_kit import BAPTISM, LIVE, RIGHT, TICK, WRONG_YEAR, asked, call, cloud, texts      # noqa: F401


def test_no_cloud_turn_reaches_the_plan_while_the_job_is_open(call):
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    cloud(rig, 'a1', WRONG_YEAR)
    rig.pump(3.0)
    assert [t for t in texts(rig) if t != 'Крещение Руси было в'] == [], 'the cloud\'s year is unconfirmed: it does not sound while the job has not refused or answered'


def test_the_job_is_the_answer_and_the_cloud_with_another_number_is_never_heard(call):
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    cloud(rig, 'a1', WRONG_YEAR)
    rig.job_says(0, RIGHT)
    rig.job_ends(0)
    rig.pump(3.0)
    assert any('988' in t for t in texts(rig))
    assert not any('восемьдесят' in t for t in texts(rig)), texts(rig)


def test_the_cloud_that_comes_after_the_job_adds_nothing(call):
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    rig.job_says(0, RIGHT)
    rig.job_ends(0)
    rig.pump(TICK * 3)
    before = list(texts(rig))
    assert any('988' in t for t in before)
    cloud(rig, 'a1', WRONG_YEAR)
    rig.pump(1.0)
    assert not any('восемьдесят' in t for t in texts(rig)), texts(rig)

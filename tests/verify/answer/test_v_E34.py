"""V3 E34: the cloud's «Да.» on a question about a year never sounds without the job having been asked (scene n1_04 step 10, c14: «Да.» and two repeats of the timer).

On the real ControlledMedia and wire (rig ``call``, the profile of the working call). The fix is H6 `6ce5a53` (held: no cloud turn reaches the plan while the job on that final has not refused it). Red here = a defect
card for the family A (``cm_answer``: the right to sound) and P (engine). Not run on the laptop."""
from answer_kit import BAPTISM, LIVE, RIGHT, TICK, asked, bare, call, cloud, fail_open_jobs, spoken_failures, texts      # noqa: F401


def test_the_job_is_asked_and_the_bare_yes_is_not_cued(call):
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    cloud(rig, 'a1', 'Да.')
    rig.pump(2.0)
    assert rig.fake.runs and rig.fake.run(0).question == BAPTISM, 'the job is asked on the question of the year'
    assert bare(rig, 'Да.') == [] and texts(rig) == [], f'nothing sounded while the job is open: {texts(rig)}'


def test_the_job_answers_and_the_yes_never_comes_after_it(call):
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    cloud(rig, 'a1', 'Да.')
    rig.job_says(0, RIGHT)
    rig.job_ends(0)
    rig.pump(3.0)
    assert any('988' in t for t in texts(rig)), texts(rig)
    assert bare(rig, 'Да.') == [], 'the job on the question gives the answer; the bare yes of the cloud never'


def test_when_the_jobs_fail_the_bare_yes_is_still_no_answer_to_a_question_of_a_year(call):
    """H6.1: the fallback text is judged too: a bare «Да.» on a question that is not a yes-or-no one is refused."""
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    cloud(rig, 'a1', 'Да.')
    fail_open_jobs(rig)
    rig.pump(10.0)
    assert bare(rig, 'Да.') == [], f'sounded: {texts(rig)}'

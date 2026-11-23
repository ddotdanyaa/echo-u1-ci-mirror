"""E22.3 (the owner, 14.11 L31710: «чтобы вот всегда быстрый ответ… двойные системы, тройные системы»; D-8): the job of the open question has said nothing for ``reserve_text.NEXT_ROAD_S`` and
the cloud has a text for it: the cloud's text is weighed at once by the SAME judges as after a failure of the job (numbers, «не», privacy), and said if they pass. The job that comes later is nobody's
answer (it is let go as a failed one: ``cm_route._cloud_for_late_job``). A job that speaks within the bound is the answer, as before. Real ControlledMedia and wire (rig ``call``); the clock is the
world's. Written, not run on the laptop (cloud only)."""
from test_h3_tempo import TICK, call                                          # noqa: F401 - call is the fixture
from test_h5_live import BAPTISM, LIVE, RIGHT, WRONG_YEAR, asked, cloud
from echo_sync.reserve_text import NEXT_ROAD_S

CAPITAL = 'Какая столица Австралии вообще'
CLOUD_RIGHT = 'Столица Австралии — Канберра.'
JOB_RIGHT = 'Столица Австралии — Канберра, город на юго-востоке страны.'


def test_a_cloud_text_comes_in_the_time_of_a_silent_job_and_is_said(call):
    rig = call(**LIVE)
    asked(rig, CAPITAL, uid='u1')
    rig.pump(NEXT_ROAD_S + 0.5)                       # the job has said nothing
    assert rig.said() == [], 'precondition: nothing is said while the job is silent and the cloud is mute'
    cloud(rig, 'a1', CLOUD_RIGHT)
    assert any('Канберра' in t for t in rig.said()), rig.said()


def test_a_refused_cloud_text_leaves_the_job_alive_and_it_answers(call):
    """Critic R 2: the judges' refusal of the cloud's text does not kill the job: what the listener hears is the job's answer."""
    rig = call(**LIVE)
    asked(rig, BAPTISM, uid='u1')
    rig.pump(NEXT_ROAD_S + 0.5)
    cloud(rig, 'a1', WRONG_YEAR)
    rig.pump(TICK * 5)
    assert not any('восьмой' in t for t in rig.said()), 'the judges of the failure path hold here too'
    assert not rig.fake.run(0).ended.is_set(), 'the job is still at work'
    rig.job_says(0, RIGHT)
    rig.job_ends(0)
    rig.pump(TICK * 3)
    assert any('988' in t for t in rig.said()), rig.said()


def test_a_cloud_that_ended_before_the_bound_is_weighed_on_the_tick(call):
    """Critic R 3: the cloud's text came at once (1-1.5 s), the job is silent: no event of the cloud comes later, the tick weighs it when the job is NEXT_ROAD_S late."""
    rig = call(**LIVE)
    asked(rig, CAPITAL, uid='u1')
    cloud(rig, 'a1', CLOUD_RIGHT)
    assert rig.said() == [], 'precondition: set aside while the job has its time'
    rig.pump(NEXT_ROAD_S + 0.5)
    assert any('Канберра' in t for t in rig.said()), rig.said()


def test_a_lead_already_said_does_not_hold_the_cloud_forever(call):
    """Critic R 1: the lead (``lead_said``) is published before the cloud text: a late job is not let go for it, and the cloud's text after the lead is said."""
    rig = call(**LIVE)
    asked(rig, 'Что такое инфляция', uid='u1')
    rig.pump(0.5)
    assert any('Инфляция' in t for t in rig.said()), 'precondition: the lead was said'
    rig.pump(NEXT_ROAD_S + 0.5)
    cloud(rig, 'a1', 'Инфляция — рост цен на товары и услуги.')
    assert any('рост цен' in t.lower() for t in rig.said()), rig.said()


def test_a_job_that_speaks_before_the_bound_is_the_answer_not_the_cloud(call):
    rig = call(**LIVE)
    asked(rig, CAPITAL, uid='u1')
    cloud(rig, 'a1', 'Столица Австралии — Сидней.')   # in time of the job: set aside
    assert rig.said() == [], 'the cloud is set aside while the job has its time'
    rig.job_says(0, JOB_RIGHT)
    rig.job_ends(0)
    rig.pump(TICK * 3)
    said = ' '.join(rig.said())
    assert 'Канберра' in said and 'Сидней' not in said, said


def test_the_job_that_comes_after_the_cloud_text_does_not_say_it_twice(call):
    rig = call(**LIVE)
    asked(rig, CAPITAL, uid='u1')
    rig.pump(NEXT_ROAD_S + 0.5)
    cloud(rig, 'a1', CLOUD_RIGHT)
    before = list(rig.said())
    assert before, 'precondition: the cloud stood in'
    rig.job_says(0, JOB_RIGHT)
    rig.job_ends(0)
    rig.pump(TICK * 5)
    assert rig.said() == before, 'the late job does not break in on a portion that was said'

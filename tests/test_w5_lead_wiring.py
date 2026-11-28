"""W5-lead on the real controller: the rig of H3/H4 (real NativeMediaSocket, ShadowEar, controller, injected clock; scripted detector, recognizer, cloud and job).
The lead is the owner's rule of fast_text on since f84a05a9 (the key ``lead_cue`` is deleted, ``lead_for_call`` with it): the wiring is in the controller, no profile switch."""
import helpers_s6_state as S
from echo_sync.settings import DEFAULTS, resolve
from test_h4_ear_first import final, question, speaks
from test_h3_tempo import TICK, call, cloud_of       # noqa: F401 - the fixture
from test_h5_live import LIVE, asked, fails, spoken_failures

EAR='когда началась первая мировая война'
FINAL='Когда началась Первая мировая война?'
LEAD='Первая мировая война началась'


def test_the_lead_has_no_setting_of_its_own():
    assert 'lead_cue' not in DEFAULTS and 'lead_cue' not in resolve({'fast_text':'on','lead_cue':'on'})


def wired(rig):
    return rig      # the lead is wired by the controller itself (``cm_answer._lead_cue``) whenever the channel is there


def test_the_lead_is_cued_at_the_final_before_the_jobs_text_and_brain_goes_on_after_it(call,caplog):
    caplog.set_level('INFO')
    rig=wired(call(fast_text='on'))
    question(rig,EAR)
    final(rig,'u1',FINAL)
    assert rig.said()==[LEAD],'the question\'s own words, before the job has said anything'
    assert any('echo-sync lead_cue' in r.getMessage() for r in caplog.records)
    rig.job_says(0,'Первая мировая война началась 28 июля 1914 года.')
    rig.job_ends(0)
    rig.pump(0.5)
    state=rig.c.state()
    assert state['answer']=='Первая мировая война началась 28 июля 1914 года.',state['answer']
    assert [chunk for chunk in state['chunks']][0]==LEAD and not any(LEAD in chunk for chunk in state['chunks'][1:]),'no word said twice'


def test_with_the_channel_off_there_is_no_lead(call):
    """Replaces «off the answer goes as it did»: the key is gone, what is left of the off state is the channel: with no brain nothing leads."""
    rig=call()
    head,rest=cloud_of(EAR)      # no channel, no job stream (``rig.fake`` is None): the ear's scene is played without the job precondition of ``question``
    speaks(rig,EAR,speech=1.0,turn='u1',announced=0.5,partial=head)
    rig.pump(TICK*2)
    if rest:
        rig.w.feed(S.turn_delta('u1',rest,1))
    final(rig,'u1',FINAL)
    assert rig.said()==[]


def test_a_yes_no_question_gets_no_lead(call):
    rig=wired(call(fast_text='on'))
    question(rig,'правда ли что земля круглая')
    final(rig,'u1','Правда ли, что Земля круглая?')
    assert rig.said()==[]


# ---- a lead is no answer: when every road dies after it, the honest failure is said (LEADDEAD; the owner's rule: never silence) -------------------------------------
DEFINE = 'Что такое инерция'
FAILURE_BOUND = 14.0        # the bound of the always-answer host (tests/test_always_answer_host.py)


def test_a_lead_said_and_every_road_dead_says_the_failure_once_and_never_the_lead_again(call):
    rig = wired(call(**LIVE))
    asked(rig, DEFINE)
    lead = rig.said()
    assert len(lead) == 1, 'precondition: the question\'s own words were cued at the final'
    began = rig.w.clock.t
    fails(rig, 0)
    fails(rig, 1)
    while not spoken_failures(rig) and rig.w.clock.t - began < FAILURE_BOUND:
        rig.pump(TICK)
    assert len(spoken_failures(rig)) == 1, 'the honest phrase, within the bound'
    assert rig.said() == lead, 'the lead is not said again'
    rig.pump(FAILURE_BOUND)
    assert len(spoken_failures(rig)) == 1 and rig.said() == lead, 'once, and the lead never replayed'


def test_a_job_that_broke_after_a_real_portion_still_ends_the_answer_where_it_broke(call):
    """The neighbour: something of an ANSWER is published, so the failure ends it there, with no phrase of failure and no lead said again."""
    rig = wired(call(**LIVE))
    asked(rig, DEFINE)
    rig.job_says(0, 'Инерция — свойство тела сохранять скорость. Это первый закон Ньютона.')
    rig.pump(TICK * 3)
    said = rig.said()
    assert len(said) >= 2, 'precondition: a real portion came after the lead'
    fails(rig, 0)
    rig.pump(FAILURE_BOUND)
    assert not spoken_failures(rig), 'what was said stands and the answer ends there'
    assert rig.said()[:len(said)] == said

"""W5-lead on the real controller: the rig of H3/H4 (real NativeMediaSocket, ShadowEar, controller, injected clock; scripted detector, recognizer, cloud and job).
The lead is the owner's rule of fast_text on since f84a05a9 (the key ``lead_cue`` is deleted, ``lead_for_call`` with it): the wiring is in the controller, no profile switch."""
import helpers_s6_state as S
from echo_sync.settings import DEFAULTS, resolve
from test_h4_ear_first import final, question
from test_h3_tempo import call       # noqa: F401 - the fixture

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
    question(rig,EAR)
    final(rig,'u1',FINAL)
    assert rig.said()==[]


def test_a_yes_no_question_gets_no_lead(call):
    rig=wired(call(fast_text='on'))
    question(rig,'правда ли что земля круглая')
    final(rig,'u1','Правда ли, что Земля круглая?')
    assert rig.said()==[]

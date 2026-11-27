"""W5-lead on the real controller: the rig of H3/H4 (real NativeMediaSocket, ShadowEar, controller, injected clock; scripted detector, recognizer, cloud and job).
The wiring is the patch in cloud_context/reports/w5-lead.md (controlled_media.py and settings.py are not this task's files): until it is applied these tests fail,
marked strict xfail so that the patch turns them into a hard XPASS failure and the mark has to go with it."""
import pytest

import helpers_s6_state as S
from echo_sync.settings import resolve
from test_h4_ear_first import final, question
from test_h3_tempo import call       # noqa: F401 - the fixture

WIRED=resolve({'fast_text':'on','local_ear':'act','lead_cue':'on'}).get('lead_cue')=='on'
pytestmark=pytest.mark.xfail(not WIRED,reason='the wiring patch of cloud_context/reports/w5-lead.md is not applied',strict=True)

EAR='когда началась первая мировая война'
FINAL='Когда началась Первая мировая война?'
LEAD='Первая мировая война началась'


def test_the_setting_is_off_by_default_and_needs_the_channel():
    assert resolve({})['lead_cue']=='off'
    assert resolve({'fast_text':'on','lead_cue':'on'})['lead_cue']=='on'
    assert resolve({'lead_cue':'on'})['lead_cue']=='off','no brain, nothing to lead'
    assert resolve({'fast_text':'on','lead_cue':'yes'})['lead_cue']=='off'


def wired(rig):
    rig.c.lead_cue=rig.settings['lead_cue']=='on'       # what controlled_host does with the profile, as it does for quick_math
    return rig


def test_the_lead_is_cued_at_the_final_before_the_jobs_text_and_brain_goes_on_after_it(call,caplog):
    caplog.set_level('INFO')
    rig=wired(call(fast_text='on',lead_cue='on'))
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


def test_off_the_answer_goes_as_it_did(call):
    rig=wired(call(fast_text='on'))
    question(rig,EAR)
    final(rig,'u1',FINAL)
    assert rig.said()==[]


def test_a_yes_no_question_gets_no_lead(call):
    rig=wired(call(fast_text='on',lead_cue='on'))
    question(rig,'правда ли что земля круглая')
    final(rig,'u1','Правда ли, что Земля круглая?')
    assert rig.said()==[]

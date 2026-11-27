"""w8-admission: the text gate wired into the controller (``_open_to_the_cloud``), production code, a scripted job stream, no network.

Fails on cloud-base: ``controlled_media.py`` is the coordinator's; the exact patch is cloud_context/reports/w8-admission.controlled_media.diff.
When it is applied these turn into XPASS (strict) and the marker goes."""
import pytest

import helpers_s6_state as S
from test_h1_fast_text import errors_of, rig, user_says      # noqa: F401 - rig is the fixture

# w10 item 6: the patch is applied (cloud_context/reports/w8-admission.controlled_media.diff), the strict xfail is gone

@pytest.mark.parametrize('final',['Миша, ты зарядку мою не видел?'])
def test_talk_to_a_person_spends_no_job(rig,final):
    user_says(rig,'u1',final)
    rig.w.feed(S.turn_created('a1','assistant','Ну'));rig.pump(0.7)
    assert len(rig.fake.runs)==0 and rig.cues()==[] and errors_of(rig)==[]

@pytest.mark.parametrize('final',['Я вчера до двух ночи сидел над курсовой, глаза слипаются.'])
def test_a_remark_is_the_jobs_to_judge(rig,final):      # no key: the broad «talk» (statement, noise) never silenced a call
    user_says(rig,'u1',final)
    rig.w.feed(S.turn_created('a1','assistant','Ну'));rig.pump(0.7)
    assert len(rig.fake.runs)==1

@pytest.mark.parametrize('final',['Ну и кто так делает вообще?','Точно?'])
def test_unknown_still_goes_to_the_job(rig,final):
    user_says(rig,'u1',final)
    rig.w.feed(S.turn_created('a1','assistant','Ну'));rig.pump(0.7)
    assert len(rig.fake.runs)==1

"""h28: «more of it must not break it», through the real chain (tools/replay/quantity.py). Seconds are the rig's clock, not a phone's."""
import pytest

from tools.replay import quantity as Q

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


@pytest.mark.parametrize('finals', [True, False])
@pytest.mark.parametrize('k', [0, 5, 30, 120])
def test_the_next_question_does_not_feel_the_garbage(k, finals):
    got = Q.question_after_garbage(k, finals=finals)
    assert got['false_cues'] == 0
    assert got['cue'] and got['cue'].startswith('Устойчивый') and got['s'] < 1.0


@pytest.mark.parametrize('ask', ['контрольная функция финансов', 'Так, нет, перечисли название видов финансовых отношений'])
def test_a_question_with_no_form_needs_no_cloud(ask):
    got = Q.question_after_garbage(5, finals=False, ask=ask)
    assert got['cue'] and got['s'] < 1.0


def test_silence_repeats_with_no_mode_for_about_a_minute():
    got = Q.silence_repeats(90.0)
    assert got['first'] == 1 and got['repeats'] == 1 and got['gaps'][0] < 3.0      # the cap of a call that is not writing: one silent repeat (``max_auto_repeats``), then silence; the cycle of many repeats is the pen's (``repeat_cap``)


def test_talk_around_holds_and_a_new_question_replaces():
    got = Q.talk_holds()
    assert got['kept'] and got['cue'].startswith('Между государством') and got['s'] < 1.0      # h30 (the owner on the call): the first words of a cue are the answer, not its count: «Шесть видов:» is cut off the head of the bank's answer (instant._no_count_head)


def test_a_late_job_does_not_replace_the_answer_under_the_owner():
    rig = Q.rig_of()
    try:
        Q.ear_only(rig, 'Перечисли виды финансовых отношений')
        rig.pump(1.0)
        Q.ear_only(rig, 'нет потому что государством')
        rig.pump(1.0)
        if rig.fake.runs:
            rig.job_says(len(rig.fake.runs) - 1, 'Совсем другой ответ модели на другую тему.')
            rig.job_ends(len(rig.fake.runs) - 1)
        rig.pump(6.0)
        assert not [c.text for c in rig.cues() if 'другой' in c.text.lower()]
    finally:
        rig.close()
        rig._mp.undo()

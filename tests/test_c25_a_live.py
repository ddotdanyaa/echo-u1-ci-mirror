"""c25-a: two cases of the owner's live calls, on the stand with the cloud's turns (``no_cloud.Scene`` mode 'cloud', the text model hung or failing).
1. While the model thinks on a new question the silence timer must not say the old portion again (G1, subclass ear_tempo): a question the ear writes without «?»
   («Нужно не увеличивать, а уменьшать …») whose job went back to the cloud is a question all the same.
2. A short «нет» right after a cue takes the portion off (no more repeats of it) and asks the model for another answer; a «нет» that is the portion itself
   («Нет, …» cued, «Нет.» said) is a try at it, and a «нет» long after the cue is not this rule's."""
import pytest

from tools.replay import no_cloud as N

PROF = dict(N.PROFILE, prepare_wide='on', ear_release='on', gate_text='on', spare_helper='on', open_overlap='on', warm_start='on',
            stop_in_flight='on', stumble_place='on', ear_job='on', cloud_form='on', ear_lookup='on')
Q1 = 'Что такое нематериальные активы?'
OLD = 'Имущество без физической формы;'


def scene(script, model='hang', bank=N.BANK, length=30.0):
    s = N.Scene('cloud', profile=PROF, length=length, model=model, bank=bank)
    try:
        script(s)
        return s, s.play()
    finally:
        s.close()      # h31: gives S.host_kwargs and fast_text.threading back


def after(s, at, act):
    s._when_heard(at, act, 'scripted')


@pytest.mark.parametrize('q2', ['Нужно не увеличивать, а уменьшать эту жидкость при таком давлении', 'А как амортизацию считают'])
def test_the_timer_does_not_say_the_old_portion_while_a_new_question_is_thought_on(q2):
    lines = []
    s, rec = scene(lambda s: (s.ask(1.0, Q1), after(s, 4.0, lambda p: lines.append(s.say(s.now() + 0.5, 'ask', q2, want='unknown')))))
    assert lines, 'the second question was never asked'
    assert [c for c in rec.cues if c[0] > lines[0].onset and c[1] == OLD] == []


def _no(s, holder, text='Нет.', delay=0.3):
    after(s, 4.0, lambda p: holder.append(s.say(s.now() + delay, 'no', text)))


def test_a_short_no_right_after_the_cue_takes_the_portion_off_and_asks_for_another_answer():
    said = []
    s, rec = scene(lambda s: (s.ask(1.0, Q1), _no(s, said)))
    assert said
    assert [c for c in rec.cues if c[0] > said[0].onset and c[1] == OLD] == []           # no repeat of the portion rejected
    asked = [j for j in rec_jobs(s) if j['at'] >= said[0].offset]
    assert asked and 'другой ответ' in asked[0]['heard'].lower(), asked                   # the model is asked for another answer, with the answer in play


@pytest.mark.parametrize('text', ['Нет, не то.', 'Неправильно.'])
def test_other_short_rejections_do_the_same(text):
    said = []
    s, rec = scene(lambda s: (s.ask(1.0, Q1), _no(s, said, text)))
    assert [c for c in rec.cues if c[0] > said[0].onset and c[1] == OLD] == []
    assert any('другой ответ' in j['heard'].lower() for j in rec_jobs(s) if j['at'] >= said[0].offset)


def rec_jobs(s):
    return s.out.jobs


NO_BANK = N.BANK + [{'id': 'no', 'q': 'Можно ли амортизировать землю?', 'alt': [], 'answer': 'Нет, земля не амортизируется.'}]


def test_a_no_that_is_the_portion_is_a_try_not_a_rejection():
    said = []
    s, rec = scene(lambda s: (s.ask(1.0, 'Можно ли амортизировать землю?'), _no(s, said)), bank=NO_BANK)
    assert any(c[1].startswith('Нет') for c in rec.cues)
    assert not any('другой ответ' in j['heard'].lower() for j in rec_jobs(s))


def test_a_no_long_after_the_cue_is_not_this_rule():
    said = []
    s, rec = scene(lambda s: (s.ask(1.0, Q1), _no(s, said, delay=8.0)))
    assert said
    assert not any('другой ответ' in j['heard'].lower() for j in rec_jobs(s))

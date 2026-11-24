"""A job pending on words that are only our own played cue read back (the kind owner's ``_said_back``) is retired once the cue is over and the listener is quiet: nothing is left up after an answer
(test_marathon). A remark of no form and a question said during the cue are not read-backs: their jobs stay. Through the real controller, the job's stream scripted, fixed timing."""
import helpers_s6_state as S
from test_h4_ear_first import speaks
from test_h3_tempo import TICK, call      # noqa: F401 - call is the fixture

QUIET_S = 3.0      # more than the silence the controller waits for before it lets a candidate go


def short_answer(rig):
    """An answer said and acked whole: nothing of its plan waits."""
    rig.asks('u1', 'Что такое инерция', 0, 'Инерция — свойство тела.')
    rig.pump(0.5)
    speak_and_final(rig, 'свойство тела', turn='u2')      # read back as it is said: the portion is acked, nothing of the plan waits
    rig.pump(0.5)


def speak_and_final(rig, text, turn):
    rig.says(text, speech=1.5)
    rig.w.feed(S.turn_created(turn, 'user', text.split()[0]))
    rig.w.feed(S.turn_done(turn, 'user', text))
    rig.pump(TICK)


def speak_on_the_ear(rig, text):
    """The ear heard it (its turn announced) and prepared a job; the cloud's final of it is not in yet."""
    speaks(rig, text, speech=1.5, turn='u3', announced=0.5)


def retired(rig, n):
    rig.pump(QUIET_S)
    return rig.fake.run(n).cancelled.is_set()


def test_a_pending_job_on_the_cue_read_back_is_retired_when_the_cue_is_over_and_the_listener_quiet(call):
    rig = call(fast_text='on')
    short_answer(rig)
    speak_on_the_ear(rig, 'инерция свойство тела')      # the owner reads the whole answer back once more
    assert rig.fake.run(1), 'precondition: the ear prepared a job on it'
    assert retired(rig, 1), 'the read-back of our own cue is no question: its job is let go'
    assert rig.c.candidate is None


def test_a_remark_of_no_form_said_during_the_cue_keeps_its_job(call):
    rig = call(fast_text='on')
    short_answer(rig)
    speak_and_final(rig, 'а двадцать пять', turn='u3')      # no form: the job of the final judges it
    assert not retired(rig, 1), 'a remark may yet be the job to answer'


def test_a_question_said_during_the_cue_keeps_its_job(call):
    rig = call(fast_text='on')
    short_answer(rig)
    speak_on_the_ear(rig, 'что такое трение')
    assert not retired(rig, 1), 'a real question is no read-back'

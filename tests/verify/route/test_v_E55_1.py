"""V6 E55.1: «a network stall of 8-12 s: three jobs in a row with no text in 4 s put the channel out for the call». The expectation of the backlog: after a stall of 12 s on the candidate the channel is alive,
at most one question gets an honest refusal. On the base the verdict on a road belongs to ``reserve_text.Roads`` (STALLS silent losses of a road in a row rest it for a time, never for the call), and
the controller hands a question back to the cloud at ANSWER_WAIT_SECONDS. One stall of 12 s, then the next question: it has its job, and its answer is spoken. Real ControlledMedia and wire (rig ``call``)."""
from route_kit import BAPTISM, LIVE, RIGHT, TICK, answer_with_job, asked, call, texts      # noqa: F401
from echo_sync.reserve_text import GIVE_UP_S


def test_after_one_stall_of_twelve_seconds_the_next_question_is_answered_by_its_job(call):
    rig = call(**LIVE)
    asked(rig, 'Кто написал Войну и мир', uid='u0')
    rig.pump(GIVE_UP_S + 1.0)                        # no word of the job for the whole of the limit
    before = len(rig.fake.runs)
    answer_with_job(rig, BAPTISM, RIGHT, 'u1')
    assert len(rig.fake.runs) > before, 'the channel is alive after the stall'
    assert any('988' in t for t in texts(rig)), texts(rig)


def test_the_stall_costs_at_most_one_question_its_refusal(call):
    """The honest sentence (``reserve_text.REFUSAL``) is said once a question and never glued to another question's answer."""
    from echo_sync.reserve_text import REFUSAL
    rig = call(**LIVE)
    asked(rig, 'Кто написал Войну и мир', uid='u0')
    rig.pump(GIVE_UP_S + 1.0)
    answer_with_job(rig, BAPTISM, RIGHT, 'u1')
    said = texts(rig)
    assert sum(1 for t in said if t.startswith(REFUSAL.split('.')[0])) <= 1, said
    assert not [t for t in said if t.startswith(REFUSAL.split('.')[0]) and '988' in t], said

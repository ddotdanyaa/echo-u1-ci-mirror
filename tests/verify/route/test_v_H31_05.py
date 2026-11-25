"""V6 H31-05 (= R5): «the controller reads the flag ``replaces``: the provisional refusal is lifted when the real text has come; a refusal is not glued to an answer». The text of the job that comes after the
honest sentence of the roads (``reserve_text.REFUSAL``, 8 s of silence of every road) is the answer; the sentence is not part of it (cm_answer: ``reason=fast_text_replaces_refusal``). Real ControlledMedia
and wire (rig ``call``); the job's text is late by design. What this proves is the logic of the controller, not a measurement."""
from route_kit import LIVE, RIGHT, TICK, asked, call, texts, BAPTISM      # noqa: F401
from echo_sync.reserve_text import REFUSAL, REFUSE_AFTER_S


def test_a_job_text_that_comes_after_the_refusal_is_the_answer_and_not_glued_to_the_refusal(call):
    rig = call(**LIVE)
    asked(rig, BAPTISM, uid='u1')
    rig.pump(REFUSE_AFTER_S + 1.0)                   # the roads are silent: the honest sentence may have been said by now
    n = len(rig.fake.runs) - 1
    rig.job_says(n, RIGHT)
    rig.job_ends(n)
    rig.pump(TICK * 6)
    said = texts(rig)
    head = REFUSAL.split('.')[0]
    assert any('988' in t for t in said), said
    assert not [t for t in said if head in t and '988' in t], f'the refusal is glued to the answer: {said}'
    assert sum(1 for t in said if t.startswith(head)) <= 1, said

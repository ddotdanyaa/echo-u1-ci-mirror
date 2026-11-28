"""V3 E56: a job on the STABLE text of the cloud (250 ms without a change, the ear silent): the answer is ready when the final comes, and the rule of the sound is not changed: nothing sounds before the final is judged
(the backlog's −0.9 s: the hint goes at the final, not 0.9 s after it). Closes A7 (the final on the phone later than the ear by ≈3 s).

Real ControlledMedia and wire (rig ``call`` with ``prepare_wide`` on, ``WIDE`` of test_h7: the setting is still a key; ``test_h7`` pins its being off in a profile). Not run on the laptop."""
from answer_kit import TICK, WIDE, call, partial, texts      # noqa: F401
import helpers_s6_state as S

QUESTION = 'В каком году было крещение Руси'
ANSWER = 'Крещение Руси произошло в 988 году.'


def test_the_job_of_the_stable_text_is_ready_and_sounds_at_the_final_not_before_not_later(call):
    rig = call(**WIDE)
    partial(rig, 'u1', QUESTION)
    rig.pump(0.5)
    assert rig.fast.count == 1, 'a job on the stable text, before any final'
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    rig.pump(1.5)
    assert texts(rig) == [], 'nothing sounds before the final is judged'
    final_at = rig.w.clock.t
    rig.w.feed(S.turn_done('u1', 'user', QUESTION))
    rig.pump(TICK * 3)
    cues = rig.cues()
    assert [c.text for c in cues] == [ANSWER] and cues[0].t - final_at <= TICK * 3 + 0.2, [(c.text, c.t - final_at) for c in cues]
    assert rig.fast.count == 1, 'the final adopted the job: no second one'


def test_a_stable_text_that_the_final_contradicts_is_never_sounded(call):
    rig = call(**WIDE)
    partial(rig, 'u1', QUESTION)
    rig.pump(0.5)
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    rig.w.feed(S.turn_done('u1', 'user', 'В каком году было Куликовское сражение'))
    rig.pump(TICK * 3)
    assert not any('988' in t for t in texts(rig)), texts(rig)

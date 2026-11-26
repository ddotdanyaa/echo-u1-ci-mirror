"""V3 E43.1 (F8, seed 1206): after a failed job the cloud is silent: the listener hears neither a hint nor the message of the skip, by ``ANSWER_WAIT_SECONDS`` at the latest (the backlog: «честное сообщение ≤8 с»).

Real ControlledMedia and wire (rig ``call``). Row 1: the question has a final (turn), both jobs fail, the cloud says nothing. Row 2: the candidate of the ear (no turn of the cloud at all), its job fails, the cloud says nothing
(the watchdog's candidate branch). «Heard» is any cue, a spoken diagnostic too. Red = a card for the family T (``cm_answer`` watchdog) / A. Not run on the laptop."""
from answer_kit import BAPTISM, LIVE, TICK, asked, call, fail_open_jobs, heard_all      # noqa: F401
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS

SLACK = 1.5      # a tick of the stand and the time the phrase itself takes to begin


def test_a_failed_job_and_a_silent_cloud_are_not_silence_past_the_bound(call):
    rig = call(**LIVE)
    began = rig.w.clock.t
    asked(rig, BAPTISM)
    fail_open_jobs(rig)
    rig.pump(ANSWER_WAIT_SECONDS + 2.0)
    out = heard_all(rig)
    assert out, 'F8: nothing at all was heard'
    assert out[0].t - began <= ANSWER_WAIT_SECONDS + SLACK, f'first sound after {out[0].t - began:.1f} s'


def test_a_candidate_of_the_ear_whose_job_failed_is_not_silence_past_the_bound(call):
    rig = call(**LIVE)
    ended = rig.says('в каком году было крещение руси', speech=2.0)
    fail_open_jobs(rig)
    rig.pump(ANSWER_WAIT_SECONDS + 2.0)
    out = heard_all(rig)
    assert out, 'seed 1206: the question stood by the ear, the job failed, the cloud was silent: nothing was heard'
    assert out[0].t - ended <= ANSWER_WAIT_SECONDS + SLACK, f'first sound after {out[0].t - ended:.1f} s'

"""V3 Н6 (call 16:06, c25-b): a question the EAR heard and the cloud never turned into a final: the answer or the honest phrase comes within the bound, after a LONG speech too (the first hint was 10 s after a long speech).

Real ControlledMedia and wire (rig ``call``). Row 1: a base reference by the ear alone (the bound of ``EAR_FIRST_BIND_SECONDS``, H6 item 6, the same as test_h5_live). Row 2: a question the job answers, the ear after 12 s of
speech, no turn of the cloud: the first sound of any kind by ``ANSWER_WAIT_SECONDS`` from the end of the speech. Red row 2 = a card for T/P (the ear stands in for the final). Not run on the laptop."""
from answer_kit import LIVE, TICK, call, fail_open_jobs, heard_all, job_answers      # noqa: F401
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, EAR_FIRST_BIND_SECONDS

EAR_17 = 'семнадцатая статья налогового кодекса'
SLACK = 1.5


def test_a_reference_the_ear_alone_heard_is_answered_by_the_bound(call):
    rig = call(**LIVE)
    uid = rig.onset()
    rig.pump(1.4)
    ended = rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, EAR_17)
    rig.pump(EAR_FIRST_BIND_SECONDS + 3 * TICK)
    out = heard_all(rig)
    assert out and out[0].t - ended <= EAR_FIRST_BIND_SECONDS + SLACK, [(c.text, c.t - ended) for c in out]


def test_a_question_after_a_long_speech_with_no_final_of_the_cloud_is_not_silence_past_the_bound(call):
    rig = call(**LIVE)
    ended = rig.says('в каком году было крещение руси', speech=12.0)
    rig.pump(1.0)
    if rig.fake.runs:
        job_answers(rig, 0, "Крещение Руси произошло в 988 году.")
    rig.pump(ANSWER_WAIT_SECONDS + 1.0)
    out = heard_all(rig)
    assert out, 'the question the ear heard was never answered and never refused'
    assert out[0].t - ended <= ANSWER_WAIT_SECONDS + SLACK, f'first sound after {out[0].t - ended:.1f} s'

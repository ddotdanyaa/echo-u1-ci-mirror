"""V3 E27: historical provenance / privacy / cancellation, checked on the CURRENT SHA (the backlog: «проверить присутствие/использование»). Three rows, each on the real ControlledMedia and wire:
cancellation: the job of a question that the next question cancelled never sounds; privacy: a remark about one's own data goes to no public search and no job with sources; provenance: an answer from the model's knowledge is
``unsourced`` (rows in test_v_E16 and test_v_E14). The CACHE row is not a test: ``answer_reuse`` is not read by ``fast_text`` (grep, not a behaviour); that is an open item of the family A. Not run on the laptop."""
import helpers_s6_state as S
from answer_kit import TICK, WIDE, call, job_answers, texts      # noqa: F401


def test_the_job_of_a_cancelled_question_is_never_spoken(call):
    rig = call(**WIDE)
    rig.says('кто написал войну и мир', speech=1.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Кто написал Анну Каренину'))
    rig.pump(TICK)
    rig.w.feed(S.turn_done('u2', 'user', 'Что такое инфляция'))
    rig.pump(TICK)
    for n in (0, 1):      # the ear's job (kept beside the final) and the job of the first final: both cancelled by the next question, so their threads never take another text (FakeRun.say would wait for an ack that cannot come)
        assert rig.fake.run(n).cancelled.is_set(), f'the job {n} of a question that was gone is still alive'
    rig.fake.run(0).script.put(('delta', 'Лев Толстой.'))      # a text that still arrives from a cancelled job
    rig.pump(1.0)
    job_answers(rig, rig.fast.count - 1, 'Устойчивый рост цен.')
    assert texts(rig) == ['Устойчивый рост цен.'], texts(rig)


def test_a_remark_about_ones_own_data_reaches_no_public_search(call):
    rig = call(**WIDE)
    rig.w.feed(S.turn_created('u1', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('u1', 'user', 'Сколько у меня сейчас на счету?'))
    rig.pump(2.0)
    assert rig.w.lookup_calls == []
    assert not any('Сколько у меня' in str(run.request) and 'счёт' in str(run.request).casefold() and 'url' in str(run.request).casefold() for run in rig.fake.runs)

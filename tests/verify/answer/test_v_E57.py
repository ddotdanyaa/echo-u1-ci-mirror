"""V3 E57: a ready job is not thrown away: the reason of a refusal (``_fits``) is in the call trace, and the job kept beside the one on the final (two places, never three) is the answer when the final is the same question.

Real ControlledMedia and wire (rig ``call`` with ``prepare_wide`` on). Rows: the final is the same question in other writing -> the one job answers, no second job; the final is another question -> the refusal is
told with its rule and the kept job is not the answer; the rules named in ``call_trace.py`` are the only ones. Not run on the laptop."""
import helpers_s6_state as S
from answer_kit import TICK, WIDE, call, job_answers, journal, lines, texts      # noqa: F401

RULES = {'released', 'failed', 'old', 'played', 'numbers', 'words', 'alike', 'empty', 'broken'}      # echo_sync/call_trace.py: fast_refused


def test_the_same_question_in_other_writing_is_served_by_the_job_the_ear_prepared(call):
    rig = call(**WIDE)
    notes = journal(rig)
    rig.says('кто написал войну и мир', speech=1.5)
    assert rig.fast.count == 1
    rig.w.feed(S.turn_done('u1', 'user', 'Кто написал «Войну и мир»?'))
    rig.pump(TICK)
    job_answers(rig, 0, 'Лев Толстой.')
    rig.pump(TICK * 3)
    assert rig.fast.count == 1, f'a second job was begun: the ready one was thrown away ({lines(notes, "fast_refused")})'
    assert texts(rig) == ['Войну и мир написал', 'Лев Толстой.'], "the lead of the question (W5-lead, question_lead.py: its own words at once), then the answer of the one job, nothing else"


def test_another_question_is_refused_with_its_rule_and_the_kept_job_does_not_answer_it(call):
    rig = call(**WIDE)
    notes = journal(rig)
    rig.says('кто написал войну и мир', speech=1.5)
    kept = rig.fast.job
    rig.w.feed(S.turn_done('u1', 'user', 'Кто написал Анну Каренину'))
    rig.pump(TICK)
    refused = lines(notes, 'fast_refused')
    assert refused and all(line['rule'] in RULES for line in refused), refused
    assert rig.fast.spare is kept, 'the second place: the job on the ear is kept beside the one on the final'
    rig.fake.run(0).say('Толстой.')
    job_answers(rig, rig.fast.count - 1, 'Лев Толстой.')
    rig.pump(TICK * 3)      # the first cue waits for the silence that ends the ear's utterance (cm_speech.first_cue_hold, H7 item 6): as the other test does
    assert texts(rig) == ['Лев Толстой.'], 'the answer of the new question only'

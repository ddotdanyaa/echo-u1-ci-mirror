"""V4 Н1 (call 12:31, c25): the first portion does not restate the question («Статья 58 Налогового кодекса —» and then nothing new). Backlog: the first thing said is the substance, not the words of the question.

Real ControlledMedia, NativeMediaSocket and FastText (rig ``call``): the job's text streams into the real portioner and the first-cue rule. Not run on the laptop. A red test is a defect card for the family P (the
first portion) or A (``first_useful``).
"""
import helpers_s6_state as S
from echo_sync.textutil import norm_words
from portion_kit import LIVE_RULES, TICK, call      # noqa: F401 - call is the fixture

ASKED = 'Что говорит статья 58 Налогового кодекса'
ANSWER = 'Статья 58 Налогового кодекса — порядок уплаты налогов и сборов. Налоги платят в срок.'


def ask(rig):
    rig.w.feed(S.turn_created('u1', 'user', 'Что'))
    rig.w.feed(S.turn_done('u1', 'user', ASKED))
    rig.pump(TICK)


def restates(cue):
    """Every word of the cue is a word of the question (a number counts as one)."""
    return set(norm_words(cue)) <= set(norm_words(ASKED)) | {'58'}


def test_the_head_that_only_repeats_the_question_is_not_said_alone_while_the_stream_is_at_it(call):
    rig = call(**LIVE_RULES)
    ask(rig)
    rig.job_says(0, 'Статья 58 Налогового кодекса —')
    rig.pump(2.0)
    assert not any(restates(cue) for cue in rig.said()), f'the question read back: {rig.said()}'


def test_the_first_portion_of_the_whole_answer_carries_what_is_new(call):
    rig = call(**LIVE_RULES)
    ask(rig)
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    assert rig.said(), 'the answer is said'
    assert not restates(rig.said()[0]), f'the first portion is the question again: {rig.said()}'
    assert 'порядок' in rig.said()[0].lower() or 'уплат' in rig.said()[0].lower(), rig.said()

"""W13 item 6: the coalescing window (3.2 s) and MERGE_PATIENCE_SECONDS count from the end of the speech, not from the admission
(``question_clock``): s4#6 waited 3.29 s. And what the code works out (``quick_math``) is no search: arithmetic went to the lookup
(``lookup_policy='required'``, +2.5 and +4.2 s)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture


def _late_admission(rig):
    c = rig.c
    assert c.coalesce_seconds == 3.2, c.coalesce_seconds
    c.question_id = 'q'
    c.user_started_at['q'] = 5.0
    c.ear_ended = 7.0           # the speech ended
    c.user_done_at['q'] = 9.0   # the cloud's final, 2 s later
    c.question_clock = 10.0     # the admission
    c.question_text = 'Это называется в'      # cut after a function word: the seam of the wait (``_holding``)
    c.direct_content = True
    return c


def test_the_window_counts_from_the_end_of_the_speech(call):
    c = _late_admission(call(fast_text='on'))
    assert c._holding(9.5), 'within 3.2 s of the end of the speech'
    assert not c._holding(10.5), '3.5 s after the end of the speech: nothing more to wait for'


def test_without_the_ears_end_the_final_is_the_clock(call):
    c = _late_admission(call(fast_text='on'))
    c.ear_ended = None
    assert c._holding(12.0) and not c._holding(13.5)


def test_an_end_of_an_older_utterance_is_not_this_ones(call):
    c = _late_admission(call(fast_text='on'))
    c.ear_ended = 4.0
    assert c._holding(12.0)


def _asks(rig, text):
    rig.w.feed(S.turn_created('u1', 'user', text.split()[0]))
    rig.w.feed(S.turn_done('u1', 'user', text))
    rig.pump(2 * TICK)


def test_arithmetic_is_no_search(call):
    rig = call(fast_text='on')
    _asks(rig, 'Сколько будет 15 процентов от 2000?')
    assert rig.c.direct_content, 'the code works it out: no lookup'


def test_a_rate_is_still_looked_up(call):
    rig = call(fast_text='on')
    _asks(rig, 'Какая сейчас ставка НДС в России?')
    assert not rig.c.direct_content


def test_the_continuation_of_a_question_has_one_rule_and_the_old_names_are_gone(call):
    """question/cm-continuation: ``_goes_on`` is the one rule of how a tail goes on with the question (the narrow seam is its first answer, ``_holding`` and
    ``_continuation`` both read it); the second places of it (``_old_seam``, ``_coalescing_open``, ``_utterance_open``, ``_job_heard``, ``_fast_head_stands``,
    ``_fast_goes_on``) are gone from the code."""
    import re
    root = Path(__file__).parent.parent / 'echo_sync'
    gone = re.compile(r'\b(_old_seam|_coalescing_open|_utterance_open|_job_heard|_fast_head_stands|_fast_goes_on)\b')
    assert not [p.name for p in root.glob('*.py') if gone.search(p.read_text(encoding='utf-8'))]
    c = _late_admission(call(fast_text='on'))
    state = c.state()
    for tail, kind in (('газообразное', 'seam'), ('Стоп', None)):
        assert c._goes_on(tail, c._classify(tail, state), False, seam=True) == kind, tail

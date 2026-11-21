"""U20-S6, hold8: the refusal anchored to the question's drop deadline (the one anchor: no key)."""
import pytest

import helpers_s6_fault as F
from test_answer_watchdog import Call
from helpers_fast_fake import channel, open_question

from echo_sync import reserve_text as TG
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, REFUSE_BEFORE_DROP_SECONDS



def test_the_deadline_is_the_final_plus_the_wait_and_the_refusal_is_half_a_second_before_it(tmp_path):
    call = Call(tmp_path)
    call.ask(said_for=3.0)
    final = call.clock.now
    assert call.controller.answer_deadline() == pytest.approx(final + ANSWER_WAIT_SECONDS)
    assert call.controller.refuse_deadline() == pytest.approx(final + 7.5)
    assert REFUSE_BEFORE_DROP_SECONDS == 0.5


def test_no_deadline_without_an_open_question(tmp_path):
    assert Call(tmp_path).controller.answer_deadline() is None


def test_the_channel_refuses_at_the_controllers_moment():
    fast, fake, clock = channel()
    fast.refuse_at = lambda qid: 1000.0 + 7.5
    open_question(fast)
    clock.t = 1000.0 + 7.4
    assert [e for e in fast.poll() if e['kind'] == 'text'] == []
    clock.t = 1000.0 + 7.6
    assert [e['text'] for e in fast.poll() if e['kind'] == 'text'] == [TG.REFUSAL]


def test_with_no_deadline_of_the_controller_the_refusal_counts_from_the_job():
    fast, fake, clock = channel()
    open_question(fast)
    clock.t = 1000.0 + TG.REFUSE_AFTER_S + 0.1
    assert [e['text'] for e in fast.poll() if e['kind'] == 'text'] == [TG.REFUSAL]

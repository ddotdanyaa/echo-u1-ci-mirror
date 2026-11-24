"""REDD: the answer watchdog of a question that took no plan over.

The cloud run on 980c85a0 had 26 tests red with ``'NoneType' object is not subscriptable`` and ~30 more that never heard the phrase
«Нет ответа»: ``_plan_held`` read ``self.suspended['entry']`` while nothing was suspended, the TypeError ended ``_answer_watchdog`` inside
``_resume_after_nothing`` and no ``unanswered`` action was ever made (fixed in 289c5f89). This pins the cause itself, through the real
ControlledMedia: no plan held is ``None`` (never an exception), and the question nobody answers is still reported, once, with its reason."""
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS
from test_answer_watchdog import Call, reports


def test_no_plan_taken_over_is_held_as_none_and_never_raises(tmp_path):
    call = Call(tmp_path)
    controller = call.controller
    assert controller.suspended is None
    assert controller._plan_held(None) is None and controller._plan_held({}) is None
    assert controller._plan_held(controller.state()) is None
    assert controller._resume_after_nothing([]) is None
    controller.suspended = {'entry': 5, 'gives_back': True}          # a plan whose entry the history no longer has: nothing to take up
    assert controller._plan_held({'history': []}) is None


def test_a_question_that_took_no_plan_over_is_still_reported_when_nobody_answers(tmp_path):
    call = Call(tmp_path)
    call.ask()
    epoch = call.controller.epoch
    found = reports(call.run(ANSWER_WAIT_SECONDS + 5))
    assert [action for _, action in found] == [{'type': 'unanswered', 'epoch': epoch, 'reason': 'no_assistant_turn'}], found

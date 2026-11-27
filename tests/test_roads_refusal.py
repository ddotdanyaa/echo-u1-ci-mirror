"""The honest sentence in place of silence is a rule of the roads (``Roads.step``: ``refuse_at``, ``cloud_silent``), through the real ``FastText``: no word of any road by ``REFUSE_AFTER_S`` and the cloud silent - one provisional sentence, the question lives to ``GIVE_UP_S``;
the cloud has an answer of its own - none, and the question is let go at ``ALL_DEAD_S`` as failed so that the controller takes that answer back. A hung road is no failure of the channel."""
import types

from helpers_fast_fake import channel, open_question, until

from echo_sync import fast_text as FT
from echo_sync import reserve_text as RT


def texts(events):
    return [e['text'] for e in events if e['kind'] == 'text']


def test_nothing_by_the_limit_gives_the_refusal_once_and_not_silence_and_the_end_is_at_give_up():
    fast, fake, clock = channel()
    assert open_question(fast) == 'started' and until(lambda: len(fake.runs) == 1)
    clock.t += RT.REFUSE_AFTER_S - 0.1
    assert fast.poll() == []
    clock.t += 0.2
    events = fast.poll()
    assert [(e['kind'], e['text'], e.get('provisional')) for e in events] == [('text', RT.REFUSAL, True)]
    clock.t += 1.0
    assert fast.poll() == []      # once
    clock.t = 1000.0 + RT.GIVE_UP_S
    assert [e['kind'] for e in fast.poll()] == ['done'] and not fast.off


def test_a_question_whose_due_has_passed_gets_the_sentence_at_once_and_its_job_goes_on_to_replace_it():
    """fix5: the decision is due 8 s after the END OF THE SPEECH (``ControlledMedia.decision_due``); a final that comes after that moment is decided at once: the provisional sentence at the
    first poll, not REFUSE_AFTER_S after the job began, and the job is not let go at the due (the old walk died there with the sentence): its text, when it comes, replaces the sentence (F20)."""
    fast, fake, clock = channel()
    fast.refuse_at, fast.due = (lambda qid: clock.t - 1.5), (lambda qid: clock.t - 1.0)      # the speech ended 9 s ago: the due is behind the final
    assert open_question(fast) == 'started' and until(lambda: len(fake.runs) == 1)
    events = fast.poll()
    assert [(e['kind'], e['text'], e.get('provisional')) for e in events] == [('text', RT.REFUSAL, True)]
    clock.t += 1.0
    fake.runs[0].script.put(('delta', 'Инерция - свойство тела.'))
    assert until(lambda: fast.job.first_at is not None)
    events = fast.poll()
    assert texts(events) == ['Инерция - свойство тела.'] and events[0].get('replaces') is True


def test_a_cloud_that_has_its_answer_is_no_reason_for_the_sentence_and_the_question_is_failed_at_eight():
    fast, fake, clock = channel()
    fast.cloud_answer = lambda: True
    open_question(fast)
    assert until(lambda: len(fake.runs) == 1)
    clock.t = 1000.0 + RT.REFUSE_AFTER_S + 0.1
    events = fast.poll()
    assert texts(events) == [] and [e['kind'] for e in events] == ['failed']


def test_a_stall_of_the_net_twelve_seconds_long_does_not_put_the_channel_out_for_the_call():
    fast, fake, clock = channel()
    for n in range(4):
        clock.t = 1000.0 + 20 * n
        assert open_question(fast) in ('started', 'off') and not fast.off
        until(lambda: len(fake.runs) >= 1)
        clock.t += RT.GIVE_UP_S + 0.1
        fast.poll()
        fast.poll()
    assert not fast.off and not fast.closed


def test_the_transport_bound_follows_give_up_and_the_refusal_is_not_later_than_the_controller_gives_up():
    controller = types.SimpleNamespace(fast_exchanges=lambda: [], fast_in_play=lambda: None, settings={}, ear_ended=None, source_segment_id=None,
                                       refuse_deadline=lambda *a: None, decision_due=lambda *a: None)      # round 3: ``for_call`` takes the refusal and the walk's bounds from the controller (hold8), a stand-in has none due
    channel_ = FT.for_call({'fast_text': 'on'}, controller, credentials=lambda: ('t', 'a'))
    try:
        assert channel_.stream.first_text_s == RT.GIVE_UP_S and channel_.roads is channel_.stream
    finally:
        channel_.close()
    from echo_sync import controlled_media as CM
    assert RT.REFUSE_AFTER_S <= CM.ANSWER_WAIT_SECONDS      # h31 triage: with the refusal at 11 s the controller had dropped the question at 8 s and the apology was never said

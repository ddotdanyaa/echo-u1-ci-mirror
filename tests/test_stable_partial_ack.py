"""WAVE 2 / Task B, item 5 (L1 latency): confirm on the stable partial transcript instead of waiting for the provider's final.

LATENCY_BASELINE: the ACK -> next portion latency is 1.26 s (median), 96 % of it the wait for the provider's FINAL transcript,
although the text is known about 0.8 s earlier. Required: accept the ACK as soon as the partial transcript fully matches the
portion (the same matcher: all content words, numbers and «не»/«ни» exact) and has been stable for ``ACK_STABLE_SECONDS``;
the later final of the same utterance must never advance again. Time is injected: nothing here sleeps.

WAVE 2 integration (task-b + task-c): the wrong-partial tests need a portion with words to leave out, add and change. The fixture is
the 2nd portion of the plan below, «при ста градусах Цельсия.» (4 words), reached by repeating the first cue whole, as the listener
does; what each test asserts is what Task B wrote. F1 (wave F): a call cuts by meaning, so the answer leads with a clause of its own
before «при ста градусах Цельсия.» to keep that very portion the 2nd (the old answer is two sentences = two portions now).
"""
import asyncio

import pytest

import helpers_s6_ack as H
from echo_sync.controlled_media import ACK_STABLE_SECONDS

# Production plan (F1): «Вода закипает в обычной кастрюле на плите,» | «при ста градусах Цельсия.» | «При ста градусах вода кипит.» |
# «В горах она закипает раньше.» (two portions follow the one under test, as before)
ANSWER = ('Вода закипает в обычной кастрюле на плите, при ста градусах Цельсия. При ста градусах вода кипит. '
          'В горах она закипает раньше.')
AT = 1                                       # the portion under test is the 2nd; the 1st cue is repeated whole before it
PORTION = 'при ста градусах Цельсия.'
# Production plan (F1): «Закон был принят в 1945.» | «Он действует до сих пор.»: the portion that ends in a number is the 1st (it was
# the 3rd of «Закон был» | «принят» | «в 1945.» | «Он действует» | «до сих пор.»).
NUMBER_ANSWER = 'Закон был принят в 1945. Он действует до сих пор.'
NUMBER_AT = 0
TICK = 0.1


def speaks(actions):
    return [a['text'] for a in actions if a['type'] == 'speak']


class Speaker:
    """One user turn as the provider streams it: created, a delta per word, then (when asked) the final. Time is the dictation's."""

    def __init__(self, d, tid='u-live'):
        self.d, self.tid, self.sent = d, tid, ''
        self.actions = []

    def start(self):
        self.d.controller.speech_started()
        self.actions += self.d.controller.provider(H.created(self.tid, 'user', ''))
        return self

    def words(self, text, step=0.2):
        for word in text.split():
            self.d.clock.advance(step)
            piece = ('' if not self.sent else ' ') + word
            self.sent += piece
            n = len(self.sent)
            self.actions += self.d.controller.provider({'type': 'turn.delta', 'turn_id': self.tid, 'delta': piece,
                                                        'start_ms': n * 10, 'end_ms': n * 10 + 5})
        return self

    def wait(self, seconds):
        """Let time pass, ticking the controller every 0.1 s as the host does; return what it spoke."""
        spoken = []
        end = self.d.clock() + seconds
        while self.d.clock() < end - 1e-9:
            self.d.clock.advance(min(TICK, end - self.d.clock()))
            actions = self.d.controller.tick(now=self.d.clock())
            self.actions += actions
            spoken += speaks(actions)
        return spoken

    def final(self, text=None):
        actions = self.d.controller.provider(H.done(self.tid, 'user', text if text is not None else self.sent))
        self.actions += actions
        return speaks(actions)


def dictation(tmp_path, answer=ANSWER, at=AT, **kwargs):
    """The dictation of ``answer`` with the ``at`` cues before the portion under test repeated whole: the portion is the one that waits."""
    d = H.Dictation(tmp_path / 'stable', answer, **kwargs)
    for n in range(at):
        assert d.say(d.current, gap=4.0).after == n + 1, 'precondition: the cue before the portion is confirmed'
    d.clock.advance(4.0)                                   # the listener's reaction time
    return d


def test_a_stable_full_partial_confirms_before_the_final(tmp_path):
    d = dictation(tmp_path)
    portion = d.current
    assert portion == PORTION, 'precondition: the portion under test'
    s = Speaker(d).start().words(portion)
    assert d.index == AT, 'the transcript has just become complete'
    spoken = s.wait(ACK_STABLE_SECONDS + TICK)
    assert spoken == [d.chunks[AT + 1]] and d.index == AT + 1, 'the next portion is spoken without waiting for the final'


def test_it_waits_for_the_transcript_to_be_stable(tmp_path):
    d = dictation(tmp_path)
    s = Speaker(d).start().words(d.current)
    assert s.wait(ACK_STABLE_SECONDS - TICK - 0.01) == [], 'not stable yet'
    assert d.index == AT
    assert s.wait(TICK * 2) == [d.chunks[AT + 1]]


def test_the_later_final_of_the_same_utterance_never_advances_again(tmp_path):
    d = dictation(tmp_path)
    s = Speaker(d).start().words(d.current)
    assert len(s.wait(ACK_STABLE_SECONDS + TICK)) == 1 and d.index == AT + 1
    s.wait(0.8)
    assert s.final(PORTION + '.') == [], 'the final of the utterance that was already confirmed speaks nothing'
    assert d.index == AT + 1
    assert s.final(PORTION) == [] and d.index == AT + 1, 'and neither does its retransmission'
    assert s.wait(0.5) == [] and d.index == AT + 1


def test_a_final_that_differs_from_the_confirmed_partial_is_still_the_same_utterance(tmp_path):
    d = dictation(tmp_path)
    s = Speaker(d).start().words(d.current)
    s.wait(ACK_STABLE_SECONDS + TICK)
    assert d.index == AT + 1
    assert s.final(PORTION.rstrip('.') + ' и всё') == [] and d.index == AT + 1


def test_the_final_alone_still_confirms_when_no_partial_was_seen(tmp_path):
    d = dictation(tmp_path)
    out = d.say(d.current, gap=0.0)
    assert out.after == AT + 1 and out.speaks == [d.chunks[AT + 1]]


def test_a_partial_with_a_missing_word_never_confirms(tmp_path):
    d = dictation(tmp_path)
    s = Speaker(d).start().words('при ста Цельсия')            # «градусах» is missing
    assert s.wait(5.0) == [] and d.index == AT


@pytest.mark.parametrize('said', [
    'не при ста градусах Цельсия',
    'при ста не градусах Цельсия',
    'при ста градусах Фаренгейта',
    'при ста градусах Цельсия два',
], ids=['not-first', 'not-inside', 'other-word', 'extra-number'])
def test_a_wrong_partial_never_confirms(tmp_path, said):
    d = dictation(tmp_path)
    s = Speaker(d).start().words(said)
    assert s.wait(5.0) == [] and d.index == AT
    assert s.final() == [] and d.index == AT, 'and its final does not either'


def test_a_partial_that_keeps_growing_restarts_the_stability_wait(tmp_path):
    d = dictation(tmp_path)
    s = Speaker(d).start().words(d.current)
    assert s.wait(ACK_STABLE_SECONDS - TICK - 0.01) == []
    s.words('а ещё')                                           # more words arrive: the text is not what it was
    assert s.wait(ACK_STABLE_SECONDS + 3 * TICK) == [], 'the longer text is no longer the portion'
    assert d.index == AT
    # G3, rule 2 (changed on purpose): the final is a repeat that goes on: the portion is confirmed once, and the plain words after it say nothing
    s.final()
    assert d.index == AT + 1


def test_a_portion_ending_in_a_number_waits_for_the_final(tmp_path):
    d = dictation(tmp_path, NUMBER_ANSWER, at=0)
    for n in range(NUMBER_AT):                                 # the portions before the one that ends in a number are confirmed
        assert d.say(d.current, gap=4.0).after == n + 1
    d.clock.advance(2.0)
    assert d.current.rstrip('.').split()[-1].isdigit(), f'precondition: the portion ends in a number: {d.current!r}'
    s = Speaker(d).start().words(d.current)
    assert s.wait(3.0) == [] and d.index == NUMBER_AT, 'a partial «1945» may still be «19450»: only the final confirms'
    assert s.final() == [d.chunks[NUMBER_AT + 1]] and d.index == NUMBER_AT + 1


def test_the_halves_of_a_split_repeat_confirm_on_the_stable_partial_of_the_second(tmp_path):
    d = dictation(tmp_path)
    head, tail = 'при ста', 'градусах Цельсия'
    first = Speaker(d, 'h1').start().words(head)
    first.final()
    d.clock.advance(0.5)
    second = Speaker(d, 't1').start().words(tail)
    assert d.index == AT
    assert second.wait(ACK_STABLE_SECONDS + TICK) == [d.chunks[AT + 1]] and d.index == AT + 1
    assert second.final() == [] and d.index == AT + 1


def test_the_stable_partial_can_be_switched_off(tmp_path):
    d = dictation(tmp_path)
    d.controller.ack_stable_seconds = 0
    s = Speaker(d).start().words(d.current)
    assert s.wait(5.0) == [] and d.index == AT, 'the base: only the final confirms'
    assert s.final() == [d.chunks[AT + 1]]


def test_a_new_call_stays_quiet_until_an_explicit_repeat(tmp_path):
    old = dictation(tmp_path)
    portion = old.current
    d = old.reconnect()                                        # a new ControlledMedia over the same session
    d.clock.advance(4.0)
    s = Speaker(d).start().words(portion)
    assert s.wait(3.0) == [] and d.index == AT, 'persisted position is not playback authority in a new call'


def test_through_the_wire_the_stable_partial_is_confirmed_by_the_transport_tick(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'wire')
        try:
            await wire.begin(ANSWER)
            for n in range(AT):                                # the cue before the portion is repeated whole
                await wire.user(wire.chunks[n], tid=f'cue-{n}')
                assert wire.index == n + 1, 'precondition: the cue before the portion is confirmed'
            first = wire.chunks[AT]
            wire.skew += 4.0
            await wire.socket.provider(H.created('u2', 'user', ''))
            sent = ''
            for word in first.split():
                piece = ('' if not sent else ' ') + word
                sent += piece
                await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': piece,
                                            'start_ms': len(sent) * 10, 'end_ms': len(sent) * 10 + 5})
            assert wire.index == AT
            await wire.elapse(0.05)                            # tick: the partial has not been stable for long enough
            assert wire.index == AT
            await wire.elapse(ACK_STABLE_SECONDS + 0.05)
            assert wire.index == AT + 1 and wire.synthesized[-1] == wire.chunks[AT + 1], 'the next portion was synthesized and sent'
            frames = wire.audio_frames
            await wire.socket.provider(H.done('u2', 'user', first))              # the final, long after
            await wire.settle()
            assert wire.index == AT + 1 and wire.audio_frames == frames, 'the final changed nothing'
        finally:
            await wire.close()
    asyncio.run(run())

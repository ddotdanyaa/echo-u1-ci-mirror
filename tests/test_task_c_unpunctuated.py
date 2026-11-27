"""WAVE 2 / Task C-seg: an answer without terminal punctuation is delivered completely once the host's tick ran (DEF-SEG-13).

The S6 acceptance test of DEF-SEG-13 feeds provider events without ever ticking the controller, so it cannot see the grace
flush (``ControlledMedia._settle``, fix round 2: after 1.2 s without a continuation the last, possibly cut, word is accepted
as the end of the answer). The host ticks every 0.1 s (``NativeMediaSocket.tick``). With that tick, and with the short
first cue of Task C-seg, every unpunctuated answer of the hand corpus gets its cue and its tail.

WAVE 2 integration (task-b + task-c): Task B's ruling 1 declares the end of an answer only for a listener who has run out of the
text published so far (``ControlledMedia._listener_waits``), so the tail of the answer comes while somebody is repeating the cues.
The run therefore has a listener, as the product does: every cue is repeated aloud ``REACTION`` s after it was issued (their own
voice, an estimated 1.5 s of synthesis and the time the cue takes to say have gone by), the speech lasting ``SPEECH`` s, and the
answer is complete when the listener has repeated its last portion. The gate itself is not touched.
"""
from __future__ import annotations

import pathlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                                       # noqa: E402
from echo_sync.controlled_media import ControlledMedia                          # noqa: E402

UNPUNCTUATED = [item for item in H.HAND_CORPUS if not item.punctuated]
REACTION, SPEECH = 6.0, 1.0       # seconds from a cue being issued to the start of the listener's repeat, and its length
LIMIT = 300.0                     # seconds of host ticks at most: the longest answer of the corpus has six portions (~45 s)


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def run_with_ticks(directory, item):
    clock = Clock()
    c = ControlledMedia(pathlib.Path(directory) / 's.sqlite3', session_id='native-probe-' + '0' * 32, clock=clock, **H.HOST_KWARGS)
    words = H.slices(item.question, 'words')
    c.provider(H.created('u1', 'user', words[0]))
    for n, piece in enumerate(words[1:], 1):
        c.provider(H.delta('u1', piece, n))
    c.provider(H.done('u1', 'user', item.question))
    cues = []
    agenda = []                                          # what the listener does next: (when, 'speech' | 'final', turn id, the cue's text)

    def feed(events):
        for a in events:
            if a['type'] == 'speak':
                cues.append(a['text'])
                agenda[:] = [(clock.now + REACTION, 'speech', f'ack{len(cues)}', a['text'])]    # the latest cue is the one repeated

    pieces = H.slices(item.answer, 'words')
    feed(c.provider(H.created('a1', 'assistant', pieces[0])))
    for n, piece in enumerate(pieces[1:], 1):
        feed(c.provider(H.delta('a1', piece, n)))
    feed(c.provider(H.done('a1', 'assistant', item.answer)))
    for _ in range(int(LIMIT / 0.1)):                    # host ticks, 0.1 s each, until the listener has heard it all
        clock.now += 0.1
        for entry in [e for e in agenda if e[0] <= clock.now + 1e-9]:
            agenda.remove(entry)
            _, kind, tid, text = entry
            if kind == 'speech':
                c.speech_started()
                feed(c.provider(H.created(tid, 'user', '')))
                agenda.append((clock.now + SPEECH, 'final', tid, text))
            else:
                feed(c.provider(H.done(tid, 'user', text)))
        feed(c.tick(now=clock.now))
        if (c.state() or {}).get('completed'):
            break
    state = c.state() or {}
    return cues, list(state.get('chunks', [])), bool(state.get('completed'))


@pytest.mark.parametrize('item', UNPUNCTUATED, ids=[i.id for i in UNPUNCTUATED])
def test_an_unpunctuated_answer_is_delivered_completely_after_the_grace_flush(tmp_path, item):
    cues, chunks, completed = run_with_ticks(tmp_path, item)
    assert cues, 'silence'
    flat, got = H.nospace(item.answer), H.nospace(''.join(chunks))
    head_elided = flat.endswith(got) and H.nospace(item.elide).startswith(flat[:len(flat) - len(got)])
    assert got == flat or head_elided, (item.answer, chunks)
    assert not H.cut_words(item.answer, chunks, shift=len(flat) - len(got) if head_elided else 0)
    assert completed, f'the listener did not get to the end of the answer: {cues}'

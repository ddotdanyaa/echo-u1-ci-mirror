# factory-backlog-id: U91
"""U91: a final the phone sends again after a reconnect (same turn id, same words) is the question already answered and played:
the new call must not say the answer a second time."""
from helpers_w1f import ControlledMedia, HOST_KWARGS, PROFILE, created, done


def test_u91_a_final_repeated_after_a_reconnect_gives_no_second_answer(tmp_path):
    now = [0.0]

    def build():
        return ControlledMedia(tmp_path / 'u91.sqlite3', session_id='native-probe-' + '0' * 32, clock=lambda: now[0],
                               **{**HOST_KWARGS, **PROFILE})

    question = 'Сколько будет два плюс два?'
    first = build()
    first.begin_call()
    acts = []
    for event in (created('u1', 'user', question), done('u1', 'user', question)):
        now[0] += 0.5
        acts += first.provider(event) or []
    cues = [a for a in acts if a['type'] == 'speak']
    assert [c['text'] for c in cues] == ['Четыре.']
    first.cue_started(cues[0])
    now[0] += 1.0
    first.playback_done(cues[0], now=now[0])
    first.end_call()      # the transport's close() always ends the call, an abrupt drop included (native_media_socket.close)
    now[0] += 5.0

    second = build()      # the phone dialled again: a new call on the same session
    second.begin_call()
    again = []
    for event in (created('u1', 'user', question), done('u1', 'user', question)):
        now[0] += 0.5
        again += second.provider(event) or []
    assert [a['text'] for a in again if a['type'] == 'speak'] == []

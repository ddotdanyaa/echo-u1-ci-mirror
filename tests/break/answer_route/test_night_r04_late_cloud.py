# factory-backlog-id: E-R04
"""E-R04 (SC3 «the cloud is late and silent»): the cloud connects at the 7th second of a call, and nothing says «Облако недоступно» before a question that needs the cloud.

Decision 26.11-4: the cloud is not announced as unavailable until a question is asked that needs the cloud's answer.
Scene in seconds: 0 s the phone opens the call, the helper offers nothing; at 6 s the call opens from the local bases (LOCAL_OPEN_GRACE_S), at 7 s the offer comes and the same call takes the cloud.
Order of events: (quiet) nobody asks anything for 10 s after the cloud came; (after) a question 2 s after the cloud, answered by the cloud. In neither order is the cloud announced as gone before the question that needs it.
The REAL host (controlled_host.serve, ControlledMedia, NativeMediaSocket), only the phone, the helper pipe, SAPI and the roads are the stand's."""
import helpers_always_answer as H
from echo_sync import reserve_text
from bk_common import BStand, Heard, Q_INERTIA, fail, local_call, run_stand

class RestingRoads(dict):
    """The rest of every reserve road of the text, whatever its key and model: every road rests until the end of the call."""

    def get(self, road, default=0.0):
        return 1e12


def rest_every_road(host):
    """What an earlier call left (the state of the roads is kept across the calls of the process): the first road rests too; the reserve roads rest through ``RestingRoads`` (patched in by the scene)."""
    with reserve_text._LOCK:
        reserve_text._PRIMARY['until'] = 1e12


CLOUD_AT_S = 7.0            # the offer of the helper comes this long after the phone's session.update
PHRASE = 'облако недоступно'


def _announced(saw, before):
    """The phrases of the system that began before ``before`` (virtual time) and say that the cloud is gone."""
    return [i['text'] for i in saw.service if i['first'] < before and PHRASE in ' '.join(str(i['text']).casefold().split())]


def _scene(tmp_path, ask_after):
    stand = BStand({'codex': fail('http_429')})

    async def body(host, stand):
        rest_every_road(host)
        t_start = host.now()
        _, ready = await H.open_local(host)
        assert ready, 'the call did not open at all'
        await host.advance(max(0.0, CLOUD_AT_S - (host.now() - t_start)))
        host.bridge.push('O', b'v=0\n')                  # the cloud connects: the 7th second
        await host.advance(2.0)
        if ask_after is None:                             # nobody asks: ten quiet seconds
            await host.advance(10.0)
            return Heard(host, t_start), host.now(), None
        t_q = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.0)
        await host.advance(0.8)
        await host.answer(H.cloud_answer(Q_INERTIA)[0], tid='a1')
        await host.advance(18.0)
        return Heard(host, t_start), t_q, t_q
    return run_stand(tmp_path, stand, body, patches=((reserve_text, '_REST', RestingRoads()),), **local_call())


def test_the_cloud_that_came_at_the_7th_second_is_not_announced_as_gone_before_a_question_that_needs_it(tmp_path):
    saw, bound, t_q = _scene(tmp_path / 'quiet', None)
    said = _announced(saw, bound)
    assert not said, f'quiet call, the cloud came at {CLOUD_AT_S} s and nobody had asked yet, but ECHO said {said!r}'
    saw, bound, t_q = _scene(tmp_path / 'after', 1)
    said = _announced(saw, t_q)
    assert not said, f'the cloud came at {CLOUD_AT_S} s, the question was asked after it, but before the question ECHO said {said!r}'
    assert H.cloud_answer(Q_INERTIA)[0].split()[0].lower() in saw.text.lower(), f'the question after the late cloud was not answered: {saw.text!r}'

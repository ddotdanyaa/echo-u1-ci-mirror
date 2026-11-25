"""g10-audit: weak places of the head found by reading, each a failing test (xfail strict) and an exact patch in cloud_context/reports/g10-audit.md."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_ack as H
from echo_sync import controlled_media as CM
from echo_sync.controlled_media import ControlledMedia


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def make(tmp_path, name='c', **keywords):
    return ControlledMedia(tmp_path / (name + '.sqlite3'), session_id=H.SESSION, clock=H.FakeClock(), **{**H.HOST_KWARGS, 'fast_text': 'on', **keywords})


def ask(c, text, uid='u1'):
    c.speech_started()
    c.provider(H.created(uid, 'user', text.split()[0]))
    return c.provider(H.done(uid, 'user', text))


# --- A1. the tail wait keeps the first route: the sources that came while the job waited for the rest are lost --------------------------

@pytest.mark.xfail(strict=True, reason='g10 A1: _fast_tail_waits keeps route/extra of the first call')
def test_a1_sources_given_during_the_tail_wait_go_with_the_release(tmp_path):
    c = make(tmp_path)
    ask(c, 'Скажите какой размер у этого закон о')
    assert c.fast_tail is not None and c.fast_asked is None, 'the job waits for the rest of an open tail'
    sources = [{'url': 'https://example.org/a', 'text': 'Размер — двадцать процентов.'}]
    assert c._fast_release('sources', sources=sources) == [], 'still inside the wait'
    c.clock.advance(CM.FAST_TAIL_SECONDS + 0.1)
    out = [a for a in c._fast_tail_due(c.clock()) if a['type'] == 'fast']
    assert len(out) == 1
    assert out[0]['route'] == 'sources' and out[0].get('sources') == sources, out[0]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def ev(tid, role, text, final=True):
    return {'type': 'turn.done' if final else 'turn.created', 'turn': {'id': tid, 'role': role, 'transcript': text}}


PLAIN = {'words_per_portion': 3}


# --- A2. a question taken on a partial (the model's delegation) whose final never comes is never given up: the cap waits for ever ------------

@pytest.mark.xfail(strict=True, reason='g10 A2: _answer_watchdog returns [] for a non-final question before the answer cap')
def test_a2_a_partial_question_taken_by_delegation_is_given_up_at_the_cap(tmp_path):
    clk = Clock()
    c = ControlledMedia(tmp_path / 'm.db', session_id='t', settings=PLAIN, source_delivery='delegation', session_context_fallback=True, clock=clk)
    clk.t = 1.0
    c.provider(ev('u1', 'user', 'Почему меняются времена года на Земле', final=False))
    c.provider({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'target': 'client'}})
    assert c.question_id == 'u1'
    seen = []
    for t in range(2, 200):
        clk.t = float(t)
        seen += c.tick(now=clk.t)
    assert any(a['type'] == 'unanswered' for a in seen), 'silence for ever: no «не знаю точно» after the cap'


# --- A3. the model's delegation after the sources went out on the session context gets no result ----------------------------------------

def test_a3_a_delegation_after_the_session_context_delivery_gets_its_result(tmp_path):
    c = ControlledMedia(tmp_path / 's.db', session_id='s', source_delivery='delegation', session_context_fallback=True, settings={'words_per_portion': 3})
    c.provider(ev('u', 'user', 'Почему меняются времена года?'))
    first = c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'Наклон земной оси определяет смену сезонов: так меняются времена года.'}])[0]
    assert first['source_transport'] == 'session_context'
    assert c.delivery_sent(c.epoch, None)
    out = c.provider({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u', 'target': 'client'}})
    assert [a.get('delegation_id') for a in out if a['type'] == 'context'] == ['d1'], 'the model waits for a tool result that never comes'


# --- A4. a new call keeps the earlier call's topic: «А почему?» searches yesterday's question ---------------------------------------------

def test_a4_a_new_call_does_not_search_with_the_earlier_calls_topic(tmp_path):
    import time
    c = ControlledMedia(tmp_path / 'm.db', session_id='t', settings=PLAIN)
    epoch = c.provider(ev('u1', 'user', 'Почему меняются времена года?'))[-1]['epoch']
    c.grounding(epoch, [{'url': 'https://www.example.org/primary', 'text': 'Verified reference excerpt.'}])
    c.provider(ev('a1', 'assistant', c.answer_marker + 'Наклон земной оси меняет освещение полушарий.'))
    later = time.time() + 3 * 3600
    d = ControlledMedia(tmp_path / 'm.db', session_id='t', settings=PLAIN)
    d.engine.clock = lambda: later
    d.begin_call()
    look = [a for a in d.provider(ev('n1', 'user', 'А почему?')) if a['type'] == 'lookup']
    assert not look or 'времена года' not in look[0]['lookup_question'], look[0]['lookup_question']


# --- A5. ack_join_fragments=2: the slice [-0:] keeps every fragment, the bound is gone --------------------------------------------------

@pytest.mark.xfail(strict=True, reason='g10 A5: [-max(0,n-2):] is [-0:] for n=2')
def test_a5_fragments_are_bounded_by_ack_join_fragments_two(tmp_path):
    c = ControlledMedia(tmp_path / 'm.db', session_id='t', settings=PLAIN, ack_join_fragments=2)
    epoch = c.provider(ev('u1', 'user', 'Почему меняются времена года?'))[-1]['epoch']
    c.grounding(epoch, [{'url': 'https://www.example.org/primary', 'text': 'Verified reference excerpt.'}])
    c.provider(ev('a1', 'assistant', c.answer_marker + 'Наклон земной оси меняет освещение полушарий.'))
    for i, t in enumerate(['Наклон', 'Земной', 'Оси наклон']):
        c.provider(ev(f'x{i}', 'user', t))
    assert len(c.heard_since_portion()) <= c.ack_join_fragments - 1


# === fast_text.py (owner A2): F1-F4 ===================================================================================================
import queue
import threading
import time

from echo_sync import fast_text as FT
from echo_sync import codex_road as CR


class Run:
    def __init__(self, request, cancelled):
        self.request, self.cancelled, self.script, self.ended = request, cancelled, queue.Queue(), threading.Event()

    def generate(self):
        try:
            while True:
                try:
                    kind, value = self.script.get(timeout=0.01)
                except queue.Empty:
                    if self.cancelled.is_set():
                        return
                    continue
                if kind == 'delta':
                    yield value
                elif kind == 'end':
                    return
                else:
                    raise RuntimeError(value)
        finally:
            self.ended.set()


class Fake:
    def __init__(self):
        self.runs = []

    def __call__(self, request, cancelled):
        self.runs.append(Run(request, cancelled))
        return self.runs[-1].generate()


class FClock:
    t = 1000.0

    def __call__(self):
        return self.t


def until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


def channel():
    fake, clock = Fake(), FClock()
    fast = FT.FastText(fake, instructions=lambda: 'POLICY', history=lambda: [], clock=clock, wake=lambda: None)
    return fast, fake, clock


# F3 -------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.xfail(strict=True, reason='g10 F2: _mind_spare applies FIRST_TEXT_S with the tail guard on')
def test_f_a_spare_is_not_killed_at_first_text_s():
    """prepare_wide + tail_guard (the candidate flag set of test_w14_old_answer): poll() skips the FIRST_TEXT_S bound (the roads give up at GIVE_UP_S) (a stall of the net is no failure), but _mind_spare applies it to the spare all the same: the prepared job of the question
    is killed at 4 s, counted as a stall, and the release of that very question starts a new request instead of adopting it."""
    fast, fake, clock = channel()
    fast.wide = True
    assert fast.prepare('Что такое инерция?') is True
    assert fast.prepare('Сколько будет пять на пять?') is True          # the first one moves to the spare place
    assert until(lambda: len(fake.runs) == 2)
    clock.t += FT.FIRST_TEXT_S + 0.1
    fast.poll()
    assert fast.job.outcome is None, 'the job in the first place is kept'
    assert fast.spare is not None and fast.spare.outcome is None, 'the spare is not'
    assert fast.release(qid='q1', turn='t1', epoch=1, question='Что такое инерция?') == 'adopted'


# F4 -------------------------------------------------------------------------------------------------------------------------------
class _Resp:
    status_code = 200

    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self):
        return iter(self.lines)


class _Client:
    def __init__(self):
        self.closed = threading.Event()

    def stream(self, method, url, **kw):
        if self.closed.is_set():
            raise RuntimeError('Cannot send a request, as the client has been closed.')     # what httpx raises: no dead socket, no retry
        return _Resp(['data: {"type":"response.output_text.delta","delta":"ok"}', 'data: {"type":"response.completed","response":{}}'])

    def close(self):
        self.closed.set()


@pytest.mark.xfail(strict=True, reason='g10 F4: _use(+1) after _client(), outside _state')
def test_f_a_job_counts_itself_on_the_client_before_another_job_can_let_it_go():
    """w3-integ 15: two jobs on one client (prepare_wide, the twin). Job B takes the client (_client) and only then counts itself in (_use +1);
    in between job A, whose socket died, lets the client go (_renew): it sees no user and closes it, and B streams on a closed client:
    RuntimeError, which is no dead socket, so no retry: B fails. The window is the ``cancelled.is_set()`` between the two."""
    made = []
    transport = CR.CodexTransport(lambda: ('tok', 'acc'), client_factory=lambda: made.append(_Client()) or made[-1])

    class Cancelled:
        hit = False

        def is_set(self):
            if not self.hit and made:
                self.hit = True
                transport._renew(made[0])                     # job A's dead-socket retry, at this instant
                made[0].closed.wait(0.3)                      # its close thread, if any, has run
            return False

    said = list(transport({'x': 1}, Cancelled()))
    assert said == ['ok']


# F5 -------------------------------------------------------------------------------------------------------------------------------
# c22-reviewfix: fixed by the half-open breaker of c22-break P08 (the breaker no longer closes the transport): the xfail mark is gone
def test_f_a_spare_that_times_out_does_not_close_the_transport_under_a_live_answer():
    """prepare_wide without the tail guard: the breaker counts the first-text timeout of the SPARE (a speculative job nobody asked for),
    and at BREAKER it closes the transport (_close_stream -> CodexTransport.close closes the httpx client) while the released job of the open
    question is in the middle of its answer: a healthy answer is cut, the question gets 'failed'."""
    fake, clock = Fake(), FClock()
    closed = []
    fake.close = lambda: closed.append(True)
    fast = FT.FastText(fake, instructions=lambda: 'POLICY', history=lambda: [], clock=clock, wake=lambda: None)
    fast.wide = True
    assert fast.prepare('Что такое инерция?') is True
    assert fast.release(qid='q1', turn='t1', epoch=1, question='Сколько будет пять на пять?') == 'started'
    assert fast.spare is not None                        # the prepared job is kept beside the job on the final
    assert until(lambda: len(fake.runs) == 2)
    clock.t += FT.FIRST_TEXT_S + 0.1
    fake.runs[1].script.put(('delta', '25.'))              # the job on the final speaks: the channel works
    assert until(lambda: fast.job.buffer == '25.')
    events = fast.poll()
    assert [e['text'] for e in events if e['kind'] == 'text'] == ['25.']
    assert not closed, 'the transport was closed under the answer in flight'


# === A6. a doubt («Разве?») of an answer whose first sentence has no substance: _fast_verdict recurses without end ========================
import helpers_s6_state as S6
from test_h3_tempo import TICK as H3_TICK, call       # noqa: F401,E402 - ``call`` is the fixture
from test_h5_live import LIVE                          # noqa: E402


@pytest.mark.xfail(strict=True, reason='g10 A6: _fast_verdict re-enters itself with the same held sentence: RecursionError kills the pump, the channel is lost')
def test_a6_a_doubt_of_an_answer_whose_first_sentence_has_no_substance_is_confirmed_not_recursed(call, caplog):
    rig = call(**LIVE)
    rig.asks('u0', 'В каком году было крещение Руси', 0, 'Так и есть. Крещение Руси было в 988 году.')
    rig.pump(1.0)
    count = len(rig.said())
    rig.w.feed(S6.turn_created('u1', 'user', ''))
    rig.w.feed(S6.turn_done('u1', 'user', 'Разве?'))
    rig.pump(H3_TICK * 2)
    assert len(rig.fake.runs) == 2, 'precondition: the doubt went to a job'
    rig.job_says(1, '—')
    rig.job_ends(1)
    rig.pump(0.3)
    assert 'RecursionError' not in caplog.text, 'the pump died and the channel is lost for the call'
    assert len(rig.said()) == count + 1, 'a doubt gets a confirmation'

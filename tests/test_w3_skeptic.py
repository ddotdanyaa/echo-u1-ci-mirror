"""w3-skeptic: an independent look for where the version breaks (H6, H7 and their seams with T1, Q1, a2). No network: the real FastText, CodexTransport, NativeMediaSocket and controller; only the job's
stream, the HTTP client, the ear's recognizer and the cloud's events are scripted. A red suspicion is ``xfail(strict=True)`` with its level and its first cause; the report (cloud_context/reports/w3-skeptic.md)
has the exact patch. The passing tests pin conditions that a manual mutant showed nothing else pinned, and the seams that held when they were pushed."""
import threading
import time

import pytest

import helpers_s6_state as S
from echo_sync import fast_text as FT
from test_h1_fast_text import settled, until
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_h5_live import LIVE, plan
from test_h6 import INERTIA, MATERIALS_ANSWER, input_of
from test_h7 import WIDE, wide_fast
import test_t1_transport as T

WAR = 'Кто написал Войну и мир'


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def said_by_the_cloud(rig, uid, text):
    rig.w.feed(S.turn_created(uid, 'user', text.split()[0]))
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK)


# =====================================================================================================================================
# T1 x H7 item 5: two jobs on ONE client (WAVE3 item 15)
# =====================================================================================================================================

def test_a_reconnect_of_one_job_does_not_close_the_client_under_another():
    """``prepare_wide``: the job on the final and the job kept beside it stream at once on the call's one client. The second gets a dead socket before its first text and takes its one retry: the client it
    lets go is the one the first job is reading its answer from. Closing an httpx client closes every socket of it: the answer stops in the middle (``no_terminal_event``, or a read error)."""
    speaking = T.Resp(T.sse({'type': 'response.output_text.delta', 'delta': 'Первая фраза. '}, {'type': 'response.output_text.delta', 'delta': 'Вторая.'}, {'type': 'response.completed'}))
    stream, factory = T.transport(T.Client(speaking, T.dead()))
    first = stream({}, threading.Event())
    assert next(first) == 'Первая фраза. ', 'precondition: the first job is in the middle of its answer'
    assert T.run(stream) == ['Да.'], 'the second job got its answer on its one retry'
    time.sleep(0.05)
    shared = factory.made[0]
    assert not shared.closed, 'the client was closed while a job was reading from it'
    assert list(first) == ['Вторая.']
    stream.close()


def test_a_reconnect_with_no_other_job_lets_the_old_client_go():
    """The other side of the patch: alone, the job that met a dead socket still lets that client go (one retry, a new client, the old one closed)."""
    stream, factory = T.transport(T.Client(T.dead()))
    assert T.run(stream) == ['Да.'] and len(factory.made) == 2
    assert until(lambda: factory.made[0].closed)
    stream.close()


# =====================================================================================================================================
# H7 item 5 x the open question: the ear's text of a question whose job already runs
# =====================================================================================================================================

def test_a_late_ear_text_of_the_question_in_flight_is_not_said_twice(call):
    """The cloud's final came first (the ear lagged, or the listener says the question again), its job runs; the ear's text of the same question gets a place beside it. Only one answer is ever said."""
    rig = call(**WIDE)
    said_by_the_cloud(rig, 'u1', WAR)
    rig.says(WAR.casefold(), speech=1.5)
    if rig.fast.count > 1:
        rig.job_says(1, 'Толстой.')      # the job beside it is quicker
    rig.job_says(0, 'Лев Толстой.')
    rig.job_ends(0)
    rig.pump(1.0)
    assert rig.said() == ['Лев Толстой.']


def test_a_late_ear_text_of_the_question_in_flight_starts_no_second_request():
    fast, fake, _ = wide_fast()
    fast.release(qid='u1', turn='t1', epoch=1, question=WAR)
    assert fast.prepare(WAR.casefold())
    assert fast.count == 1 and fast.spare is None, 'the job of the open question is the job of this text'
    fast.close()


def test_a_release_with_sources_never_adopts_the_job_kept_beside():
    """Mutant M02: a question the lookup gave sources for is answered from them. A prepared job has none, in the first place or in the second (``spare``): it is let go, and the job starts with the sources."""
    fast, fake, _ = wide_fast()
    fast.prepare(WAR.casefold())
    kept = fast.job
    fast.prepare('когда родился пушкин')
    assert fast.spare is kept, 'precondition: the job on this question waits in the second place'
    assert fast.release(qid='u1', turn='t1', epoch=1, question=WAR, material='источники') == 'started'
    assert kept.cancelled.is_set() and fast.job is not kept and fast.job.has_material and fast.spare is None
    fast.close()


# =====================================================================================================================================
# Q1 x H6 item 3: a figure behind a repeat of the portion
# =====================================================================================================================================

def figures(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer=MATERIALS_ANSWER)
    rig.pump(1.0)
    return rig, rig.c.state()['chunks'][0]


def test_a_plain_figure_is_answered_by_the_code(call):
    rig, _ = figures(call)
    said_by_the_cloud(rig, 'u1', 'Сколько будет двести разделить на четыре?')
    rig.pump(TICK * 3)
    assert rig.said()[-1] == 'Пятьдесят.' and len(rig.fake.runs) == 1


def test_a_figure_glued_after_a_repeat_of_the_portion_is_answered_by_the_code(call):
    """n1_04 step 10's glue, with a figure in place of the question: the listener repeats the portion and asks «сколько будет двести разделить на четыре» in one final. H6 cuts the repeat off for the job; Q1
    answers that figure by code in the same tick and exactly. The order of the two: the base reads the glued final, misses, and the model is asked."""
    rig, portion = figures(call)
    said_by_the_cloud(rig, 'u1', f'{portion} Сколько будет двести разделить на четыре?')
    rig.pump(TICK * 3)
    assert input_of(rig, len(rig.fake.runs) - 1) != 'Сколько будет двести разделить на четыре?' or len(rig.fake.runs) == 1, 'the model was asked a figure'
    assert rig.said()[-1] == 'Пятьдесят.'


def test_a_failed_prepared_job_is_not_kept_for_what_the_final_may_say():
    """Mutant M09: only a job at work or done well waits in the second place. One that failed is let go at the release, not one poll later: no look (``prepared``) and no adoption can meet it."""
    fast, fake, _ = wide_fast()
    fast.prepare(WAR.casefold())
    failed = fast.job
    fake.run(0).fail()
    settled(fast)
    assert failed.outcome == 'error'
    assert fast.release(qid='u1', turn='t1', epoch=1, question='Кто написал Анну Каренину') == 'started'
    assert fast.spare is None and fast.job is not failed
    fast.close()


@pytest.mark.parametrize('heard, asked', [
    ('в каком году была битва прикалки', 'В каком году была великая битва при Калке'),
    ('когда была битва прикалки', 'Когда была битва при Калке и Непрядве'),
], ids=['one-more-word', 'another-river'])
def test_a_word_the_ear_garbled_forgives_that_word_and_no_other(heard, asked):
    """Mutant M11 (H7 item 2, ``soft``): «прикалки» for «при Калке» is forgiven; a content word of the final the ear has not at all, beside it, is another question and stays a refusal."""
    assert FT.refusal('в каком году была битва прикалки', 'В каком году была битва при Калке', soft=True) is None, 'precondition: the garbled word alone is forgiven'
    assert FT.refusal(heard, asked, soft=True) == 'words'

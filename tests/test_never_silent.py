"""g19-never-silent (WAVE18): a question the system has heard, by the ear or by the cloud, gets a sound within NEVER_SILENT_S on every path of the stand: the bank, the reference base, the job (model,
material), the lookup, the model that hangs, the lookup that hangs. With no answer by then a short honest phrase is said. Silence after a question is a defect.

The H3 rig (test_h3_tempo): the real NativeMediaSocket, ShadowEar, ControlledMedia and FastText on the injected clock; scripted: the detector, the recognizer, the cloud, the job's stream. The candidate's flags
are on. ``heard`` is the first moment the system has the question's text: the ear's text or the cloud's final, whichever came first. Any cue counts as sound, a spoken diagnostic too. Nothing here measures a phone.
"""
import asyncio

import pytest

import helpers_s6_state as S
import helpers_w5_instant as fx
from echo_sync.instant import Instant
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture

NEVER_SILENT_S = 3.0
FLAGS = dict(fast_text='on', ear_release='on', instant='on', material_pick='on', spare_helper='on', warm_start='on', open_overlap='on')
YEAR_Q, YEAR_EAR, YEAR_A = 'В каком году было крещение Руси?', 'в каком году было крещение руси', 'Крещение Руси произошло в 988 году.'
LAW_Q, LAW_EAR = 'Семнадцатая статья Налогового кодекса', 'семнадцатая статья налогового кодекса'
BANK_Q, BANK_EAR = 'Когда пал Константинополь?', 'когда пал константинополь'
LOOKUP_Q, LOOKUP_EAR = 'В каком году принят нынешний закон о бухгалтерском учёте?', 'в каком году принят нынешний закон о бухгалтерском учёте'
LOOKUP_A = 'Закон о бухгалтерском учёте номер 402 принят в 2011 году.'
ROUTES = ('cloud', 'ear', 'both')
# What is still red on the product, with its first cause (cloud_context/reports/g19-never-silent.md): strict, so the day it is fixed the mark must go.
EAR_WAITS = pytest.mark.xfail(strict=True, reason='the cloud lost the turn: the ear waits EAR_FIRST_BIND_SECONDS / EAR_FINAL_SECONDS (4 s) from its text for a witness that never comes')
NO_HOLD = pytest.mark.xfail(strict=True, reason='no honest phrase before an answer: the first sound of a hung job is the refusal of tail_guard (8 s, off by default) or «Нет ответа» of the watchdog (12 s)')


def routes(*red):
    return [pytest.param(route, marks=EAR_WAITS) if route in red else route for route in ROUTES]


def sounds(rig):
    return [c for c in rig.w.cues]


def ask(rig, route, final, ear, uid='u1'):
    """The question by ``route``: the cloud's turn only (the ear heard nothing), the ear only (the cloud lost the turn), or both (the ear first, the final 0.8 s later). Returns ``heard``."""
    if route == 'cloud':
        rig.w.feed(S.turn_created(uid, 'user', final.split()[0]))
        rig.pump(1.5)
        rig.w.feed(S.turn_done(uid, 'user', final))
        heard = rig.w.clock.t
        rig.pump(TICK)
        return heard
    uid_ear = rig.onset()
    if route == 'both':
        rig.pump(0.4)
        rig.w.feed(S.turn_created(uid, 'user', final.split()[0]))
        rig.pump(1.1)
    else:
        rig.pump(1.5)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid_ear, ear)
    heard = rig.w.clock.t
    rig.pump(TICK)
    if route == 'both':
        rig.pump(0.7)
        rig.w.feed(S.turn_done(uid, 'user', final))
        rig.pump(TICK)
    return heard


def job_after(rig, at, text, n=None):
    """The job of the question says ``text`` at ``at`` (the rig's clock), and ends. The newest job, if ``n`` is None."""
    while rig.w.clock.t < at:
        rig.pump(TICK)
    run = rig.fake.runs[-1] if n is None else rig.fake.runs[n]
    run.say(text)
    rig.pump(TICK)
    run.finish()
    rig.pump(TICK)


def first_sound(rig, heard, within=12.0):
    """Seconds from ``heard`` to the first sound after it (None: silence ``within`` seconds)."""
    end = heard + within
    while rig.w.clock.t < end:
        after = [c for c in sounds(rig) if c.t >= heard - 1e-6]
        if after:
            return round(after[0].t - heard, 2)
        rig.pump(TICK)
    return None


def asked_and_timed(rig, route, final, ear, *, answer=None, answer_at=None):
    heard = ask(rig, route, final, ear)
    if answer is not None and rig.fake.runs:
        job_after(rig, heard + answer_at, answer)
    return heard, first_sound(rig, heard)


# =====================================================================================================================================
# the paths that answer
# =====================================================================================================================================

@pytest.mark.parametrize('route', routes('ear'))
def test_the_job_that_answers_in_a_second_is_heard_in_time(call, route):
    rig = call(**FLAGS)
    heard = ask(rig, route, YEAR_Q, YEAR_EAR)
    assert rig.fake.runs, 'precondition: a job was started'
    job_after(rig, heard + 1.0, YEAR_A)
    took = first_sound(rig, heard)
    assert took is not None and took <= NEVER_SILENT_S, (route, took, [(c.t - heard, c.text) for c in sounds(rig)])


@pytest.mark.parametrize('route', routes('ear'))
def test_the_reference_base_is_heard_in_time(call, route):
    rig = call(**FLAGS)
    heard = ask(rig, route, LAW_Q, LAW_EAR)
    if rig.fake.runs:
        job_after(rig, heard + 1.0, 'Статья 17 Налогового кодекса — общие условия установления налогов.')
    took = first_sound(rig, heard)
    assert took is not None and took <= NEVER_SILENT_S, (route, took, [(c.t - heard, c.text) for c in sounds(rig)])


@pytest.mark.parametrize('route', routes('ear'))
def test_the_bank_is_heard_in_time(call, route):
    rig = call(**FLAGS)
    rig.c.instant = Instant(fx.bank())
    heard = ask(rig, route, BANK_Q, BANK_EAR)
    took = first_sound(rig, heard)
    if took is None and rig.fake.runs:
        pytest.fail(f'{route}: the bank did not answer and the job was left alone: {[(c.t - heard, c.text) for c in sounds(rig)]}')
    assert took is not None and took <= NEVER_SILENT_S, (route, took, [(c.t - heard, c.text) for c in sounds(rig)])


@pytest.mark.parametrize('route', routes('ear'))
def test_the_material_job_is_heard_in_time(call, route):
    """The material goes into the job's request (material_pick): on the stand the path is the job's, with the material's answer."""
    rig = call(**FLAGS)
    heard = ask(rig, route, 'Что такое амортизация основных средств?', 'что такое амортизация основных средств')
    assert rig.fake.runs, 'precondition: a job was started'
    job_after(rig, heard + 1.2, 'Амортизация — постепенный перенос стоимости основных средств на расходы.')
    took = first_sound(rig, heard)
    assert took is not None and took <= NEVER_SILENT_S, (route, took, [(c.t - heard, c.text) for c in sounds(rig)])


@pytest.mark.parametrize('route', ('cloud', 'both'))
def test_the_lookup_is_heard_in_time(call, route):
    rig = call(**FLAGS)
    heard = ask(rig, route, LOOKUP_Q, LOOKUP_EAR)
    rig.pump(0.3)
    if rig.fake.runs:
        job_after(rig, heard + 1.2, LOOKUP_A)
    took = first_sound(rig, heard)
    assert took is not None and took <= NEVER_SILENT_S, (route, took, [(c.t - heard, c.text) for c in sounds(rig)])


# =====================================================================================================================================
# the paths that hang: a short honest phrase in time, and the answer still comes if it comes
# =====================================================================================================================================

@NO_HOLD
@pytest.mark.parametrize('route', ROUTES)
def test_the_model_that_hangs_gets_an_honest_phrase_in_time(call, route):
    rig = call(**FLAGS)
    heard = ask(rig, route, YEAR_Q, YEAR_EAR)
    took = first_sound(rig, heard)
    assert took is not None and took <= NEVER_SILENT_S, (route, took, [(c.t - heard, c.text) for c in sounds(rig)])


@pytest.mark.parametrize('route', ROUTES)
def test_the_model_that_hangs_says_something_at_all(call, route):
    """The weaker bound: whatever the 3 s, a hung model is never silence for 15 s."""
    rig = call(**FLAGS)
    heard = ask(rig, route, YEAR_Q, YEAR_EAR)
    assert first_sound(rig, heard, within=15.0) is not None, (route, [(c.t - heard, c.text) for c in sounds(rig)])


@pytest.mark.parametrize('route', [pytest.param(route, marks=NO_HOLD) if route == 'ear' else route for route in ROUTES])      # fix5 (F20): on a final (cloud, both) the roads' sentence comes at the due and the job's late text takes its place: XPASS, the mark is gone; the ear's candidate still ends its job at the due
def test_a_late_answer_after_the_honest_phrase_is_still_said(call, route):
    rig = call(**FLAGS)
    heard = ask(rig, route, YEAR_Q, YEAR_EAR)
    first_sound(rig, heard)
    job_after(rig, heard + 4.5, YEAR_A)
    rig.pump(4.0)
    assert any('988' in c.text for c in sounds(rig)), (route, [(c.t - heard, c.text) for c in sounds(rig)])


@pytest.fixture
def hung_lookup(monkeypatch):
    async def never(self, question):
        self.lookup_calls.append(question)
        await asyncio.Event().wait()
    monkeypatch.setattr(S.World, '_lookup', never)


@NO_HOLD
@pytest.mark.parametrize('route', ('cloud', 'both'))
def test_the_lookup_that_hangs_gets_an_honest_phrase_in_time(call, hung_lookup, route):
    rig = call(**FLAGS)
    heard = ask(rig, route, LOOKUP_Q, LOOKUP_EAR)
    took = first_sound(rig, heard)
    assert took is not None and took <= NEVER_SILENT_S, (route, took, [(c.t - heard, c.text) for c in sounds(rig)])


# =====================================================================================================================================
# the honest phrase is no defect of its own: talk stays silent, one phrase per question
# =====================================================================================================================================

def test_talk_is_no_question_and_gets_no_phrase(call):
    rig = call(**FLAGS)
    uid = rig.onset()
    rig.pump(1.5)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, 'ну в общем вчера было прикольно')
    rig.w.feed(S.turn_created('u1', 'user', 'Ну'))
    rig.w.feed(S.turn_done('u1', 'user', 'Ну в общем вчера было прикольно.'))
    rig.pump(TICK)
    for run in rig.fake.runs:
        run.say('—')
        run.finish()
    rig.pump(10.0)
    assert sounds(rig) == [], [c.text for c in sounds(rig)]


@pytest.mark.parametrize('route', ROUTES)
def test_one_honest_phrase_per_question(call, route):
    rig = call(**FLAGS)
    heard = ask(rig, route, YEAR_Q, YEAR_EAR)
    rig.pump(12.0)
    texts = [c.text for c in sounds(rig)]
    assert len(texts) - len(set(texts)) <= 1, texts

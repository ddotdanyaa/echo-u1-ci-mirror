"""Registry 6.04 «Память между звонками и днями». Registry state: ВЫКЛЮЧЕНО, НЕ СДЕЛАНО (topic_recap, ledger_carry, resume_next_day: off).
Proves, through the real controller (tests/helpers_night_memory.Call: real ControlledMedia, engine, ledger, fast_text; only cloud, text model, phone are scripted), the three promises of the row:
 1 topic recap: an answer given early in a long call reaches the model's request (and so the prompt) after it left the window of the last exchanges
 2 earlier calls: an exchange of a call 20 h ago reaches the request of a new call
 3 «продолжай» next day: 20 h later it says the next portion of yesterday's unfinished answer, nothing goes to the model
The keys of THIS function are not set: the engine default (settings.DEFAULTS) is read at run time, so a strict xfail turns XPASS when it is switched on.
 4 the same after a PROCESS RESTART: the first stand is closed, a NEW stand is raised on the same state directory (disk ledger), and 2 and 3 are asked of it
 5 days and weeks (U03-06): an exchange of 3 days ago reaches a new call (the recap window of the code is 36 h, so this stays a red target)
Other keys: fast_text=on (live); conversation_ledger=memory (live) for 1, disk for 2-5 (live is memory, the row needs disk); v6_memory left at its default (the v6 card would carry the memory alone).
Off-switch check: the three defaults flipped to on in a private copy of the tree (registry_proof/6.04.json)."""
import pytest

import helpers_night_memory as M
import helpers_s6_state as S
from echo_sync.settings import DEFAULTS as D

H = 3600.0
TOPICS = 'озеро поезд гитара ветер мост лес сад окно книга'.split()
Q_LATE = 'Какая глубина у озера, про которое мы говорили в самом начале?'
DEEP = '40 метров'


def mind(request):
    """Text model of the test: a story of three portions; a late question is answered from the request alone."""
    q, seen = M.asked(request), M.memory_of(request)
    if q.startswith('Расскажи про '):
        t = q[len('Расскажи про '):-1]
        return 'Про %s известно главное. Глубина %s %s. Берег %s зарос лесом.' % (t, t, DEEP, t)
    if q == Q_LATE:
        return DEEP + '.' if 'озеро' in seen and DEEP in seen else M.UNKNOWN
    return 'Ответ модели на просьбу продолжить.'


def played(tmp_path, body, **profile):
    """Run body(call) on the stand (the other keys of the profile are the test's), always closed; ledger recap alone carries the memory (v6_memory at its default)."""
    call = M.Call(tmp_path, mind=mind, **{'topic_recap': D['topic_recap'], **profile})
    try:
        return body(call)
    finally:
        call.close()


def asked_of(call, since):
    return [M.asked(r) for r in call.all_requests()[since:]]      # what went to the model after the first ``since`` jobs


@pytest.mark.xfail(strict=True, reason='реестр 6.04: ВЫКЛЮЧЕНО, НЕ СДЕЛАНО: topic_recap по умолчанию off, сводка темы не идёт в запрос')
def test_topic_recap_carries_an_early_answer_into_the_request(tmp_path):
    def body(call):
        for topic in TOPICS:                       # nine exchanges: the first has left the window of the last six
            call.pump(120.0, 1.0)
            call.ask('Расскажи про %s?' % topic)
        call.pump(120.0, 1.0)
        call.say(Q_LATE)
        return M.whole(call.all_requests()[-1]), call.cues()
    sent, cues = played(tmp_path, body, topic_recap=D['topic_recap'], conversation_ledger='memory')
    assert 'Ранее в этом разговоре' in sent and 'Расскажи про озеро' in sent     # the block with the pointer to the early question
    assert DEEP + '.' in cues and M.UNKNOWN not in cues                             # the prompt in the ear is right because the memory was in the request


def test_ledger_carry_puts_yesterdays_exchange_into_the_new_call(tmp_path):
    def body(call):
        call.ask('Расскажи про озеро?')            # the earlier call
        call.w.advance(20 * H, step=1200.0)        # the line is down for 20 hours, then the phone dials again
        call.redial(1.0)
        call.say(Q_LATE)
        return M.whole(call.all_requests()[-1]), call.cues()
    sent, cues = played(tmp_path, body, ledger_carry=D['ledger_carry'], conversation_ledger='disk')
    assert 'Прошлые разговоры' in sent and 'Расскажи про озеро' in sent and '20 ч назад' in sent
    assert DEEP + '.' in cues


def test_continue_next_day_goes_on_with_yesterdays_answer(tmp_path):
    def body(call):
        call.say('Расскажи про озеро?')
        call.pump(1.0)
        call.say(S.relaxed([c for c in call.w.cues if not c.diagnostic][-1].text))      # the first portion said back, the second waits
        call.pump(1.0)
        call.ask('Расскажи про поезд?')           # another question interrupts yesterday's answer
        shown, sent = len(call.cues()), len(call.all_requests())
        call.w.advance(20 * H, step=1200.0)        # the next day
        call.say('Продолжай.')
        call.pump(1.0)
        return call.cues()[shown:], asked_of(call, sent)
    cues, to_model = played(tmp_path, body, conversation_ledger='disk')
    assert cues == ['Глубина озеро %s.' % DEEP]     # the next portion of the unfinished answer, said locally
    assert 'Продолжай.' not in to_model              # and the words did not go to the model


def restarted(tmp_path, before, after, **profile):
    """A process restart between two stands: ``before(call)`` on the first, which is then closed for good; ``after(call)`` on a NEW stand over the same state directory (only the disk is left)."""
    played(tmp_path, before, **profile)
    return played(tmp_path, after, **profile)


def test_ledger_carry_survives_a_process_restart(tmp_path):
    def after(call):
        call.w.advance(20 * H + 600.0, step=1200.0)       # the new process has run since the old one died; then the phone dials again
        call.redial(1.0)
        call.say(Q_LATE)
        return M.whole(call.all_requests()[-1]), call.cues()
    sent, cues = restarted(tmp_path, lambda call: call.ask('Расскажи про озеро?'), after, ledger_carry=D['ledger_carry'], conversation_ledger='disk')
    assert 'Прошлые разговоры' in sent and 'Расскажи про озеро' in sent and '20 ч назад' in sent       # read from the day file of the dead process
    assert DEEP + '.' in cues


def test_continue_next_day_survives_a_process_restart(tmp_path):
    def before(call):
        call.say('Расскажи про озеро?')
        call.pump(1.0)
        call.say(S.relaxed([c for c in call.w.cues if not c.diagnostic][-1].text))      # the first portion said back, the second waits
        call.pump(1.0)
        call.ask('Расскажи про поезд?')

    def after(call):
        shown, sent = len(call.cues()), len(call.all_requests())
        call.w.advance(20 * H, step=1200.0)
        call.say('Продолжай.')
        call.pump(1.0)
        return call.cues()[shown:], asked_of(call, sent)
    cues, to_model = restarted(tmp_path, before, after, conversation_ledger='disk')
    assert cues == ['Глубина озеро %s.' % DEEP] and 'Продолжай.' not in to_model


@pytest.mark.xfail(strict=True, reason='реестр 6.04: ВЫКЛЮЧЕНО, НЕ СДЕЛАНО: «дни и недели» (U03-06) не сделаны: сводка прошлых звонков берёт не старше 36 часов (LEDGER_CARRY_S), обмен трёхдневной давности в запрос не идёт')
def test_ledger_carry_reaches_back_days(tmp_path):
    def body(call):
        call.ask('Расскажи про озеро?')
        call.w.advance(72 * H + 600.0, step=1200.0)       # three days (the day files keep 14)
        call.redial(1.0)
        call.say(Q_LATE)
        return M.whole(call.all_requests()[-1]), call.cues()
    sent, cues = played(tmp_path, body, ledger_carry=D['ledger_carry'], conversation_ledger='disk')
    assert 'Прошлые разговоры' in sent and 'Расскажи про озеро' in sent and '72 ч назад' in sent
    assert DEEP + '.' in cues

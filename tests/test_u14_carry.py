"""U14-S8: the recap of earlier calls (ledger_carry) and the explicit next-day resume (resume_next_day). The carry is off by default; the resume is always on."""
import time

from echo_sync import fast_text as FT
from echo_sync import timer_policy
from echo_sync.conversation_ledger import ConversationLedger, LEDGER_CARRY_S
from echo_sync.engine import RESUME_NEXT_DAY_S
from echo_sync.settings import DEFAULTS, resolve

from test_cl2_resume import A_QUESTION, A_PORTIONS, B_QUESTION, Session
from test_h1_fast_text import manager

H = 3600.0


class Wall:
    def __init__(self, at=1_800_000_000.0):
        self.at = at

    def __call__(self):
        return self.at


def _yesterday(tmp_path, n=1):
    wall = Wall()
    led = ConversationLedger(directory=tmp_path, wall=wall)
    led.open_call(1.0)
    for i in range(n):
        led.user_final('t%d' % i, 'Почему меняются времена года номер %d?' % i, final_rev=1, at=2.0)
        led.answer('r%d' % i, 'Наклон земной оси меняет освещение. ' * 8, tid='t%d' % i, at=3.0)
        wall.at += 60
    return wall


def test_recap_has_the_pointer_after_20_hours_and_is_within_600(tmp_path):
    wall = _yesterday(tmp_path, n=12)
    wall.at += 20 * H
    led = ConversationLedger(directory=tmp_path, wall=wall)
    led.open_call(1.0)
    text = led.recap_calls(LEDGER_CARRY_S)
    assert 0 < len(text) <= 600
    assert 'Почему меняются времена года номер 11' in text and '20 ч назад' in text          # the pointer: when and what
    assert 'номер 0?' not in text                                                            # the newest first; the oldest fall off the budget
    assert led.recap_calls(LEDGER_CARRY_S) == text                                           # deterministic


def test_recap_leaves_out_the_present_call_and_what_is_older_than_the_window(tmp_path):
    wall = _yesterday(tmp_path)
    wall.at += 40 * H
    led = ConversationLedger(directory=tmp_path, wall=wall)
    led.open_call(1.0)
    assert led.recap_calls(LEDGER_CARRY_S) == ''                                             # 40 h: beyond 36 h
    wall.at += 0
    led2 = ConversationLedger(directory=tmp_path, wall=wall)
    led2.open_call(1.0)
    led2.user_final('now', 'вопрос этого звонка', final_rev=1)
    led2.answer('rx', 'ответ этого звонка', tid='now')
    assert 'этого звонка' not in led2.recap_calls(100 * H)


def test_memory_ledger_has_no_recap():
    led = ConversationLedger()
    led.open_call(1.0)
    led.user_final('t', 'вопрос', final_rev=1)
    led.answer('r', 'ответ', tid='t')
    assert led.recap_calls(LEDGER_CARRY_S) == ''


def test_prompt_gets_the_recap_only_when_given_and_is_byte_identical_otherwise():
    fast, fake, clock = manager()
    assert fast._start('Что такое инерция').request['instructions'] == 'POLICY'
    fast.carry = lambda: 'CARRY'
    assert fast._start('x').request['instructions'] == 'POLICY\n\nCARRY'
    fast.carry = lambda: ''
    assert fast._start('y').request['instructions'] == 'POLICY'


def test_memory_has_no_switch_left():
    keys = ('ledger_carry', 'topic_recap', 'recall_words', 'conversation_ledger', 'resume_next_day')      # memory is always on: no key, nothing to resolve
    d = resolve({k: 'on' for k in keys})
    assert not any(k in d or k in DEFAULTS for k in keys)


def test_constants_are_in_the_timer_table():
    assert timer_policy.unregistered() == [] and timer_policy.stale() == []
    assert 'engine.RESUME_NEXT_DAY_S' in timer_policy.TIMERS and 'conversation_ledger.LEDGER_CARRY_S' in timer_policy.TIMERS


def _left_yesterday(tmp_path, settings):
    s = Session(tmp_path, settings=settings)
    s.say(A_QUESTION)
    s.say(A_PORTIONS[0])
    s.say(B_QUESTION)
    s.to_the_end()
    s.clock.advance(20 * H)
    return s


def test_continue_20_hours_later_restores(tmp_path):
    s = _left_yesterday(tmp_path, {'conversation_ledger': 'disk'})
    assert s.say('Продолжай.') == A_PORTIONS[1]
    assert s.calls[-1] != 'Продолжай.'


def test_continue_40_hours_later_goes_to_the_model(tmp_path):
    s = _left_yesterday(tmp_path, {'conversation_ledger': 'disk'})
    s.clock.advance(20 * H)
    assert s.say('Продолжай.') != A_PORTIONS[1]
    assert s.calls[-1] == 'Продолжай.'


def test_the_long_window_is_for_the_explicit_command_only(tmp_path):
    s = _left_yesterday(tmp_path, {'conversation_ledger': 'disk'})
    s.say('Расскажи про другое что-нибудь новое?')
    assert s.state['history'][-1]['question'].startswith('Расскажи')
    assert RESUME_NEXT_DAY_S >= 36 * H

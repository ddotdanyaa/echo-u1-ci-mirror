"""one-input U118: an objection, a clarification and a repeat are three different remarks about the answer in play (M1: the judge). A table of 22 remarks, RU, driven through the real controller
(``tests/helpers_night_memory.Call``: an answer of three portions is begun, then the remark is heard); the verdict is read from the one ``echo-sync judge`` line of the final.
Reconnection: the facts of a long conversation (M9, ``ConversationLedger``) are in the request after a redial inside ``CONVERSATION_GAP_S``, and a remark after the redial is judged the same way."""
import logging
import re

import pytest

import helpers_night_memory as M
from echo_sync.conversation_ledger import CONVERSATION_GAP_S

ANSWER = 'Первая часть ответа про инерцию. Вторая часть ответа про силу. Третья часть ответа про массу.'
OBJECTION, CLARIFICATION, REPEAT = 'correction', 'question', 'repeat'      # the kinds of the judge: an objection is a correction of the answer, a clarification asks about it, a repeat asks it again
# (remark, kind, reason or None when only the kind is a contract). The first ten were told apart by the classifier already; the rest were silent or plain questions.
TABLE = [
    ('нет, это неверно', OBJECTION, None),
    ('ты ошибся, там не пятьдесят а шестьдесят', OBJECTION, None),
    ('я с этим не согласен', OBJECTION, None),
    ('это неправда', OBJECTION, None),
    ('нет, ты не прав', OBJECTION, None),
    ('но ведь это не так', OBJECTION, 'objection_form'),
    ('ты что-то путаешь', OBJECTION, 'objection_form'),
    ('объясни проще', CLARIFICATION, 'clarification_request'),
    ('расскажи подробнее', CLARIFICATION, 'clarification_request'),
    ('а если наоборот', CLARIFICATION, 'clarification_request'),
    ('приведи пример', CLARIFICATION, 'clarification_request'),
    ('а можно проще', CLARIFICATION, 'clarification_request'),
    ('в смысле', CLARIFICATION, 'clarification_request'),
    ('что ты имеешь в виду', CLARIFICATION, 'clarification_request'),
    ('то есть как это понимать', CLARIFICATION, 'clarification_request'),
    ('повтори', REPEAT, None),
    ('ещё раз пожалуйста', REPEAT, None),
    ('можешь повторить последнюю часть', REPEAT, None),
    ('скажи заново', REPEAT, None),
    ('нет, повтори', REPEAT, None),
    ('не понял, повтори', REPEAT, None),
    ('повтори, я не расслышал', REPEAT, None),
]


class Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def emit(self, record):
        self.rows.append(record.getMessage())

    def verdict(self, tid):
        rows = [dict(re.findall(r'(\w+)=(\S+)', r)) for r in self.rows if r.startswith('echo-sync judge ') and ('tid=%s ' % tid) in r]
        return rows[-1] if rows else None


@pytest.fixture
def lines():
    log, handler, level = logging.getLogger('echo-sync'), Lines(), logging.getLogger('echo-sync').level
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    yield handler
    log.removeHandler(handler)
    log.setLevel(level)


@pytest.fixture
def make(tmp_path):
    calls = []

    def build(mind=lambda request: ANSWER, **over):
        call = M.Call(tmp_path / f'c{len(calls)}', mind=mind, **{'fast_text': 'on', **over})
        calls.append(call)
        return call
    yield build
    for call in calls:
        call.close()


@pytest.mark.parametrize('remark,kind,reason', TABLE, ids=[row[0] for row in TABLE])
def test_the_remark_about_the_answer_has_its_own_kind(make, lines, remark, kind, reason):
    call = make()
    call.say('Что такое инерция?')
    call.pump(1.0)
    row = lines.verdict(call.say(remark))
    assert row is not None and row['kind'] == kind, row
    if reason:
        assert row['reason'] == reason, row


def test_the_table_has_the_three_kinds_and_twenty_remarks():
    assert len(TABLE) >= 20 and {row[1] for row in TABLE} == {OBJECTION, CLARIFICATION, REPEAT}


def test_the_facts_of_a_long_conversation_and_the_judgement_of_a_remark_survive_a_redial(make, lines):
    call = make(mind=M.mind, conversation_ledger='memory', topic_recap='on', v6_memory='on')
    call.say(M.OPENING)
    call.say(M.COND)
    call.say(M.PRICE_OLD)
    call.pump(5.0, 1.0)
    call.say(M.PRICE_FIX)
    call.ask(M.Q_WARRANTY)
    call.redial(CONVERSATION_GAP_S - 60.0)      # the line dropped, the phone dialled again inside the gap: the same conversation
    row = lines.verdict(call.say('но ведь это не так'))
    assert row is not None and row['kind'] == OBJECTION, row
    call.pump(2.0)
    call.say(M.Q_PRICE)
    call.pump(2.0)
    memory = M.memory_of(call.request_for(M.Q_PRICE))
    assert '700' in memory and 'пять процентов' in memory, memory[:600]
    assert any('700' in line for line in M.lines_with(call.request_for(M.Q_PRICE), '500')), 'the correction stands next to the value it took back'

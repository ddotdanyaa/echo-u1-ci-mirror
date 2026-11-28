"""Registry 6.03 «Память влияет на ответ: карточка в запросе к модели».
Registry state: ALWAYS ON (the key v6_memory is deleted).
Proved (the promise of the row, with the memory keys at the ENGINE DEFAULTS, nothing of the memory turned on by the test): through the real controller (helpers_night_memory.Call: World + real
fast_text job + v6_memory hook + CallTrace journal) a text-model request carries what was said earlier in the call: the condition of minute 5 at minute 40 AND at minute 170, the correction
«не 500, а 700» told AFTER the old price under a heading that says the correction stands (U88, the coordinator's decision of 15.11), a refined final in place of its misheard first final; the card is not empty on a new call (a laptop with the state file of an earlier call; a redial
inside one conversation). Only the request sent to the model, the prompts the owner hears and the call journal are read.
Other keys at live server values: fast_text=on, conversation_ledger=memory, topic_recap=off. Memory is always on (no switch): the tests are plain.
Dummy check (private copy): a stub of the card hook -> the memory tests fail;
a stub of the card hook (v6_memory.Memory.apply returns what it was given) -> the tests that passed at on fail again."""
import pytest

import helpers_night_memory as M
from echo_sync import v6_memory as V
from echo_sync.settings import DEFAULTS

MEMORY_KEYS = {key: DEFAULTS[key] for key in ('v6_memory_chars', 'v6_memory_step_min', 'v6_memory_lines')}
LIVE = {'fast_text': 'on', 'conversation_ledger': 'memory', 'topic_recap': 'off'}        # the server's values of OTHER functions' keys
TOLD = lambda request: 'скидка пять процентов' in M.whole(request) and 'больше трёхсот единиц' in M.whole(request)       # noqa: E731 - the condition of minute 5


def play(tmp_path):
    """Condition at minute 5, price and its correction, a misheard final refined, then the questions at minutes 40-50 and 170 (one big virtual step); returns what the stand saw."""
    call = M.Call(tmp_path, **LIVE, **MEMORY_KEYS)
    try:
        for minute, step in ((1.0, lambda: call.say(M.OPENING)), (5.0, lambda: call.say(M.COND)), (10.0, lambda: call.say(M.PRICE_OLD)),
                             (12.0, lambda: call.say(M.PRICE_FIX)), (15.0, lambda: call.refine(call.say(M.PAY_MISHEARD), M.PAY))):
            call.go(minute)
            step()
        asked = {}
        for minute, question in ((40.0, M.Q_COND), (45.0, M.Q_PRICE), (50.0, M.Q_PAY), (170.0, M.Q_COND)):
            call.go(minute) if minute < 60 else call.pump(minute * 60.0 - call.minute() * 60.0, 5.0)
            call.ask(question)
            asked[(question, minute)] = call.request_for(question, after=minute)
        return asked, call.cues(), [row for row in call.journal() if row.get('ev', '').startswith('memory_card')]
    finally:
        call.close()


def new_call(tmp_path, redial_at=None):
    """The condition at minute 5, the question at minute 40, on a NEW call: the laptop holds the state file of an earlier call (redial_at None), or the line drops at ``redial_at`` and the
    phone dials again 20 s later (one conversation goes on). Returns the question's request and the prompts heard."""
    call = M.Call(tmp_path, **LIVE, **MEMORY_KEYS)
    try:
        if redial_at is None:
            M.earlier_call(call)
        call.go(5.0)
        call.say(M.COND)
        if redial_at is not None:
            call.go(redial_at - 2.0)
            call.say(M.SHIP_OLD)                                                          # the call goes on until two minutes before the drop: the redial is inside CONVERSATION_GAP_S of the newest record
            call.go(redial_at)
            call.redial(20.0)
            call.zero -= redial_at * 60.0 + 20.0                                          # the minutes of the stand go on
        call.go(39.5)
        call.ask(M.Q_COND)
        return call.request_for(M.Q_COND, after=39.0), call.cues()
    finally:
        call.close()


@pytest.fixture(scope='module')
def played(tmp_path_factory):
    return play(tmp_path_factory.mktemp('mem'))



def test_condition_of_minute_5_is_in_the_request_at_minute_40(played):
    request = played[0][(M.Q_COND, 40.0)]
    assert TOLD(request), M.memory_of(request)[:300]
    assert 'Скидка пять процентов' in ' '.join(played[1])                                 # the prompt the owner hears is right only through the request



def test_condition_of_minute_5_is_in_the_request_at_minute_170(played):
    request = played[0][(M.Q_COND, 170.0)]                                                # "170 minutes ago": the row's promise at its far end
    assert TOLD(request), M.memory_of(request)[:300]
    assert ' '.join(played[1]).count('Скидка пять процентов') == 2 and M.UNKNOWN not in played[1]


def test_correction_beats_the_old_fact(played):
    request = played[0][(M.Q_PRICE, 45.0)]
    assert '700' in M.whole(request)
    lines = M.whole(request).split('\n')
    olds = [i for i, line in enumerate(lines) if '500' in line and '700' not in line]
    fixes = [i for i, line in enumerate(lines) if '500' in line and '700' in line]
    assert fixes and all(any(j > i for j in fixes) for i in olds), (olds, fixes)       # U88: 500 is never told without its correction after it
    assert not olds or V.HEAD['exact'] in lines[:olds[0]], 'the old value stands under no heading that says the correction after it is what stands'
    assert 'Цена 700 рублей' in ' '.join(played[1])



def test_refined_final_replaces_the_misheard_one(played):
    request = played[0][(M.Q_PAY, 50.0)]
    assert 'Срок оплаты 30 дней' in M.whole(request)
    assert '90 дней' not in M.whole(request)



def test_journal_counts_the_memory_sent_to_the_model(played):
    rows = [row for row in played[2] if row['ev'] == 'memory_card']
    assert rows and all(row['mode'] == 'on' for row in rows) and sum(row['sent_chars'] for row in rows) > 0



def test_card_is_not_empty_on_a_new_call_after_an_earlier_one(tmp_path):
    """N1 of the row: the card was empty on every new call (the laptop holds the state file of an earlier call)."""
    request, cues = new_call(tmp_path)
    assert TOLD(request), M.memory_of(request)[:300]
    assert 'Скидка пять процентов' in ' '.join(cues)



def test_card_carries_what_was_said_before_a_redial_in_one_conversation(tmp_path):
    request, cues = new_call(tmp_path, redial_at=20.0)
    assert TOLD(request), M.memory_of(request)[:300]
    assert 'Скидка пять процентов' in ' '.join(cues)

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

"""M1 (night 13.11): the conversation memory reaches the model's request. The first causes of night-bench / night-memory, each locked by a count, through the real controller where
the cause lives in it. No network, no stand."""
import pytest

from echo_sync import v6_memory as V
from echo_sync.controlled_media import ControlledMedia
from echo_sync.conversation_ledger import ConversationLedger


def turn(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def answered(c, tid, question, answer):
    c.provider(turn(tid, 'user', question))
    c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'source'}])
    acts = c.provider(turn('a' + tid, 'assistant', getattr(c, 'answer_marker', '') + answer))
    cue = next(x for x in acts if isinstance(x, dict) and x.get('text'))
    c._cue_event('began', cue, c.clock())
    c._cue_event('done', cue, c.clock() + 1.0)


# -- б: an answer takes the place of the earlier revision of the SAME question only ----------------------------------------------------------------------------------

def test_b_a_revision_of_the_same_question_still_supersedes_the_row_before_it():
    led = ConversationLedger()
    led.user_final('u1', 'какая цена', final_rev=1, at=1.0)
    led.answer('r1', 'Цена 500.', tid='u1', at=2.0)
    led.answer('r2', 'Цена 700.', tid='u1', supersedes='r1', at=3.0)
    assert [(r.ref, r.superseded) for r in led.records() if r.kind == 'answer'] == [('r1', True), ('r2', False)]


def test_b_the_answer_of_another_question_stays_however_many_follow():
    led = ConversationLedger()
    prev = None
    for n in range(1, 21):
        led.user_final('u%d' % n, 'вопрос номер %d' % n, final_rev=1, at=n * 10.0)
        led.answer('r%d' % n, 'ответ %d' % n, tid='u%d' % n, supersedes=prev, at=n * 10.0 + 1)
        prev = 'r%d' % n
    assert sum(1 for r in led.records() if r.kind == 'answer' and not r.superseded) == 20


def test_b_memory_is_always_on_the_older_exchanges_come_as_the_topic_recap_and_every_answer_stays_live(tmp_path):
    """M9: no flag stands between the ledger and the request (the old test of the live profile with the recap off is gone with the key): after 8 exchanges the two that left the window of 6 are in the recap."""
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings={'conversation_ledger': 'memory'})
    c.begin_call()
    for n in range(1, 9):
        answered(c, 'u%d' % n, 'Почему вопрос номер %d важен?' % n, 'Потому что ответ номер %d.' % n)
    assert c.fast_recap().startswith('Ранее в этом разговоре:') and 'номер 1' in c.fast_recap()
    assert sum(1 for r in c.convo.records() if r.kind == 'answer' and not r.superseded) == 8


# -- г: who said it: the owner saying the prompt aloud is not the room ---------------------------------------------------------------------------------------------

def test_g_the_owner_saying_the_prompt_back_is_written_as_said_back_not_as_the_room(tmp_path):
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings=MEMORY)
    c.begin_call()
    c.provider(turn('u1', 'user', 'Какой у вас гарантийный срок на оборудование?'))
    c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'source'}])
    acts = c.provider(turn('a1', 'assistant', getattr(c, 'answer_marker', '') + 'Гарантия 24 месяца с даты поставки.'))
    cue = next(x for x in acts if isinstance(x, dict) and x.get('text'))
    c._cue_event('began', cue, c.clock())
    c._cue_event('done', cue, c.clock() + 1.0)
    c.provider(turn('b1', 'user', cue['text']))                     # the owner says the portion aloud: the judge takes it for the repeat of the prompt
    rows = {r.tid: r for r in c.convo.records() if r.kind == 'user'}
    assert c.resolutions.records['b1']['resolution'] == 'ack', 'precondition: the judge heard the prompt said back'
    assert rows['b1'].who == 'back' and rows['u1'].who is None


def a_ledger_with_our_answer_long_ago():
    """Minute 22: a question of the room, our answer, the owner says it back; then 20 other exchanges."""
    led = ConversationLedger()
    led.user_final('q', 'Какой у вас гарантийный срок на оборудование?', final_rev=1, at=22 * 60.0)
    led.answer('r1', 'Гарантия 24 месяца с даты поставки.', tid='q', at=22 * 60.0 + 2)
    led.user_final('b', 'гарантия 24 месяца с даты поставки', final_rev=1, at=22 * 60.0 + 6, who='back')
    for n in range(20):
        at = 30 * 60.0 + n * 60.0
        led.user_final('u%d' % n, 'Какой срок поставки у партии %d?' % n, final_rev=1, at=at)
        led.answer('r%d' % (n + 2), 'Срок поставки партии %d - %d дней.' % (n, 10 + n % 7), tid='u%d' % n, at=at + 2)
        led.user_final('b%d' % n, 'срок поставки партии %d %d дней' % (n, 10 + n % 7), final_rev=1, at=at + 6, who='back')
    return led


def test_g_no_said_back_words_are_told_as_said_in_the_room():
    led = a_ledger_with_our_answer_long_ago()
    back = {r.text for r in led.records() if r.kind == 'user' and r.who == 'back'}
    for question in ('Какую гарантию на оборудование мы называли?', 'Какой срок поставки у партии 3?', 'что ещё'):
        card = V.build_card(led, question, since=0.0)
        room = [line for part in card.lines.values() for line in part if ', %s: «' % V.SPEAKER in line or line.startswith('Прозвучало без ответа')]
        assert not [line for line in room if any(b in line for b in back)], room


def test_g_our_answer_of_long_ago_is_found_and_told_as_ours():
    card = V.build_card(a_ledger_with_our_answer_long_ago(), 'Какую гарантию на оборудование мы называли?', since=0.0)
    ours = [line for part in card.lines.values() for line in part if '24 месяца' in line]
    assert ours and all(', %s: «' % V.OURS in line for line in ours), card.text


def test_g_a_long_chain_of_the_exact_things_keeps_the_utterance_that_bears_on_the_question():
    """The answer of minute 22 bears on the question (a rare word of it and a number); twenty later utterances with numbers share a word with it and join its chain. The chain is longer
    than the cap: what is cut is the later links, never the utterance the question is about."""
    led = ConversationLedger()
    led.user_final('q', 'Какой у вас гарантийный срок?', final_rev=1, at=22 * 60.0)
    led.answer('r1', 'Гарантия 24 месяца с даты поставки.', tid='q', at=22 * 60.0 + 2)
    for n in range(8):           # the exchange of minute 22 leaves the newest exchanges
        led.user_final('w%d' % n, 'Почему вопрос номер %s важен?' % 'абвгдежз'[n], final_rev=1, at=25 * 60.0 + n * 10)
        led.answer('ra%d' % n, 'Потому что так.', tid='w%d' % n, at=25 * 60.0 + n * 10 + 2)
    for n in range(20):
        led.user_final('u%d' % n, 'вагон %d ушёл в %d часов, %d тонн' % (100 + n, 24, 200 + n), final_rev=1, at=30 * 60.0 + n * 60.0)
    card = V.build_card(led, 'гарантию на сколько месяцев', since=0.0, lines=0)
    assert len(card.part('exact')) <= V.START['exact_lines']
    assert any('24 месяца' in line for line in card.part('exact')), card.part('exact')


# -- е: a redial is the same conversation: the new controller of the session goes on with its ledger --------------------------------------------------------------------

MEMORY = {'conversation_ledger': 'memory', 'topic_recap': 'on'}
COND = 'условие такое скидка пять процентов только если заказ больше трёхсот единиц'


def test_e_the_controller_of_a_redial_keeps_what_was_said_before_the_drop(tmp_path):
    first = ControlledMedia(tmp_path / 's.db', session_id='s', settings=MEMORY)
    first.begin_call()
    first.provider(turn('k1', 'user', COND))
    for n in range(1, 4):
        answered(first, 'u%d' % n, 'Почему вопрос номер %d важен?' % n, 'Потому что ответ номер %d.' % n)
    again = ControlledMedia(tmp_path / 's.db', session_id='s', settings=MEMORY)      # the line dropped, the phone dialled again
    again.begin_call()
    assert again.call_began is None, 'precondition: the same conversation'
    card = V.build_card(again.convo, 'какая скидка по условию', since=again.call_began)
    assert any('пять процентов' in line for part in card.lines.values() for line in part), dict(card.parts)
    assert sum(1 for r in again.convo.records() if r.kind == 'answer' and not r.superseded) == 3


def test_e_a_redial_after_minutes_with_no_answer_goes_on_with_the_memory_of_the_call(tmp_path):
    """The call began an hour after the last one; ten minutes of talk and no answer (no portion spoken lately), the line drops, the phone dials again 20 s later. ``begin_call`` takes it for
    a new call (its rule is the age of the last portion); the memory takes it for what it is: the conversation goes on, the words were said 20 s before."""
    t = [1_794_000_000.0]

    def controller():
        c = ControlledMedia(tmp_path / 's.db', session_id='s', settings=MEMORY, clock=lambda: t[0] - 1_793_000_000.0)
        c.engine.clock = lambda: t[0]
        c.begin_call()
        return c
    first = controller()
    answered(first, 'u0', 'Почему меняются времена года?', 'Наклон земной оси меняет освещение.')
    t[0] += 3600.0
    call = controller()
    assert call.call_began is not None, 'precondition: a new call'
    t[0] += 60.0
    call.provider(turn('k1', 'user', COND))
    t[0] += 600.0
    call.provider(turn('k2', 'user', 'просто разговор о погоде и о вечернем кофе'))
    t[0] += 20.0
    again = controller()
    assert again.call_began is not None and again.call_began > call.call_began, 'precondition: begin_call took the redial for a new call'
    memory = V.Memory({}, again)
    instructions, _ = memory.apply(Fast(), 'какая скидка по условию', 'POLICY', [])
    assert 'пять процентов' in instructions, instructions
    assert 'Наклон земной оси' not in instructions and 'времена года' not in instructions      # the call of an hour before is not this conversation


@pytest.mark.parametrize('silence_s,kept', [(140.0, True), (1800.0, False)])
def test_e_the_conversation_goes_on_over_a_silence_shorter_than_the_gap_only(tmp_path, silence_s, kept):
    """The stand's redial: two minutes of silence before the line drops and 20 s to dial again (kept); the phone's next call half an hour later (a new conversation)."""
    from echo_sync.conversation_ledger import CONVERSATION_GAP_S
    assert 140.0 < CONVERSATION_GAP_S < 1800.0
    t = [1_794_000_000.0]

    def controller():
        c = ControlledMedia(tmp_path / 's.db', session_id='s', settings=MEMORY, clock=lambda: t[0] - 1_793_000_000.0)
        c.engine.clock = lambda: t[0]
        c.begin_call()
        return c
    first = controller()
    answered(first, 'u0', 'Почему меняются времена года?', 'Наклон земной оси меняет освещение.')
    t[0] += 3600.0
    call = controller()
    call.provider(turn('k1', 'user', COND))
    t[0] += silence_s
    again = controller()
    instructions, _ = V.Memory({}, again).apply(Fast(), 'какая скидка по условию', 'POLICY', [])
    assert ('пять процентов' in instructions) == kept, instructions


def test_e_another_state_file_or_session_starts_with_an_empty_ledger(tmp_path):
    first = ControlledMedia(tmp_path / 's.db', session_id='s', settings=MEMORY)
    first.begin_call()
    first.provider(turn('k1', 'user', COND))
    assert len(ControlledMedia(tmp_path / 'other.db', session_id='s', settings=MEMORY).convo) == 0
    assert len(ControlledMedia(tmp_path / 's.db', session_id='t', settings=MEMORY).convo) == 0


# -- д: the journal counts what went out to the model --------------------------------------------------------------------------------------------------------------

class Fast:
    carry = recap = None

    def _played(self):
        return None


class Owner:
    def __init__(self, led):
        self.convo, self.call_began = led, None


def notes_of(mode, n=3):
    led, seen = ConversationLedger(), []
    led.user_final('u0', 'условие такое скидка пять процентов от трёхсот единиц', final_rev=1, at=1.0)
    memory = V.Memory({}, Owner(led), note=lambda ev, **f: seen.append((ev, f)))
    out = [memory.apply(Fast(), 'какая скидка', 'POLICY', []) for _ in range(n)]
    return [f for ev, f in seen if ev == 'memory_card'], out


def test_d_on_counts_the_characters_and_lines_that_went_into_the_request_and_their_sum():
    rows, out = notes_of('on')
    sent = [instructions[len('POLICY'):].lstrip('\n') for instructions, _ in out]
    assert all(s for s in sent)
    assert [r['sent_chars'] for r in rows] == [len(s) for s in sent]
    assert [r['sent_lines'] for r in rows] == [s.count('\n') + 1 for s in sent]
    assert [r['sent_total_chars'] for r in rows] == [sum(len(s) for s in sent[:k + 1]) for k in range(len(sent))]


"""WAVE 2 / Task E, ruling 3 (fix round on d4c15e9): the early (stable-partial) ACK is reconciled with the FINAL of the same turn.

What the independent review found: the stable-partial ACK (ACK_STABLE_SECONDS = 0.15 s) accepts any utterance that merely BEGINS with
the waiting portion, because the provider's partial transcript grows word by word (gaps of 0.14-1.2 s) and a partial equal to the portion is
«stable» for 150 ms before the next word arrives. The turn is then taken, its final is ignored as already seen, and whatever the
listener said in the same breath after the portion is never classified: a follow-up question on the same subject («А Вторая мировая когда
началась?» after the first cue «Вторая мировая») advanced the cursor and played the stale next portion; «<portion> повтори» advanced
instead of repeating; «стоп» and a correction in the same breath were ignored (the base ignored «стоп» too, as an attempt at the portion).

Ruling: keep the 0.15 s early ACK, but when the FINAL of the same turn arrives, classify what comes after the portion (the tail) and, if
it is STOP / QUESTION / CORRECTION / a request to repeat, act on it (stop / new epoch + cancel / replay) instead of dropping the final
as already seen; extra plain words after the portion stay ignored, and the turn never advances a second time.

The helpers are those of tests/test_stable_partial_ack.py: one user turn as the provider streams it, time injected, nothing sleeps.
"""
import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

import helpers_s6_ack as H
from echo_sync.controlled_media import ACK_STABLE_SECONDS
from echo_sync.engine import SILENT, EchoEngine
from echo_sync.settings import resolve
from echo_sync.textutil import norm_words
from echo_sync.user_intents import HESITATION_WORDS, is_confirmation_tag
from test_stable_partial_ack import ANSWER, AT, PORTION, TICK, Speaker, dictation, speaks
from engine_say import engine_reply

PROD_SETTINGS = H.PROD_SETTINGS


def types(actions):
    return [a['type'] for a in actions]


def early_then(tmp_path, tail, *, name='early', comma=False):
    """The listener repeats the waiting portion and, in the same breath, says ``tail``. The early ACK has taken the portion (and the next
    one is spoken) before the tail is heard; then the final of the whole turn arrives. Returns ``(dictation, speaker, spoken by the
    early ACK, actions of the final)``. ``comma``: the final is punctuated the way the recognizer does it, «<portion>, <tail>»."""
    d = dictation(tmp_path / name)
    portion = d.current
    assert portion == PORTION, 'precondition: the portion under test'
    s = Speaker(d).start().words(portion)
    spoken = s.wait(ACK_STABLE_SECONDS + TICK)
    assert spoken == [d.chunks[AT + 1]] and d.index == AT + 1, 'precondition: the early ACK took the portion'
    s.words(tail, step=0.3)
    s.wait(0.8)
    before = len(s.actions)
    s.final(f"{s.sent[:-(len(tail) + 1)].rstrip('.')}, {tail}" if comma else None)
    return d, s, spoken, s.actions[before:]


# ====================================================================================================================
# the four phrases of the ruling
# ====================================================================================================================

def test_a_stop_in_the_same_breath_stops(tmp_path):
    d, s, spoken, actions = early_then(tmp_path, 'стоп')
    assert 'cancel' in types(actions), 'the stop said after the portion was not acted on: ' + str(actions)
    assert d.state.get('paused'), 'the dictation goes on after «стоп»'          # CL2, ruling 1: «стоп» pauses the answer
    # Coordinator ruling (W1F-B, 3 Nov 2026): «стоп» is a PAUSE that keeps the plan, and «text of the same answer that keeps arriving after
    # the pause [is] kept in the plan (never spoken while paused …)»: the paused answer stays bound to its question (until then this test
    # pinned ``question_id is None``: nothing of the cloud joined a paused answer).
    assert d.controller.question_id == 'q1'
    assert speaks(actions) == []


def test_a_follow_up_question_in_the_same_breath_is_a_new_question(tmp_path):
    d, s, spoken, actions = early_then(tmp_path, 'а почему?')
    c = d.controller
    assert 'cancel' in types(actions) and ({'route', 'lookup'} & set(types(actions))), types(actions)
    assert c.question_id == 'u-live', 'the follow-up is the question now'
    assert 'почему' in c.question_text.lower()
    assert speaks(actions) == [], 'the stale next portion was played again instead of taking the question'


def test_a_repeat_request_in_the_same_breath_replays(tmp_path):
    """Task E replayed the portion that waits after the early ACK (the next one, cut and started again). Task E2, ruling 3: the early advance is
    taken back and the portion the listener has just said is replayed, as the base did (see the E2 section below for the rest of the contract)."""
    d, s, spoken, actions = early_then(tmp_path, 'повтори')
    assert speaks(actions) == [d.chunks[AT]], 'the portion the listener has just said is spoken again'
    assert d.index == AT, 'a repeat request never moves the cursor: the early advance is taken back'


def test_a_correction_in_the_same_breath_is_a_new_turn(tmp_path):
    d, s, spoken, actions = early_then(tmp_path, 'нет, не так')
    assert 'cancel' in types(actions) and ({'route', 'lookup'} & set(types(actions))), types(actions)
    assert d.controller.question_id == 'u-live'
    assert speaks(actions) == []


def test_a_hearing_repair_in_the_same_breath_replays_too(tmp_path):
    d, s, spoken, actions = early_then(tmp_path, 'не расслышал')
    assert speaks(actions) == [d.chunks[AT]], 'a request to hear it again is a repeat request'
    assert d.index == AT


# ====================================================================================================================
# what must stay as it was
# ====================================================================================================================

@pytest.mark.parametrize('tail', ['и всё', 'спасибо', 'ну вот', 'да'], ids=['and_that_is_all', 'thanks', 'well_then', 'yes'])
def test_extra_plain_words_after_the_portion_stay_ignored(tmp_path, tail):
    d, s, spoken, actions = early_then(tmp_path, tail)
    assert actions == [] and d.index == AT + 1 and not d.completed


def test_a_final_that_only_repeats_the_portion_does_nothing_more(tmp_path):
    d = dictation(tmp_path / 'plain')
    s = Speaker(d).start().words(d.current)
    s.wait(ACK_STABLE_SECONDS + TICK)
    before = len(s.actions)
    assert s.final() == [] and s.actions[before:] == [] and d.index == AT + 1


def test_a_tail_that_repeats_the_next_portion_does_not_advance_a_second_time(tmp_path):
    """The listener reads on without waiting for the cue: «<portion> <next portion>». G7 (wave 16, «опередил подсказку: следующая порция сразу,
    без двойной порции»): the next portion, said whole and word for word, was said: its cue is cancelled and the one after it comes, once.
    Before G7 the turn was only ever one confirmation and the listener heard the portion he had just read."""
    d = dictation(tmp_path / 'read-on')
    nxt = d.chunks[AT + 1]
    s = Speaker(d).start().words(d.current)
    s.wait(ACK_STABLE_SECONDS + TICK)
    assert d.index == AT + 1
    s.words(nxt, step=0.3)
    s.wait(0.8)
    before = len(s.actions)
    s.final()
    assert types(s.actions[before:]) == ['cancel', 'speak'] and d.index == AT + 2, s.actions[before:]
    assert d.chunks[AT + 2] in json.dumps(s.actions[before:][1], ensure_ascii=False)
    s.final()
    assert d.index == AT + 2, 'the same final twice is one step'


def test_a_tail_that_is_only_the_start_of_the_next_portion_does_not_advance_a_second_time(tmp_path):
    d = dictation(tmp_path / 'read-on-part')
    nxt = d.chunks[AT + 1]
    s = Speaker(d).start().words(d.current)
    s.wait(ACK_STABLE_SECONDS + TICK)
    s.words(' '.join(nxt.split()[:max(1, len(nxt.split()) // 2)]), step=0.3)
    s.wait(0.8)
    before = len(s.actions)
    s.final()
    assert 'cancel' not in types(s.actions[before:]) and d.index == AT + 1


def test_a_tail_is_not_acted_on_after_something_else_has_happened(tmp_path):
    """Between the early confirmation and the final another turn asked a new question: the tail belongs to an answer that is gone."""
    d = dictation(tmp_path / 'stale-epoch')
    s = Speaker(d).start().words(d.current)
    s.wait(ACK_STABLE_SECONDS + TICK)
    assert d.index == AT + 1
    s.words('стоп', step=0.3)
    asked = d.controller.provider(H.done('u-other', 'user', 'Что такое фотосинтез?'))
    assert 'cancel' in types(asked) and d.controller.question_id == 'u-other', 'precondition: a new question took over'
    epoch = d.controller.epoch
    out = d.controller.provider(H.done('u-live', 'user', s.sent))
    assert out == [] and d.controller.epoch == epoch and d.controller.question_id == 'u-other', 'the stale stop ended the new question'


def test_a_final_that_comes_long_after_is_not_acted_on(tmp_path):
    from echo_sync.controlled_media import ACK_JOIN_SECONDS
    d = dictation(tmp_path / 'late-final')
    s = Speaker(d).start().words(d.current)
    s.wait(ACK_STABLE_SECONDS + TICK)
    s.words('стоп', step=0.3)
    d.clock.advance(ACK_JOIN_SECONDS + 1.0)
    before = len(s.actions)
    s.final()
    assert s.actions[before:] == [] and not d.completed


def test_the_tail_is_acted_on_once(tmp_path):
    d, s, spoken, actions = early_then(tmp_path, 'стоп')
    assert 'cancel' in types(actions)
    epoch = d.controller.epoch
    assert s.final() == [] and d.controller.epoch == epoch, 'a retransmitted final stopped it a second time'
    again = d.controller.provider(H.done('u-live', 'user', s.sent + ' ещё раз'))
    assert again == [] and d.controller.epoch == epoch, 'a revised final of the same turn acted again'


def test_a_replay_is_not_repeated_by_a_revised_final_of_the_same_turn(tmp_path):
    """A repeat request leaves the epoch where it is, so only the bookkeeping of the turn can tell that it was already heard."""
    d, s, spoken, actions = early_then(tmp_path, 'повтори')
    assert speaks(actions) == [d.chunks[AT]]
    again = d.controller.provider(H.done('u-live', 'user', s.sent + ' пожалуйста'))
    assert speaks(again) == [], 'the revised final of the same turn asked for the repeat a second time'


def test_a_final_that_no_longer_starts_with_the_portion_is_left_alone(tmp_path):
    """The recognizer revised its first words: where the portion ends is not known, so nothing is guessed."""
    d = dictation(tmp_path / 'revised')
    s = Speaker(d).start().words(d.current)
    s.wait(ACK_STABLE_SECONDS + TICK)
    assert d.index == AT + 1
    out = d.controller.provider(H.done('u-live', 'user', 'при ста градусах Фаренгейта стоп'))
    assert out == [] and not d.completed


def test_without_the_early_ack_nothing_changes(tmp_path):
    """The early ACK switched off: the final is the only event. G3, rule 2 (changed on purpose): the repeat in it is confirmed once, the tail acts alone."""
    d = dictation(tmp_path / 'off')
    d.controller.ack_stable_seconds = 0
    s = Speaker(d).start().words(d.current + ' стоп')
    assert s.wait(2.0) == [] and d.index == AT
    s.final()
    assert d.index == AT + 1 and not d.completed and d.controller.state().get('paused')


def test_the_log_line_carries_no_words(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        d, s, spoken, actions = early_then(tmp_path, 'стоп')
    assert 'early_ack_tail' in caplog.text
    assert 'стоп' not in caplog.text.lower() and 'градусах' not in caplog.text.lower()


# ====================================================================================================================
# the review's repro: a follow-up question that begins with the words of the first cue
# ====================================================================================================================

SECOND_WORLD_WAR = 'Вторая мировая война закончилась второго сентября тысяча девятьсот сорок пятого года.'


@pytest.mark.parametrize('follow_up', [
    'А Вторая мировая когда началась?',
    'Вторая мировая, а где она закончилась?',
    'Вторая мировая... нет, Первая мировая когда закончилась?',
], ids=['and_when_did_it_begin', 'and_where_did_it_end', 'no_the_first_one'])
def test_a_follow_up_question_that_begins_with_the_first_cue_is_a_question(tmp_path, follow_up):
    """followup_swallowed.py / followup2.py: the first cue is the subject of the question («Вторая мировая»), the listener (or anybody)
    asks something else about it, one partial per word 0.4 s apart. The partial «Вторая мировая» is the cue and was stable for 150 ms."""
    d = H.Dictation(tmp_path / 'follow', SECOND_WORLD_WAR, question='Когда закончилась Вторая мировая война?')
    c = d.controller
    first = d.current
    assert first.lower().startswith('вторая мировая'), f'precondition: the first cue is the subject: {first!r}'
    old_question = c.question_id
    d.clock.advance(4.0)
    s = Speaker(d, 'u-follow').start()
    for word in follow_up.split():
        s.words(word, step=0.0)
        s.wait(0.4)                                           # one partial per word, 0.4 s apart, the controller ticking all the time
    s.wait(1.0)
    before = len(s.actions)
    s.final()
    acted = s.actions[before:]
    assert c.question_id == 'u-follow' != old_question, 'the follow-up was swallowed by the stable partial: ' + str(types(s.actions))
    assert 'cancel' in types(acted), types(acted)
    assert 'вторая мировая' in c.question_text.lower(), 'the question lost the words of the portion (Task E2, ruling 2): ' + repr(c.question_text)


# ====================================================================================================================
# the last portion, and the transport
# ====================================================================================================================

def test_a_stop_after_the_last_portion_is_heard_too(tmp_path):
    d = H.Dictation(tmp_path / 'last', 'Вода кипит при ста градусах Цельсия.')
    while d.index < len(d.chunks) - 1:                          # repeat every portion but the last whole
        before = d.index
        assert d.say(d.current, gap=4.0).after == before + 1
    last = d.current
    assert d.index == len(d.chunks) - 1 and not d.completed, 'precondition: the last portion waits'
    d.clock.advance(4.0)
    s = Speaker(d).start().words(last)
    s.wait(ACK_STABLE_SECONDS + TICK)
    assert d.completed, 'precondition: the early ACK took the last portion'
    s.words('стоп', step=0.3)
    s.wait(0.8)
    before = len(s.actions)
    s.final()
    assert 'cancel' in types(s.actions[before:]) and d.controller.question_id is None


def test_through_the_transport_a_tail_stop_cuts_the_cue_that_the_early_ack_started(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'wire-tail', pcm_ms=3000)
        try:
            await wire.begin(ANSWER)
            for n in range(AT):
                await wire.user(wire.chunks[n], tid=f'cue-{n}')
            first = wire.chunks[AT]
            wire.skew += 4.0
            await wire.socket.provider(H.created('u2', 'user', ''))
            sent = ''
            for word in first.split():
                piece = ('' if not sent else ' ') + word
                sent += piece
                await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': piece,
                                            'start_ms': len(sent) * 10, 'end_ms': len(sent) * 10 + 5})
            await wire.elapse(ACK_STABLE_SECONDS + 0.1)           # the early ACK: the next portion is synthesized and playing
            assert wire.index == AT + 1 and wire.synthesized[-1] == wire.chunks[AT + 1]
            cleared = wire.cleared()
            await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': ' стоп',
                                        'start_ms': 900, 'end_ms': 905})
            await wire.socket.provider(H.done('u2', 'user', first + ' стоп'))
            await wire.settle()
            return wire.cleared() - cleared, wire.controller.state().get('paused')     # CL2, ruling 1: «стоп» pauses
        finally:
            await wire.close()
    cleared, paused = asyncio.run(run())
    assert cleared >= 1 and paused, 'the stop said after the portion left the stale cue playing'


# ====================================================================================================================
# WAVE 2 / Task E2, ruling 1 (second fix round, scoped re-review P2): a one-word confirmation tag is no question
# ====================================================================================================================
# The stable partial takes the portion; the tail «да?» was then classified ALONE against the next portion, where it is a QUESTION: the
# dictation was cancelled and the cloud, which heard the whole utterance and answers it («Да.»), either had nothing to dictate («Нет ответа»)
# or its reply («Да, верно.») became the new dictation. The base ignored these tails (an attempt at the portion), the candidate before it
# advanced. A tag that is ONE word (optionally after а / и) is treated like the plain-word tails: ignored, the plan goes on.

TAGS = ['да', 'правильно', 'верно', 'понял', 'точно', 'ага', 'угу', 'так', 'нормально', 'всё', 'дальше', 'следующее']
TAGGED = ([(tag, '', False) for tag in TAGS] + [(tag, '', True) for tag in TAGS]
          + [(tag, lead, True) for tag in ('дальше', 'всё', 'правильно', 'да') for lead in ('а ', 'и ')])
PLAN = ['Вода закипает в обычной кастрюле на плите,', PORTION, 'При ста градусах вода кипит.', 'В горах она закипает раньше.']   # F1


TAG_IDS = {'да': 'yes', 'правильно': 'right', 'верно': 'correct', 'понял': 'understood', 'точно': 'exactly', 'ага': 'aha', 'угу': 'uhuh',
           'так': 'so', 'нормально': 'fine', 'всё': 'all', 'дальше': 'next', 'следующее': 'following'}
LEAD_IDS = {'': '', 'а ': 'and_a_', 'и ': 'and_i_'}


@pytest.mark.parametrize('tag,lead,comma', TAGGED, ids=[f"{LEAD_IDS[lead]}{TAG_IDS[tag]}{'_comma' if comma else ''}" for tag, lead, comma in TAGGED])
def test_a_one_word_confirmation_tag_in_the_same_breath_does_not_end_the_dictation(tmp_path, tag, lead, comma):
    d, s, spoken, actions = early_then(tmp_path, f'{lead}{tag}?', comma=comma)
    assert actions == [], f'the tag «{lead}{tag}?» was acted on: {actions}'
    assert d.index == AT + 1 and not d.completed, 'the dictation stopped or moved'
    assert d.controller.question_id == 'q1', 'the tag became the question'
    assert d.chunks == PLAN, 'the plan was replaced'


@pytest.mark.parametrize('tag', ['да?', 'правильно?', 'верно?'], ids=['yes', 'right', 'correct'])
def test_the_dictation_goes_on_after_a_tag(tmp_path, tag):
    d, s, spoken, actions = early_then(tmp_path, tag)
    out = d.say(d.chunks[AT + 1], gap=2.0)
    assert out.after == AT + 2 and out.speaks == [d.chunks[AT + 2]], 'the next repeat was not taken after the tag'


@pytest.mark.parametrize('tail', ['почему?', 'да? а почему так?', 'да, а откуда это известно?', 'правильно ли это?'],
                         ids=['one_question_word', 'tag_then_question', 'tag_then_longer_question', 'li_question'])
def test_a_real_question_after_the_portion_is_still_a_question(tmp_path, tail):
    """The tag is a closed list of ONE word: a question word, or more than one word, is the question it always was."""
    d, s, spoken, actions = early_then(tmp_path, tail)
    assert 'cancel' in types(actions) and d.controller.question_id == 'u-live', types(actions)


# -- the vocabulary itself ---------------------------------------------------------------------------------------------

FILLERS = frozenset(resolve({})['fillers']) | HESITATION_WORDS


@pytest.mark.parametrize('said', ['да', 'Да?', 'правильно', 'Верно?', 'точно', 'понял?', 'ага', 'угу', 'так', 'нормально?', 'всё?', 'Всё', 'дальше?',
                                  'следующее?', 'а дальше?', 'и всё?', 'а да?', 'ну правильно?', 'э верно?', 'так правильно?'])
def test_the_closed_list_of_one_word_confirmation_tags(said):
    assert is_confirmation_tag(norm_words(said), FILLERS), said


@pytest.mark.parametrize('said', ['', 'почему?', 'да ведь?', 'это всё?', 'я правильно сказал?', 'и что?', 'а потом?', 'да правильно', 'да да',
                                  'а', 'ну', 'так ведь?', 'или нет?', 'что?', 'повтори', 'стоп', 'нет'])
def test_anything_else_is_not_a_tag(said):
    assert not is_confirmation_tag(norm_words(said), FILLERS), said


def test_through_the_transport_a_tag_question_leaves_the_plan_and_the_cloud_s_answer_to_it_is_not_dictated(tmp_path):
    """rr2_tagq_wire.py: «<portion>, да?» + the cloud's «Да.» / «Да, верно.»: before, the phone heard «Нет ответа. Повторите вопрос.» or the
    reply four times in place of the plan."""
    async def run(tag, reply):
        wire = H.Wire(tmp_path / f'wire-{TAG_IDS[tag.rstrip("?")]}', pcm_ms=200)
        try:
            await wire.begin(ANSWER)
            for n in range(AT):
                await wire.user(wire.chunks[n], tid=f'cue-{n}')
            await wire.elapse(2.0)
            plan = list(wire.chunks)
            wire.skew += 4.0
            await wire.socket.provider(H.created('u2', 'user', ''))
            sent = ''
            for word in plan[AT].split():
                piece = ('' if not sent else ' ') + word
                sent += piece
                await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': piece,
                                            'start_ms': len(sent) * 10, 'end_ms': len(sent) * 10 + 5})
                await wire.elapse(0.1)
            await wire.elapse(0.2)                                     # a short pause after the portion (the comma): the early ACK
            assert wire.index == AT + 1 and wire.synthesized[-1] == plan[AT + 1], 'precondition: the early ACK took the portion'
            await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': ', ' + tag, 'start_ms': 900, 'end_ms': 905})
            await wire.elapse(0.6)
            await wire.socket.provider(H.done('u2', 'user', sent + ', ' + tag))
            await wire.settle()
            await wire.socket.provider(H.created('a2', 'assistant', reply.split()[0]))
            await wire.socket.provider(H.done('a2', 'assistant', reply))
            await wire.settle()
            for _ in range(10):                                        # longer than the cloud's wait for a cue (8 s)
                await wire.elapse(1.0)
            errors = [f['error']['code'] for f in wire.sent if f.get('type') == 'error']
            heard = [f['delta'] for f in wire.sent if f.get('type') == 'response.audio_transcript.delta']
            state = wire.controller.state()
            await wire.user(plan[AT + 1], tid='u3')                    # …and the listener goes on with the next portion
            return plan, errors, heard, state, wire.index
        finally:
            await wire.close()
    for tag, reply in (('да?', 'Да.'), ('правильно?', 'Да, верно.')):
        plan, errors, heard, state, index_after = asyncio.run(run(tag, reply))
        assert errors == [], f'«{tag}»: the phone was told about an error: {errors}'
        assert set(heard) <= set(plan), f'«{tag}»: the phone heard something that is not the plan: {[h for h in heard if h not in plan]}'
        assert state['chunks'] == plan and state['chunk_index'] == AT + 1 and not state['completed'], f'«{tag}»: the plan was replaced'
        assert index_after == AT + 2, f'«{tag}»: the dictation did not go on'


# ====================================================================================================================
# WAVE 2 / Task E2, ruling 2 (scoped re-review P2): a question said after an early-accepted portion keeps the portion's words
# ====================================================================================================================
# The partial «И ставка Центробанка» is the whole portion and stable for 150 ms, so the stable partial takes it; the FINAL then says
# «…, а какая она сейчас?». The tail was handed to ``_accept_user`` ALONE: the question text, the lookup query, the lookup topic, the route
# (``needs_verification``) and the history were all made of «какая она сейчас?», without the subject. The kind (stop / question / correction /
# repeat) is still decided by the tail; what was ASKED is the whole utterance, its leading fillers aside.

RATE_QUESTION = 'Что влияет на курс рубля?'
# F1: a clause before «и ставка Центробанка.» keeps that very portion (the old answer is one meaning portion now)
RATE_ANSWER = 'На курс рубля влияют мировые цены на нефть, и ставка Центробанка.'


def rate_dictation(tmp_path, name='rate'):
    """The portion «и ставка Центробанка.» waits (every portion before it was repeated whole); the listener has had time to react."""
    d = H.Dictation(tmp_path / name, RATE_ANSWER, question=RATE_QUESTION)
    while 'Центробанка' not in d.current:
        before = d.index
        assert d.say(d.current, gap=4.0).after == before + 1
    assert d.current == 'и ставка Центробанка.', f'precondition: the portion under test: {d.current!r}'
    d.clock.advance(4.0)
    return d


def asked_in_the_same_breath(d, text, tid='u-follow'):
    """The listener's utterance word by word (one partial per word, 0.4 s apart, the controller ticking all the time), then its final.
    Returns ``(speaker, the actions of the final)``."""
    s = Speaker(d, tid).start()
    for word in text.split():
        s.words(word, step=0.0)
        s.wait(0.4)
    s.wait(1.0)
    before = len(s.actions)
    s.final()
    return s, s.actions[before:]


def the_cloud_answers(d, s, answer, tid='a-follow'):
    """The cloud answers the utterance it heard; time goes on for 4.5 s (a question that ends in a function word, «…нет, не так», is held for
    3.2 s in case it goes on). Returns what the controller spoke."""
    out = d.controller.provider(H.created(tid, 'assistant', answer.split()[0]))
    out += d.controller.provider(H.done(tid, 'assistant', answer))
    s.actions += out
    return speaks(out) + s.wait(4.5)


def test_the_lookup_query_of_a_current_rate_question_keeps_the_subject(tmp_path):
    """rr2_followup_text.py case D: bf76690 gave the public search the query «какая она сейчас?» (the base: «ставка Центробанка, а какая она сейчас?»)."""
    d = rate_dictation(tmp_path)
    s, acted = asked_in_the_same_breath(d, 'И ставка Центробанка, а какая она сейчас?')
    c = d.controller
    lookups = [a for a in s.actions if a['type'] == 'lookup']
    assert len(lookups) == 1 and c.question_id == 'u-follow', types(s.actions)
    assert 'ставка Центробанка' in lookups[0]['lookup_question'], lookups[0]
    assert 'ставка Центробанка' in lookups[0]['question'] and 'ставка Центробанка' in c.question_text
    assert c.lookup_topic.startswith('ставка Центробанка'), 'the topic the next «а почему?» inherits lost its subject'
    assert lookups[0]['lookup_question'].lower().startswith('ставка'), 'the leading «И» of the utterance is a filler, not part of the query'


def test_a_current_rate_question_goes_to_the_lookup_route_because_of_its_subject(tmp_path):
    """rr2_followup_text.py case C: «И ставка Центробанка, какая она?» needs verification as a whole («какая» + «ставка»), the tail alone does not."""
    d = rate_dictation(tmp_path)
    s, acted = asked_in_the_same_breath(d, 'И ставка Центробанка, какая она?')
    c = d.controller
    assert c.question_id == 'u-follow' and c.direct_content is False, 'the route was decided on «какая она?» and went to the model alone'
    assert 'lookup' in types(s.actions) and 'route' not in types(s.actions), types(s.actions)
    assert 'ставка Центробанка' in c.question_text


@pytest.mark.parametrize('follow_up,kept', [
    ('А Вторая мировая когда началась?', 'вторая мировая когда началась'),
    ('Вторая мировая, а где она закончилась?', 'вторая мировая, а где она закончилась'),
    ('Вторая мировая... нет, Первая мировая когда закончилась?', 'вторая мировая... нет, первая мировая когда закончилась'),
], ids=['and_when_did_it_begin', 'and_where_did_it_end', 'no_the_first_one'])
def test_the_question_text_is_the_whole_utterance_without_its_leading_filler(tmp_path, follow_up, kept):
    d = H.Dictation(tmp_path / 'follow-text', SECOND_WORLD_WAR, question='Когда закончилась Вторая мировая война?')
    d.clock.advance(4.0)
    s, acted = asked_in_the_same_breath(d, follow_up)
    assert d.controller.question_id == 'u-follow'
    assert d.controller.question_text.lower().startswith(kept), d.controller.question_text


def test_the_answer_to_the_follow_up_is_dictated_and_the_history_keeps_the_whole_question(tmp_path):
    """End to end: the engine re-classifies the question text when the cloud's answer arrives, so the text must still be one it takes as a
    question; the history (what «а почему?» later inherits) holds what was asked."""
    d = H.Dictation(tmp_path / 'follow-history', SECOND_WORLD_WAR, question='Когда закончилась Вторая мировая война?')
    d.clock.advance(4.0)
    s, acted = asked_in_the_same_breath(d, 'А Вторая мировая когда началась?')
    spoken = the_cloud_answers(d, s, 'Вторая мировая война началась первого сентября тысяча девятьсот тридцать девятого года.')
    assert spoken, 'the answer to the follow-up was never dictated'
    assert 'вторая мировая когда началась' in d.state['history'][-1]['question'].lower(), d.state['history']


@pytest.mark.parametrize('tail', ['нет, не так', 'это неверно'], ids=['no_not_so', 'this_is_wrong'])
def test_a_correction_keeps_the_words_of_the_portion_and_its_answer_is_dictated(tmp_path, tail):
    """A correction opens an utterance («нет, не так», «это неверно»); after the portion's words the engine would not take the whole as one. The
    controller decides the kind from the tail, and the engine is told the same: the answer must still be dictated."""
    d = rate_dictation(tmp_path, 'correction')
    s, acted = asked_in_the_same_breath(d, f'И ставка Центробанка, {tail}')
    c = d.controller
    assert c.question_id == 'u-follow' and 'cancel' in types(acted), types(acted)
    assert c.question_text.lower().startswith('ставка центробанка'), c.question_text
    spoken = the_cloud_answers(d, s, 'Ставка Центробанка зависит от инфляции и решений совета директоров.')
    assert spoken, 'the answer to the correction was never dictated'
    assert d.state['history'][-1]['question'].lower().startswith('ставка центробанка'), d.state['history']


def test_a_question_without_a_question_mark_keeps_the_portion_and_is_still_answered(tmp_path):
    """No «?» and the question word comes after the portion's words: the controller sees a question in the tail («когда это происходит»), the
    engine, given the whole, would see none (it looks for a question word among the first three). The answer must still be dictated."""
    d = H.Dictation(tmp_path / 'no-mark', SECOND_WORLD_WAR, question='Когда закончилась Вторая мировая война?')
    d.clock.advance(4.0)
    s, acted = asked_in_the_same_breath(d, 'Вторая мировая когда это началось')
    c = d.controller
    assert c.question_id == 'u-follow' and 'cancel' in types(acted), types(acted)
    assert c.question_text.lower().startswith('вторая мировая когда это началось'), c.question_text
    assert the_cloud_answers(d, s, 'Вторая мировая война началась первого сентября тысяча девятьсот тридцать девятого года.'), 'never dictated'


def test_a_context_follow_up_after_the_portion_keeps_its_route_and_its_topic(tmp_path):
    """«<portion>, а почему?»: the tail is a pure follow-up of the previous exchange. The kind and the topic work as before (the topic stays the
    original question, the query carries it), the route inherits the lookup of a source-backed exchange, and the portion's words are added."""
    d = H.Dictation(tmp_path / 'context', ANSWER, question='Что такое температура кипения воды?')
    with d.controller.engine._db() as db:                      # the exchange before was a lookup one (its sources were delivered)
        row = db.execute('SELECT state FROM sessions WHERE session_id=?', (H.SESSION,)).fetchone()
        stored = json.loads(row[0])
        stored['history'][-1]['retrieval_status'] = 'source_backed'
        db.execute('UPDATE sessions SET state=? WHERE session_id=?', (json.dumps(stored, ensure_ascii=False), H.SESSION))
    assert d.say(d.current, gap=4.0).after == AT
    d.clock.advance(4.0)
    topic = d.controller.lookup_topic
    s = Speaker(d).start().words(d.current)
    assert s.wait(ACK_STABLE_SECONDS + TICK) == [d.chunks[AT + 1]]
    s.words('а почему?', step=0.3)
    s.wait(0.8)
    before = len(s.actions)
    s.final()
    lookups = [a for a in s.actions[before:] if a['type'] == 'lookup']
    assert len(lookups) == 1 and d.controller.direct_content is False, 'the lookup of the exchange before was not inherited'
    assert lookups[0]['lookup_question'].startswith('при ста градусах Цельсия. а почему?'), lookups[0]
    assert lookups[0]['lookup_question'].endswith('К вопросу: ' + topic) and d.controller.lookup_topic == topic, (lookups[0], topic)


def test_the_engine_records_the_whole_utterance_for_a_question_it_classified_in_part(tmp_path):
    engine = EchoEngine(tmp_path / 'asked.sqlite3', lambda *args: 'Ответ на вопрос.', settings=PROD_SETTINGS)
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое кипение?', request={}, model='m')
    engine_reply(engine, session_id='s', turn_id='stop', text='стоп', request={}, model='m')
    engine_reply(engine, session_id='s', turn_id='tail', text='а почему?', request={}, model='m', asked='вода кипит при ста градусах, а почему?')
    state = engine.state('s')
    assert state['question'] == 'вода кипит при ста градусах, а почему?'
    assert state['history'][-1]['question'] == 'вода кипит при ста градусах, а почему?'


def test_the_whole_utterance_is_recorded_only_for_a_question_or_a_correction(tmp_path):
    engine = EchoEngine(tmp_path / 'asked-only.sqlite3', lambda *args: 'Ответ на вопрос.', settings=PROD_SETTINGS)
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое кипение?', request={}, model='m')
    before = engine.state('s')
    engine_reply(engine, session_id='s', turn_id='again', text='повтори', request={}, model='m', asked='вода кипит, повтори')
    assert engine.state('s')['question'] == before['question'] == 'Что такое кипение?'
    assert engine.state('s')['history'] == before['history']


def test_a_prepared_question_keeps_what_the_bank_matched(tmp_path):
    """A question of the prepared bank is answered from it; the utterance that was given alongside is not what the bank matched."""
    engine = EchoEngine(tmp_path / 'asked-bank.sqlite3', lambda *args: 'не должно вызываться', settings=PROD_SETTINGS,
                        qa=[{'question': 'Что такое кипение', 'answer': 'Кипение — это переход жидкости в пар.'}])
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое кипение', request={}, model='m', asked='при ста градусах, что такое кипение')
    state = engine.state('s')
    assert state['question'] == 'Что такое кипение' and state['answer'] == 'Кипение — это переход жидкости в пар.', state


# ====================================================================================================================
# WAVE 2 / Task E2, ruling 3 (scoped re-review P3): «<portion> повтори» takes the early advance back
# ====================================================================================================================
# Task E replayed, for a repeat request or a hearing repair said after the portion, the portion that waits AFTER the early ACK: the next one,
# which the early ACK had already started, so that cue was cut and started again and the listener never heard the portion they asked about.
# The base replayed the portion just said and left the cursor alone. Ruling: undo the early advance (``EchoEngine.rewind``) and replay that
# portion; never cut and restart the next one.

REPEATS = ['повтори', 'повторите пожалуйста', 'ещё раз', 'не расслышал', 'не понял', 'что?']


@pytest.mark.parametrize('tail', REPEATS, ids=['repeat', 'repeat_please', 'once_more', 'did_not_hear', 'did_not_understand', 'what'])
def test_a_repeat_request_after_the_portion_takes_the_early_advance_back_and_replays_the_portion(tmp_path, tail):
    d, s, spoken, actions = early_then(tmp_path, tail)
    assert speaks(actions) == [d.chunks[AT]], f'«{tail}»: the portion just said was not replayed: {actions}'
    assert d.index == AT and not d.completed, f'«{tail}»: the early advance was not taken back'
    cue = [a for a in actions if a['type'] == 'speak'][0]
    assert d.controller.authorized(cue), 'the replayed cue is not the one the cursor waits for'
    assert d.controller.question_id == 'q1' and 'cancel' not in types(actions), 'a repeat request is no new question'


def test_the_replayed_portion_is_confirmed_by_the_next_repeat_like_any_other(tmp_path):
    d, s, spoken, actions = early_then(tmp_path, 'повтори')
    out = d.say(d.chunks[AT], gap=2.0)
    assert out.after == AT + 1 and out.speaks == [d.chunks[AT + 1]], 'the replayed portion could not be confirmed again'


def test_the_cue_the_early_ack_started_is_no_longer_the_one_the_cursor_waits_for(tmp_path):
    """The transport cuts what it plays when the replay arrives, and a cue that is still being paced out is dropped by ``authorized``."""
    d = dictation(tmp_path / 'stale-cue')
    s = Speaker(d).start().words(d.current)
    s.wait(ACK_STABLE_SECONDS + TICK)
    next_cue = [a for a in s.actions if a['type'] == 'speak'][-1]
    assert d.controller.authorized(next_cue) and d.index == AT + 1, 'precondition: the next portion was issued by the early ACK'
    s.words('повтори', step=0.3)
    s.wait(0.8)
    s.final()
    assert not d.controller.authorized(next_cue), "the next portion's cue is still valid after the advance was taken back"


@pytest.mark.parametrize('tail', ['повтори', 'не расслышал', 'что?'], ids=['repeat', 'did_not_hear', 'what'])
def test_a_repeat_request_after_the_last_portion_replays_the_last_portion(tmp_path, tail):
    """The early ACK of the last portion completes the dictation (nothing is spoken). «повтори» then used to find nothing to repeat, and «что?», with
    nothing waiting, was a new question; the base replayed the last portion."""
    d = H.Dictation(tmp_path / 'last-repeat', 'Вода кипит при ста градусах Цельсия.')
    while d.index < len(d.chunks) - 1:
        before = d.index
        assert d.say(d.current, gap=4.0).after == before + 1
    last = d.current
    d.clock.advance(4.0)
    s = Speaker(d).start().words(last)
    s.wait(ACK_STABLE_SECONDS + TICK)
    assert d.completed, 'precondition: the early ACK took the last portion'
    s.words(tail, step=0.3)
    s.wait(0.8)
    before = len(s.actions)
    s.final()
    acted = s.actions[before:]
    assert speaks(acted) == [last], f'«{tail}»: {acted}'
    assert not d.completed and d.current == last and d.controller.question_id == 'q1', 'the last portion was not waiting again'


def test_a_repeat_request_for_a_position_that_has_been_left_is_ignored(tmp_path):
    """Between the early ACK and the final another turn confirmed the next portion: the request belongs to a position that is gone."""
    d = dictation(tmp_path / 'moved-on')
    s = Speaker(d).start().words(d.current)
    s.wait(ACK_STABLE_SECONDS + TICK)
    assert d.index == AT + 1
    assert d.say(d.chunks[AT + 1], gap=1.0).after == AT + 2, 'precondition: another turn confirmed the next portion'
    s.words('повтори', step=0.3)
    before = len(s.actions)
    s.final()
    assert s.actions[before:] == [] and d.index == AT + 2, 'the stale request moved the cursor or replayed a portion'


def test_the_log_line_of_a_repeat_tail_carries_no_words(tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        early_then(tmp_path, 'повтори')
    assert 'early_ack_tail' in caplog.text and 'повтори' not in caplog.text.lower()


def test_through_the_transport_a_repeat_tail_replays_the_portion_just_said_and_does_not_restart_the_next(tmp_path):
    async def run():
        wire = H.Wire(tmp_path / 'wire-repeat', pcm_ms=1500)
        try:
            await wire.begin(ANSWER)
            for n in range(AT):
                await wire.user(wire.chunks[n], tid=f'cue-{n}')
            plan = list(wire.chunks)
            wire.skew += 4.0
            await wire.socket.provider(H.created('u2', 'user', ''))
            sent = ''
            for word in plan[AT].split():
                piece = ('' if not sent else ' ') + word
                sent += piece
                await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': piece,
                                            'start_ms': len(sent) * 10, 'end_ms': len(sent) * 10 + 5})
            wire.skew += ACK_STABLE_SECONDS + 0.1
            await wire.socket.tick()                              # the early ACK: the next portion is synthesized and begins to play…
            await asyncio.sleep(0.2)
            assert wire.index == AT + 1 and wire.synthesized[-1] == plan[AT + 1], 'precondition: the early ACK started the next portion'
            assert wire.socket.audio is not None and not wire.socket.audio.done(), 'precondition: …and is still playing (1.5 s of audio)'
            synthesized, cleared = len(wire.synthesized), wire.cleared()
            await wire.socket.provider({'type': 'turn.delta', 'turn_id': 'u2', 'delta': ' повтори', 'start_ms': 900, 'end_ms': 905})
            await wire.socket.provider(H.done('u2', 'user', sent + ' повтори'))
            await wire.settle()
            heard = [f['delta'] for f in wire.sent if f.get('type') == 'response.audio_transcript.delta']
            return plan, wire.synthesized[synthesized:], wire.cleared() - cleared, wire.index, heard
        finally:
            await wire.close()
    plan, synthesized_after, cleared, index, heard = asyncio.run(run())
    assert synthesized_after == [plan[AT]], f'what was synthesized after the repeat request: {synthesized_after}'
    assert cleared >= 1, 'the cue of the next portion was not cut off on the phone'
    assert index == AT, 'the cursor stayed one portion ahead'
    assert heard[-1] == plan[AT] and heard.count(plan[AT + 1]) == 1, f'the next portion was started again, or the portion just said was not the last thing heard: {heard}'


# F1 (wave F): the first cue of a stream is a meaning portion - the clause ends at its comma (WAVE 2 / L2 cued «свойство тела»)
# c23-final(B): c22-merge (G15, cloud_context/reports/c22-merge.md п.1/3, intended) holds a first cue that ends on a comma while the next clause may still fit its 9 words:
# «свойство тела сохранять своё состояние покоя,» (6 words) is no cue any more, the stream waits. The frontier under test is the same with a closed sentence.
FRONTIER_DELTA = 'тела сохранять своё состояние покоя.'
FRONTIER_CUE = 'свойство тела сохранять своё состояние покоя.'


def test_at_the_frontier_of_a_stream_a_repeat_tail_takes_the_wait_back_and_replays_the_cue(tmp_path):
    """The answer is still streaming and the first cue is all there is: the early ACK parks the frontier (``stream_waiting_next``) and moves no
    cursor. «<cue> повтори» clears the wait and replays the cue; the cursor was never ahead."""
    clock = H.FakeClock()
    c = H.ControlledMedia(tmp_path / 'frontier.sqlite3', session_id='frontier', clock=clock, **H.HOST_KWARGS)
    c.provider(H.created('u1', 'user', 'Что'))
    clock.advance(0.5)
    c.provider(H.done('u1', 'user', 'Что такое инерция?'))
    c.provider(H.created('a1', 'assistant', 'Инерция — это свойство '))
    cue = [a for a in c.provider({'type': 'turn.delta', 'turn_id': 'a1', 'delta': FRONTIER_DELTA,
                                  'start_ms': 40, 'end_ms': 79}) if a['type'] == 'speak'][0]
    assert cue['text'] == FRONTIER_CUE and c.state()['streaming'], 'precondition: a streaming answer with one cue'
    clock.advance(0.6)
    c.playback_done(cue, now=clock())
    clock.advance(4.0)
    rig = SimpleNamespace(controller=c, clock=clock)
    s = Speaker(rig).start().words(FRONTIER_CUE.rstrip(',.'))
    assert s.wait(ACK_STABLE_SECONDS + TICK) == [], 'the frontier has no next portion to speak yet'
    assert c.state()['stream_waiting_next'] and c.state()['chunk_index'] == 0, 'precondition: the early ACK parked the frontier'
    s.words('повтори', step=0.3)
    s.wait(0.8)
    before = len(s.actions)
    s.final()
    acted = s.actions[before:]
    assert speaks(acted) == [FRONTIER_CUE], acted
    assert not c.state()['stream_waiting_next'] and c.state()['chunk_index'] == 0 and c.authorized([a for a in acted if a['type'] == 'speak'][0])


# -- EchoEngine.rewind: the step one acknowledgement made, taken back ------------------------------------------------------------------

def engine_with_plan(tmp_path, name='rewind'):
    engine = EchoEngine(tmp_path / f'{name}.sqlite3', lambda *args: 'Один два три. Четыре пять шесть. Семь восемь девять.',
                        settings={'words_per_portion': 3, 'on_mismatch': 'silent'})
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое счёт?', request={}, model='m')
    return engine


def ack(engine, tid):
    state = engine.state('s')
    return engine_reply(engine, session_id='s', turn_id=tid, text=state['chunks'][state['chunk_index']], request={}, model='m')


def test_rewind_takes_back_one_acknowledgement(tmp_path):
    engine = engine_with_plan(tmp_path)
    before = engine.state('s')
    ack(engine, 'a1')
    assert engine.state('s')['chunk_index'] == 1
    assert engine.rewind(session_id='s', revision=before['revision'], index=0) is True
    after = engine.state('s')
    assert (after['chunk_index'], after['completed']) == (0, False)
    assert engine_reply(engine, session_id='s', turn_id='r', text='повтори', request={}, model='m') == before['chunks'][0], 'and the repeat is the first portion'


def test_rewind_takes_back_the_acknowledgement_that_completed_the_dictation(tmp_path):
    engine = engine_with_plan(tmp_path)
    revision = engine.state('s')['revision']
    for n in range(len(engine.state('s')['chunks'])):
        ack(engine, f'a{n}')
    assert engine.state('s')['completed']
    last = len(engine.state('s')['chunks']) - 1
    assert engine.rewind(session_id='s', revision=revision, index=last) is True
    state = engine.state('s')
    assert (state['chunk_index'], state['completed']) == (last, False)


def test_rewind_takes_back_the_wait_at_the_frontier_of_a_stream(tmp_path):
    from echo_sync.generator import StreamingAnswer
    prefix = 'Первый второй третий'
    engine = EchoEngine(tmp_path / 'frontier.sqlite3', lambda *args: StreamingAnswer(prefix),
                        settings={'words_per_portion': 3, 'on_mismatch': 'silent'})
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое инерция?', request={}, model='m')
    revision = engine.state('s')['revision']
    assert engine_reply(engine, session_id='s', turn_id='ack', text=prefix, request={}, model='m') == SILENT
    assert engine.state('s')['stream_waiting_next']
    assert engine.rewind(session_id='s', revision=revision, index=0) is True
    state = engine.state('s')
    assert (state['chunk_index'], state['completed'], state['stream_waiting_next']) == (0, False, False)
    assert engine_reply(engine, session_id='s', turn_id='r', text='повтори', request={}, model='m') == prefix


def test_rewind_leaves_a_frontier_that_already_waited_before_the_acknowledgement(tmp_path):
    from echo_sync.generator import StreamingAnswer
    prefix = 'Первый второй третий'
    engine = EchoEngine(tmp_path / 'frontier2.sqlite3', lambda *args: StreamingAnswer(prefix),
                        settings={'words_per_portion': 3, 'on_mismatch': 'silent'})
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое инерция?', request={}, model='m')
    revision = engine.state('s')['revision']
    engine_reply(engine, session_id='s', turn_id='ack1', text=prefix, request={}, model='m')
    engine_reply(engine, session_id='s', turn_id='ack2', text=prefix, request={}, model='m')           # consumed already: this one changed nothing
    assert engine.rewind(session_id='s', revision=revision, index=0, waiting=True) is True
    assert engine.state('s')['stream_waiting_next'] and engine.state('s')['chunk_index'] == 0


def test_rewind_does_nothing_when_the_acknowledgement_changed_nothing(tmp_path):
    engine = engine_with_plan(tmp_path)
    state = engine.state('s')
    assert engine.rewind(session_id='s', revision=state['revision'], index=0) is True
    assert engine.state('s') == state


def test_rewind_refuses_when_the_cursor_has_gone_on_since(tmp_path):
    engine = engine_with_plan(tmp_path, 'moved-on')
    revision = engine.state('s')['revision']
    ack(engine, 'a1')
    ack(engine, 'a2')                                                       # two steps on: the first one is not the last thing that happened
    before = engine.state('s')
    assert engine.rewind(session_id='s', revision=revision, index=0) is False
    assert engine.state('s') == before


def test_rewind_refuses_another_revision_an_unknown_session_and_a_portion_that_is_not_there(tmp_path):
    engine = engine_with_plan(tmp_path, 'refused')
    revision = engine.state('s')['revision']
    ack(engine, 'a1')
    before = engine.state('s')
    assert engine.rewind(session_id='s', revision=revision + 1, index=0) is False
    assert engine.rewind(session_id='nobody', revision=revision, index=0) is False
    assert engine.rewind(session_id='s', revision=revision, index=99) is False
    assert engine.rewind(session_id='s', revision=revision, index='0') is False
    assert engine.state('s') == before


def test_rewind_refuses_while_a_question_is_pending(tmp_path):
    seen = []

    def generate(*args):
        state = engine.state('s')
        seen.append(engine.rewind(session_id='s', revision=state['revision'], index=0))
        return 'Один два три.'
    engine = EchoEngine(tmp_path / 'pending.sqlite3', generate, settings={'words_per_portion': 3, 'on_mismatch': 'silent'})
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое счёт?', request={}, model='m')
    assert seen == [False], 'a state with a question in flight was rewound'


# -- found by the mutation check of ruling 3 -------------------------------------------------------------------------------------------------

def test_a_repeat_tail_leaves_a_frontier_that_was_already_waiting_before_the_early_ack(tmp_path):
    """The listener has already repeated the only portion there is, so the frontier waits for text. They say it AGAIN with «повтори»: the early
    ACK changed nothing, there is nothing to take back, and the wait must stay: the text that comes next is released once."""
    clock = H.FakeClock()
    c = H.ControlledMedia(tmp_path / 'frontier-twice.sqlite3', session_id='frontier2', clock=clock, **H.HOST_KWARGS)
    c.provider(H.created('u1', 'user', 'Что'))
    clock.advance(0.5)
    c.provider(H.done('u1', 'user', 'Что такое инерция?'))
    c.provider(H.created('a1', 'assistant', 'Инерция — это свойство '))
    cue = [a for a in c.provider({'type': 'turn.delta', 'turn_id': 'a1', 'delta': FRONTIER_DELTA,
                                  'start_ms': 40, 'end_ms': 79}) if a['type'] == 'speak'][0]
    clock.advance(0.6)
    c.playback_done(cue, now=clock())
    clock.advance(4.0)
    rig = SimpleNamespace(controller=c, clock=clock)
    first = Speaker(rig, 'u-first').start().words(FRONTIER_CUE.rstrip(',.'))
    first.wait(ACK_STABLE_SECONDS + TICK)
    first.final()
    assert c.state()['stream_waiting_next'], 'precondition: the first repeat parked the frontier'
    clock.advance(4.0)
    second = Speaker(rig, 'u-second').start().words(FRONTIER_CUE.rstrip(',.'))
    second.wait(ACK_STABLE_SECONDS + TICK)
    second.words('повтори', step=0.3)
    second.wait(0.8)
    before = len(second.actions)
    second.final()
    assert speaks(second.actions[before:]) == [FRONTIER_CUE], 'the portion was not replayed'
    assert c.state()['stream_waiting_next'] and c.state()['chunk_index'] == 0, 'the wait for the next text was taken back with the request'
    released = c.provider(H.done('a1', 'assistant', 'Инерция — это свойство тела сохранять своё состояние покоя. Пока на него не действуют силы.'))
    assert len(speaks(released)) == 1 and c.state()['chunk_index'] == 1, 'the text that came next was not released'


def streaming_engine(tmp_path, name, prefix):
    from echo_sync.generator import StreamingAnswer
    engine = EchoEngine(tmp_path / f'{name}.sqlite3', lambda *args: StreamingAnswer(prefix),
                        settings={'words_per_portion': 3, 'on_mismatch': 'silent'})
    engine_reply(engine, session_id='s', turn_id='q', text='Что такое инерция?', request={}, model='m')
    return engine


def test_rewind_refuses_a_frontier_that_two_acknowledgements_have_reached(tmp_path):
    """The first acknowledgement moved the cursor, the second parked the new frontier: the state is not where the FIRST one left it."""
    engine = streaming_engine(tmp_path, 'two-steps', 'Первый второй третий четвёртый пятый шестой')
    revision = engine.state('s')['revision']
    ack(engine, 'a1')
    ack(engine, 'a2')
    before = engine.state('s')
    assert before['chunk_index'] == 1 and before['stream_waiting_next'], 'precondition: moved on, then parked at the new frontier'
    assert engine.rewind(session_id='s', revision=revision, index=0) is False
    assert engine.state('s') == before


def test_rewind_refuses_a_cursor_that_moved_by_itself_after_a_frontier_acknowledgement(tmp_path):
    """The frontier waited before the early ACK (it consumed nothing); the text then arrived and the stream moved the cursor on. Taking that
    step back would undo something the acknowledgement never did."""
    prefix = 'Первый второй третий'
    engine = streaming_engine(tmp_path, 'moved-by-text', prefix)
    revision = engine.state('s')['revision']
    ack(engine, 'a1')
    assert engine.state('s')['stream_waiting_next']
    engine.extend_answer(session_id='s', revision=revision, answer=prefix + ' четвёртый пятый шестой седьмой восьмой девятый.')
    before = engine.state('s')
    assert before['chunk_index'] == 1 and not before['stream_waiting_next'], 'precondition: the stream moved the cursor on'
    assert engine.rewind(session_id='s', revision=revision, index=0, waiting=True) is False
    assert engine.state('s') == before


def test_rewind_never_sets_the_cursor_before_the_first_portion(tmp_path):
    engine = engine_with_plan(tmp_path, 'negative')
    revision = engine.state('s')['revision']
    before = engine.state('s')
    assert engine.rewind(session_id='s', revision=revision, index=-1) is False
    assert engine.state('s') == before

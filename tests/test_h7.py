"""H7: the job starts earlier, what is ready is not thrown away; and first what the owner's call of 5 Nov 10:27 showed (.superpowers/sdd/wave2/owner-call-1027-timeline.txt; c14, ``fast_text`` on, the tempo and the ear release off). No network, no
sleep: the real NativeMediaSocket, ShadowEar and controller on the injected clock; only the speech detector, the recognizer's worker, the cloud's events and the job's stream are scripted, each case in the live order of its events. What this
proves is the logic: nothing here is a measurement of a call.
"""
import json
import logging
import threading
from collections import Counter
from pathlib import Path

import pytest

import helpers_s6_state as S
from echo_sync import fast_text as FT
from echo_sync import codex_road as CR
from echo_sync.classifier import question_part, strip_fillers
from echo_sync.timer_policy import ONSET_HOLD_MAX_S
from echo_sync.controlled_media import EAR_RELEASE_SILENCE_SECONDS, PREPARE_WORDS, TEMPO_START_SECONDS
from echo_sync.first_useful import first_cue
from echo_sync.reference_kb import lookup
from echo_sync.settings import CALL_SETTINGS, resolve
from echo_sync.timer_policy import TEMPO_REPEAT_SECONDS
from test_h1_fast_text import FakeHttp, FakeResponse, manager, settled, sse
from test_a2_same_question import REFUSE as A2_REFUSE
import test_h3_tempo as T3
from test_h3_tempo import GRID, PORTION, TICK, call, into_speech, replay, the_whole_call       # noqa: F401 - call is the fixture
from test_h5_live import asked, decisions, plan, spoken_failures

CALL_1027 = {'fast_text': 'on', 'ear': 'off', 'max_auto_repeats': 3}      # as it ran: no tempo of the ear (no ear: the wait is 6.0 s)
HEAD_89 = ('так, ну вот было бы круто, если бы ты говорил "конец" ещё, вот, чтобы я понимал типа, что это конец фразы, а то ты интонацией не даёшь, хотя да, конец это лишнее слово, лучше интонацией как-то научиться, чтобы я интонацией понимал, '
           'что это конечное слово твоё, да, и ответы подробнее нужны, мне кажется, мне нравится, ты пять слов говоришь, я прям чётко их говорю, и задержка почти минимальная, вот, но иногда, конечно, ты плохо срабатываешь с повторами, я хочу, чтобы ты '
           'ещё быстрее было, потому что сейчас типа ну вот по факту, вот давай даже затестим, я сейчас повтор отработаю прям по секундам, когда я буду договаривать свою фразу, я буду говорить количество секунд, вот сейчас на второй минуте, вторая '
           'минута разговора, только я задам вопрос, я скажу, какое количество секунд, значит, план счетов 89 счет какой')
SAID_89 = HEAD_89 + '? 30 секунд'
SAID_15 = 'Не знаю, ладно. Хорошо, давай заново. Вот сейчас третья минута идёт. Так, значит, что такое пятнадцатый счёт в плане счетов ? 13 секунд'
SAID_55 = ('А, ну вот да, его бесило то, что я говорил, ну смотри, я короче когда договорил было 14 секунд, а он ответил в 16 секунд, но вообще быстро, то есть прям очень быстро, но это в этот раз быстро, в предыдущий раз когда я ааа, ты же в подготовил '
           'этот готовый перечень ответов таблицу, молодец, ну давай тогда спрошу посложнее, да, тогда вот задам вопрос по налоговому кодексу, так, значит 55 статья налогового кодекса')
SAID_KALKA = 'причём по-разному представить различные ситуации, которые возможны вот и соответственно придумать как решить эту проблему так, ну давай ещё что-нибудь отработаем значит в каком году была битва при Калке'
SAID_INFLATION = 'ну и всё бесплатно собственно делаешь, вот, так, давай ещё какой-нибудь вопрос проверим, допустим, значит вопрос по экономике России скажем что такое инфляция'
NO_89 = 'Счёта 89 в плане счетов нет.'


def delegated(uid, did='d1'):
    return {'type': 'delegation.created', 'item': {'id': did, 'type': 'delegation', 'target': 'client', 'user_bidi_turn_id': uid}}


def said_with_a_delegation(rig, uid, text, head=None):
    """150.41 of the call: the model asks for a search on what it has so far, the final comes 0.6 s later."""
    rig.w.feed(S.turn_created(uid, 'user', text.split()[0]))
    rig.w.feed(S.turn_delta(uid, (head or text[:len(text) - 12]), 1))
    rig.pump(TICK)
    rig.w.feed(delegated(uid))
    rig.pump(TICK * 5)
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK)


def job_answers(rig, n, text):
    rig.job_says(n, text)
    rig.job_ends(n)


# =====================================================================================================================================
# 0a. a long remark with a real question at its end: the gates read the question part, the job is asked
# =====================================================================================================================================

@pytest.mark.parametrize('said, part', [
    (SAID_89, 'план счетов 89 счет какой'),
    (SAID_15, 'что такое пятнадцатый счёт в плане счетов'),
    (SAID_55, '55 статья налогового кодекса'),
    (SAID_KALKA, 'в каком году была битва при Калке'),
    (SAID_INFLATION, 'что такое инфляция'),
    ('Хорошо, значит, какой, что это за счёт номер 14 в плане счетов', 'какой, что это за счёт номер 14 в плане счетов'),
    ('Вот сейчас третья минута идёт. Сколько планет в Солнечной системе? Да.', 'Сколько планет в Солнечной системе'),
], ids=['89', '15', '55', 'kalka', 'inflation', '14', 'tail'])
def test_the_question_part_of_a_remark(said, part):
    assert question_part(said) == part


@pytest.mark.parametrize('said', ['Какая сейчас ставка НДС, когда я продаю товар?', 'Что такое инерция', 'Кто написал роман, который называется Война и мир', 'Как мне вернуть налог', 'Семнадцатая статья Налогового кодекса', 'Какая ставка, если продаю товар'])
def test_a_plain_question_is_its_own_part(said):
    assert question_part(said) == said


def test_a_subordinate_clause_stays_with_its_question():
    assert question_part('Я вот думаю, какой налог платят, когда продают квартиру') == 'какой налог платят, когда продают квартиру'


def test_a_question_that_is_a_verb_of_meaning_is_not_cut_at_it():
    assert question_part('я хотел бы вот сейчас узнать у тебя что значит слово амортизация в бухучёте') == 'что значит слово амортизация в бухучёте'


def test_151_a_long_remark_ending_on_a_question_gets_a_job_with_no_search(call, caplog):
    """150.41 the delegation on the partial, 151.0 the final, «я» of the preface made it personal: personal_unanswerable, 13.5 s, «Нет ответа. Повторите вопрос.»"""
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    said_with_a_delegation(rig, 'u1', SAID_89, HEAD_89)
    assert not decisions(caplog, 'personal_unanswerable')
    assert rig.fast.count == 1, 'the job is asked'
    assert rig.w.lookup_calls == [], 'there is nothing to search: an account is no article and no rate'
    job_answers(rig, 0, NO_89)
    assert rig.said() == [NO_89] and spoken_failures(rig) == []


def test_253_a_bare_topic_after_a_remark_is_answered_by_the_base(call, caplog):
    """253.69: speech_too_long_for_an_attempt, a candidate, its job answered, the route read «я» and threw the answer away: personal_unanswerable, 9.6 s, «Нет ответа»."""
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    asked(rig, SAID_55)
    rig.pump(TICK * 2)
    assert rig.said() and rig.said()[0].startswith('Статья 55')
    assert not decisions(caplog, 'personal_unanswerable') and spoken_failures(rig) == []


def test_253_the_same_order_with_an_article_the_base_has_not(call, caplog):
    """The route of the same final past the base: the search gets the question part only, and its sources go to a job."""
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    text = SAID_55.replace('55 статья', '9999 статья')
    asked(rig, text)
    rig.pump(TICK * 2)
    if rig.c.candidate is not None:
        job_answers(rig, 0, 'Статьи 9999 в Налоговом кодексе нет.')
        rig.pump(TICK * 2)
    assert not decisions(caplog, 'personal_unanswerable')
    assert rig.w.lookup_calls and not any('бесило' in query or ' я ' in query for query in rig.w.lookup_calls), rig.w.lookup_calls


@pytest.mark.parametrize('said, answer', [
    ('Я вот сейчас договорю и всё, я сказал что я готов, значит что такое амортизация', 'Амортизация — перенос стоимости на расходы.'),
    ('Я сейчас думаю вслух, у меня тут в голове каша, скажем что такое вексель', 'Вексель — долговая ценная бумага.'),
    ('Мой сосед сегодня спросил меня, что я думаю, ну ладно, в каком году отменили крепостное право', 'В 1861 году.'),
], ids=['amort', 'bill', 'serfdom'])
def test_the_neighbours_of_a_remark_with_i_in_it(call, caplog, said, answer):
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    asked(rig, said)
    rig.pump(TICK * 2)
    job_answers(rig, 0, answer)
    rig.pump(TICK * 2)
    assert rig.said() and spoken_failures(rig) == [] and not decisions(caplog, 'personal_unanswerable')


def test_a_personal_question_that_needs_a_source_goes_to_the_job_with_no_search(call):
    """Nothing public is left of it: the job with the no-source request, not 8 s of silence."""
    rig = call(**CALL_1027)
    asked(rig, 'Как мы у меня применяем статью 218 НК')
    rig.pump(TICK * 2)
    assert rig.fast.count == 1 and FT.NO_SOURCE_BRAIN in str(rig.fake.run(0).request), 'the job knows there is no source'


def test_with_the_channel_off_the_gates_read_as_they_did(call, caplog):
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call()
    said_with_a_delegation(rig, 'u1', SAID_89, HEAD_89)
    # w10 item 1 (WAVE10.md, newer than this pin): with the channel off the frame («я понимал», «мне кажется») still never reaches the search, but the
    # general question after it does - its question part, not silence (before: personal_unanswerable)
    assert decisions(caplog, 'personal_public_remainder') and not decisions(caplog, 'personal_unanswerable')
    assert rig.c.lookup_query == 'план счетов 89 счет какой'


# =====================================================================================================================================
# 0b. a false «Не нашёл» in 0.2 s: every judgement of a final by words reads the question part
# =====================================================================================================================================

def test_194_a_now_in_the_preface_is_no_data_that_changes(call, caplog):
    """194.52: no_source_current_data 0.2 s after the final."""
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    text = SAID_15.replace('пятнадцатый счёт в плане счетов', 'амортизация')
    said_with_a_delegation(rig, 'u1', text)
    rig.pump(TICK * 2)
    assert rig.c.direct_content and rig.w.lookup_calls == [] and not decisions(caplog, 'no_source_current_data')
    job_answers(rig, 0, 'Амортизация — перенос стоимости на расходы.')
    assert rig.said() and spoken_failures(rig) == []


def test_a_question_with_no_source_goes_on_to_the_job_with_the_no_source_request(call, monkeypatch, caplog):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    asked(rig, 'Вот сейчас третья минута идёт. Так, значит, что сказано в 9999 статье налогового кодекса')
    rig.pump(TICK * 2)
    assert not decisions(caplog, 'no_source_current_data') and spoken_failures(rig) == []
    assert rig.fast.count == 1 and FT.NO_SOURCE_BRAIN in str(rig.fake.run(0).request)


@pytest.mark.parametrize('question', ['Какая сейчас ставка НДС', 'Вот смотри, ладно. Какая сейчас ставка НДС'])
def test_not_found_stays_for_data_that_really_changes(call, monkeypatch, question):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    rig = call(**CALL_1027)
    asked(rig, question)
    rig.pump(TICK * 3)
    assert [cue.text for cue in spoken_failures(rig)] == ['Не нашёл. Повторите вопрос.']


# =====================================================================================================================================
# 0c. the base with a tail
# =====================================================================================================================================

@pytest.mark.parametrize('said', [
    'что такое пятнадцатый счёт в плане счетов ? 13 секунд', SAID_15, 'что такое пятнадцатый счёт тринадцать секунд', 'что такое пятнадцатый счёт в плане счетов? Вот.', 'пятнадцатый счёт, да, спасибо', 'что за 15 счёт? Две секунды',
])
def test_a_short_tail_that_asks_nothing_is_no_reason_to_miss(said):
    assert lookup(said, tails=True).startswith('Счёт 15')


def test_the_long_remark_before_the_reference_is_no_reason_either():
    assert lookup(SAID_55, tails=True).startswith('Статья 55 Налогового кодекса')


@pytest.mark.parametrize('said', ['Проводка по счёту 71', 'Вот смотри, проводка по счёту 71', 'счёт 71 какие проводки', 'счёт 71? Какие проводки', 'Счёт 71, 15 рублей', 'что такое счёт 71? Сальдо', 'как закрыть счёт 90 за две минуты'])
def test_the_negatives_stay(said):
    assert lookup(said, tails=True) is None


def test_a_number_that_is_no_account_leaves_the_base_silent():
    assert lookup(SAID_89, tails=True) is None


def test_off_the_tail_it_reads_as_it_did():
    assert lookup('что такое пятнадцатый счёт в плане счетов ? 13 секунд') is None and lookup(SAID_55) is None


# =====================================================================================================================================
# 0d. the first portion carries the answer (H5 item 5, on this call's text through the real portioner)
# =====================================================================================================================================

KALKA = 'Битва на реке Калке произошла в 1223 году.'


@pytest.mark.parametrize('pieces', [[KALKA], ['Битва на реке Калке произошла', ' в 1223 году.'], ['Битва на реке ', 'Калке произошла ', 'в 12', '23 году.']], ids=['whole', 'at_the_verb', 'in_pieces'])
def test_362_the_first_portion_of_the_battle_has_the_year(call, pieces):
    """362.07 «Битва на реке Калке произошла», then, 9 s later, «в 1223 году.»: «можно сразу год говорить»."""
    rig = call(**CALL_1027)
    asked(rig, SAID_KALKA)
    for piece in pieces:
        rig.job_says(0, piece)
    rig.job_ends(0)
    assert '1223' in rig.said()[0], rig.said()


def test_the_first_portion_on_the_part_of_the_question_alone():
    cue = first_cue(KALKA, 'в каком году была битва при Калке', CALL_SETTINGS, final=True, last=True, patient=True)
    assert '1223' in cue


# =====================================================================================================================================
# 0e. detail: a fact is the fact; a definition gets 2-3 sentences, the first alone a usable answer
# =====================================================================================================================================

DEFINITION = 'Инфляция — это устойчивый рост общего уровня цен. Из-за неё деньги со временем покупают меньше. Её измеряют индексом потребительских цен.'


def test_the_brain_asks_for_the_fact_alone_and_for_detail_in_a_definition():
    assert 'На вопрос о факте' in FT.BRAIN and 'определение или объяснение' in FT.BRAIN
    assert 'первая фраза сама по себе годится как ответ' in FT.BRAIN
    assert 'две-три короткие фразы' in FT.BRAIN


def test_a_definition_of_three_sentences_is_said_to_its_end(call):
    """The portioner keeps all of them, one after another, and its first portion is a usable answer alone."""
    rig = call(**CALL_1027)
    asked(rig, SAID_INFLATION)
    job_answers(rig, 0, DEFINITION)
    state = rig.c.state()
    assert rig.said()[0].startswith('устойчивый рост') and ' '.join(state['chunks']).endswith('индексом потребительских цен.')
    assert [sentence for sentence in ('цен.', 'меньше.', 'цен.') if any(chunk.endswith(sentence) for chunk in state['chunks'])] == ['цен.', 'меньше.', 'цен.']


# =====================================================================================================================================
# 0g. help when he stumbles: the tail, at once
# =====================================================================================================================================

INFLATION = 'Инфляция — это устойчивый рост общего уровня цен.'
BODY = 'устойчивый рост общего уровня цен.'           # the term of the question goes (definition_body), as for a plain question


def test_480_a_word_of_the_portion_and_a_stop_brings_only_what_is_missing_in_a_second_and_a_bit(call):
    """472.84-476.91 the cue, 478.1-480.3 «инфляция это устойчивый» (the ear wrote «цвета устойчивый»), silence; with the tempo off the whole portion came 15.4 s later, from the start. «запнулся на втором слове, зачем он мне сначала начинает повторять»."""
    rig = call(fast_text='on', max_auto_repeats=3)
    asked(rig, 'что такое инфляция')
    job_answers(rig, 0, INFLATION)
    assert rig.said() == [BODY]
    rig.pump(1.0)
    ended = rig.says('цвета устойчивый', speech=2.2)
    cue = rig.next_cue(2.0)
    assert cue is not None and cue.t - ended <= TEMPO_START_SECONDS + GRID, 'within 1.2 s'
    assert cue.text == 'рост общего уровня цен.', 'only what is missing'


def test_with_the_channel_off_a_misheard_start_waits_for_the_cloud_as_it_did(call):
    rig = call(max_auto_repeats=3)
    rig.first_portion()
    rig.pump(0.5)
    ended = rig.says('цвета статья', speech=1.0)
    assert rig.c.repeat_at is None and rig.w.clock.t - ended < 1.0, 'a try, the final decides'


@pytest.mark.parametrize('said', ['какой устойчивый', 'разве устойчивый', 'очень хороший устойчивый', 'рост'], ids=['question', 'doubt', 'three', 'alone'])
def test_what_is_no_misheard_start_stays_what_it_was(call, said):
    rig = call(fast_text='on', max_auto_repeats=3)
    asked(rig, 'что такое инфляция')
    job_answers(rig, 0, INFLATION)
    rig.pump(1.0)
    rig.says(said, speech=1.0)
    cue = rig.next_cue(1.5)
    assert cue is None or not cue.text.startswith('рост общего') or said == 'рост', cue


def test_the_wait_for_a_repeat_in_the_tempos_mode_is_two_seconds(call):
    """The owner, 10:27: «там ну максимум секунда две наверное должна быть перерыва». It was 3.5 (H3); with the tempo on the timer of a portion nobody has started is 2.0 s, a start that stopped keeps its 1.2 s."""
    assert TEMPO_REPEAT_SECONDS == 2.0 and resolve({'local_ear': 'act'})['repeat_seconds'] == 2.0
    rig = call(fast_text='on', max_auto_repeats=3)
    asked(rig, 'что такое инфляция')
    job_answers(rig, 0, INFLATION)
    ended = rig.ended()
    cue = rig.next_cue(3.0)
    assert cue is not None and cue.text == BODY and cue.t - ended == pytest.approx(2.0, abs=GRID)


def test_what_the_shorter_wait_costs_on_the_order_of_20_34(call):
    """75.14 of the call of 4 Nov: he began 2.14 s after the end of the cue. With 3.5 s he got what was missing (H3's test keeps that order with the old wait); with 2.0 s the portion comes back 0.14 s before he begins. The owner's ruling; this pins its price."""
    rig = call()
    times, texts, _ = replay(rig)
    assert texts[0] == PORTION and times[0] == pytest.approx(75.0, abs=2 * GRID)


# =====================================================================================================================================
# 1. the journal (Б10): every job, every refusal, the usage; no token, no header, no word at info level
# =====================================================================================================================================

def journal(rig):
    """The trace of the call: ``(ev, fields)``."""
    notes = []
    rig.fast.report = lambda ev, **fields: notes.append((ev, fields))
    return notes


def lines(notes, ev):
    return [fields for kind, fields in notes if kind == ev]


def test_a_job_leaves_a_line_when_it_is_over(call):
    rig = call(**CALL_1027)
    notes = journal(rig)
    rig.says('так значит', speech=0.5)
    rig.pump(0.3)
    asked(rig, 'что такое инерция')
    job_answers(rig, 0, 'Инерция — свойство тела сохранять скорость.')
    line = lines(notes, 'fast_job')[-1]
    assert line['on'] == 'final' and line['outcome'] == 'ok' and line['released'] == 1 and line['first'].startswith('Инерция') and line['chars'] > 10
    assert line['after_ear_ms'] == pytest.approx(600, abs=250) and line['ttft_ms'] is not None


def test_a_job_on_the_ear_says_so_and_how_long_after_the_offset(call):
    rig = call(fast_text='on')
    notes = journal(rig)
    rig.says('в каком году было крещение руси', speech=2.0, lag=0.15)
    rig.w.feed(S.turn_created('u1', 'user', 'В каком'))
    rig.w.feed(S.turn_done('u1', 'user', 'В каком году было крещение Руси'))
    rig.pump(TICK)
    job_answers(rig, 0, 'В 988 году.')
    line = lines(notes, 'fast_job')[-1]
    assert line['on'] == 'ear' and line['after_ear_ms'] == pytest.approx(250, abs=150) and line['adopted'] == 1 and rig.fast.count == 1


def test_a_refusal_says_which_rule_and_the_log_has_no_word_of_it(call, caplog):
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(fast_text='on')
    notes = journal(rig)
    rig.says('в каком году было крещение руси', speech=2.0)
    rig.w.feed(S.turn_created('u1', 'user', 'В каком'))
    rig.w.feed(S.turn_done('u1', 'user', 'В каком году было восстание Спартака'))
    rig.pump(TICK)
    line = lines(notes, 'fast_refused')[-1]
    assert line['rule'] == 'words' and line['job'] == 1
    assert line['heard'].startswith('в каком') and line['asked'].endswith('Спартака'), 'the call trace keeps the words'
    logged = [message for message in decisions(caplog, 'fast_text refused')]
    assert logged and 'rule=words' in logged[-1] and 'Спартака' not in logged[-1] and 'крещение' not in logged[-1]


@pytest.mark.parametrize('heard, asked, rule', [
    ('сколько будет сорок восемь на два', 'Сколько будет 48 на 3', 'numbers'),
    ('можно вернуть товар', 'Нельзя не вернуть товар', 'numbers'),
    ('кто написал войну и мир', 'Кто написал Анну Каренину', 'words'),
    ('кто написал войну и мир и когда и зачем и почему', 'Кто написал войну', 'alike'),
    ('', 'Кто написал войну', 'empty'),
    ('кто написал войну и мир', 'Кто написал войну и мир', None),
    ('было 80 рублей потратил 20 рублей сколько осталось', 'Было 20 рублей потратил 80 рублей сколько осталось', 'roles'),
], ids=['number', 'not', 'word', 'alike', 'empty', 'same', 'roles'])
def test_the_rule_of_the_match_is_named(heard, asked, rule):
    assert FT.refusal(heard, asked) == rule and FT.same_question(heard, asked) == (rule is None)


def test_a_refusal_by_age_failure_or_the_answer_in_play_is_named(call):
    rig = call(**CALL_1027)
    notes = journal(rig)
    job = rig.fast._start('что такое инерция')
    rig.fast.job = job
    job.started -= FT.WHOLE_S + 1
    assert not rig.fast._fits(job, 'что такое инерция')
    job.started += FT.WHOLE_S + 1
    job.played = ('вопрос', 'ответ')
    assert not rig.fast._fits(job, 'что такое инерция')
    job.played = None
    job.finish('error', 'http_500')
    assert not rig.fast._fits(job, 'что такое инерция')
    assert [line['rule'] for line in lines(notes, 'fast_refused')][-3:] == ['old', 'played', 'failed']


def test_a_refusal_of_a_look_is_one_line(call):
    """``prepared`` is asked on every tick while the ear waits."""
    rig = call(**CALL_1027)
    notes = journal(rig)
    rig.fast.job = job = rig.fast._start('что такое инерция')
    for _ in range(5):
        rig.fast.prepared('кто написал войну')
    assert len(lines(notes, 'fast_refused')) == 1
    job.finish('cancelled')


def test_usage_comes_from_the_completed_event_and_nothing_else_of_it():
    usage = {'input_tokens': 900, 'output_tokens': 40, 'total_tokens': 940, 'input_tokens_details': {'cached_tokens': 512}, 'output_tokens_details': {'reasoning_tokens': 12}, 'secret': 'x'}
    http = FakeHttp(FakeResponse(200, sse({'type': 'response.output_text.delta', 'delta': 'Да'}, {'type': 'response.completed', 'response': {'usage': usage, 'id': 'r1'}})))
    got = list(CR.codex_stream(lambda: ('tok', 'acct'), client_factory=lambda: http)({'model': 'm'}, threading.Event()))
    assert got == ['Да', {'usage': {'input_tokens': 900, 'output_tokens': 40, 'total_tokens': 940, 'cached_tokens': 512, 'reasoning_tokens': 12}}]


def test_the_usage_reaches_the_line_of_the_job_with_no_token(call):
    rig = call(**CALL_1027)
    notes = journal(rig)
    asked(rig, 'что такое инерция')
    run = rig.fake.run(0)
    run.say('Инерция — свойство тела.')
    run.say({'usage': {'input_tokens': 900, 'output_tokens': 40}})
    rig.job_ends(0)
    line = lines(notes, 'fast_job')[-1]
    assert line['input_tokens'] == 900 and line['output_tokens'] == 40 and line['chars'] == len('Инерция — свойство тела.')
    assert not any(key in str(notes).casefold() for key in ('bearer', 'authorization', 'chatgpt-account'))


def test_the_host_gives_the_channel_the_call_trace(call):
    rig = call(**CALL_1027)
    note = object()
    made = FT.for_call(rig.settings, rig.c, stream=rig.fake, instructions=lambda: 'POLICY', wake=lambda: None, clock=rig.w.clock.now, report=note)
    assert made.report is note and made.ear_ended() is None
    source = (Path(FT.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    assert 'wake=fast_wake,report=calltrace.note)' in source


def test_a_trace_that_fails_changes_nothing(call):
    rig = call(**CALL_1027)

    def broken(ev, **fields):
        raise OSError('disk')
    rig.fast.report = broken
    asked(rig, 'что такое инерция')
    job_answers(rig, 0, 'Инерция — свойство тела сохранять скорость.')
    assert rig.said()


# =====================================================================================================================================
# 2. why a ready job is thrown away (С4): the rule of the match on the real pairs of the ear and the final (logs/echo_calls, 61 pairs of 3-40 words)
# =====================================================================================================================================
# 17 of the 61 passed on the last piece of the ear, 25 on all its pieces. Rule 'words' refused 25, 'numbers' 16: the final holds the remark around the question and the ear's job the question alone. So the match reads the two parts that ask. The rest of
# 'words' is another word: of those a word the dictionary does not know, close to the one the final has, is the ear's garble of it. Numbers and «не», «ни» stay exact.

SAME = [
    ('двадцать первая статья налогового кодекса', 'А какой вопрос? Двадцать первая статья налогового кодекса'),
    ('так что такое двадцать седьмая статья налогового кодекса', 'И ещё раз говорю, тут должна быть настроена система, которая постоянно бы слушала, тогда нам все проблемы решим, но большинство проблем, имею в виду. Так, что такое двадцать седьмая статья Налогового кодекса'),
    ('пять умножить на пять', ', прям подсказывала, быстрее реагировать нужно, значит медленно пока реагируешь. Хорошо. Пять умножить на пять'),
    ('так в каком году было крещение руси', 'Двадцать пять. Хорошо, считаем быстро. Так, в каком году было крещение Руси'),
    ('хорошо значит какой что это за счёт номер четырнадцать в плане счетов', 'Даже не отвечает, или его бесят типа количество секунд, когда я в конце говорю, давай не буду говорить. Хорошо, значит, какой, что это за счёт номер 14 в плане счетов'),
    ('значит что такое пятьдесят пятая статья налогового кодекса', 'секунда, и он даже не дал ответа, значит что такое 55 статья налогового кодекса'),
    ('ну что сколько будет дважды два', 'Тааак, ну что, сколько будет дважды два'),
    ('дважды два сколько будет', 'Все, славно, отлично. Че там, дважды два сколько будет'),
    ('значит сорок восемь умножить на десять', 'Так, двадцать три, хорошо. Значит, сорок восемь умножить на десять'),
    ('тебе нужно обязательно сказать что такое девятая статья налогового кодекса', 'Блядь, ты ещё и не отвечаешь, когда я тебе говорю, что это, тебе нужно обязательно сказать, что такое девятая статья налогового кодекса'),
    ('ого и тут резко заработал так что такое двадцать седьмая статья налогового кодекса', 'Ого, и тут ты резко заработал. Так, что такое двадцать седьмая статья Налогового кодекса'),
    ('так что такое пятнадцатая статья налогового кодекса', 'Так, что такое пятнадцатая статья Налогового кодекса'),
    ('значит в каком году была битва прикалки', 'причём по-разному представить различные ситуации, которые возможны вот и соответственно придумать как решить эту проблему так, ну давай ещё что-нибудь отработаем значит в каком году была битва при Калке'),
    ('семнадцатая статья налогового кодекса', '? Семнадцатая статья Налогового кодекса'),
    ('так в каком году было крещение руси', 'Так, в каком году было крещение Руси'),
    ('двадцать первая статья налогового кодекса', 'А двадцать первая статья Налогового кодекса'),
]
ANOTHER = [
    ('пятнадцатая статья налогового кодекса', 'Что такое девятнадцатая статья налогового кодекса'),           # 122.3 of the call of 4 Nov 09:41: the ear misheard the number
    ('короче вот я тебе в тридцать шесть секунд сказал сейчас пятьдесят две уже пятьдесят давай тогда перефразирую вопрос такое во пятнадцатая статья налогового кодекса',
     'Короче, вот, я, типа, тридцать шесть секунд сказал, сейчас пятьдесят две уже, пятьдесят три, ты молчишь, а значит, ты не смог мне подсказать. Давай тогда перефразирую вопрос: что такое восемнадцатая статья налогового кодекса'),
    ('да в чем заключается планы', 'Так, значит в чём заключается смысл экономики плановой'),
    ('сейчас вообще типа ты пишешь похоже сколько будет десять', 'Сейчас вообще, типа, ты сломался, походу, ты пишешь "похоже, у меня нет доступа". Ну, ладно. Так, давай тогда по-другому тебя проверим. Сколько будет десять плюс тринадцать?'),
    ('на десять', 'сорок восемь умножить на десять'),
    ('пятнадцатая статья налогового кодекса', 'Двадцать седьмая статья Налогового кодекса'),
    ('кто написал войну и мир', 'Кто написал Анну Каренину'),
    ('когда родился пушкин', 'Когда родился Лермонтов'),
    ('что такое дебет', 'Что такое дебет и кредит'),
    ('что такое дебет', 'Что такое кредит'),
    ('какой налог на прибыль', 'Какой налог на добавленную стоимость'),
    ('столица франции', 'Столица Германии'),
    ('что такое сальто', 'Что такое сальдо'),                                                                               # both words of the language: nobody can tell which was said
    ('можно вернуть товар', 'Нельзя не вернуть товар'),
    ('можно ли не платить налог', 'Можно ли платить налог'),
    ('сколько будет сорок восемь на два', 'Сколько будет 48 на 3'),
    ('сколько будет сорок восемь на два', 'Он сказал не то. Сколько будет 49 на 2'),
    ('какая столица австралии', 'Какая столица Австрии'),
]


def wide_fast(**keywords):
    fast, fake, clock = manager(strip=lambda text: strip_fillers(text, None), **keywords)
    fast.wide = True
    return fast, fake, clock


@pytest.mark.parametrize('heard, final', SAME, ids=range(len(SAME)))
def test_a_job_for_the_same_question_is_adopted(heard, final):
    fast, fake, _ = wide_fast()
    fast.prepare(heard)
    assert fast.release(qid='u1', turn='t1', epoch=1, question=final) == 'adopted'
    assert fast.count == 1
    fast.close()


@pytest.mark.parametrize('heard, final', ANOTHER, ids=range(len(ANOTHER)))
def test_a_job_for_another_question_is_never_adopted(heard, final):
    fast, fake, _ = wide_fast()
    fast.prepare(heard)
    assert fast.release(qid='u1', turn='t1', epoch=1, question=final) == 'started'
    fast.close()


@pytest.mark.parametrize('heard, final', [pair for pair in ANOTHER if pair[1] != 'Что такое дебет и кредит'], ids=range(len(ANOTHER) - 1))     # that job has answered more than was asked, 0.75 alike: as before H7
def test_the_other_way_round_it_is_no_more_adopted(heard, final):
    """A job on the cloud's stable partial and an ear's final that goes another way."""
    fast, _, _ = wide_fast()
    fast.prepare(final)
    assert fast.release(qid='u1', turn='t1', epoch=1, question=heard) == 'started'
    fast.close()


@pytest.mark.parametrize('name, heard, final', A2_REFUSE, ids=[row[0] for row in A2_REFUSE])
def test_the_parts_that_ask_do_not_take_the_roles_of_a2_away(name, heard, final):
    """«было 80, потратил 20, сколько денег осталось» and the numbers changed over have one part that asks: A2's table through the wide rule, both ways."""
    for ear, said in ((heard, final), (final, heard)):
        fast, _, _ = wide_fast()
        fast.prepare(ear)
        assert fast.release(qid='u1', turn='t1', epoch=1, question=said) == 'started'
        fast.close()


def test_a_refusal_for_the_roles_around_the_part_says_so():
    fast, _, _ = wide_fast()
    fast.prepare('если у меня было 80 рублей и я потратил 20 рублей сколько денег осталось')
    assert fast._why_not(fast.job, 'Если у меня было 20 рублей, и я потратил 80 рублей, сколько денег осталось?') == 'roles'
    fast.close()


def test_without_the_setting_the_match_is_as_it_was():
    fast, _, _ = manager(strip=lambda text: strip_fillers(text, None))
    fast.prepare('пять умножить на пять')
    assert fast.release(qid='u1', turn='t1', epoch=1, question=SAME[2][1]) == 'started', 'the final with the remark around it'
    fast.close()


def test_the_setting_is_read_like_ear_release():
    assert resolve({})['prepare_wide'] == 'off'
    assert resolve({'fast_text': 'on', 'local_ear': 'act', 'prepare_wide': 'on'})['prepare_wide'] == 'on'
    assert resolve({'fast_text': 'on', 'local_ear': 'shadow', 'prepare_wide': 'on'})['prepare_wide'] == 'on'
    assert resolve({'local_ear': 'act', 'prepare_wide': 'on'})['prepare_wide'] == 'off', 'no channel, nothing to prepare'
    assert resolve({'fast_text': 'on', 'prepare_wide': 'on'})['prepare_wide'] == 'off', 'no ear, nobody says it has stopped'
    assert resolve({'fast_text': 'on', 'local_ear': 'act', 'prepare_wide': 'yes'})['prepare_wide'] == 'off', 'an unknown value is off'


@pytest.mark.parametrize('profile', [{'fast_text': 'on', 'ear': 'off'}, {'fast_text': 'on'}], ids=['no_ear', 'ear_tempo'])
@pytest.mark.parametrize('where', ['first_portion', 'second_portion', 'finished'])
def test_the_answer_in_play_was_not_the_suspect(call, where, profile):
    """С4 named ``job.played``. A question said while an answer is in play: the plan retires in the very ``_open_question`` before the release, and the rule of the answer in play still holds: its entry in the history is the same pair."""
    rig = call(**profile)
    notes = journal(rig)
    plan(rig, asked='Что такое инерция', answer='Инерция — свойство тела сохранять скорость. Это первый закон Ньютона, он описан в механике.')
    rig.pump(0.5)
    if where != 'first_portion':
        rig.w.feed(S.turn_done('ux', 'user', rig.c.state()['chunks'][0]))
        rig.pump(0.3)
    if where == 'finished':
        for n in range(1, len(rig.c.state()['chunks'])):
            rig.w.feed(S.turn_done(f'ux{n}', 'user', rig.c.state()['chunks'][n]))
            rig.pump(0.3)
    runs = rig.fast.count
    rig.says('в каком году было крещение руси', speech=2.0)
    assert rig.fast.count == runs + 1
    rig.w.feed(S.turn_created('u1', 'user', 'В каком'))
    rig.w.feed(S.turn_done('u1', 'user', 'В каком году было крещение Руси'))
    rig.pump(TICK)
    assert rig.fast.count == runs + 1 and lines(notes, 'fast_refused') == [], 'adopted'


# =====================================================================================================================================
# 3. a job on a stable partial of the cloud (С1) 4. a job on the ear's text with no question form (С2)
# =====================================================================================================================================

WIDE = {'fast_text': 'on', 'prepare_wide': 'on'}      # prepare_wide needs the ear, so this scene runs with the ear's tempo (the old no-tempo variant has no owner's rule)
ACCOUNT = 'Как отразить покупку материалов'
MATERIALS = 'Купили материалы за 10 000 рублей: дебет счёта материалов, кредит счёта денег.'


def partial(rig, uid, text):
    """The cloud's text of a turn that stays open."""
    rig.w.feed(S.turn_created(uid, 'user', text.split()[0]))
    rig.w.feed(S.turn_delta(uid, text[len(text.split()[0]):], 1))


@pytest.mark.parametrize('text', ['в каком году было крещение Руси', 'крещение Руси в каком году', 'амортизация основных средств'], ids=['question', 'late', 'topic'])
def test_a_partial_that_stands_still_for_a_quarter_of_a_second_gets_a_job(call, text):
    """The text of the question is there 1.06 s after the end of speech on the phone, the final at 2.23 s."""
    rig = call(**WIDE)
    partial(rig, 'u1', text)
    rig.pump(0.1)
    assert rig.fast.count == 0, 'it has only just stopped'
    rig.pump(0.3)
    assert rig.fast.count == 1 and text in str(rig.fake.run(0).request)
    assert rig.said() == [], 'a prepared job says nothing'


def test_a_partial_that_grows_gets_none(call):
    rig = call(**WIDE)
    partial(rig, 'u1', 'в каком году')
    for n in range(4):
        rig.pump(0.2)
        rig.w.feed(S.turn_delta('u1', f' слово{n}', n + 2))
    assert rig.fast.count == 0


def test_no_job_on_a_partial_while_the_ear_hears_speech(call):
    rig = call(**WIDE)
    rig.onset()
    partial(rig, 'u1', 'в каком году было крещение Руси')
    rig.pump(1.0)
    assert rig.fast.count == 0, 'the cloud lags: the speaker is still talking'
    rig.offset()
    rig.pump(0.2)
    assert rig.fast.count == 1


def test_the_partials_job_is_adopted_by_its_final_and_nothing_is_said_before_it(call):
    rig = call(**WIDE)
    notes = journal(rig)
    partial(rig, 'u1', 'В каком году было крещение Руси')
    rig.pump(0.4)
    rig.job_says(0, 'В 988 году.')
    rig.job_ends(0)
    assert rig.said() == [], 'nothing until it is adopted'
    rig.w.feed(S.turn_done('u1', 'user', 'В каком году было крещение Руси'))
    rig.pump(TICK * 2)
    assert rig.said() == ['В 988 году.'] and rig.fast.count == 1
    assert lines(notes, 'fast_job')[-1]['on'] == 'partial'


def test_a_partial_behind_the_ear_waits_for_it(call):
    """162.6 of the replay: the ear has «тысяча девятьсот восемьдесят восьмой ты уверена», the cloud so far «тысяча девятьсот восемьдесят»."""
    rig = call(**WIDE)
    rig.says('в каком году было крещение руси', speech=2.0)
    count = rig.fast.count
    partial(rig, 'u1', 'в каком году')
    rig.pump(0.5)
    assert rig.fast.count == count
    rig.w.feed(S.turn_delta('u1', ' было крещение Руси', 2))
    rig.pump(0.5)
    assert rig.fast.count == count, 'caught up: the same question: the job of the ear is it'


def test_the_partial_is_in_the_call_trace_with_or_without_a_job(call):
    rig = call(**WIDE)
    notes = journal(rig)
    partial(rig, 'u1', 'в каком году было крещение Руси')
    rig.pump(0.4)
    partial(rig, 'u2', 'да')
    rig.pump(0.4)
    assert [(line['text'], line['prepared']) for line in lines(notes, 'fast_partial')] == [('в каком году было крещение Руси', 1), ('да', 0)]


@pytest.mark.parametrize('said', ['Купили материалы за 10 000', 'стоп', 'повтори ещё раз', 'дальше'], ids=['repeat', 'stop', 'again', 'next'])
def test_a_repeat_or_a_command_on_a_partial_starts_none(call, said):
    rig = call(**WIDE)
    plan(rig)
    runs = rig.fast.count
    rig.pump(0.5)
    partial(rig, 'u1', said)
    rig.pump(0.5)
    assert rig.fast.count == runs


def test_with_the_setting_off_a_stable_partial_starts_nothing(call):
    rig = call(**CALL_1027)
    partial(rig, 'u1', 'в каком году было крещение Руси')
    rig.pump(1.0)
    assert rig.fast.count == 0


@pytest.mark.parametrize('said', ['амортизация основных средств', 'крещение руси дата', 'налог на прибыль организаций', 'я хотел бы узнать про вексель'], ids=['a', 'b', 'c', 'd'])
def test_an_ear_final_with_no_question_form_gets_a_job(call, said):
    """54% of the finals on the calls had no form at the ear: the job waited for the final."""
    rig = call(**WIDE)
    rig.says(said, speech=1.5)
    assert rig.fast.count == 1 and rig.said() == []


def test_with_the_setting_off_it_gets_none(call):
    rig = call(**CALL_1027)
    rig.says('вот я сегодня не выспался совсем', speech=1.5)
    assert rig.fast.count == 0


@pytest.mark.parametrize('said', ['купили материалы за десять тысяч рублей', 'купили материалы за', 'да', 'ну да', 'стоп стоп', 'повтори ещё раз', 'продолжай дальше пожалуйста'], ids=['repeat', 'try', 'yes', 'yes2', 'stop', 'again', 'on'])
def test_a_repeat_a_command_or_a_try_starts_none(call, said):
    rig = call(**WIDE)
    plan(rig)
    runs = rig.fast.count
    rig.pump(0.5)
    rig.says(said, speech=1.0)
    assert rig.fast.count == runs


def test_two_words_are_no_job(call):
    rig = call(**WIDE)
    rig.says('налог прибыль', speech=1.0)
    assert rig.fast.count == 0


def test_a_question_the_base_answers_needs_no_job(call):
    rig = call(**WIDE)
    rig.says('что такое семьдесят первый счёт', speech=1.5)
    assert rig.fast.count == 0


def test_a_question_that_needs_a_lookup_prepares_none(call):
    """A job with sources is never a prepared one: this one would be thrown away."""
    rig = call(**WIDE)
    rig.says('какая сейчас ставка ндс', speech=1.5)
    assert rig.fast.count == 0


def test_the_pieces_of_one_breath_are_one_text(call):
    rig = call(**WIDE)
    rig.says('как отразить', speech=1.0)
    rig.pump(0.3)
    rig.says('покупку материалов на складе', speech=1.5)
    assert 'как отразить покупку материалов на складе' in str(rig.fake.run(0).request) or 'как отразить покупку материалов на складе' in str(rig.fake.run(rig.fast.count - 1).request)


def test_a_new_breath_is_a_text_of_its_own(call):
    rig = call(**WIDE)
    rig.says('как отразить покупку', speech=1.0)
    rig.pump(1.2)
    rig.says('налог на прибыль организаций', speech=1.5)
    assert 'как отразить' not in str(rig.fake.run(1).request['input'])


def test_a_long_remark_stops_preparing_at_the_bound_in_words(call):
    """LiveKit's max_speech_duration: a minute of remark is not a job per piece."""
    rig = call(**WIDE)
    for n in range(14):
        rig.says('вот я тут говорю о своём и не спрашиваю', speech=2.0)
        rig.pump(0.2)
    assert rig.fast.count <= PREPARE_WORDS // 9 + 1


def test_after_the_bound_a_new_breath_prepares_again(call):
    rig = call(**WIDE)
    answered = 0
    for n in range(14):
        rig.says('вот я тут говорю о своём и не спрашиваю', speech=2.0)
        rig.pump(0.2)
        while answered < rig.fast.count:             # a job that says nothing for 4 s is a failure: three of them are the breaker
            job_answers(rig, answered, '—')
            answered += 1
    runs = rig.fast.count
    rig.pump(1.2)
    rig.says('что такое амортизация', speech=1.5)
    assert rig.fast.count == runs + 1


def test_the_job_on_a_remark_is_adopted_by_its_final_and_declines(call):
    """The verdict stays the job's: «—», nothing is said."""
    rig = call(**WIDE)
    rig.says('ну вот я сегодня не выспался совсем', speech=2.0)
    rig.w.feed(S.turn_created('u1', 'user', 'Ну'))
    rig.w.feed(S.turn_done('u1', 'user', 'Ну вот я сегодня не выспался совсем'))
    rig.pump(TICK)
    job_answers(rig, 0, '—')
    rig.pump(1.0)
    assert rig.said() == [] and spoken_failures(rig) == [] and rig.fast.count == 1


def test_an_ear_final_that_no_final_follows_says_nothing(call):
    """A prepared job is never adopted by itself."""
    rig = call(**WIDE)
    rig.says('амортизация основных средств', speech=1.5)
    rig.job_says(0, 'Амортизация — перенос стоимости.')
    rig.job_ends(0)
    rig.pump(1.0)
    assert rig.said() == []


# =====================================================================================================================================
# 5. two places for a job (С3): a prepared job is kept until the job on the final has given its text. This changes H2's ruling of one job
# =====================================================================================================================================

LAW_WHOLE = 'В каком году принят закон о бухгалтерском учёте'
LAW_HEAD = 'В каком году принят'
LAW_ANSWER = 'Закон принят в 2011 году.'


def adopted_or_not(fast, text, qid='u1', turn='t1'):
    return fast.release(qid=qid, turn=turn, epoch=1, question=text)


def test_the_prepared_job_is_kept_beside_the_job_on_the_final():
    fast, fake, _ = wide_fast()
    fast.prepare('кто написал войну и мир')
    prepared = fast.job
    assert adopted_or_not(fast, 'Кто написал Анну Каренину') == 'started'
    assert fast.spare is prepared and not prepared.cancelled.is_set() and fast.job is not prepared
    fast.close()


def test_it_goes_when_the_job_on_the_final_has_given_its_text():
    fast, fake, clock = wide_fast()
    fast.prepare('кто написал войну и мир')
    prepared = fast.job
    adopted_or_not(fast, 'Кто написал Анну Каренину')
    fast.poll()
    assert fast.spare is prepared, 'no text yet'
    fake.run(1).say('Лев Толстой.')
    settled(fast)
    events = fast.poll()
    assert fast.spare is None and prepared.cancelled.is_set() and [event['kind'] for event in events] == ['text']
    fast.close()


def test_a_breath_has_two_new_jobs_at_most():
    fast, _, _ = wide_fast()
    for text in ('кто написал войну и мир', 'когда родился пушкин', 'что такое инфляция'):
        fast.prepare(text, breath=1)
    assert fast.count == 2
    fast.prepare('что такое инфляция', breath=2)
    assert fast.count == 3
    fast.close()


def test_the_fitting_one_is_used_when_the_final_goes_on():
    """The cloud cut one utterance in two: the head gets a job, the rest makes it what the ear prepared. Nothing is started a third time."""
    fast, fake, _ = wide_fast()
    fast.prepare(LAW_WHOLE)
    prepared = fast.job
    assert adopted_or_not(fast, LAW_HEAD) == 'started'
    head = fast.job
    assert adopted_or_not(fast, LAW_WHOLE, qid='u2', turn='t2') == 'adopted'
    assert fast.job is prepared and fast.count == 2 and head.cancelled.is_set() and fast.spare is None
    fast.close()


def test_a_job_with_sources_keeps_nothing_beside_it():
    fast, _, _ = wide_fast()
    fast.prepare('кто написал войну и мир')
    prepared = fast.job
    fast.release(qid='u1', turn='t1', epoch=1, question='Кто написал войну и мир', material='источники')
    assert prepared.cancelled.is_set() and fast.spare is None
    fast.close()


def test_a_second_text_keeps_the_first_and_a_third_lets_it_go():
    fast, _, _ = wide_fast()
    fast.prepare('кто написал войну и мир')
    first = fast.job
    fast.prepare('когда родился пушкин')
    second = fast.job
    assert fast.spare is first and not first.cancelled.is_set()
    fast.prepare('что такое инфляция', breath=1)
    assert fast.spare is second and first.cancelled.is_set() and fast.count == 3, 'two places, never three'
    fast.close()


def test_either_of_two_prepared_jobs_may_be_the_final():
    fast, _, _ = wide_fast()
    fast.prepare('кто написал войну и мир')
    first = fast.job
    fast.prepare('когда родился пушкин')
    second = fast.job
    assert adopted_or_not(fast, 'Кто написал Войну и мир') == 'adopted'
    assert fast.job is first and second.cancelled.is_set() and fast.spare is None
    fast.close()


def test_a_text_one_of_them_fits_starts_nothing():
    fast, _, _ = wide_fast()
    fast.prepare('кто написал войну и мир')
    fast.prepare('когда родился пушкин')
    assert fast.prepare('кто написал войну и мир') and fast.count == 2
    fast.close()


def test_what_is_prepared_beside_an_open_answer_waits_and_is_not_touched_by_its_text():
    fast, fake, _ = wide_fast()
    adopted_or_not(fast, 'Кто написал Анну Каренину')
    answer = fast.job
    fast.prepare('когда родился пушкин')
    beside = fast.spare
    assert beside is not None and fast.job is answer
    fake.run(0).say('Лев Толстой.')
    settled(fast)
    fast.poll()
    assert fast.spare is beside and not beside.cancelled.is_set(), 'it was not there for that final: it stays for the next one'
    fast.close()


def test_the_kept_job_has_its_bounds():
    fast, fake, clock = wide_fast()
    fast.prepare('кто написал войну и мир')
    prepared = fast.job
    adopted_or_not(fast, 'Кто написал Анну Каренину')
    clock.advance(FT.FIRST_TEXT_S + 0.1)
    fast.poll()
    assert fast.spare is None and prepared.outcome == 'timeout'
    fast.close()


def test_the_text_of_a_kept_job_reaches_nobody():
    fast, fake, _ = wide_fast()
    fast.prepare('кто написал войну и мир')
    adopted_or_not(fast, 'Кто написал Анну Каренину')
    fake.run(0).say('Толстой написал Войну и мир.')
    settled(fast)
    assert fast.poll() == []
    fake.run(1).say('Лев Толстой.')
    settled(fast)
    assert [event['text'] for event in fast.poll()] == ['Лев Толстой.']
    fast.close()


def test_one_job_as_before_without_the_setting():
    fast, _, _ = manager(strip=lambda text: strip_fillers(text, None))
    fast.prepare('кто написал войну и мир')
    prepared = fast.job
    fast.prepare('когда родился пушкин')
    assert prepared.cancelled.is_set() and fast.spare is None
    second = fast.job
    assert adopted_or_not(fast, 'Кто написал Анну Каренину') == 'started'
    assert second.cancelled.is_set() and fast.spare is None
    fast.close()


def test_a_new_question_cancels_both(call):
    """A job on the final, a job kept beside it, the next question: neither of them says a word."""
    rig = call(**WIDE)
    rig.says('кто написал войну и мир', speech=1.5)
    kept = rig.fast.job
    rig.w.feed(S.turn_done('u1', 'user', 'Кто написал Анну Каренину'))
    rig.pump(TICK)
    old = rig.fast.job
    assert rig.fast.spare is kept
    rig.w.feed(S.turn_done('u2', 'user', 'Что такое инфляция'))
    rig.pump(TICK)
    assert kept.cancelled.is_set() and old.cancelled.is_set() and rig.fast.spare is None and rig.fast.job is not old
    job_answers(rig, rig.fast.count - 1, 'Устойчивый рост цен.')
    assert rig.said() == ['Устойчивый рост цен.']


def test_a_cancelled_job_is_never_spoken(call):
    rig = call(**WIDE)
    rig.says('кто написал войну и мир', speech=1.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Кто написал Анну Каренину'))
    rig.pump(TICK)
    rig.fake.run(0).say('Толстой.')
    rig.job_says(1, 'Лев Толстой.')
    rig.job_ends(1)
    rig.pump(1.0)
    assert rig.said() == ['Лев Толстой.'] and 'Толстой.' not in [text for text in rig.said() if text != 'Лев Толстой.']


def test_the_cloud_cuts_one_utterance_in_two_and_the_job_of_the_ear_answers(call):
    """n1_04 step 10: a final on an open tail, then its rest. The ear has the whole: its job gets a place beside the job on the head."""
    rig = call(**WIDE)
    rig.says(LAW_WHOLE.casefold(), speech=2.5)
    rig.w.feed(S.turn_created('u1', 'user', 'В'))
    rig.w.feed(S.turn_done('u1', 'user', LAW_HEAD))
    rig.pump(TICK)
    rig.w.feed(S.turn_created('u2', 'user', 'о'))
    rig.w.feed(S.turn_done('u2', 'user', 'о бухгалтерском учёте'))
    rig.pump(TICK * 3)
    job_answers(rig, 0, LAW_ANSWER)
    assert rig.said() == [LAW_ANSWER] and rig.fast.count <= 2


# -- the replays, before and after: what the quota pays, and that nothing stale is ever said ---------------------------------------------------------------------------------

CALL_1027_REPLAY = json.loads((Path(__file__).parent / 'fixtures' / 'call_1027_replay.json').read_text(encoding='utf-8'))
ANSWERS_1027 = (('51 счет', 'Счёт 51 «Расчётные счета» учитывает деньги на счетах в банке.'), ('89', NO_89), ('пятнадцатый счёт', 'Счёт 15 — заготовление и приобретение материалов.'), ('битва при калке', 'Битва на реке Калке произошла в 1223 году.'),
                ('инфляция', 'Инфляция — это устойчивый рост общего уровня цен.'))


def job_of_1027(question):
    heard = question.rsplit('Сейчас прозвучало: ', 1)[-1].casefold()
    return next((answer for words, answer in ANSWERS_1027 if words in heard), '—')


def replay_1027(rig, monkeypatch, *, late=1.2):
    """Every event of the cloud and of the ear at its time, the job answering ``late`` seconds after it is asked. The model's delegations are not in it."""
    monkeypatch.setattr(T3, 'CALL_2034', [tuple(row) for row in CALL_1027_REPLAY['cloud']])
    monkeypatch.setattr(T3, 'CALL_EAR', [tuple(row) for row in CALL_1027_REPLAY['ear']])
    return the_whole_call(rig, job=job_of_1027, late=late, until=566.0)


def jobs(notes):
    """What the journal has of a replay: all of them, by what they started on, the adopted ones, and how long the text of those had been waiting."""
    rows = lines(notes, 'fast_job')
    return len(rows), Counter(row['on'] for row in rows), [line['ready_ms'] for line in lines(notes, 'fast_adopted')]


def finals(rows):
    return sum(1 for row in rows if row[1] == 'user')


def into_speech_of(cues, ear):
    return [(at, text) for at, text, _ in cues if any(onset + ONSET_HOLD_MAX_S + GRID < at < offset for onset, offset, _, _ in ear)]


@pytest.mark.parametrize('wide', [False, True], ids=['off', 'on'])
def test_the_replay_of_the_call_of_1027(call, monkeypatch, wide, capsys):
    rig = call(fast_text='on', max_auto_repeats=3, **({'prepare_wide': 'on'} if wide else {}))
    notes = journal(rig)
    cues = replay_1027(rig, monkeypatch)
    rig.fast.close()
    total, on, adopted = jobs(notes)
    with capsys.disabled():
        print(f'\n[H7] 10:27 wide={wide} finals={finals(CALL_1027_REPLAY["cloud"])} ear={len(CALL_1027_REPLAY["ear"])} jobs={total} on={dict(on)} adopted={len(adopted)} ready_ms={adopted} cues={len(cues)}')
    assert into_speech_of(cues, CALL_1027_REPLAY['ear']) == []


@pytest.mark.parametrize('wide', [False, True], ids=['off', 'on'])
def test_the_replay_of_the_call_of_20_34(call, wide, capsys):
    rig = call(fast_text='on', **({'prepare_wide': 'on'} if wide else {}))
    notes = journal(rig)
    cues = the_whole_call(rig)
    rig.fast.close()
    total, on, adopted = jobs(notes)
    with capsys.disabled():
        print(f'\n[H7] 20:34 wide={wide} finals={finals(T3.CALL_2034)} ear={len(T3.CALL_EAR)} jobs={total} on={dict(on)} adopted={len(adopted)} ready_ms={adopted} cues={len(cues)}')
    said = [text for _, text, _ in cues]
    assert '25' in said and any('988' in text for text in said) and not any('1988' in text.replace(' ', '') for text in said)
    assert into_speech(cues) == []


def test_the_same_cues_with_and_without_the_setting(call):
    """The rule of the task: nothing here changes what may be said. The first words of each answer of the call of 20:34, with it and without it."""
    def replayed(**profile):
        rig = call(fast_text='on', **profile)
        cues = the_whole_call(rig)
        rig.fast.close()
        return [text for _, text, _ in cues]
    assert replayed() == replayed(prepare_wide='on')


@pytest.mark.parametrize('late', [0.2, 2.0, 3.5])
def test_the_whole_call_with_the_setting_and_the_job_late(call, late):
    rig = call(fast_text='on', prepare_wide='on')
    assert into_speech(the_whole_call(rig, late=late)) == []


@pytest.mark.parametrize('fail', [(0,), (2,), (4,)], ids=lambda value: f'job{value[0]}')
def test_the_whole_call_with_the_setting_and_a_job_failing(call, fail):
    rig = call(fast_text='on', prepare_wide='on')
    assert into_speech(the_whole_call(rig, fail=fail)) == []


# =====================================================================================================================================
# 6. the ear's text wakes the loop (Б3), the first cue goes at its time (Б4)
# =====================================================================================================================================

def test_the_ears_text_is_taken_before_the_next_tick(call):
    rig = call(**WIDE)
    rig.ear.wake = lambda: rig.w.loop.call_soon(rig.w.wire.ear_wake)
    uid = rig.onset()
    rig.pump(1.5)
    rig.offset()
    rig.w.clock.advance(0.03)
    rig.worker.heard(uid, 'амортизация основных средств')
    rig.w.settle()
    assert rig.fast.count == 1, 'no tick has run'


def test_the_ear_wakes_nobody_with_the_setting_off(call):
    rig = call(fast_text='on')      # an ear: CALL_1027 has none (``ear: off``), so there would be nothing to wake
    assert rig.ear.wake is None
    source = (Path(FT.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    assert "if ear is not None and profile_settings['prepare_wide']=='on':ear.wake=ear_wake" in source


def test_a_wake_and_a_tick_take_a_text_once(call):
    rig = call(**WIDE)
    rig.ear.wake = lambda: rig.w.loop.call_soon(rig.w.wire.ear_wake)
    uid = rig.onset()
    rig.pump(1.5)
    rig.offset()
    rig.worker.heard(uid, 'амортизация основных средств')
    rig.pump(TICK * 3)
    assert rig.fast.count == 1


def test_a_broken_wake_does_not_lose_the_text(call):
    rig = call(**WIDE)

    def broken():
        raise RuntimeError('loop closed')
    rig.ear.wake = broken
    uid = rig.onset()
    rig.pump(1.5)
    rig.offset()
    rig.worker.heard(uid, 'амортизация основных средств')
    rig.pump(TICK)
    assert rig.fast.count == 1


def test_the_first_cue_is_released_at_the_time_of_the_gate_not_on_the_tick_after_it(call):
    rig = call(fast_text='on', prepare_wide='on')
    rig.c.prepared_job = None      # rule 2 off: the ear opens nothing on the job prepared on its text (the key ear_release is deleted, f84a05a9)
    asked(rig, 'что такое инерция')
    ended = None
    uid = rig.onset()
    rig.pump(1.0)
    ended = rig.offset()
    rig.worker.heard(uid, 'э-э')
    rig.pump(TICK)
    asked_at = []
    wire = rig.w.wire
    wire._release_at = asked_at.append
    rig.job_says(0, 'Инерция — свойство тела сохранять скорость.')
    rig.job_ends(0)
    assert asked_at and asked_at[-1] == pytest.approx(ended + EAR_RELEASE_SILENCE_SECONDS)
    assert rig.said() == []
    rig.w.clock.t = ended + EAR_RELEASE_SILENCE_SECONDS + 1e-6
    rig.w.run(wire._release_pending())
    rig.w.settle()
    assert rig.said() == ['свойство тела сохранять скорость.'], 'with no tick'


def test_while_speech_goes_on_no_time_is_set(call):
    rig = call(fast_text='on', prepare_wide='on')
    asked(rig, 'что такое инерция')
    rig.onset()
    asked_at = []
    rig.w.wire._release_at = asked_at.append
    rig.job_says(0, 'Инерция — свойство тела сохранять скорость.')
    rig.job_ends(0)
    assert asked_at == [] and rig.said() == []


def test_without_the_setting_the_tick_looks(call):
    rig = call(fast_text='on')
    hold = rig.c.first_cue_hold()
    assert hold is None or hold[1] is None


def test_a_job_refused_ten_times_is_three_rows_and_one_sum(call, caplog):
    """U07-S4: the single owner of the refusal log: REFUSED_NOTES_PER_JOB rows in full, the rest one fast_refused_sum when the job is accounted; the logger line stays for every refusal."""
    caplog.set_level(logging.INFO, 'echo-sync')
    rig = call(**CALL_1027)
    notes = journal(rig)
    rig.fast.job = job = rig.fast._start('что такое инерция')
    for number in range(10):
        assert not rig.fast._fits(job, 'кто написал войну %d' % number)
    assert len(lines(notes, 'fast_refused')) == FT.REFUSED_NOTES_PER_JOB == 3
    assert lines(notes, 'fast_refused_sum') == []
    assert len(decisions(caplog, 'fast_text refused')) == 10
    job.finish('cancelled')
    rig.fast._account(job)
    rig.fast._account(job)
    [total] = lines(notes, 'fast_refused_sum')
    assert sum(total['rules'].values()) == 7 and total['last_asked'].endswith('войну 9') and total['job'] == job.number and total['last_t'] >= 0


def test_the_refusal_log_of_a_job_reads_back_whole_through_harvest(call):
    """U07-S4 x U06-S5: ONE contract: the sum holds the refusals beyond the noted ones, ``last_t`` is ms after the JOB started; harvest adds the counts and puts the end on the call clock."""
    from tools import harvest as H
    rig = call(**CALL_1027)
    notes = journal(rig)
    rig.fast.job = job = rig.fast._start('что такое инерция')
    for number in range(10):
        rig.fast._fits(job, 'кто написал войну %d' % number)
    job.finish('cancelled')
    rig.fast._account(job)
    rows, at = [{'t': 0, 'ev': 'call_open', 'source': 'phone', 'max_auto_repeats': 3}], 100000
    for ev, fields in notes:
        if ev in ('fast_refused', 'fast_refused_sum'):
            rows.append({'t': at, 'ev': ev, **fields})
            at += 1000
    (one,) = [event for event in H.events(H.read_rows(rows)) if event['label'] == 'refusal']
    assert one['raw'] == 10 and sum(one['rules'].values()) == 10
    [first] = [r for r in rows if r['ev'] == 'fast_refused'][:1]
    [total] = [r for r in rows if r['ev'] == 'fast_refused_sum']
    assert one['t1'] == pytest.approx(max(102.0, 100.0 + max(0, total['last_t'] - first['ms']) / 1000), abs=0.01)


def test_a_job_with_few_refusals_has_no_sum(call):
    rig = call(**CALL_1027)
    notes = journal(rig)
    rig.fast.job = job = rig.fast._start('что такое инерция')
    for number in range(3):
        rig.fast._fits(job, 'кто написал войну %d' % number)
    job.finish('cancelled')
    rig.fast._account(job)
    assert len(lines(notes, 'fast_refused')) == 3 and lines(notes, 'fast_refused_sum') == []

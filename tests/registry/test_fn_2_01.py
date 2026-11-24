"""Функция 2.01 «Вопрос или нет: по форме и «могу ли ответить»». Реестр: РАБОТАЕТ НА СЕРВЕРЕ (на телефоне форма не проверена).
Стенд: helpers_night_memory.Call (настоящие ControlledMedia, fast_text.for_call, журнал звонка; поддельны облако, телефон и текстовая модель). LIVE - живой файл сервера
целиком (65 ключей) через resolve(), как профиль звонка. Отклонения: v6_memory, topic_recap = off (стенд включает их сам, на сервере их нет); host сам ставит preset/ack_match/
on_mismatch (CALL_SETTINGS; строка реестра их не называет); в тестах 5-7 меняется ОДИН ключ (fillers, question_window, cancel_min_words, clarifications - на сервере умолчания кода);
в тестах с cloud= fast_text=off (облако отвечает само, текстовой модели нет). Снаружи: строки журнала judge (форма) и decision, запрос к модели, подсказка. Модель mind отвечает
по содержанию (городу, теме) или молчит; chatty отвечает на всё. 1 форма без «?»: модели уходит вопрос без вводных, подсказка отвечает на него; 2 болтовня из списка не уходит
модели; 3 «могу ли ответить»: реплика без формы принимается (cloud_admitted), если модель ответила; 4 то же без ответа - тишина (контроль к xfail test_9); bank_min_words не
действует (контроллер зовёт analyze с пустым банком), clarifications меняет только метку (test_7b). Остатки К22 и просьба «Подскажи мне …» при ответе облака - xfail. Не меряет облако: звук телефона, живую речь и живую модель."""
import logging

import pytest

import helpers_night_memory as M
import helpers_s6_state as S

LIVE = {
    'preset': 'meaning', 'portion_sense': 'off', 'abbreviations': {}, 'local_ear': 'act',
    'ear_early_ms': 0, 'ear_vocab': 'off', 'fast_text': 'on', 'text_transport': 'http', 
    'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on',     'material_pick': 'on', 'warm_start': 'on', 'instant': 'on', 
    'stumble_place': 'on', 
    'stop_in_flight': 'on', 'gate_text': 'off', 
    'bank_rejoin': 'on', 'brain_short': 'off', 'pcm_cache_mb': 800, 'pcm_record': 'on',
    'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 'facts_journal': 'on', 
    'v5_answer_gate': 'shadow', 'adopt_missing_words': 1, 'spare_helper': 'on', 'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0,
    'open_overlap': 'on', 'inline_repeat': False, 'max_auto_repeats': 3, 
    'conversation_ledger': 'memory', 'recall_words': 'on', 
}
NOT_ON_THE_SERVER = {'topic_recap': 'off'}
FACTS = {'тулы': 'Билет до Тулы стоит 640 рублей.', 'омска': 'Билет до Омска стоит 1900 рублей.', 'мост': 'Мост закрыт на ремонт до пятницы.',
         'норвег': 'Осло - столица Норвегии.', 'ладог': 'Ладога - самое большое озеро Европы. Оно лежит возле Петербурга.'}


def mind(request):
    """The text model: answers a question by what it is about, says nothing to what it has no answer for."""
    return next((answer for key, answer in FACTS.items() if key in M.asked(request).lower()), '—')      # the BRAIN's own way of saying nothing: a stream with no word at all is a failed road, not a decline


def chatty(request):
    """A model that answers anything it is sent (the worst case); an answer that only repeats the question back would be dropped by the product, so it does not."""
    return 'Хорошо, маршрут проложен через новый мост.'


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')


def hear(tmp_path, said, model=mind, then=None, cloud=None, **keys):
    """The words are said (``then``: said 2 s after, while the first answer waits), the model answers by ``model``; ``cloud``: no text model, the cloud answers itself with this text."""
    call = M.Call(tmp_path, mind=model, **{**LIVE, **NOT_ON_THE_SERVER, **({'fast_text': 'off'} if cloud else {}), **keys})
    try:
        call.say(said)
        if then:
            call.pump(2.0, 0.5)
            call.say(then)
        elif cloud:
            call.pump(0.5)
            call.w.feed(S.turn_created('a1', 'assistant', 'О'))
            call.w.feed(S.turn_done('a1', 'assistant', ' ' + cloud))
        call.pump(8.0, 1.0)
        rows = call.journal()
        voiced = call.cues()
        assert len(voiced) <= (2 if then else 1) * (1 + LIVE['max_auto_repeats']), voiced      # the cap of the timer holds: a cue and at most max_auto_repeats silent repeats of it (the speech of the owner, ``then``, starts the count again)
        return {'judge': [(r['kind'], r['reason']) for r in rows if r['ev'] == 'judge'], 'decisions': [(r['kind'], r['reason']) for r in rows if r['ev'] == 'decision'],
                'cues': [c for i, c in enumerate(voiced) if i == 0 or c != voiced[i - 1]], 'voiced': len(voiced), 'asked': [M.asked(request) for _, _, request in call.requests]}
    finally:
        call.close()


@pytest.mark.parametrize('said, to_the_model, cue, form', [('Сколько стоит билет до Тулы', 'Сколько стоит билет до Тулы', FACTS['тулы'], 'question_word'),
                                                          ('так сколько стоит билет до Омска', 'сколько стоит билет до Омска', FACTS['омска'], 'question_word'),
                                                          ('Скажи пожалуйста почему закрыт мост', 'почему закрыт мост', FACTS['мост'], 'question_word'),
                                                          ('Подскажи мне столицу Норвегии', 'мне столицу Норвегии', FACTS['норвег'], 'question_imperative')])
def test_1_a_question_by_form_without_a_mark_goes_to_the_model_and_is_answered_by_its_content(tmp_path, said, to_the_model, cue, form):
    out = hear(tmp_path, said)
    assert out['asked'] == [to_the_model] and out['cues'] == [cue], out          # the lead-in is stripped; the cue answers THIS question
    assert out['judge'] == [('question', form)] and ('question', 'cloud_admitted') not in out['decisions'], out     # the form was known: no admission needed


@pytest.mark.parametrize('said', ['угу', 'Так', 'понятно', 'ладно спасибо'])
def test_2_listed_chatter_is_no_question_even_for_a_model_that_answers_everything(tmp_path, said):
    out = hear(tmp_path, said, model=chatty)
    assert out['asked'] == [] and out['cues'] == [] and not any(kind == 'question' for kind, _ in out['decisions']), out


@pytest.mark.parametrize('said, cue', [('Билет до Тулы я вчера купил', FACTS['тулы']), ('мы летим в Омск', None), ('Норвегия очень красивая страна', FACTS['норвег'])])
def test_3_a_statement_the_model_can_answer_is_admitted_and_cued_by_its_content(tmp_path, said, cue):
    out = hear(tmp_path, said)
    assert out['judge'] == [('silent', 'not_a_question')] and out['asked'] == [said], out        # no form: the model is the judge
    assert out['cues'] == ([cue] if cue else []) and (('question', 'cloud_admitted') in out['decisions']) == bool(cue), out


@pytest.mark.parametrize('said', ['вчера был дождь и мы остались дома', 'ага ладно поехали', 'ну хорошо договорились'])
def test_4_chatter_and_statements_the_model_has_no_answer_for_stay_silent(tmp_path, said):
    out = hear(tmp_path, said)
    assert out['cues'] == [] and ('silent', 'fast_text_declined') in out['decisions'] and not any(kind == 'question' for kind, _ in out['decisions']), out


def test_5_the_fillers_key_decides_which_lead_in_words_are_stripped(tmp_path):
    said = 'давайте сколько стоит билет до Тулы'
    assert hear(tmp_path / 'a', said)['asked'] == [said]                                         # not a filler by default: said as it is
    assert hear(tmp_path / 'b', said, fillers=['давайте'])['asked'] == ['сколько стоит билет до Тулы']
    assert hear(tmp_path / 'c', 'так ' + said[8:], fillers=[])['asked'] == ['так ' + said[8:]]      # the default «так» is no filler when the list is empty


@pytest.mark.parametrize('window, judge, admitted', [(3, ('silent', 'not_a_question'), True), (4, ('question', 'question_word'), False)])
def test_6_the_question_window_decides_how_far_the_question_word_may_stand(tmp_path, window, judge, admitted):
    out = hear(tmp_path, 'в среду вечером почему закрыт мост', question_window=window)        # the 4th word
    assert out['judge'] == [judge] and (('question', 'cloud_admitted') in out['decisions']) == admitted and out['cues'] == [FACTS['мост']], out


@pytest.mark.parametrize('said, minimum, judge, retires', [('Как глубоко', 3, ('silent', 'mismatch_policy_silent'), False), ('Как глубоко', 2, ('question', 'question_word'), True),
                                                            ('Почему мост закрыт', 3, ('question', 'question_word'), True), ('Почему мост закрыт', 4, ('silent', 'mismatch_policy_silent'), True)])
def test_7_cancel_min_words_decides_if_a_short_question_by_form_retires_a_waiting_answer(tmp_path, said, minimum, judge, retires):
    out = hear(tmp_path, 'Расскажи про озеро Ладога', then=said, cancel_min_words=minimum)
    assert out['judge'][-1] == judge and out['cues'][0] == 'Ладога - самое большое озеро Европы.', out
    assert (('retire', 'new_question') in out['decisions']) == retires, out          # a weak form retires too when the model can answer it (the last row): «могу ли ответить» wins


@pytest.mark.parametrize('listed, reason', [(None, 'mismatch_policy_silent'), ([], 'only_fillers')])
def test_7b_the_clarifications_key_reaches_the_classifier_but_changes_only_the_label(tmp_path, listed, reason):
    out = hear(tmp_path, 'Расскажи про озеро Ладога', then='а', **({} if listed is None else {'clarifications': listed}))
    assert out['judge'][-1] == ('silent', reason) and out['cues'] == ['Ладога - самое большое озеро Европы.'], out        # the same silence and no new cue either way


@pytest.mark.parametrize('said', ['Назови мне столицу Норвегии', 'Скажи мне сколько стоит билет до Тулы'])
def test_8_control_the_cloud_without_the_model_answers_requests_of_other_form(tmp_path, said):
    out = hear(tmp_path, said, cloud='Ответ облака.')
    assert out['cues'] == ['Ответ облака.'], out


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.01: работает; в единой ветке остаток: «Подскажи мне …» без вопросительного слова при ответе облака без текстовой модели: '
                   'judge question_imperative, но решение silent/not_a_question и question_rejected_at_publish - подсказки нет')
@pytest.mark.parametrize('said', ['Подскажи мне столицу Норвегии', 'Скажи мне название реки в Кракове', 'Подскажи мне номер нужного автобуса'])
def test_8c_a_request_without_a_question_word_is_cued_by_the_cloud_answer_too(tmp_path, said):
    out = hear(tmp_path, said, cloud='Ответ облака.')
    assert out['cues'] == ['Ответ облака.'], out


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.01: остаток К22 - болтовня из нескольких слов вне списка и не-вопросы уходят текстовой модели, и если она что-то сказала, это звучит')
@pytest.mark.parametrize('said', ['ага ладно поехали', 'ну хорошо договорились', 'Городские сборы, акцизный налог'])
def test_9_chatter_outside_the_list_is_not_sent_to_the_model_and_not_cued(tmp_path, said):
    out = hear(tmp_path, said, model=chatty)           # judge says not_a_question (test_4 holds for the same words with a silent model)
    assert out['asked'] == [] and out['cues'] == [], out


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.01: остаток К22 - обрывок из одного вопросительного слова («Как», «Сколько», «Что значит») судится вопросом и уходит модели')
@pytest.mark.parametrize('said', ['Как', 'Сколько', 'Что значит', 'Какая'])
def test_9b_a_bare_question_word_is_a_fragment_not_a_question(tmp_path, said):
    out = hear(tmp_path, said)
    assert out['asked'] == [] and not any(kind == 'question' for kind, _ in out['judge']), out

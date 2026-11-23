"""Реестр 4.03b «Хвост модели: второй запрос и честный отказ вместо тишины» (одна дорога: ключа tail_guard больше нет, честный отказ и разбор дорог это Roads). Что ТУТ доказано: (1) обрыв или тайм-аут сети не считается отказом
самой модели: сколько бы их ни шло подряд, канал быстрого текста остаётся включённым и следующий вопрос уходит модели; (2) отказ квоты (429) ставит задания на паузу, а не копит отказы.
Чего это не доказывает: фраза «Нет ответа. Повторите вопрос.» и повторный запрос после отказа это контроллер и общий предохранитель, они есть и при tail_guard=off (контрольный тест). Три собственные ошибки модели
гасят канал и без дорог запаса (тоже контроль). Не проверяется стендом: запрос-двойник через 2 с, честный отказ на 8 с, жизнь задания до 12 с, повторная проба через 30 с (часы быстрого текста настоящие, а модель стенда отвечает сразу):
это замер на ноутбуке и модульные тесты tests/test_roads_refusal.py, tests/test_roads_channel.py, tests/test_never_silent.py. Граница: сценарная модель, которая бросает исключения."""
import _h4 as H
from echo_sync.codex_road import FastTextError      # исключение транспорта модели (граница): так сеть сообщает «квота»

QUESTIONS = ['Какая река самая длинная в Африке?', 'Сколько спутников у Марса?', 'Из чего варят борщ?', 'Где находится город Ольштын?']
LAST = 'Какой газ самый лёгкий?'
ANSWER = 'Самый лёгкий газ — водород.'
NO_ANSWER = 'Нет ответа. Повторите вопрос.'


def broken_model(failure):
    """Модель, которая на вопросы QUESTIONS падает с ``failure``, а на LAST отвечает."""
    def answers(question, request):
        if question == LAST:
            return ANSWER
        raise failure('scripted')
    return H.Model(answers)


def test_failures_of_the_net_in_a_row_never_switch_the_channel_off(tmp_path, monkeypatch):
    model = broken_model(TimeoutError)                        # тайм-аут сети: не вина модели

    async def body(host):
        for question in QUESTIONS:
            await H.say(host, question)
            await host.advance(10)                            # облако молчит дольше 8 с
        await H.say(host, LAST)
        await host.advance(3)
        return H.journal(host), list(host.spoken())

    rows, spoken = H.play(tmp_path, monkeypatch, body, model=model)
    assert set(QUESTIONS) <= set(model.questions()), 'every failed question was sent to the model: %s' % model.questions()
    assert model.questions()[-1] == LAST, 'the fifth question went to the model after four net failures: %s' % model.questions()
    assert ANSWER in spoken, 'the model answer of the fifth question was spoken: %s' % spoken
    assert ('answer', 'fast_text_owns') in H.decisions(rows)


def test_a_quota_refusal_rests_the_first_road_but_never_bans_it_the_next_question_is_asked_of_it_when_no_road_is_left(tmp_path, monkeypatch):
    """Отказ квоты (429): первая дорога отдыхает 600 с, но отдых это порядок, а не запрет (``Roads.order``): других дорог нет, и следующий вопрос уходит ей же: связь возвращается без нового звонка."""
    def answers(question, request):
        if question == QUESTIONS[0]:
            raise FastTextError('http_429')
        return ANSWER
    model = H.Model(answers)

    async def body(host):
        await H.say(host, QUESTIONS[0])
        await host.advance(3)
        await H.say(host, QUESTIONS[1])
        await host.advance(3)
        return H.journal(host)

    rows = H.play(tmp_path, monkeypatch, body, model=model)
    assert model.questions() == [QUESTIONS[0], QUESTIONS[1]], 'a rest is an order, not a ban: the next question is asked again: %s' % model.questions()
    assert H.decisions(rows)[-1] != ('answer', 'fast_text_failed_handed_back') and ('answer', 'fast_text_owns') in H.decisions(rows), H.decisions(rows)


def test_control_a_failed_question_is_asked_again_and_the_person_hears_a_phrase(tmp_path, monkeypatch):
    """Контроль: после отказа единственной дороги вопрос возвращается облаку сразу, повторного запроса той же дороге нет (``Roads``: дороги мертвы), человек слышит фразу вместо тишины."""
    model = broken_model(TimeoutError)

    async def body(host):
        await H.say(host, QUESTIONS[0])
        await host.advance(10)
        return H.journal(host), list(host.spoken())

    rows, spoken = H.play(tmp_path, monkeypatch, body, model=model)
    assert model.questions() == [QUESTIONS[0]], model.questions()
    assert ('answer', 'fast_text_failed_asked_again') in H.decisions(rows)
    assert spoken == [NO_ANSWER], 'a failed question is answered with the phrase, not silence: %s' % spoken


def test_three_own_errors_of_the_model_never_put_it_out_the_roads_own_the_verdict(tmp_path, monkeypatch):
    """Предохранителя нет: сколько бы своих ошибок модели ни было подряд, следующий вопрос уходит той же дороге (она отдыхает, но не под запретом)."""
    model = broken_model(RuntimeError)

    async def body(host):
        for question in QUESTIONS:
            await H.say(host, question)
            await host.advance(3)

    H.play(tmp_path, monkeypatch, body, model=model)
    assert set(model.questions()) == set(QUESTIONS), 'every question is asked of the model: %s' % model.questions()

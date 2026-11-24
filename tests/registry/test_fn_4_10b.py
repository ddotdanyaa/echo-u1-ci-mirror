"""4.10b: короткая инструкция BRAIN (brain_short) и начало ответа словами вопроса (lead_cue). Реестр: brain_short ВЫКЛЮЧЕН на сервере; начало ответа словами вопроса (lead_cue) с f84a05a9 правило владельца без ключа: действует при fast_text on.
Тесты brain_short идут под живым профилем и помечены xfail(strict); «при включённом ключе» — тот же сценарий с ключом on. Тесты начала ответа идут под живым профилем без отметки."""
import pytest

import _h4 as H

QS = ['Какая река течёт через Прагу?', 'Какая гора самая высокая в Альпах?', 'Какое озеро самое глубокое в мире?', 'Как называется столица Норвегии?',
      'Какой океан самый маленький?', 'Какая пустыня самая большая в Африке?']
LONG = 'Это ответ на вопрос номер %d. ' + 'Дальше идёт подробное продолжение ответа. ' * 12
WHEN = 'Когда была основана Венеция?'
LEAD = 'Венеция была основана'
OFF = 'реестр 4.10b: выключено, brain_short=off'


def brain_scene(tmp_path, monkeypatch, **own):
    """Шесть вопросов подряд с длинными ответами; что движок послал модели: инструкция первого запроса и история последнего."""
    model = H.Model(lambda q, r: LONG % (QS.index(q) + 1) if q in QS else None)

    async def body(host):
        for question in QS:
            await H.say(host, question)
            await host.advance(1)
    H.play(tmp_path, monkeypatch, body, model=model, **own)
    assert model.questions() == QS, model.questions()
    first, last = model.requests[0].request['instructions'], model.requests[-1].request['instructions']
    history = last.split('Последние реплики этого разговора')[1].split('\n') if 'Последние реплики этого разговора' in last else []
    return first, [line for line in history if line.startswith('Ответ: ')]


def check_brain(first, answers):
    assert len(first) < 2600, 'the BRAIN sent to the model is short: %d chars' % len(first)
    for rule in ('выведи ровно один символ: —', '[стоп]', 'Первые слова', 'цифрами'):
        assert rule in first, rule                                  # короткая, но правила на месте
    assert 1 <= len(answers) <= 3 and all(len(line) <= len('Ответ: ') + 200 for line in answers), [len(a) for a in answers]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=OFF)
def test_b_short_brain_and_short_history_go_to_the_model(tmp_path, monkeypatch):
    check_brain(*brain_scene(tmp_path, monkeypatch))


def test_b_short_brain_and_short_history_go_to_the_model_with_the_key_on(tmp_path, monkeypatch):
    check_brain(*brain_scene(tmp_path, monkeypatch, brain_short='on'))


def test_the_scene_itself_is_sound_the_model_gets_every_question_and_the_long_text_is_there(tmp_path, monkeypatch):
    first, answers = brain_scene(tmp_path, monkeypatch)
    assert 'Ты суфлёр' in first and 'Первые слова' in first and answers, (len(first), answers)


def lead_scene(tmp_path, monkeypatch, model, **own):
    async def body(host):
        await H.say(host, WHEN)
        await host.advance(3)
        return H.journal(host), host.spoken()
    rows, spoken = H.play(tmp_path, monkeypatch, body, model=model, **own)
    assert model.questions() == [WHEN]
    return rows, spoken


def check_lead_first(rows, spoken):
    """Модель молчит, а человек сразу слышит начало ответа словами вопроса, в форме, как они стояли в вопросе."""
    assert spoken and spoken[0] == LEAD, spoken


def check_lead_then_substance(rows, spoken):
    """Модель отвечает с сути: начало засчитано сказанным, ответ идёт дальше без повтора слов начала."""
    assert ('ack', 'lead_passed') in H.decisions(rows), H.decisions(rows)
    assert spoken and 'пятом веке' in spoken[0] and 'Венеция' not in spoken[0], spoken


def test_b_the_answer_opens_with_the_words_of_the_question_while_the_model_is_silent(tmp_path, monkeypatch):
    check_lead_first(*lead_scene(tmp_path, monkeypatch, H.Model({})))


def test_b_substance_follows_the_lead_without_repeating_it(tmp_path, monkeypatch):
    check_lead_then_substance(*lead_scene(tmp_path, monkeypatch, H.Model({'венеци': 'В пятом веке. Город стоит на островах лагуны.'})))


def test_a_yes_no_question_gets_no_lead_and_the_model_answer_goes_as_it_is(tmp_path, monkeypatch):
    """Контроль: вопрос «да или нет» начала не получает никогда; ответ модели звучит как есть."""
    async def body(host):
        await H.say(host, 'Правда ли, что Луна меньше Земли?')
        await host.advance(2)
        return host.spoken()
    spoken = H.play(tmp_path, monkeypatch, body, model={'луна': 'Да, меньше. Её диаметр около четверти земного.'})
    assert spoken[0] == 'Да, меньше.', spoken

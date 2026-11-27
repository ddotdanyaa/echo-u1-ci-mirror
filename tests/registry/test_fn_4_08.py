"""Реестр 4.08 «Верность ответа: условия вопроса, ложная посылка, вторая модель»: ТОЛЬКО В ВЕТКЕ, ключа в сборке нет, в коде единой ветки проверки ответа нет (случай C: не сделано).
Человек должен получить ответ, который не нарушает отрицание, единицы и не принимает ложную посылку; ошибку первого ответа должен поймать второй взгляд (вторая модель). Сценарная модель
(граница) на вопрос отвечает неверно, а на любой запрос, в который попал её же первый ответ (так выглядит повторный взгляд), верно. Движок выдаёт первый ответ как есть: целевые тесты xfail(strict).
Контроли зелёные: верный первый ответ звучит и уходит одним запросом; на возражение человека («ты уверен?») исправление звучит, значит краснота целевых от отсутствия автоматической проверки.
Проверка на пустышку: ECHO_REGISTRY_SET="fast_text=off" краснит контроли; --runxfail показывает, что движок сказал вместо ожидаемого."""
import json

import pytest

import _h4 as H

CASES = {      # условие вопроса (отрицание, единицы), ложная посылка: (вопрос, неверный ответ модели, верный ответ)
    'negation': ('Назови самую большую планету Солнечной системы, кроме Юпитера.', 'Юпитер — самая большая планета Солнечной системы.', 'Это Сатурн.'),
    'units': ('Какова высота горы Эверест в метрах?', 'Высота Эвереста — 29 тысяч футов.', '8849 метров.'),
    'premise': ('Почему Солнце вращается вокруг Земли?', 'Солнце вращается вокруг Земли, потому что её притягивает.', 'Нет, это Земля вращается вокруг Солнца.'),
}


def model_for(case):
    _, wrong, right = CASES[case]

    def answers(asked, request):      # первый взгляд: неверно; запрос, в котором уже лежит первый ответ (повторный взгляд или спор человека): верно
        return right if wrong in json.dumps(request, ensure_ascii=False) else wrong
    return H.Model(answers)


def play(tmp_path, monkeypatch, case, challenge=False, correct_first=False):
    question, wrong, right = CASES[case]
    model = H.Model({question: right}) if correct_first else model_for(case)

    async def body(host):
        await H.say(host, question)
        await host.advance(3)
        if challenge:
            await H.say(host, 'Ты уверен в этом ответе?')
            await host.advance(3)
        return host.spoken()

    return model, H.play(tmp_path, monkeypatch, body, model=model)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 4.08: только в ветке, проверки ответа и второй модели в единой ветке нет: неверный первый ответ выдаётся как есть')
@pytest.mark.parametrize('case', sorted(CASES))
def test_a_wrong_first_answer_is_caught_before_the_person_hears_it(tmp_path, monkeypatch, case):
    _, wrong, right = CASES[case]
    model, spoken = play(tmp_path, monkeypatch, case)
    assert wrong not in spoken, ('the person was given the answer that breaks the question', spoken)
    assert right in spoken, ('the corrected answer was never given', spoken, model.questions())


@pytest.mark.parametrize('case', sorted(CASES))
def test_control_a_right_first_answer_is_spoken_by_one_request(tmp_path, monkeypatch, case):
    question, _, right = CASES[case]
    model, spoken = play(tmp_path, monkeypatch, case, correct_first=True)
    assert spoken[:1] == [right], spoken
    assert model.questions() == [question], 'a right answer needs one request only'


@pytest.mark.parametrize('case', sorted(CASES))
def test_control_the_person_challenging_the_answer_gets_it_corrected(tmp_path, monkeypatch, case):
    _, wrong, right = CASES[case]
    model, spoken = play(tmp_path, monkeypatch, case, challenge=True)
    assert wrong in spoken and right in spoken and spoken.index(wrong) < spoken.index(right), spoken      # ошибку никто не ловил сам: она прозвучала, поправил её только спор человека
    assert len(model.requests) == 2, model.questions()


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

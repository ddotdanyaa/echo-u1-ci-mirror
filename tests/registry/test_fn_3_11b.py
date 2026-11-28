"""Реестр 3.11b: вести по подготовленному тексту порциями (prepared_speech). Всегда включено (ключа нет: правило хозяина, 16.11).
Человек положил доклад в materials/context.md и сказал «Начинаем»: система без вопроса к модели идёт по тексту, порцию за порцией (следующая после того, как порцию повторили вслух);
вопрос в середине получает ответ, и после него доклад продолжается с той порции, на которой остановился.
"""
import _h3 as H

SPEECH = ('Добрый день, друзья. Сегодня я расскажу о том, как устроены приливы. Их вызывает притяжение Луны. '
          'Дважды в сутки вода поднимается и опускается. У берегов бухты Фанди перепад достигает шестнадцати метров.')
QUESTION = 'А почему приливы бывают дважды в сутки?'
ANSWER = 'Потому что Земля вращается под лунной волной.'


def last(host):
    return (host.spoken() or [''])[-1]                      # пустая подсказка: проверка упадёт на утверждении, а не на индексе


def scenario(tmp_path, monkeypatch, **own):
    model = H.Model({'почему': ANSWER})                    # модель знает только про вопрос из середины; на «Начинаем» ответила бы '—'

    async def body(host):
        await H.say(host, 'Начинаем')
        first = last(host)
        await H.say(host, first)                            # человек повторил первую порцию вслух
        second = last(host)
        await host.advance(1)
        await H.say(host, QUESTION)                         # вопрос в середине доклада
        answer = last(host)
        await host.advance(1)
        await H.say(host, answer)                           # ответ повторён вслух
        await host.advance(1)
        return first, second, answer, last(host), H.journal(host)

    return model, H.play(tmp_path, monkeypatch, body, model=model, files={'materials/context.md': SPEECH}, **own)


def check(model, result):
    first, second, answer, resumed, rows = result
    assert first.startswith('Добрый день') and first in SPEECH, ('the first portion is the start of the prepared text', first)
    assert second != first and second in SPEECH and SPEECH.index(second) > SPEECH.index(first), ('the next portion follows it in the text', second)
    assert len(model.questions()) == 1 and 'почему приливы' in model.questions()[0], ('the text went with no question to the model; only the real question did', model.questions())
    assert 'Земля' in answer, ('a question in the middle gets its answer', answer)
    assert resumed == second, ('after the answer the speech goes on with the portion that was waiting', resumed, second)


def test_b_live_profile_the_speech_is_led_by_portions(tmp_path, monkeypatch):
    model, result = scenario(tmp_path, monkeypatch)
    check(model, result)


def test_b_the_speech_decisions_are_in_the_journal(tmp_path, monkeypatch):
    model, result = scenario(tmp_path, monkeypatch)
    check(model, result)
    assert ('question', 'speech_start') in H.decisions(result[4]) and ('resume', 'speech_goes_on') in H.decisions(result[4])

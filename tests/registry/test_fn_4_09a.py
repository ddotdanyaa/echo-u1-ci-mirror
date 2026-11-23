"""4.09a: честная фраза на личный изменчивый вопрос («что у меня в календаре», «какой у меня баланс»): короткая фраза сразу, без модели и поиска, а не выдуманные данные.
Правило хозяина ответа, без ключа. Личный вопрос получает честную фразу, контроль на обычном вопросе."""
import pytest

import _h4 as H

INVENTED = {'баланс': 'На вашем счету четыреста рублей.', 'календар': 'Сегодня у вас обед в час и звонок в три.', 'посылк': 'Ваша посылка приедет завтра.'}
PERSONAL = ['Какой у меня сейчас баланс?', 'Что у меня сегодня в календаре?', 'Где моя посылка?']


def personal_questions(tmp_path, monkeypatch, **own):
    """Каждый личный вопрос в отдельном звонке: модель, спроси её, выдумала бы данные; человек ждёт секунду."""
    out = []
    for number, question in enumerate(PERSONAL):
        model = H.Model(INVENTED)

        async def body(host):
            await H.say(host, question)
            await host.advance(1)
            return H.journal(host), host.spoken()
        rows, spoken = H.play(tmp_path / str(number), monkeypatch, body, model=model, **own)
        out.append((question, model.questions(), spoken, rows))
    return out


def check_honest(results):
    for question, asked, spoken, rows in results:
        assert asked == [], (question, 'личный вопрос ушёл модели', asked)
        assert spoken, (question, 'подсказки нет')
        first = spoken[0].casefold()
        assert 'нет доступа' in first or 'не вижу' in first or 'не знаю' in first, (question, spoken)
        assert not any(ch.isdigit() for ch in ''.join(spoken)) and 'рубл' not in ''.join(spoken), (question, spoken)
        assert ('question', 'local_reference') in H.decisions(rows), (question, H.decisions(rows))


def test_b_personal_volatile_question_gets_an_honest_phrase_at_once_without_the_model(tmp_path, monkeypatch):
    check_honest(personal_questions(tmp_path, monkeypatch))


def test_control_ordinary_and_task_questions_still_go_to_the_model(tmp_path, monkeypatch):
    texts = ['Какая столица у Перу?', 'Если у меня в кошельке сто монет, сколько останется после покупки?']
    model = H.Model({'столица': 'Столица Перу — Лима.', 'кошельк': 'Останется немного монет.'})

    async def body(host):
        for text in texts:
            await H.say(host, text)
            await host.advance(4)
        return host.spoken()
    spoken = H.play(tmp_path, monkeypatch, body, model=model)
    assert model.questions() == texts, model.questions()
    assert any('Лима' in cue for cue in spoken), spoken
    assert not any('нет доступа' in cue for cue in spoken), spoken

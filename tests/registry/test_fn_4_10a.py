"""Реестр 4.10a: форма подсказки, ответ а не пересказ задания. Человек слышит первым словом сам ответ (число, имя, да или нет), а не вступление и не пересказ вопроса.
Снаружи это видно двумя вещами: правила формы в инструкции, что ушла модели (fast_text, BRAIN_KEEP), и первая подсказка телефону. Ключа у функции нет, живой профиль её включает.
Модель стенда сценарная: она слушается правила, если оно есть в ушедшей инструкции, и иначе начинает с пересказа вопроса (так видно, что красное от самой инструкции).
Проверка на пустышку (ключа нет): плагин вне репозитория убирает правила формы из инструкции, тест не меняется."""
import _h4 as H

RULES = ('Первые слова ответа и есть ответ', 'Никаких вступлений', 'Сначала суть одной законченной фразой')
QUESTIONS = {'Сколько спутников у Марса?': ('Два. Их зовут Фобос и Деймос.', 'Два.'),
             'Правда ли, что Луна старше Земли?': ('Нет. Луна образовалась позже Земли.', 'Нет.'),
             'Какой город стоит на реке Рейн и славится собором?': ('Кёльн. Его собор строили несколько веков.', 'Кёльн.')}
PREAMBLE = 'Вы спрашиваете: %s. '


def obedient(question, request):
    """Модель, что следует правилам формы, если они ей даны; без правил пересказывает задание."""
    known = [q for q in QUESTIONS if q.casefold() == question.casefold()]
    if not known:
        return None                                       # не вопрос: модель молчит
    answer = QUESTIONS[known[0]][0]
    given = request['instructions']
    return answer if all(rule in given for rule in RULES) else PREAMBLE % question.rstrip('?') + answer


def call(tmp_path, monkeypatch):
    model = H.Model(obedient)

    async def body(host):
        firsts = []
        for question in QUESTIONS:
            await H.say(host, question)
            await host.advance(3)
            firsts.append(host.spoken()[-1])
            await H.say(host, 'Хорошо, понятно, пойдём дальше.')      # реплика без вопроса, чтобы следующий вопрос был новым заданием
            await host.advance(1)
        return firsts, H.journal(host)

    firsts, rows = H.play(tmp_path, monkeypatch, body, model=model)
    return model, firsts, rows


def test_a_every_request_to_the_model_carries_the_answer_first_rules(tmp_path, monkeypatch):
    model, _, _ = call(tmp_path, monkeypatch)
    assert set(QUESTIONS) <= set(model.questions()), model.questions()
    for item in model.requests:
        if item.question in QUESTIONS:
            missing = [rule for rule in RULES if rule not in item.request['instructions']]
            assert not missing, (item.question, missing)


def test_a_the_first_published_cue_opens_with_the_answer_not_a_retelling(tmp_path, monkeypatch):
    _, firsts, rows = call(tmp_path, monkeypatch)
    for first, (_, head) in zip(firsts, QUESTIONS.values()):
        assert first.startswith(head), (first, head)
        assert 'спрашиваете' not in first, first
    assert ('answer', 'fast_text_owns') in H.decisions(rows)
    assert [text for text in H.cues(rows) if text.startswith('Вы спрашиваете')] == []

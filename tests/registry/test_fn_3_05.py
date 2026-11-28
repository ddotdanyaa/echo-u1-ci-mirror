"""Реестр 3.05 «Ждущая порция и новый вопрос»: пока порция ждёт повтора, новый вопрос человека принимается: уходит модели и получает свой ответ.
Реестр: СЛОМАНО (выключателя нет). Целевой тест xfail(strict); контрольные зелёные: тот же вопрос, когда ничего не ждёт, и ясный вопрос (с вопросительным словом) при ждущей порции.
Закреплённая поломка (test_PINNED_BREAKAGE_*, зелёные): НЕ «функция работает», а текущее неправильное поведение; снять вместе с xfail целевого теста, когда поломку починят.
Пустышка: ECHO_REGISTRY_SET="fast_text=off" краснит контрольные; целевой при --runxfail падает на «the new question never reached the model».
Воспроизведение держится на форме вопроса: тема та же, что у порции, два-три слова общие с ней, вопросительного слова нет."""
import pytest
import _h3 as H

QUESTION = 'Что такое солнечное затмение?'
PORTION = 'Солнечное затмение — это когда Луна закрывает Солнце от наблюдателя на Земле. Оно длится несколько минут. Такое случается несколько раз в год.'
# новые вопросы человека на ту же тему, что и порция: общие слова с порцией (солнечное затмение, несколько минут, Луна закрывает Солнце), вопросительного слова нет
NEW = {
    'Солнечное затмение длится несколько минут или дольше': 'Полная фаза длится от силы семь минут.',
    'Солнечное затмение видно из любой точки Земли': 'Нет, полоса полной тени узкая.',
}
# что движок решает сейчас по каждой реплике при ждущей порции (после user_final новой реплики); это закреплённая поломка, не норма
PINNED = {
    'Солнечное затмение длится несколько минут или дольше': [('silent', 'unrelated_speech'), ('silent', 'mismatch_policy_silent'), ('silent', 'said_back')],
    'Солнечное затмение видно из любой точки Земли': [('silent', 'attempt_shared_stem'), ('silent', 'mismatch_policy_silent')],
}
WAITING = 'когда Луна закрывает Солнце от наблюдателя на Земле.'      # порция, что звучит (первая из трёх)
CLEAR = ('Солнечное затмение в каком месяце бывает чаще', 'Чаще всего в апреле и в октябре.')


def model_for(new_answer):
    return H.Model(lambda question, request: PORTION if 'Что такое' in question else new_answer)


def run(tmp_path, monkeypatch, new_question, new_answer, *, waiting_for, **own):
    """Один звонок. waiting_for > 0: сначала вопрос с ответом из трёх предложений, человек молчит это время (порция ждёт повтора), потом новый вопрос.
    waiting_for == 0: новый вопрос задан, когда ничего не ждёт. Возвращает (что звучало после нового вопроса, вопросы модели, журнал)."""
    model = model_for(new_answer)

    async def body(host):
        if waiting_for:
            await H.say(host, QUESTION)
            await host.advance(waiting_for)
        before = len(host.spoken())
        if waiting_for and not before:
            raise RuntimeError('precondition: the first portion never sounded')
        await H.say(host, new_question)
        await host.advance(3)
        return host.spoken()[before:], H.journal(host)

    spoken, rows = H.play(tmp_path, monkeypatch, body, model=model, **own)
    if [row['text'] for row in rows if row['ev'] == 'user_final'][-1] != new_question:
        raise RuntimeError('precondition: the new question did not reach the engine')
    return spoken, model.questions(), rows


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 3.05: сломано: новый вопрос при ждущей порции молчанием или как «попытка повторить» порцию, модель не спрошена')
@pytest.mark.parametrize('new_question', list(NEW))
def test_new_question_is_taken_while_a_portion_waits(tmp_path, monkeypatch, new_question):
    spoken, asked, rows = run(tmp_path, monkeypatch, new_question, NEW[new_question], waiting_for=6)
    assert new_question in asked, ('the new question never reached the model', asked, H.decisions(rows)[-4:])
    assert NEW[new_question] in spoken, ('the new answer was not spoken', spoken[:2], H.decisions(rows)[-4:])


@pytest.mark.parametrize('new_question', list(NEW))
def test_control_same_question_with_nothing_waiting_is_answered(tmp_path, monkeypatch, new_question):
    spoken, asked, rows = run(tmp_path, monkeypatch, new_question, NEW[new_question], waiting_for=0)
    assert asked == [new_question], asked
    assert spoken[:1] == [NEW[new_question]], spoken


def test_control_clear_question_while_a_portion_waits_is_answered(tmp_path, monkeypatch):
    spoken, asked, rows = run(tmp_path, monkeypatch, CLEAR[0], CLEAR[1], waiting_for=6)
    assert CLEAR[0] in asked, asked
    assert spoken[:1] == [CLEAR[1]], spoken


@pytest.mark.parametrize('new_question', list(NEW))
def test_PINNED_BREAKAGE_new_question_dropped_while_a_portion_waits(tmp_path, monkeypatch, new_question):
    """НЕ «функция работает»: закреплена текущая поломка 3.05. Реплика без вопросительного слова при ждущей порции модели не уходит, ответа нет, в журнале причины молчания.
    Снимается вместе с xfail целевого теста, когда поломку починят (тогда этот тест покраснеет: модель спрошена, ответ прозвучал)."""
    spoken, asked, rows = run(tmp_path, monkeypatch, new_question, NEW[new_question], waiting_for=6)
    after = rows[max(i for i, row in enumerate(rows) if row['ev'] == 'user_final') + 1:]
    assert asked == [QUESTION], ('the model was not asked the new question (pinned breakage)', asked)
    assert NEW[new_question] not in spoken, ('no answer to the new question (pinned breakage)', spoken[:2])
    assert H.decisions(after) == PINNED[new_question], ('reasons of the dropped reply (pinned breakage)', H.decisions(after))

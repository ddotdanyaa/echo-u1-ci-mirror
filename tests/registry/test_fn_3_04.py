"""Реестр 3.04: старый ответ не звучит на новый вопрос. Старый ответ (счёт без модели) прозвучал, человек задал новый вопрос; модель на него молчит ('—').
Должно быть: старый ответ после нового вопроса не возвращается сам. Замка нет: плана-возврата правило H6 (_plan_stands) не смотрит на более новый вопрос.
Два пути возврата: (1) план после отказа модели (сценарий scene); (2) ждущая порция и реплика на ту же тему без вопросительного слова (scene_portion: не закрывает, функция 3.05)."""
import pytest

import _h3 as H

OLD_QUESTION = 'Сколько будет девять умножить на семь?'          # движок считает сам: «Шестьдесят три.»
OLD_ANSWER = 'Шестьдесят три.'
NEW_QUESTION = 'Какая самая длинная река в Европе?'
NEW_ANSWER = 'Самая длинная река Европы — Волга.'
BROKEN = pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 3.04: сломано: '
                           'после нового вопроса без ответа модели снова звучит старый «Шестьдесят три.»')
STILL_BROKEN_HINT = 'после нового вопроса прозвучал старый ответ'


def scene(tmp_path, monkeypatch, answers=None, **own):
    """Старый вопрос и ответ, секунда тишины, новый вопрос, 8 с звонка. Возвращает (записи журнала, реплики после нового вопроса, всё сказанное)."""
    async def body(host):
        await H.say(host, OLD_QUESTION)
        await host.advance(1)
        await H.say(host, NEW_QUESTION)
        await host.advance(8)
        return H.journal(host), host.spoken()
    rows, spoken = H.play(tmp_path, monkeypatch, body, model=H.Model(answers or {}), **own)
    start = max(i for i, row in enumerate(rows) if row['ev'] == 'user_final')                 # новый вопрос: последняя реплика человека
    if [row['text'] for row in rows if row['ev'] == 'user_final'] != [OLD_QUESTION, NEW_QUESTION]: raise RuntimeError('both questions did not reach the engine')
    if not (H.cues(rows)[:1] == [OLD_ANSWER] and spoken[:1] == [OLD_ANSWER]): raise RuntimeError('the old answer did not sound for the old question: %s' % spoken)
    return rows, H.cues(rows[start:]), spoken


@BROKEN
def test_target_old_answer_does_not_sound_on_a_new_question(tmp_path, monkeypatch):
    rows, after, _ = scene(tmp_path, monkeypatch)
    if ('silent', 'fast_text_declined') not in H.decisions(rows): raise RuntimeError('the model did not decline the new question')
    assert OLD_ANSWER not in after, '%s: %s' % (STILL_BROKEN_HINT, after)


def test_control_a_new_question_with_an_answer_has_no_old_answer_after_it(tmp_path, monkeypatch):
    rows, after, spoken = scene(tmp_path, monkeypatch, answers={'река': NEW_ANSWER})
    assert ('answer', 'fast_text_owns') in H.decisions(rows)
    assert after and set(after) == {NEW_ANSWER}, after
    assert spoken[0] == OLD_ANSWER and OLD_ANSWER not in spoken[1:], spoken


# Путь 2: ждущая порция. Ответ из нескольких предложений выдаётся порциями, человек молчит (порция повторяется), затем реплика на ту же тему без вопросительного слова, с общими с порцией словами.
PORTION_QUESTION = 'Что такое дельта реки?'
PORTION_ANSWER = 'Дельта реки — это место, где река делится на рукава и впадает в море. Обычно она плоская и болотистая. Самая известная дельта лежит у Нила.'
REMARK = 'Дельта реки видна из космоса'                       # общее с порцией: «Дельта реки», вопросительного слова нет
CLEAR_QUESTION = 'В какой стране лежит самая большая дельта реки'     # та же тема, но вопросительное слово в начале
REMARK_ANSWER = 'Во Вьетнаме.'
BROKEN_PORTION = pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 3.04: сломано: на пути ждущей порции старый ответ звучит на новый вопрос, и при включённом замке тоже')


def scene_portion(tmp_path, monkeypatch, remark=REMARK, **own):
    """Вопрос с ответом из трёх предложений, 6 с молчания (порция ждёт повтора), реплика человека, 8 с звонка. Возвращает (вопросы модели, прежние порции, звучало после реплики, журнал)."""
    model = H.Model(lambda question, request: PORTION_ANSWER if 'Что такое' in question else REMARK_ANSWER)

    async def body(host):
        await H.say(host, PORTION_QUESTION)
        await host.advance(6)
        before = host.spoken()
        await H.say(host, remark)
        await host.advance(8)
        return before, host.spoken()[len(before):], H.journal(host)
    before, after, rows = H.play(tmp_path, monkeypatch, body, model=model, **own)
    if [row['text'] for row in rows if row['ev'] == 'user_final'] != [PORTION_QUESTION, remark]: raise RuntimeError('both utterances did not reach the engine')
    if not before or any(cue != before[0] for cue in before): raise RuntimeError('the portion did not wait for a repeat: %s' % before)
    return model.questions(), before[0], after, rows


@BROKEN_PORTION
def test_target_waiting_portion_does_not_sound_over_a_new_question(tmp_path, monkeypatch):
    asked, old, after, rows = scene_portion(tmp_path, monkeypatch)
    assert old not in after, '%s: %s, решения: %s' % (STILL_BROKEN_HINT, after[:2], H.decisions(rows)[-4:])


def test_control_clear_question_over_a_waiting_portion_gets_its_own_answer(tmp_path, monkeypatch):
    asked, old, after, rows = scene_portion(tmp_path, monkeypatch, remark=CLEAR_QUESTION)
    assert CLEAR_QUESTION in asked, asked
    assert after[:1] == [REMARK_ANSWER] and old not in after, after

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

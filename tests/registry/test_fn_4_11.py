"""Реестр 4.11 «Свидетель ответа: третий источник поправляет число»: задание сказало одно число, облачный голос в своём ответе другое; сверяет их, а решает третий источник (банк, законы, материал):
человек должен услышать поправку числа. В единой ветке это только тень (ключа нет, сверка идёт всегда; режима «on» нет): строка журнала witness, вслух ничего не меняется.
Ключ answer_witness удалён: сверка идёт всегда при текстовом канале (строка журнала witness), вслух ничего не меняется; целевой xfail остаётся красным (--runxfail).
Граница: файл-банк ноутбука (выдуманный). Стенд: часы виртуальные и недоступны потоку третьего источника, поэтому его вердикт witness_third в стенде не наблюдается."""
import json

import pytest

import _h4 as H

QUESTION = 'Какой срок гарантии на ремонт часов в мастерской Ромашка?'
JOB = 'Три месяца, а на механизм — шесть месяцев.'               # задание ведёт с числа 3
REPLY = 'Сейчас посмотрю. На ремонт часов в мастерской Ромашка гарантия до шести месяцев. Остальное уточню.'      # облачный голос: 6
BANK = [{'q': 'Гарантийный срок ремонта часов мастерская Ромашка условия', 'answer': 'Гарантия на ремонт часов в мастерской Ромашка шесть месяцев.', 'source': 'выдуманный'}]


def scenario(tmp_path, monkeypatch, reply=REPLY, **own):
    """Вопрос вне банка уходит заданию; пока звучит его ответ, облако отвечает своим числом. Возвращает (записи журнала, подсказки телефону, вопросы модели)."""
    model = H.Model({'гарант': JOB})

    async def body(host):
        await H.say(host, QUESTION)
        await host.advance(0.5)
        await H.cloud_answer(host, reply)
        await host.advance(3)
        return H.journal(host), host.spoken()
    files = {'bank.json': json.dumps(BANK, ensure_ascii=False)}
    rows, spoken = H.play(tmp_path, monkeypatch, body, model=model, files=files, instant_bank_file=str(tmp_path / 'home' / 'bank.json'), **own)
    return rows, spoken, model.questions()


def corrected(spoken):
    """Человек услышал поправку числа по третьему источнику (шесть месяцев вместо трёх), а не только ответ задания."""
    return any('Поправка' in text and 'шести месяцев' in text for text in spoken)


def witness(rows):
    return [row for row in rows if row['ev'] == 'witness']


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 4.11: ВЫКЛЮЧЕНО (answer_witness=off); и в тени поправку вслух не говорит, режима «on» нет')
def test_target_the_third_source_corrects_the_number_aloud(tmp_path, monkeypatch):
    rows, spoken, asked = scenario(tmp_path, monkeypatch)
    assert asked == [QUESTION] and spoken[0] == JOB, (asked, spoken)         # предусловие: задание ответило числом 3
    assert corrected(spoken), spoken


def test_under_the_live_profile_the_numbers_are_compared_in_the_journal_and_the_job_answer_is_all_that_is_said(tmp_path, monkeypatch):
    rows, spoken, asked = scenario(tmp_path, monkeypatch)
    assert asked == [QUESTION] and spoken[0] == JOB and set(spoken) == {JOB}, (asked, spoken)
    assert len(witness(rows)) == 1, 'the witness is a rule of the text channel now: one line of the call trace'


def test_in_shadow_the_two_numbers_are_compared_in_the_journal_and_nothing_is_said(tmp_path, monkeypatch):
    rows, spoken, asked = scenario(tmp_path, monkeypatch)
    assert len(witness(rows)) == 1, witness(rows)
    line = witness(rows)[0]
    assert (line['verdict'], line['job'], line['reply']) == ('differ', '3', '6'), line
    assert 'шести месяцев' in line['sentence'] and line['said'] == JOB, line
    assert set(spoken) == {JOB} and asked == [QUESTION], 'a shadow: only the job answer is said, no second model request'


def test_in_shadow_the_same_number_is_an_agreement(tmp_path, monkeypatch):
    rows, spoken, _ = scenario(tmp_path, monkeypatch, reply='Сейчас посмотрю. На ремонт часов в мастерской Ромашка гарантия три месяца.')
    assert len(witness(rows)) == 1, witness(rows)
    line = witness(rows)[0]
    assert (line['verdict'], line['job'], line['reply']) == ('agree', '3', '3'), line
    assert set(spoken) == {JOB}

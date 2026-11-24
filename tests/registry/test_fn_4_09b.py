"""Реестр 4.09b «Одна честная фраза при расхождении банка и базы законов»: на вопрос, где банк (файл ноутбука, выдуманный) и база законов отвечают по-разному, человек сразу слышит одну
фразу «Источники расходятся...», без модели и без ожидания. Правило хозяина ответа, без ключа.
Проверка на пустышку: ECHO_REGISTRY_SET="instant=off" краснит и тест расхождения, и контрольный (банк не работает)."""
import json

import pytest

import _h4 as H

PHRASE = 'Источники расходятся, точно не знаю.'
CONFLICT = 'Что такое статья 146 НК?'            # база законов отвечает «объект налогообложения»; банк ниже говорит другое
BANK = [
    {'q': CONFLICT, 'answer': 'Порядок применения вычетов по транспортным расходам фирмы.', 'source': 'выдуманный'},
    {'q': 'Сколько спутников у Марса', 'answer': 'У Марса два спутника: Фобос и Деймос.', 'source': 'выдуманный'},
]


def call(tmp_path, monkeypatch, body, model, **own):
    files = {'bank.json': json.dumps(BANK, ensure_ascii=False)}
    return H.play(tmp_path, monkeypatch, body, model=model, files=files, instant_bank_file=str(tmp_path / 'home' / 'bank.json'), **own)


def conflict_scene(tmp_path, monkeypatch, **own):
    model = H.Model({'146': 'Модель отвечает долго и по-своему. Это совсем другой ответ.'})      # поздний ответ модели: честная фраза должна прозвучать вместо него

    async def body(host):
        await H.say(host, CONFLICT)
        await host.advance(0.5)                       # человек ждёт полсекунды, а не 8-21 с
        return H.journal(host), host.spoken()

    return model, call(tmp_path, monkeypatch, body, model, **own)


def check_one_honest_phrase(model, rows, spoken):
    assert spoken == [PHRASE], spoken
    assert model.questions() == [], 'the model was not needed'
    assert ('question', 'local_reference') in H.decisions(rows), H.decisions(rows)
    assert H.cues(rows)[:1] == [PHRASE]


def test_bank_and_law_base_differ_one_honest_phrase_at_once(tmp_path, monkeypatch):
    model, (rows, spoken) = conflict_scene(tmp_path, monkeypatch)
    check_one_honest_phrase(model, rows, spoken)


def test_control_a_question_only_the_bank_holds_is_answered_from_the_bank(tmp_path, monkeypatch):
    model = H.Model({'марс': 'Модель: три.'})

    async def body(host):
        await H.say(host, 'Сколько спутников у Марса?')
        await host.advance(0.5)
        return H.journal(host), host.spoken()

    rows, spoken = call(tmp_path, monkeypatch, body, model, )
    assert spoken == ['У Марса два спутника: Фобос и Деймос.'] and model.questions() == [], spoken
    assert PHRASE not in H.cues(rows)

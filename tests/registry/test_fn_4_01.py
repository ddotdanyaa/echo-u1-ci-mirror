"""Реестр 4.01 «Ответ из банка»: вопрос из файла-банка ноутбука (граница: выдуманный банк, лежащий файлом) звучит без модели, подсказкой телефону; чужой вопрос банк не берёт;
справочник (план счетов, кодексы) отвечает про счёт и статью тоже без модели и без файла.
Проверка на пустышку: ECHO_REGISTRY_SET="instant=off" краснит первый и второй тесты (контрольный третий остаётся зелёным: он про чужой вопрос); четвёртый (справочник) instant=off не краснит,
его краснит подмена на границе справочника (плагин вне репозитория, controlled_media.reference_lookup и reference_kb.lookup возвращают None)."""
import json

import _h4 as H

BANK = [
    {'q': 'Какая самая высокая гора в Африке', 'alt': ['Назови самую высокую гору Африки'], 'source': 'выдуманный',
     'answer': 'Самая высокая гора Африки — Килиманджаро. Она поднимается примерно на пять тысяч девятьсот метров.'},
    {'q': 'Сколько спутников у Марса', 'answer': 'У Марса два спутника: Фобос и Деймос.', 'source': 'выдуманный'},
    {'q': 'Из чего готовят классический гуакамоле', 'answer': 'Из авокадо, лайма, лука и кинзы.', 'source': 'выдуманный'},
]


def call(tmp_path, monkeypatch, body, model=None):
    """Один звонок с банком: файл банка лежит в home, как файл ноутбука; путь к нему задаёт профиль."""
    files = {'bank.json': json.dumps(BANK, ensure_ascii=False)}
    return H.play(tmp_path, monkeypatch, body, model=model, files=files, instant_bank_file=str(tmp_path / 'home' / 'bank.json'))


def test_a_bank_question_is_answered_from_the_bank_without_the_model(tmp_path, monkeypatch):
    model = H.Model({'гор': 'Модель: Эльбрус.'})              # если бы вопрос ушёл к модели, звучал бы её ответ

    async def body(host):
        await H.say(host, 'Какая самая высокая гора в Африке?')
        first = host.spoken()[0]
        await H.say(host, first)                               # человек повторил первую порцию: звучит следующая
        await host.advance(1)
        return H.journal(host), host.spoken(), first

    rows, spoken, first = call(tmp_path, monkeypatch, body, model)
    assert model.questions() == [], 'the model was not asked'
    assert first.startswith('Самая высокая гора Африки') and 'Килиманджаро' in ' '.join([first] + spoken), spoken
    assert 'девятьсот метров' in spoken[-1], spoken
    assert ('question', 'local_reference') in H.decisions(rows)
    assert not any(kind == 'answer' for kind, _ in H.decisions(rows)), H.decisions(rows)


def test_the_bank_answers_a_rephrased_question_and_a_short_one_whole(tmp_path, monkeypatch):
    async def body(host):
        await H.say(host, 'Назови самую высокую гору Африки')
        first = host.spoken()[0]
        await host.advance(20)
        await H.say(host, 'Сколько спутников у Марса?')
        await host.advance(1)
        return H.journal(host), first

    model = H.Model({'гор': 'Модель: Эльбрус.', 'спутник': 'Модель: три.'})
    rows, first = call(tmp_path, monkeypatch, body, model)
    cues = H.cues(rows)
    assert model.questions() == []
    assert first.startswith('Самая высокая гора Африки')
    assert 'У Марса два спутника: Фобос и Деймос.' in cues, cues
    assert [d for d in H.decisions(rows) if d[1] == 'local_reference'] == [('question', 'local_reference')] * 2


def test_control_a_question_the_bank_does_not_hold_goes_to_the_model(tmp_path, monkeypatch):
    model = H.Model({'сатурн': 'У Сатурна много спутников. Их число уточняют.'})

    async def body(host):
        await H.say(host, 'Сколько спутников у Сатурна?')       # похож на вопрос о Марсе, но ответа в банке нет: чужой ответ звучать не должен
        await host.advance(3)
        return H.journal(host), host.spoken()

    rows, spoken = call(tmp_path, monkeypatch, body, model)
    assert model.questions() == ['Сколько спутников у Сатурна?']
    assert spoken and 'Сатурна' in spoken[0] and not any('Марс' in text for text in spoken), spoken
    assert ('question', 'local_reference') not in H.decisions(rows)


def test_account_and_code_article_are_answered_from_the_reference_without_the_model(tmp_path, monkeypatch):
    model = H.Model({})                                          # модель на всё отвечает «—»: любой звучащий ответ пришёл не от неё

    async def body(host):
        await H.say(host, 'Что такое счёт 62?')
        await host.advance(20)
        await H.say(host, 'Статья 209 Гражданского кодекса')
        await H.say(host, (host.spoken() or [''])[-1])               # человек повторил первую порцию: звучит продолжение
        await host.advance(1)
        return H.journal(host), host.spoken()

    rows, spoken = H.play(tmp_path, monkeypatch, body, model=model)      # банка-файла нет: справочник законов и плана счетов отвечает сам
    assert model.questions() == []
    assert spoken and spoken[0] == 'Счёт 62 — расчёты с покупателями и заказчиками.', spoken
    assert 'Статья 209 Гражданского кодекса — содержание права собственности.' in spoken, spoken
    assert H.decisions(rows).count(('question', 'local_reference')) == 2, H.decisions(rows)
    assert not any(kind == 'answer' for kind, _ in H.decisions(rows)), H.decisions(rows)

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

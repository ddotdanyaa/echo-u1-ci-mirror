"""Реестр 4.12 «Предзаготовленные ответы без модели»: вопрос из списка пар владельца (файл ноутбука, здесь выдуманный) и устоявшийся ответ из долгого кэша звучат сразу, без запроса к модели.
Правило хозяина ответа, без ключа (путь к файлу пар это граница, как файл банка). Зелёные контрольные: вопрос вне списка идёт
к модели, а изменчивый вопрос из списка не берётся. Третья часть, наполнение долгого кэша в звонке, не сделана: xfail (второй звонок с тем же home снова спрашивает модель);
контроль: тот же второй звонок, когда файл кэша положили снаружи между звонками, модели не спрашивает.
Проверка на пустышку: ECHO_REGISTRY_SET="prepared_answers_file=" краснит тесты списка."""
import hashlib
import json
import time

import pytest

import _h4 as H

RIVER = 'Самая длинная река Африки — Нил.'
PAIRS = [{'q': 'Какая самая длинная река в Африке', 'a': RIVER},
         {'q': 'Сколько спутников у Марса', 'a': 'У Марса два спутника: Фобос и Деймос.'},
         {'q': 'Какая сейчас погода в Каире', 'a': 'Тепло и сухо.'}]      # изменчивое: в список не берётся
CACHE = {'q': 'Какой газ преобладает в атмосфере Венеры', 'a': 'В атмосфере Венеры преобладает углекислый газ.'}


def ask(tmp_path, monkeypatch, question, model=None, files=None, **own):
    model = model or H.Model({'река': 'Модель говорит: Конго.', 'атмосфер': 'Модель говорит: азот.', 'погод': 'Модель говорит: дождь.'})
    files = {'pairs.json': json.dumps(PAIRS, ensure_ascii=False), **(files or {})}

    async def body(host):
        await H.say(host, question)
        await host.advance(1)
        return H.journal(host), host.spoken()

    rows, spoken = H.play(tmp_path, monkeypatch, body, model=model, files=files, prepared_answers_file=str(tmp_path / 'home' / 'pairs.json'), **own)
    return model, rows, spoken


def check_listed_answer_without_model(model, rows, spoken):
    assert spoken[:1] == [RIVER], spoken
    assert model.questions() == [], 'a prepared answer needs no model'
    assert ('question', 'local_reference') in H.decisions(rows), H.decisions(rows)
    assert H.cues(rows)[:1] == [RIVER]


def test_listed_question_is_answered_at_once_without_the_model(tmp_path, monkeypatch):
    check_listed_answer_without_model(*ask(tmp_path, monkeypatch, 'Какая самая длинная река в Африке?'))


def test_the_same_question_with_a_filler_word_hits_too(tmp_path, monkeypatch):
    check_listed_answer_without_model(*ask(tmp_path, monkeypatch, 'Ну скажи, какая самая длинная река в Африке?'))


def test_control_question_outside_the_list_goes_to_the_model(tmp_path, monkeypatch):
    model, rows, spoken = ask(tmp_path, monkeypatch, 'Какая самая длинная река в Европе?')
    assert model.questions() == ['Какая самая длинная река в Европе?'], model.questions()      # другой материк: списку нечего ответить
    assert 'Нил' not in ' '.join(spoken) and 'Конго' in spoken[0], spoken


def test_control_volatile_listed_question_is_not_taken_even_with_the_key_on(tmp_path, monkeypatch):
    model, rows, spoken = ask(tmp_path, monkeypatch, 'Какая сейчас погода в Каире?')
    assert 'Тепло и сухо.' not in spoken, spoken
    assert model.questions() == ['Какая сейчас погода в Каире?'], 'the model, not the list, answers what changes with time'


def cached_scene(tmp_path, monkeypatch, **own):
    row = {'q': CACHE['q'], 'a': CACHE['a'], 't': time.time()}
    row['h'] = hashlib.sha256((row['q'] + '\0' + row['a']).encode('utf-8')).hexdigest()
    files = {'echo-sync/prepared-answers-cache.json': json.dumps({'schema': 1, 'entries': [row]}, ensure_ascii=False)}
    return ask(tmp_path, monkeypatch, 'Какой газ преобладает в атмосфере Венеры?', files=files, **own)


def test_settled_answer_from_the_long_cache_needs_no_model(tmp_path, monkeypatch):
    model, rows, spoken = cached_scene(tmp_path, monkeypatch)
    assert spoken[:1] == [CACHE['a']] and model.questions() == [], (spoken, model.questions())


OCEAN = {'q': 'Какой океан самый глубокий на Земле', 'a': 'Самый глубокий океан — Тихий.'}


def two_calls(tmp_path, monkeypatch, planted=False):
    """Два звонка на одном tmp_path: дом профиля и файлы остаются, как у сервера между звонками; модель одна на оба. Файл пар не задан: только долгий кэш."""
    model = H.Model({'океан': OCEAN['a']})

    async def first(host):
        await H.say(host, OCEAN['q'] + '?')
        await host.advance(1)
        return host.spoken()

    async def second(host):
        await H.say(host, OCEAN['q'] + '?')
        await host.advance(1)
        return host.spoken()

    spoken = H.play(tmp_path, monkeypatch, first, model=model)
    if spoken[:1] != [OCEAN['a']] or model.questions() != [OCEAN['q'] + '?']:
        raise RuntimeError('precondition: the first call must answer the settled question through the model, got %r %r' % (spoken, model.questions()))
    if planted:      # кэш наполнил кто-то снаружи (так, как его строит ноутбук): файл между звонками
        row = {'q': OCEAN['q'], 'a': OCEAN['a'], 't': time.time()}
        row['h'] = hashlib.sha256((row['q'] + '\0' + row['a']).encode('utf-8')).hexdigest()
        (tmp_path / 'home' / 'echo-sync' / 'prepared-answers-cache.json').write_text(json.dumps({'schema': 1, 'entries': [row]}, ensure_ascii=False), encoding='utf-8')
    return model, H.play(tmp_path, monkeypatch, second, model=model)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 4.12: наполнение долгого кэша в звонке не сделано (remember нигде не вызывается), при включённом ключе тоже')
def test_settled_answer_given_in_the_first_call_is_not_asked_of_the_model_in_the_second(tmp_path, monkeypatch):
    model, spoken = two_calls(tmp_path, monkeypatch)
    assert model.questions() == [OCEAN['q'] + '?'], 'the model was asked again in the second call: %r' % model.questions()
    assert spoken[:1] == [OCEAN['a']], spoken


def test_control_second_call_needs_no_model_when_the_cache_file_is_put_between_calls(tmp_path, monkeypatch):
    model, spoken = two_calls(tmp_path, monkeypatch, planted=True)
    assert model.questions() == [OCEAN['q'] + '?'], 'the model was asked again in the second call: %r' % model.questions()
    assert spoken[:1] == [OCEAN['a']], spoken

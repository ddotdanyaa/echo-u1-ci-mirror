"""Реестр 4.02: счёт кодом (quick_math). Человек говорит умножение круглых чисел или проценты вслух, и подсказка с верным числом идёт примерно через секунду после реплики, без запроса к модели.
Ключ quick_math=on уже стоит в живом профиле. Проверка на пустышку: ECHO_REGISTRY_SET="quick_math=off" краснит зелёные тесты счёта (test_a_*), контроль остаётся зелёным.
Вердикт broken: функция «умножение круглых чисел и проценты кодом за секунду без модели» под живым профилем доказана только для лёгкой части (test_a_*: последний множитель не от двадцати, проценты от сотен).
Красные (xfail strict) закрывают остальное: (а) test_d: короткая форма без «сколько»/«умножить» кодом не считается вовсе; (б) test_b, test_e, test_c: последний множитель от двадцати и проценты от тысяч
код держит секунду, модель спрошена, отказ модели «—» даёт тишину (test_b, test_c), её неверное число звучит вместо числа кода (test_e; у процентов неверное число отвергается, test_a_percent_of_thousands_*).
Модель стенда отвечает мгновенно; на ноутбуке первый текст модели обычно приходит позже секунды, и код там чаще успевает первым: это гонка, перемерить на ноутбуке."""
import pytest

import _h4 as H

PERCENT = 'Сколько будет двадцать пять процентов от четырёхсот?'


def ask(tmp_path, monkeypatch, text, seconds=3, model=None):
    """Одна реплика, потом молчание; модель не знает ответа (её ответ '—'). Возвращает (подсказки, журнал, модель)."""
    model = model or H.Model({})

    async def body(host):
        await H.say(host, text)
        await host.advance(seconds)
        return host.spoken(), H.journal(host)

    spoken, rows = H.play(tmp_path, monkeypatch, body, model=model)
    if not [r for r in rows if r['ev'] == 'user_final']:
        raise RuntimeError('the phrase did not reach the engine: %s' % rows)      # предусловие сценария, не поведение функции
    return spoken, rows, model


def delay_ms(rows):
    """Сколько прошло от реплики человека до первой подсказки, мс виртуального времени."""
    start = next(r['t'] for r in rows if r['ev'] == 'user_final')
    return next(r['t'] for r in rows if r['ev'] == 'cue') - start


@pytest.mark.parametrize('text, result', [('Сколько будет тридцать умножить на десять?', 'Триста.'), ('Сколько будет двести умножить на три?', 'Шестьсот.'),
                                          ('Сколько будет шестьдесят на семь?', 'Четыреста двадцать.')])
def test_a_product_with_a_small_last_factor_is_counted_by_code_at_once(tmp_path, monkeypatch, text, result):
    spoken, rows, model = ask(tmp_path, monkeypatch, text)
    assert spoken[:1] == [result], spoken
    assert model.requests == [], 'no model request for a plain product: %s' % model.questions()
    assert ('question', 'local_reference') in H.decisions(rows)
    assert H.cues(rows)[0] == result and delay_ms(rows) <= 1200, delay_ms(rows)


def test_a_percent_of_hundreds_is_counted_by_code_without_the_model(tmp_path, monkeypatch):
    spoken, rows, model = ask(tmp_path, monkeypatch, PERCENT)
    assert spoken[:1] == ['Сто.'], spoken
    assert model.requests == [], model.questions()
    assert ('question', 'local_reference') in H.decisions(rows)
    assert not [r for r in rows if r['ev'] == 'fast_job'], 'the model job was not started'
    assert delay_ms(rows) <= 1200, delay_ms(rows)


@pytest.mark.parametrize('text, wrong, result', [('Сколько будет десять процентов от тысячи?', 'Девяносто.', 'Сто.'), ('Сколько будет пять процентов от двух тысяч?', 'Сто двадцать.', 'Сто.')])
def test_a_percent_of_thousands_wrong_model_number_is_refused_and_code_number_is_heard(tmp_path, monkeypatch, text, wrong, result):
    spoken, rows, model = ask(tmp_path, monkeypatch, text, model=H.Model(lambda question, request: wrong))
    assert model.questions() == [text], 'the model is asked while code holds its answer'
    assert spoken[:1] == [result] and wrong not in spoken, (spoken, H.decisions(rows))


def test_a_control_a_question_that_is_no_arithmetic_goes_to_the_model(tmp_path, monkeypatch):
    """Контроль: то же стенд-условие, но вопрос не счёт, и модель его получает (красное выше не от сценария)."""
    answer = 'Столица Австралии — город Канберра.'
    spoken, rows, model = ask(tmp_path, monkeypatch, 'Какая столица у Австралии?', model=H.Model({'столица': answer}))
    assert model.questions() == ['Какая столица у Австралии?']
    assert spoken[:1] == [answer] and ('answer', 'fast_text_owns') in H.decisions(rows)


# Поломка шире одного примера: реестр доказывает функцию умножением круглых чисел (пример живого звонка), и это как раз тот случай. Любой множитель от двадцати и проценты от тысячи
# код держит секунду (число на конце может вырасти, SPLIT_JOIN_SECONDS), мгновенная модель стенда успевает ответить '—', решение silent/fast_text_declined обрывает ответ кода: молчание.
# Живую задержку модели стенд не воспроизводит: на ноутбуке и в звонке перемерить.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="реестр 4.02: умножение с последним множителем от двадцати (двадцать..девяносто, сотни): код держит ответ секунду, "
                   "модель стенда ответила '—' за эту секунду, ответ кода оборван, человек слышит молчание")
@pytest.mark.parametrize('text, result', [('Сколько будет двадцать умножить на сорок?', 'Восемьсот.'), ('Сколько будет тридцать умножить на двести?', 'Шесть тысяч.'),
                                           ('Сколько будет пять умножить на шестьдесят?', 'Триста.'), ('Сколько будет сорок умножить на тридцать?', 'Одна тысяча двести.')])
def test_b_product_with_a_round_last_factor_is_counted_even_when_the_model_declines(tmp_path, monkeypatch, text, result):
    spoken, rows, model = ask(tmp_path, monkeypatch, text)
    assert spoken[:1] == [result], (spoken, H.decisions(rows))


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="реестр 4.02: проценты от тысячи (от сотен работают): код держит ответ секунду, модель стенда ответила '—', ответ оборван, молчание")
@pytest.mark.parametrize('text, result', [('Сколько будет десять процентов от тысячи?', 'Сто.'), ('Сколько будет пять процентов от двух тысяч?', 'Сто.')])
def test_c_percent_of_thousands_is_counted_even_when_the_model_declines(tmp_path, monkeypatch, text, result):
    spoken, rows, model = ask(tmp_path, monkeypatch, text)
    assert spoken[:1] == [result], (spoken, H.decisions(rows))


# Неверный ответ мгновенной модели. Код держит своё число секунду, модель спрошена и отвечает за эту секунду, решение answer/fast_text_owns отдаёт слово ей: человек слышит число модели («Семьсот.»), не число кода.
# У процентов от тысяч неверное число модели отвергается (зелёный тест выше), у умножения нет. На ноутбуке первый текст модели обычно приходит позже секунды: гонку перемерить.
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="реестр 4.02: умножение с последним множителем от двадцати: модель спрошена, неверное число модели за секунду звучит вместо числа кода")
@pytest.mark.parametrize('text, wrong, result', [('Сколько будет двадцать умножить на сорок?', 'Семьсот.', 'Восемьсот.'), ('Сколько будет тридцать умножить на двести?', 'Пять тысяч.', 'Шесть тысяч.'),
                                                  ('Сколько будет пять умножить на шестьдесят?', 'Двести семьдесят.', 'Триста.'), ('Сколько будет сорок умножить на тридцать?', 'Одна тысяча сто.', 'Одна тысяча двести.')])
def test_e_product_with_a_round_last_factor_wrong_model_number_does_not_drown_the_code_number(tmp_path, monkeypatch, text, wrong, result):
    spoken, rows, model = ask(tmp_path, monkeypatch, text, model=H.Model(lambda question, request: wrong))
    assert spoken[:1] == [result], (spoken, H.decisions(rows))


# Короткая форма: «N на M» без слов «сколько» и «умножить» кодом не считается вовсе (решений нет, и при fast_text=off тоже); с «сколько будет» считается (test_a_*).
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="реестр 4.02: короткая форма «N на M» без «сколько»/«умножить» кодом не считается: ни решения, ни подсказки (и при fast_text=off)")
@pytest.mark.parametrize('text, result', [('двадцать на сорок', 'Восемьсот.'), ('тридцать на десять', 'Триста.')])
def test_d_short_form_without_a_question_word_is_counted_by_code(tmp_path, monkeypatch, text, result):
    spoken, rows, model = ask(tmp_path, monkeypatch, text)
    assert spoken[:1] == [result], (spoken, H.decisions(rows))

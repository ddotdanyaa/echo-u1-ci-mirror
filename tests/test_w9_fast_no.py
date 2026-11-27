"""w9-fast-no: N135 a personal question about changing data is answered honestly at once; N134 the language of the question (E72.1, E16, E82.1).

Pure code and the REAL ``fast_text`` / ``classifier``; no network, no clock, no model. The English rows record what the system does today (Russian answer, Russian voice) and pin the one defect found:
English «not» is not protected the way «не» is, so a question and its negation are taken for one question (``test_english_not_is_not_protected``, strict xfail until the patch of ``lang_hint.NEGATION_PATCH`` lands in fast_text.py)."""
import json
import pathlib
import re
import time

import pytest

from echo_sync import fast_text as FT
from echo_sync import lang_hint as LH
from echo_sync import personal_volatile as PV
from echo_sync.classifier import analyze, strip_fillers

CORPUS = pathlib.Path(__file__).resolve().parent / 'fixtures' / 'brain_eval_n2.json'
IDLE = {'schema': 2, 'revision': 1, 'question': '', 'answer': '', 'chunks': [], 'chunk_index': 0, 'completed': True, 'pending_turn': None, 'history': []}

POSITIVE = [
    ('Сколько у меня сейчас на счету?', 'account'), ('Какой у меня остаток на карте', 'account'), ('Подскажи мой баланс', 'account'),
    ('Какая у меня погода?', 'weather'), ('Какая погода у меня за окном', 'weather'),
    ('Что у меня сегодня в календаре', 'calendar'), ('Какие у меня встречи на завтра?', 'calendar'),
    ('Сколько у меня новых писем?', 'mail'), ('Где я сейчас?', 'place'), ('Где я нахожусь', 'place'),
    ('Какой у меня пульс', 'body'), ('Сколько я прошёл шагов?', 'body'), ('Где моя посылка?', 'parcel'), ('Когда приедет мой заказ', 'parcel'),
]
NEGATIVE = [
    'Если у меня на счету 5000 рублей, сколько будет через год?',                  # a task
    'Допустим, у меня вклад под двенадцать процентов, сколько получу?',          # hypothesis
    'У меня небольшое ИП, нужно ли платить взносы за себя?',                      # stable law, "у меня" is context
    'Какая погода в Казани сегодня?',                                             # a place is named: search can answer
    'Какая температура тела у здорового человека?', 'Какая у тебя погода?', 'Сколько стоит билет до Москвы?',
    'Что такое баланс в бухгалтерии?', 'Что такое календарь?', 'Как проверить пульс?',
    'Серёж, а ты посылку отправил?', 'Мне нужно купить билет', 'Что такое счёт?',
    'Как мне открыть календарь?', 'Где мне найти письма Пушкина?', 'Что мне сказать про зарплату?', 'Объясни мне, что такое сон', 'Как мне снизить давление?',      # 4.09a: «мне» + a how-to or a definition is no data of the listener's own
    'Скажи, что такое мой календарь',
    'Скажите, сколько часов сна нужно взрослому человеку, ну, в среднем, я не совсем расслышал',             # w3 n2_h06 step 3: the «я» is of another clause, NEAR_WORDS off the thing
    'Я ложусь в одиннадцать, сколько у меня будет сна?',                                                      # a number given in words is a task as one in digits
]


def test_personal_volatile_a_number_given_just_before_makes_a_task():
    """w3 n2_h06 step 5: a question said in parts; the conditions are in the parts before it, the last part alone looks personal."""
    last = 'Сколько часов сна у меня получится'
    assert PV.personal_volatile(last) == 'body'
    assert PV.personal_volatile(last, ['Давайте на моём примере. Я ложусь спать в одиннадцать вечера', 'Вставать мне нужно в шесть утра']) is None
    assert PV.personal_volatile('Какой у меня пульс', ['Я сегодня бегал утром']) == 'body'          # talk before it with no number given leaves a personal question personal


@pytest.mark.parametrize('text,kind', POSITIVE)
def test_personal_volatile_kinds(text, kind):
    assert PV.personal_volatile(text) == kind


@pytest.mark.parametrize('text', NEGATIVE)
def test_personal_volatile_never_on_tasks_or_stable_facts(text):
    assert PV.personal_volatile(text) is None


def test_corpus_has_no_false_alarm_on_dev_and_holdout():
    rows = json.loads(CORPUS.read_text(encoding='utf-8'))['rows']
    fired = [(row['id'], row['split'], PV.personal_volatile(row['text'])) for row in rows if PV.personal_volatile(row['text'])]
    assert fired == [], 'a question the corpus wants answered (or kept silent) was taken for a personal one'


def test_reply_is_short_spoken_and_fast():
    for kind in {kind for _, kind in POSITIVE}:
        for variant in PV.VARIANTS:
            text = PV.honest_reply(kind, variant)
            assert text and not re.search(r'\d|[()\[\]]', text)
            assert all(len(sentence.split()) <= 12 for sentence in re.split(r'[.!?]\s*', text) if sentence), (kind, variant)
    start = time.perf_counter()
    for _ in range(1000):
        PV.personal_volatile('Сколько у меня сейчас на счету?')
    assert (time.perf_counter() - start) / 1000 < 0.005          # the budget is 0.3 s end to end; the decision is microseconds (cloud figure, not the laptop's)


def test_d1_two_variants_are_pinned():
    plain, hedged = PV.honest_reply('account'), PV.honest_reply('account', 'hedged')
    assert hedged.startswith(plain) and 'по памяти' in hedged and 'по памяти' not in plain
    assert PV.honest_reply('nothing') is None
    with pytest.raises(ValueError):
        PV.honest_reply('account', 'other')


def test_today_the_generic_gate_does_not_catch_it():
    """The reason for the module: «какая у меня погода» is not data that ``needs_current_data`` knows (only «сейчас», rates, sums)."""
    from echo_sync.generator import needs_current_data
    assert not needs_current_data('Какая у меня погода?')
    assert not needs_current_data('Что у меня в календаре?')


# --- N134: the English question ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize('text,lang', [
    ('What is the capital of Canada?', 'en'), ('Can you pass me the charger, please?', 'en'), ("Don't stop", 'en'), ('Столица Канады', 'ru'),
    ('Какой сейчас НДС?', 'ru'), ('Что такое GDP?', 'ru'), ('Слушай, а как будет «договор» по-английски?', 'ru'), ('Сколько будет 20 plus 5', 'ru'), ('Скажи мне пожалуйста what is the capital', 'mixed'),
    ('GDP', 'none'), ('', 'none'), ('12 345', 'none')])
def test_lang_hint(text, lang):
    assert LH.lang_hint(text) == lang


def test_what_the_system_does_with_english_today():
    for text in ('What is the capital of Canada?', 'What is the capital of Canada', 'How much does a ticket cost'):
        assert analyze(text, IDLE, [], {'on_mismatch': 'silent'}).kind == 'question'        # taken as a question, with or without «?»
        assert LH.answer_language(text) == 'ru'
    assert 'Отвечай по-русски' in FT.BRAIN_KEEP                                             # the answer is Russian, the voice is the Russian SAPI voice


def test_english_does_not_break_same_question_or_numbers():
    s = strip_fillers
    assert FT.same_question('What is the capital of Canada, um', 'What is the capital of Canada', strip=s)
    assert FT.refusal('Do we have 5 apples', 'Do we have 15 apples', strip=s) == 'numbers'
    assert FT.refusal('How many people live in Berlin', 'How many people live in Paris', strip=s) == 'words'
    assert FT.refusal('Сколько будет 20 plus 5', 'Сколько будет 20 plus 6', strip=s) == 'numbers'
    assert not FT.same_question('Is the contract valid', 'Is the contract invalid', strip=s)
    assert not FT.same_question('How much is twenty plus five', 'How much is twenty minus five', strip=s)


NOT_PAIRS = [('Is it allowed to park here', 'Is it not allowed to park here'), ('Why did the sales not grow', 'Why did the sales grow'),
             ('Can I go there', 'Can I never go there'), ('Is it allowed to park here', "Isn't it allowed to park here")]


# w10 item 8: the patch is in fast_text._protected, the strict xfail is gone
@pytest.mark.parametrize('heard,asked', NOT_PAIRS)
def test_english_not_is_not_protected(heard, asked):
    assert FT.refusal(heard, asked, strip=strip_fillers) == 'numbers' and FT.refusal(asked, heard, strip=strip_fillers) is not None


@pytest.mark.parametrize('heard,asked', NOT_PAIRS)
def test_with_the_patch_a_negation_is_a_refusal(monkeypatch, heard, asked):
    original = FT._protected

    def patched(atoms):
        found = original(atoms)
        for atom in atoms:
            if atom.atom in LH.EN_NOT:
                found['not'] += 1
        return found
    monkeypatch.setattr(FT, '_protected', patched)
    assert FT.refusal(heard, asked, strip=strip_fillers) == 'numbers' and FT.refusal(asked, heard, strip=strip_fillers) == 'numbers'
    assert FT.same_question('Is it not allowed to park here', 'Is it not allowed to park here', strip=strip_fillers)

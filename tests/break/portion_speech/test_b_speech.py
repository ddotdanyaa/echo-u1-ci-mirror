"""U237 break, family «речь»: numbers and abbreviations said aloud, numbers cut from their units, markup and links in a cue, what the voice rule leaves in the text.
The portions are the real ones the ControlledMedia plans; the owner says them back the way a person reads a figure (words, lower case). Red = a defect found."""
import re

import pytest

from bps_common import dictation
from echo_sync.speech_text import numbers_of, speak

NEUTRAL = ('Это нужно знать каждому человеку. Об этом спрашивают на каждом экзамене. Запомните это правило надолго.')

# (as written, as a person says it aloud, a wrong figure that sounds like it: the classic ear confusions 13/30, 120/12, 1941/1914)
FIGURES = (
    ('Ставка налога составляет 13 процентов от дохода.', '13 процентов', 'тринадцать процентов', 'тридцать процентов'),
    ('Вычет за обучение равен 120 000 рублей в год.', '120 000 рублей', 'сто двадцать тысяч рублей', 'двенадцать тысяч рублей'),
    ('Подать декларацию нужно до 30 апреля.', 'до 30 апреля', 'до тридцатого апреля', 'до тринадцатого апреля'),
    ('Великая Отечественная война началась в 1941 году.', 'в 1941 году', 'в тысяча девятьсот сорок первом году',
     'в тысяча девятьсот четырнадцатом году'),
)


def said_back(portion, written, aloud):
    """The portion as a person reads it back: the figure in words, the rest as written, lower case."""
    return (portion.replace(written, aloud) if written in portion else portion).lower()


@pytest.mark.parametrize('sentence,written,aloud,wrong', FIGURES, ids=['percent', 'thousands', 'date', 'year'])
def test_b16_a_figure_read_aloud_in_words_confirms_its_portion(tmp_path, sentence, written, aloud, wrong):
    d = dictation(tmp_path, answer=f'{NEUTRAL} {sentence}')
    for step in range(len(d.chunks)):
        before, portion = d.index, d.current
        out = d.say(said_back(portion, written, aloud))
        assert out.after == before + 1 or d.completed, f'portion {step} {portion!r} read back with {aloud!r} did not confirm (cursor {out.after})'
    assert d.completed


@pytest.mark.parametrize('sentence,written,aloud,wrong', FIGURES, ids=['percent', 'thousands', 'date', 'year'])
def test_b17_a_wrong_figure_that_sounds_alike_never_confirms_the_portion(tmp_path, sentence, written, aloud, wrong):
    d = dictation(tmp_path, answer=f'{NEUTRAL} {sentence}')
    for _ in range(len(d.chunks)):
        portion = d.current
        has_figure = written in portion or aloud in portion.lower()
        before = d.index
        if not has_figure:
            d.say(portion)
            continue
        heard = portion.replace(written, wrong) if written in portion else portion.lower().replace(aloud, wrong)
        out = d.say(heard.lower())
        assert out.after == before, f'{wrong!r} instead of {aloud!r} confirmed the portion {portion!r}'
        return
    raise AssertionError(f'no portion carries the figure {written!r}: {d.chunks}')


def test_b18_an_abbreviation_pair_is_one_unit_and_its_lower_case_reading_confirms(tmp_path):
    answer = ('Налог НДФЛ платит работодатель за сотрудника. Декларацию подают в ФНС по месту жительства. '
              'Правило описано в ГК РФ и в НК РФ одновременно. Это нужно знать каждому.')
    d = dictation(tmp_path, answer=answer)
    for left, right in zip(d.chunks, d.chunks[1:]):
        assert not (left.rstrip(' ,').endswith(('ГК', 'НК')) and right.startswith('РФ')), f'an abbreviation pair was cut: {left!r} | {right!r}'
    for step in range(len(d.chunks)):
        before, portion = d.index, d.current
        out = d.say(portion.lower())                    # the ear writes «ндфл», «фнс», «гк рф» in lower case
        assert out.after == before + 1 or d.completed, f'portion {step} {portion!r} in lower case did not confirm it'
    assert d.completed


BOUNDARY_SENTENCES = (
    'Вычет на лечение составляет до 150 тысяч рублей в год на одного человека с учётом расходов на лекарства и обследования.',
    'Стандартный вычет на первого ребёнка составляет 1400 рублей в месяц, а на третьего ребёнка уже 6000 рублей в месяц.',
    'Ответственность предусмотрена пунктом 3 статьи 122 Налогового кодекса Российской Федерации за неуплату налога.',
    'Закон № 204-ФЗ вступает в силу с 1 января 2026 года и действует на всей территории страны без исключений.',
    'Скидка составляет 1,5 раза от базовой цены при заказе свыше 2 тысяч штук одной партией в течение квартала.',
    'Это произошло в XV веке на территории современной Италии и сильно повлияло на торговлю всего региона.',
)
CUT_FROM_ITS_UNIT = re.compile(r'(?:\d|№|\bст\.|\bп\.|\bпп\.|\b[IVX]{1,4})\s*$')


@pytest.mark.parametrize('sentence', BOUNDARY_SENTENCES, ids=['lechenie', 'vychet', 'punkt', 'zakon', 'skidka', 'vek'])
def test_b19_no_portion_ends_on_a_bare_number_or_a_numbered_abbreviation(tmp_path, sentence):
    d = dictation(tmp_path, answer=f'{sentence} Вот и всё на сегодня. {NEUTRAL}')
    plan = d.chunks
    assert all(chunk.strip() for chunk in plan), plan
    for left, right in zip(plan, plan[1:]):
        assert not CUT_FROM_ITS_UNIT.search(left), f'a figure was cut from what it counts: {left!r} | {right!r}'


ROUND_TRIP = (
    'Цена составляет 1 500,5 руб. за единицу товара.',
    'Отчёт нужно сдать с 01.01.2025 по 31.12.2025 включительно.',
    'Телефон справочной службы +7 (495) 123-45-67 работает круглосуточно.',
    'Так было в 1990-х годах по всей стране.',
    'Ставка растёт на 5–7 % в год.',
    'Приём начинается в 12:30 по московскому времени.',
    'Закипает вода при ≈ 100 °C на уровне моря.',
    'Нужно взять 3/4 от общей суммы платежа.',
    'Дело назначено на 2-е число следующего месяца.',
    'Закон № 204-ФЗ принят в прошлом году.',
)


@pytest.mark.parametrize('sentence', ROUND_TRIP, ids=[str(n) for n in range(len(ROUND_TRIP))])
def test_b20_what_the_voice_gets_from_a_planned_portion_has_no_symbols_and_the_same_figures(tmp_path, sentence):
    d = dictation(tmp_path, answer=f'{sentence} {NEUTRAL}')
    plan = d.chunks
    for chunk in plan:
        voiced = speak(chunk)
        assert not re.search(r'[\d%№₽$€°=≈×+/]', voiced), f'the voice text still holds a symbol or a digit: {chunk!r} -> {voiced!r}'
    whole, voiced = ' '.join(plan), speak(' '.join(plan))
    assert numbers_of(whole) == numbers_of(voiced), f'the figures changed on the way to the voice: {numbers_of(whole)} -> {numbers_of(voiced)}'


def test_b21_markup_and_links_of_the_model_are_not_in_a_cue(tmp_path):
    answer = ('**Важно:** ставка составляет `13 %`, см. [ссылку](https://example.org/a?b=1) и https://example.org/page. '
              '# Остальное — потом. Подробнее на www.example.org в разделе «Налоги».')
    d = dictation(tmp_path, answer=answer)
    for chunk in d.chunks:
        assert not re.search(r'\*\*|`|\]\(|https?:|www\.|example\.org|(?:^|\s)#\s', chunk), f'markup or a link would be read aloud: {chunk!r}'

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

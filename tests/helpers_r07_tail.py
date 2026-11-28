"""R07 (stall and tail): the table of what a listener said of a portion and what must be cued.

The rows are built here; nothing in them is read from the code under test. The expectation of a row is built from the portion's own text
(``expect`` is a piece of it, cut at a word), so a row cannot agree with a wrong function by construction. The functions under test are the
production ones: ``ControlledMedia._said_of`` (the cloud's finals, ``_stuck`` and the silence timer ``_missing_part``), ``_started`` (the
local ear, ``_tempo_verdict``), ``_tail_repeated``, ``_aligned_head``.

What is cued when the listener stops: the portion from the first word they have not said (R07: «на одном слове замолчал, с того же слова и
должно подсказываться»). No clean start of the portion means the whole portion again (``None`` of the functions). A word the listener got
wrong, a skipped word, a swapped pair: the whole portion or the portion from the wrong word, never a cue that begins AFTER a word that was not
said right (that would tell them the missing word was said).

Verdicts of a cue against its row: OK (the cue is the expected one or one of ``also``); WHOLE (the whole portion where a tail was due: safe,
the listener hears words again); EARLY (a tail that begins before the due word); LATE (it begins after the due word: a word is skipped that
was not said right); OTHER (not a piece of the portion).
"""
from __future__ import annotations

import re
from collections import namedtuple

WHOLE = None          # no clean start: the whole portion is cued
Row = namedtuple('Row', 'id cat portion said expect also twice note')

PORTIONS = {
    'law1': 'Статья 17 Налогового кодекса устанавливает',
    'law2': 'общие условия установления налогов и сборов.',
    'sci1': 'Свойство тела сопротивляться изменению своего движения.',
    'sci2': 'Вода кипит при 100 градусах Цельсия',
    'sci3': 'Фотосинтез идёт в хлоропластах растений.',
    'sci4': 'Чем больше масса, тем сильнее инерция.',
    'his1': 'в 988 году при князе Владимире.',
    'his2': 'Вторая мировая война шла с 1939',
    'his3': 'по 1945 год.',
    'fin1': 'в России составляет 20 процентов.',
    'fin2': 'Бюджет проекта составляет пять миллионов рублей.',
    'fin3': 'Ставка налога составляет 13 процентов от дохода.',
    'lif1': 'Если было 80 рублей и потратили 20,',
    'lif2': 'останется 60 рублей.',
    'lif3': 'Не нагревать, а охлаждать жидкость нужно',
    'lif4': 'потом согласовать смету,',
    'wrk1': 'и только после этого подписать акт.',
    'wrk2': 'Без подписи оплата не пройдёт.',
    'wrk3': 'до конца квартала и сдать отчёт тридцатого числа.',
    'wrk4': 'а потом вернуть деньги клиенту.',
    'tlk1': 'Сегодня я расскажу о трёх главных причинах.',
    'tlk2': 'Уважаемые коллеги, начнём с итогов года.',
    'tlk3': 'Вопросы можно задавать после доклада.',
    'tlk4': 'Это не первый случай, но самый крупный.',
    'tlk5': 'Из-за этого цены выросли на пять процентов.',
    'tlk6': 'Теперь перейдём к результатам эксперимента.',
}

LEAD_IN_VOCABULARY = ['ну', 'так', 'э-э', 'эм', 'вот', 'итак', 'ладно', 'ну вот', 'слушайте']      # words resolve()['fillers'] and HESITATION_WORDS hold
LEAD_DISCOURSE = ['значит', 'короче', 'типа', 'как бы', 'в общем', 'это самое', 'ну значит', 'ммм', 'хм']
MID_FILLERS = ['э-э', 'эм', 'ну', 'вот', 'типа', 'как бы']
TRAIL_FILLERS = ['э-э', 'эм', 'ну', 'ммм', 'как его', 'как там', 'не помню', 'забыл', 'это самое', 'хм']
WRONG_WORDS = ['собака', 'вчера', 'красивый', 'быстро', 'зелёный', 'завтра']
ABBREVIATIONS = frozenset('руб коп мин сек кг км мл тыс млн млрд это'.split())      # and «это» of «этого»: another form of the same word, not a word cut off


def clean(token):
    return re.sub(r'^[^\w]+|[^\w]+$', '', token).lower()


def tokens_of(portion):
    return portion.split()


def tail(portion, k):
    return ' '.join(tokens_of(portion)[k:])


def ear(portion, k):
    return ' '.join(clean(t) for t in tokens_of(portion)[:k])


def cloud(portion, k):
    """The cloud's final: capitalised, the last word trailing off."""
    words = tokens_of(portion)[:k]
    words[-1] = re.sub(r'[^\w]+$', '', words[-1]) + '…'
    return ' '.join(words)


def _is_number(token):
    return bool(re.search(r'\d', token))


def _eligible(token):
    return not _is_number(token) and len(clean(token)) >= 4


def start_rows():
    for key, portion in PORTIONS.items():
        n = len(tokens_of(portion))
        for k in range(1, n):
            yield Row(f'start-{key}-{k}-ear', 'start', portion, ear(portion, k), tail(portion, k), (), None, '')
            yield Row(f'start-{key}-{k}-cloud', 'start', portion, cloud(portion, k), tail(portion, k), (), None, '')


def filler_rows():
    keys = list(PORTIONS)
    for i, key in enumerate(keys):
        portion = PORTIONS[key]
        n = len(tokens_of(portion))
        k = min(2, n - 1) if i % 2 == 0 else n - 1
        for kind, pool in (('lead', LEAD_IN_VOCABULARY), ('disc', LEAD_DISCOURSE)):
            filler = pool[i % len(pool)]
            yield Row(f'filler-{kind}-{key}-{k}', f'filler-{kind}', portion, f'{filler} {ear(portion, k)}', tail(portion, k), (), None, filler)
        if k >= 2:
            filler = MID_FILLERS[i % len(MID_FILLERS)]
            said = f'{ear(portion, k - 1)} {filler} {" ".join(clean(t) for t in tokens_of(portion)[k - 1:k])}'
            yield Row(f'filler-mid-{key}-{k}', 'filler-mid', portion, said, tail(portion, k), (), None, filler)
        filler = TRAIL_FILLERS[i % len(TRAIL_FILLERS)]
        yield Row(f'filler-trail-{key}-{k}', 'filler-trail', portion, f'{ear(portion, k)} {filler}', tail(portion, k), (), None, filler)
        filler = TRAIL_FILLERS[(i + 3) % len(TRAIL_FILLERS)]
        kk = max(1, k - 1)
        yield Row(f'filler-trail2-{key}-{kk}', 'filler-trail', portion, f'{ear(portion, kk)} {filler}', tail(portion, kk), (), None, filler)


def repeat_rows():
    for key, portion in PORTIONS.items():
        words = tokens_of(portion)
        n = len(words)
        if n < 3:
            continue
        k = min(2, n - 1)
        yield Row(f'repeat-first-{key}', 'repeat', portion, f'{clean(words[0])} {clean(words[0])}', tail(portion, 1), (), True, 'w1 w1')
        yield Row(f'repeat-start-{key}-{k}', 'repeat', portion, f'{ear(portion, k)} {ear(portion, k)}', tail(portion, k), (), True, 'start twice')
        yield Row(f'repeat-prefix-{key}-{k}', 'repeat', portion, f'{ear(portion, k)} {clean(words[0])}', tail(portion, k), (), True, 'start and its first word')
        yield Row(f'repeat-word-{key}-{k}', 'repeat', portion, f'{ear(portion, k)} {clean(words[k - 1])}', tail(portion, k), (), True, 'last word twice')
        yield Row(f'repeat-fill-{key}-{k}', 'repeat', portion, f'{ear(portion, k)} э-э {ear(portion, k)}', tail(portion, k), (), True, 'start, hesitation, start')


def middle_rows():
    for key, portion in PORTIONS.items():
        words = tokens_of(portion)
        n = len(words)
        if n < 5:
            continue
        yield Row(f'middle-skip1-{key}', 'middle', portion, ' '.join(clean(t) for t in words[1:3]), WHOLE, (tail(portion, 3),), None, 'w2 w3')
        yield Row(f'middle-last2-{key}', 'middle', portion, ' '.join(clean(t) for t in words[n - 2:]), WHOLE, (), None, 'the last two words only')
        yield Row(f'middle-one-{key}', 'middle', portion, clean(words[2]), WHOLE, (tail(portion, 3),), None, 'w3 alone')


def error_rows():
    for i, (key, portion) in enumerate(PORTIONS.items()):
        words = tokens_of(portion)
        n = len(words)
        for k in range(1, min(3, n - 1) + 1):
            if k >= n or not _eligible(words[k]):
                continue
            wrong = WRONG_WORDS[(i + k) % len(WRONG_WORDS)]
            yield Row(f'error-word-{key}-{k}', 'error-word', portion, f'{ear(portion, k)} {wrong}', tail(portion, k), (WHOLE,), None, f'{wrong} for {clean(words[k])}')
            word = clean(words[k])
            mangled = word[:len(word) // 2] + word[len(word) // 2 + 1:]
            yield Row(f'error-mangled-{key}-{k}', 'error-mangled', portion, f'{ear(portion, k)} {mangled}', tail(portion, k), (WHOLE,), None, f'{mangled} for {word}')
            cut = word[:min(len(word) - 2, max(2, (len(word) * 3) // 5))]
            if cut not in ABBREVIATIONS:         # «руб» of «рублей» is the abbreviation, not a word cut off
                yield Row(f'cut-{key}-{k}', 'cut', portion, f'{ear(portion, k)} {cut}', tail(portion, k), (WHOLE,), None, f'cut off at {cut}- of {word}')


def skip_swap_rows():
    for key, portion in PORTIONS.items():
        words = tokens_of(portion)
        n = len(words)
        if n < 4:
            continue
        k = 3
        if _is_number(words[1]):
            continue
        kept = [clean(t) for j, t in enumerate(words[:k + 1]) if j != 1]
        yield Row(f'skip-{key}', 'skip', portion, ' '.join(kept), WHOLE, (tail(portion, 1),), None, f'w2 left out ({clean(words[1])})')
        if clean(words[0]) in {'и', 'а', 'ну', 'вот', 'э', 'эм'}:
            continue         # «только и после» for «и только после»: a connector said late is no swap (the connectors a repeat may leave out: ru_alignment._OPTIONAL_LEADING)
        swapped = [clean(t) for t in words[:3]]
        swapped[0], swapped[1] = swapped[1], swapped[0]
        if {clean(words[0]), clean(words[1])} & {'теперь', 'сейчас', 'потом', 'затем', 'тогда', 'далее'}:      # an adverb of time moved: all the words are said, the last of them is the one they are on
            yield Row(f'swap-{key}', 'swap', portion, ' '.join(swapped), tail(portion, 2), (), None, 'an adverb moved: said all the same')
            continue
        yield Row(f'swap-{key}', 'swap', portion, ' '.join(swapped), WHOLE, (), None, 'w1 and w2 swapped')


def more_rows():
    for key, portion in PORTIONS.items():
        words = tokens_of(portion)
        n = len(words)
        k = min(2, n - 1)
        yield Row(f'more-start-{key}', 'more', portion, f'{ear(portion, k)} собака', tail(portion, k), (WHOLE,), None, 'start and a word that is not the portion\'s')


# The listener's own number words, written the way the two listeners write them: the ear in words, the cloud in digits (and the other way).
# (portion key, said, expected rest, also, note)
NUMBER_ROWS = [
    ('law1', 'статья семнадцать', 'Налогового кодекса устанавливает', (), 'words for 17'),
    ('law1', 'статья семнадцатая', 'Налогового кодекса устанавливает', (), 'ordinal for 17'),
    ('law1', 'статья семнадцатая налогового', 'кодекса устанавливает', (), 'ordinal, next word'),
    ('law1', 'статья 17 налогового', 'кодекса устанавливает', (), 'digits'),
    ('law1', 'статья семнадцать налогового кодекса', 'устанавливает', (), 'words, two more'),
    ('law1', 'статья восемнадцать', WHOLE, ('17 Налогового кодекса устанавливает',), 'wrong number'),
    ('law1', 'статья семьдесят', WHOLE, ('17 Налогового кодекса устанавливает',), 'wrong number'),
    ('law1', 'статья семь', WHOLE, ('17 Налогового кодекса устанавливает',), 'wrong number'),
    ('law1', 'статья 71', WHOLE, ('17 Налогового кодекса устанавливает',), 'wrong number, digits swapped'),
    ('his1', 'в девятьсот восемьдесят восьмом году', 'при князе Владимире.', (), 'ordinal year in words'),
    ('his1', 'в девятьсот восемьдесят восьмом', 'году при князе Владимире.', (), 'ordinal year, no word «году»'),
    ('his1', 'в девятьсот восемьдесят', '988 году при князе Владимире.', (WHOLE,), 'the number is not finished'),
    ('his1', 'в девятьсот', '988 году при князе Владимире.', (WHOLE,), 'the number is not finished'),
    ('his1', 'в 988', 'году при князе Владимире.', (), 'digits'),
    ('his1', 'в 988 году', 'при князе Владимире.', (), 'digits'),
    ('his1', 'в 988-м году', 'при князе Владимире.', (), 'digits with a case ending'),
    ('his1', 'в тысяча девятьсот восемьдесят восьмом году', WHOLE, ('988 году при князе Владимире.',), 'wrong year, 1988'),
    ('his1', 'в девятьсот восемьдесят девятом году', WHOLE, ('988 году при князе Владимире.',), 'wrong year, 989'),
    ('his1', 'в 989 году', WHOLE, ('988 году при князе Владимире.',), 'wrong year in digits'),
    ('his1', 'в 898 году', WHOLE, ('988 году при князе Владимире.',), 'wrong year, digits swapped'),
    ('lif1', 'если было восемьдесят рублей', 'и потратили 20,', (), 'words for 80'),
    ('lif1', 'если было восемьдесят', 'рублей и потратили 20,', (), 'words for 80, no unit yet'),
    ('lif1', 'если было 80 рублей и потратили', '20,', (), 'digits'),
    ('lif1', 'если было двадцать рублей', WHOLE, ('80 рублей и потратили 20,',), 'numbers swapped'),
    ('lif1', 'если было восемнадцать рублей', WHOLE, ('80 рублей и потратили 20,',), 'wrong number, 18 for 80'),
    ('lif1', 'если было восемьдесят рублей и потратили двадцать', WHOLE, (), 'the whole portion: nothing is missing'),
    ('fin1', 'в россии составляет двадцать', 'процентов.', (), 'words for 20'),
    ('fin1', 'в россии составляет 20', 'процентов.', (), 'digits'),
    ('fin1', 'в россии составляет двенадцать', WHOLE, ('20 процентов.',), 'wrong number, 12 for 20 (the usual confusion)'),
    ('fin1', 'в россии составляет пятнадцать', WHOLE, ('20 процентов.',), 'wrong number'),
    ('fin1', 'в россии составляет двадцать пять', WHOLE, ('20 процентов.',), 'a longer number that starts with 20'),
    ('fin2', 'бюджет проекта составляет 5', 'миллионов рублей.', ('пять миллионов рублей.',), 'digit for a word (the number «5 миллионов» is not finished: the whole number may be cued)'),
    ('fin2', 'бюджет проекта составляет пять миллионов', 'рублей.', (), 'words'),
    ('fin2', 'бюджет проекта составляет 5 миллионов', 'рублей.', (), 'digit for a word, scale in words'),
    ('fin2', 'бюджет проекта составляет шесть миллионов', WHOLE, ('пять миллионов рублей.',), 'wrong number'),
    ('fin2', 'бюджет проекта составляет пять тысяч', 'миллионов рублей.', (WHOLE, 'пять миллионов рублей.'), 'wrong scale: the due word is the scale'),
    ('fin2', 'бюджет проекта составляет пять миллиардов', 'миллионов рублей.', (WHOLE, 'пять миллионов рублей.'), 'wrong scale: the due word is the scale'),
    ('fin3', 'ставка налога составляет тринадцать процентов', 'от дохода.', (), 'words for 13'),
    ('fin3', 'ставка налога составляет тринадцать', 'процентов от дохода.', (), 'words for 13, no unit yet'),
    ('fin3', 'ставка налога составляет 13%', 'от дохода.', (), 'percent sign'),
    ('fin3', 'ставка налога составляет 30 процентов', WHOLE, ('13 процентов от дохода.',), 'wrong number, 30 for 13'),
    ('fin3', 'ставка налога составляет 13 копеек', 'процентов от дохода.', (WHOLE, '13 процентов от дохода.'), 'wrong unit: the due word is the unit'),
    ('sci2', 'вода кипит при ста градусах', 'Цельсия', (), 'case of 100'),
    ('sci2', 'вода кипит при ста', 'градусах Цельсия', (), 'case of 100, no unit yet'),
    ('sci2', 'вода кипит при 100', 'градусах Цельсия', (), 'digits'),
    ('sci2', 'вода кипит при сто градусах', 'Цельсия', (), 'words for 100'),
    ('sci2', 'вода кипит при тысяче градусах', WHOLE, ('100 градусах Цельсия',), 'wrong number'),
    ('sci2', 'вода кипит при 10 градусах', WHOLE, ('100 градусах Цельсия',), 'wrong number, a digit dropped'),
    ('sci2', 'вода кипит при 100 градусах Фаренгейта', WHOLE, (), 'wrong scale (whole portion said, one word wrong)'),
    ('his2', 'вторая мировая война шла', 'с 1939', (), 'start before the number'),
    ('his2', 'вторая мировая война шла с тысяча девятьсот', '1939', (WHOLE, 'с 1939'), 'the number is not finished'),
    ('his2', 'вторая мировая война шла с 1941', WHOLE, ('1939',), 'wrong year'),
    ('his3', 'по сорок пятый', WHOLE, ('год.',), 'the century is not said: 45 may be 1845 or 1945, so no tail is a safe one'),
    ('his3', 'по тысяча девятьсот сорок пятый', 'год.', (), 'ordinal in words'),
    ('his3', 'по тысяча девятьсот', '1945 год.', (WHOLE,), 'the number is not finished'),
    ('his3', 'по 1954', WHOLE, ('1945 год.',), 'digits transposed'),
    ('lif2', 'останется шестьдесят', 'рублей.', (), 'words for 60'),
    ('lif2', 'останется шесть', WHOLE, ('60 рублей.',), 'wrong number, 6 for 60'),
    ('lif2', 'останется шестнадцать', WHOLE, ('60 рублей.',), 'wrong number'),
    ('wrk3', 'до конца квартала и сдать отчёт 30-го', 'числа.', (), 'digits with an ending for an ordinal'),
    ('wrk3', 'до конца квартала и сдать отчет тридцатого', 'числа.', (), 'ё as е'),
    ('wrk3', 'до конца квартала и сдать отчёт двадцатого', WHOLE, ('тридцатого числа.',), 'wrong day'),
    ('wrk3', 'до конца квартала и сдать отчёт тридцать', WHOLE, ('тридцатого числа.', 'числа.'), 'cardinal for an ordinal'),
    ('tlk1', 'сегодня я расскажу о трёх', 'главных причинах.', (), 'number word as written'),
    ('tlk1', 'сегодня я расскажу о 3', 'главных причинах.', (), 'digit for the word'),
    ('tlk1', 'сегодня я расскажу о двух', WHOLE, ('трёх главных причинах.',), 'wrong number'),
    ('tlk1', 'сегодня я расскажу о пяти', WHOLE, ('трёх главных причинах.',), 'wrong number'),
    ('tlk5', 'из-за этого цены выросли на 5', 'процентов.', (), 'digit for the word'),
    ('tlk5', 'из-за этого цены выросли на пять', 'процентов.', (), 'words'),
    ('tlk5', 'из за этого цены выросли на пять', 'процентов.', (), 'hyphen split by the recognizer'),
    ('tlk5', 'из-за этого цены выросли на шесть', WHOLE, ('пять процентов.',), 'wrong number'),
    ('tlk5', 'из-за этого цены выросли на 50', WHOLE, ('пять процентов.',), 'wrong number, ×10'),
]

# Numbers that the table's portions do not hold. (portion, said, expected rest, also, note)
EXTRA_NUMBER_ROWS = [
    ('примерно 300 000 километров в секунду.', 'примерно 300 тысяч', 'километров в секунду.', (), 'grouped number, scale in words'),
    ('примерно 300 000 километров в секунду.', 'примерно триста тысяч', 'километров в секунду.', (), 'grouped number in words'),
    ('примерно 300 000 километров в секунду.', 'примерно триста', '300 000 километров в секунду.', (WHOLE,), 'the number is not finished'),
    ('примерно 300 000 километров в секунду.', 'примерно 300 000', 'километров в секунду.', (), 'grouped number as written'),
    ('примерно 300 000 километров в секунду.', 'примерно 300000 километров', 'в секунду.', (), 'ungrouped number'),
    ('примерно 300 000 километров в секунду.', 'примерно триста тысяч километров', 'в секунду.', (), 'grouped number in words, unit said'),
    ('примерно 300 000 километров в секунду.', 'примерно 30 000', WHOLE, ('300 000 километров в секунду.',), 'wrong number, a zero short'),
    ('примерно 300 000 километров в секунду.', 'примерно 300', '300 000 километров в секунду.', (WHOLE,), 'the thousands group is what is missing'),
    ('Температура тела составляет 36,6 градуса.', 'температура тела составляет тридцать шесть и шесть', 'градуса.', (), 'decimal in words'),
    ('Температура тела составляет 36,6 градуса.', 'температура тела составляет тридцать шесть и шесть десятых', 'градуса.', (), 'decimal in words'),
    ('Температура тела составляет 36,6 градуса.', 'температура тела составляет 36,6', 'градуса.', (), 'decimal as written'),
    ('Температура тела составляет 36,6 градуса.', 'температура тела составляет 36', '36,6 градуса.', (WHOLE,), 'half of a decimal'),
    ('Температура тела составляет 36,6 градуса.', 'температура тела составляет 36,7', WHOLE, ('36,6 градуса.',), 'wrong decimal'),
    ('Температура тела составляет 36,6 градуса.', 'температура тела составляет 37,6', WHOLE, ('36,6 градуса.',), 'wrong decimal'),
    ('Цена выросла на 5 процентов, а затраты на 5 процентов.', 'цена выросла на пять процентов а затраты', 'на 5 процентов.', (), 'a number twice in the portion'),
    ('Цена выросла на 5 процентов, а затраты на 5 процентов.', 'цена выросла на 5 процентов а затраты на', '5 процентов.', (), 'a number twice in the portion'),
    ('Цена выросла на 5 процентов, а затраты на 5 процентов.', 'цена выросла на пять процентов а затраты на шесть', WHOLE, ('5 процентов.',), 'the second number is wrong'),
    ('Встреча состоится в 15 часов 30 минут.', 'встреча состоится в пятнадцать часов', '30 минут.', (), 'time in words'),
    ('Встреча состоится в 15 часов 30 минут.', 'встреча состоится в пятнадцать', 'часов 30 минут.', (), 'time in words'),
    ('Встреча состоится в 15 часов 30 минут.', 'встреча состоится в пятнадцать часов тридцать', 'минут.', (), 'time in words'),
    ('Встреча состоится в 15 часов 30 минут.', 'встреча состоится в пятнадцать часов тринадцать', WHOLE, ('30 минут.',), 'wrong minutes'),
    ('Встреча состоится в 15 часов 30 минут.', 'встреча состоится в пятнадцать часов 3', WHOLE, ('30 минут.',), 'wrong minutes in digits'),
    ('Платить нужно 500 ₽ в месяц.', 'платить нужно пятьсот рублей', 'в месяц.', ('₽ в месяц.',), 'currency sign for the word (the sign is cued again: the right currency in words is not told from a wrong one without ru_alignment._units)'),
    ('Платить нужно 500 ₽ в месяц.', 'платить нужно пятьсот', '₽ в месяц.', ('в месяц.', '500 ₽ в месяц.', WHOLE), 'the sign is the unit'),
    ('Платить нужно 500 ₽ в месяц.', 'платить нужно 500 рублей', 'в месяц.', (), 'currency in words'),
    ('Платить нужно 500 ₽ в месяц.', 'платить нужно пятьсот долларов', '₽ в месяц.', (WHOLE, '500 ₽ в месяц.'), 'wrong currency: the due word is the currency'),
    ('Платить нужно 500 ₽ в месяц.', 'платить нужно пятьдесят рублей', WHOLE, ('500 ₽ в месяц.',), 'wrong number, 50 for 500'),
    ('Расстояние составляет 20 км в час.', 'расстояние составляет двадцать километров', 'в час.', (), 'unit in words'),
    ('Расстояние составляет 20 км в час.', 'расстояние составляет двадцать', 'км в час.', ('в час.', WHOLE), 'the unit is what is missing'),
    ('Расстояние составляет 20 км в час.', 'расстояние составляет двадцать метров', 'км в час.', (WHOLE, '20 км в час.'), 'wrong unit: the due word is the unit'),
    ('Расстояние составляет 20 км в час.', 'расстояние составляет двадцать миль', 'км в час.', (WHOLE, '20 км в час.'), 'wrong unit: the due word is the unit'),
    ('Это случилось в XIX веке в России.', 'это случилось в девятнадцатом веке', 'в России.', (), 'roman number in words'),
    ('Это случилось в XIX веке в России.', 'это случилось в девятнадцатом', 'веке в России.', (), 'roman number in words'),
    ('Это случилось в XIX веке в России.', 'это случилось в двадцатом веке', WHOLE, ('XIX веке в России.',), 'wrong century'),
]

# Spellings of the same words that the recognizers produce. (portion, said, expected rest, note)
SPELLING_ROWS = [
    ('Из-за этого цены выросли.', 'из за этого', 'цены выросли.', 'hyphen split'),
    ('Из-за этого цены выросли.', 'из-за', 'этого цены выросли.', 'hyphen kept'),
    ('Кто-то должен был это сделать.', 'кто то должен', 'был это сделать.', 'hyphen split'),
    ('Кто-то должен был это сделать.', 'кто-то должен был', 'это сделать.', 'hyphen kept'),
    ('Он взял отчёт со стола.', 'он взял отчет', 'со стола.', 'ё as е'),
    ('Он взял отчёт со стола.', 'он взял', 'отчёт со стола.', ''),
    ('Всё это нужно проверить заранее.', 'все это', 'нужно проверить заранее.', 'ё as е'),
    ('Всё это нужно проверить заранее.', 'всё', 'это нужно проверить заранее.', ''),
    ('Она сказала, что придёт позже.', 'она сказала что', 'придёт позже.', 'comma gone'),
    ('Она сказала, что придёт позже.', 'она сказала что придет', 'позже.', 'ё as е'),
    ('«Капитал» написал Карл Маркс.', 'капитал написал', 'Карл Маркс.', 'quotes gone'),
    ('«Капитал» написал Карл Маркс.', 'капитал', 'написал Карл Маркс.', 'quotes gone'),
    ('Это называется инерцией, а не силой.', 'это называется инерцией', 'а не силой.', 'comma gone'),
    ('Это называется инерцией, а не силой.', 'это называется инерцией а не', 'силой.', 'comma gone'),
    ('Это называется инерцией, а не силой.', 'это называется инерцией а', 'не силой.', 'comma gone'),
    ('Мы используем метод наименьших квадратов.', 'мы используем метод наименьших', 'квадратов.', ''),
    ('Мы используем метод наименьших квадратов.', 'мы используем метод наименьшие', 'квадратов.', 'case'),
    ('Ну что ж, начнём с главного.', 'ну что ж', 'начнём с главного.', 'a portion that opens with fillers'),
    ('Ну что ж, начнём с главного.', 'что ж', 'начнём с главного.', 'the opening filler left out'),
    ('Ну что ж, начнём с главного.', 'ну что', 'ж, начнём с главного.', 'start'),
]

# CASE: the same word in another ending. (portion key, said, expected rest, note)
CASE_ROWS = [
    ('sci1', 'свойства тела', 'сопротивляться изменению своего движения.', 'nominative for genitive'),
    ('sci1', 'свойство тело', 'сопротивляться изменению своего движения.', 'genitive for nominative'),
    ('sci1', 'свойство тела сопротивляется', 'изменению своего движения.', 'another form of the verb'),
    ('sci1', 'свойство тела сопротивляться изменением', 'своего движения.', 'instrumental for dative'),
    ('sci1', 'свойство тела сопротивляться изменения', 'своего движения.', 'genitive for dative'),
    ('sci1', 'свойство тела сопротивляться изменению своему', 'движения.', 'dative for genitive'),
    ('law2', 'общих условий', 'установления налогов и сборов.', 'genitive for nominative'),
    ('law2', 'общие условия установление', 'налогов и сборов.', 'nominative for genitive'),
    ('law2', 'общие условия установления налоги', 'и сборов.', 'nominative for genitive'),
    ('law2', 'общие условия установления налога', 'и сборов.', 'singular for plural'),
    ('law2', 'общее условие', 'установления налогов и сборов.', 'singular and neuter for plural'),
    ('tlk3', 'вопрос можно', 'задавать после доклада.', 'singular for plural'),
    ('tlk3', 'вопросы можно задавать после докладов', WHOLE, 'the whole portion with one case changed: nothing is missing'),
    ('tlk3', 'вопросы можно задавать после доклад', WHOLE, 'the whole portion with one case changed: nothing is missing'),
    ('his1', 'в 988 году при князь', 'Владимире.', 'nominative for the locative'),
    ('his1', 'в 988 году при князя', 'Владимире.', 'genitive for the locative'),
    ('tlk2', 'уважаемый коллега', 'начнём с итогов года.', 'singular for plural'),
    ('tlk2', 'уважаемые коллеги начнем с итогов', 'года.', 'ё as е'),
    ('tlk6', 'теперь перейдём к результату', 'эксперимента.', 'singular for the plural noun'),
    ('tlk6', 'теперь перейдем к результатам', 'эксперимента.', 'dative for dative, ё as е'),
    ('wrk2', 'без подписей', 'оплата не пройдёт.', 'plural for singular'),
    ('wrk2', 'без подпись', 'оплата не пройдёт.', 'nominative for genitive'),
    ('fin2', 'бюджет проекта составляет пять миллион', 'рублей.', 'nominative for genitive'),
    ('fin2', 'бюджет проекта составляет пять миллиона', 'рублей.', 'genitive singular for plural'),
]

# NEGATION, and the words that carry the meaning. (portion key, said, expected rest, also, note)
NEGATION_ROWS = [
    ('lif3', 'не нагревать', 'а охлаждать жидкость нужно', (), 'the negation is said'),
    ('lif3', 'не нагревать а охлаждать', 'жидкость нужно', (), 'the contrast is said'),
    ('lif3', 'нагревать', WHOLE, (), 'the opening «не» was left out'),
    ('lif3', 'нагревать а охлаждать', WHOLE, (), 'the opening «не» was left out'),
    ('lif3', 'не нагревать не охлаждать', WHOLE, ('а охлаждать жидкость нужно',), '«а» replaced by «не»'),
    ('lif3', 'не нагревать а нагревать', 'охлаждать жидкость нужно', (WHOLE, 'а охлаждать жидкость нужно'), 'the contrast turned round: the due word is the one that was replaced'),
    ('lif3', 'нагревать а не охлаждать', WHOLE, (), '«не» moved to the other side'),
    ('wrk2', 'без подписи оплата не', 'пройдёт.', (), 'the negation is said'),
    ('wrk2', 'без подписи оплата пройдёт', WHOLE, ('не пройдёт.',), '«не» left out'),
    ('wrk2', 'без подписи оплата не не', 'пройдёт.', (), '«не» said twice: a stammer, the due word is the next one'),
    ('wrk2', 'без подписи оплата', 'не пройдёт.', (), 'stopped before the negation'),
    ('wrk2', 'с подписью оплата', WHOLE, (), 'the preposition turned round'),
    ('tlk4', 'это не первый', 'случай, но самый крупный.', (), 'the negation is said'),
    ('tlk4', 'это не первый случай', 'но самый крупный.', (), 'the negation is said'),
    ('tlk4', 'это не первый случай но', 'самый крупный.', (), 'the negation is said'),
    ('tlk4', 'это первый случай', WHOLE, ('не первый случай, но самый крупный.',), '«не» left out'),
    ('tlk4', 'это первый случай но самый', WHOLE, (), '«не» left out'),
    ('tlk4', 'это не первый случай ни самый', WHOLE, ('но самый крупный.',), '«но» became «ни»'),
    ('tlk4', 'это', 'не первый случай, но самый крупный.', (), 'start'),
]

# A portion that opens with a short connector the listener may leave out. (portion, said, expected rest, note)
CONNECTOR_ROWS = [
    ('и только после этого подписать акт.', 'и только', 'после этого подписать акт.', 'connector said'),
    ('и только после этого подписать акт.', 'только после', 'этого подписать акт.', 'connector left out'),
    ('и только после этого подписать акт.', 'только после этого', 'подписать акт.', 'connector left out'),
    ('и только после этого подписать акт.', 'ну и только после', 'этого подписать акт.', 'filler and connector'),
    ('и только после этого подписать акт.', 'и', 'только после этого подписать акт.', 'the connector alone'),
    ('а потом вернуть деньги клиенту.', 'а потом', 'вернуть деньги клиенту.', 'connector said'),
    ('а потом вернуть деньги клиенту.', 'потом вернуть', 'деньги клиенту.', 'connector left out'),
    ('а потом вернуть деньги клиенту.', 'потом', 'вернуть деньги клиенту.', 'connector left out'),
    ('а потом вернуть деньги клиенту.', 'а', 'потом вернуть деньги клиенту.', 'the connector alone'),
    ('Но это только начало разговора.', 'но это', 'только начало разговора.', 'connector said'),
    ('Но это только начало разговора.', 'это только', WHOLE, 'a «но» that carries a contrast is not a connector that may be left out (ru_alignment._OPTIONAL_LEADING)'),
    ('Но это только начало разговора.', 'это', WHOLE, 'the same'),
    ('Так что вопрос остаётся открытым.', 'так что вопрос', 'остаётся открытым.', 'connector said'),
    ('Так что вопрос остаётся открытым.', 'вопрос остается', WHOLE, '«так что» is no connector that may be left out'),
    ('Так что вопрос остаётся открытым.', 'что вопрос', WHOLE, 'half of «так что»'),
    ('Вот почему цены растут.', 'вот почему', 'цены растут.', 'connector said'),
    ('Вот почему цены растут.', 'почему цены', 'растут.', 'connector left out'),
    ('Вот почему цены растут.', 'вот', 'почему цены растут.', 'connector alone'),
    ('Вот почему цены растут.', 'почему', 'цены растут.', 'connector left out, a word alone'),
]


def number_rows():
    for i, (key, said, expect, also, note) in enumerate(NUMBER_ROWS):
        yield Row(f'number-{key}-{i}', 'number', PORTIONS[key], said, expect, also, None, note)
    for i, (portion, said, expect, also, note) in enumerate(EXTRA_NUMBER_ROWS):
        yield Row(f'number-x{i}', 'number', portion, said, expect, also, None, note)


def spelling_rows():
    for i, (portion, said, expect, note) in enumerate(SPELLING_ROWS):
        yield Row(f'spelling-{i}', 'spelling', portion, said, expect, (), None, note)


def case_rows():
    for i, (key, said, expect, note) in enumerate(CASE_ROWS):
        yield Row(f'case-{key}-{i}', 'case', PORTIONS[key], said, expect, (), None, note)


def negation_rows():
    for i, (key, said, expect, also, note) in enumerate(NEGATION_ROWS):
        yield Row(f'negation-{key}-{i}', 'negation', PORTIONS[key], said, expect, also, None, note)


def connector_rows():
    for i, (portion, said, expect, note) in enumerate(CONNECTOR_ROWS):
        also = (tail(portion, len(said.split()) + 1),) if expect is WHOLE else ()      # a connector that is not optional: the whole portion, or the rest after the words said
        yield Row(f'connector-{i}', 'connector', portion, said, expect, also, None, note)


def all_rows():
    rows = []
    for make in (start_rows, filler_rows, repeat_rows, middle_rows, error_rows, skip_swap_rows, more_rows, number_rows, spelling_rows, case_rows,
                 negation_rows, connector_rows):
        rows.extend(make())
    assert len({row.id for row in rows}) == len(rows), 'row ids are not unique'
    return rows


# ---- what a cue is against its row ------------------------------------------------------------------------------------------------------

def position(portion, cue):
    """The index (in whitespace words) of the word the cue begins at, or None when the cue is no word-aligned tail of the portion."""
    if cue == portion:
        return 0
    if portion.endswith(cue) and portion[len(portion) - len(cue) - 1:len(portion) - len(cue)].isspace():
        return len(portion[:len(portion) - len(cue)].split())
    return None


def cue_of(found, portion):
    """What the silence timer (``_missing_part``) says for the result of ``_said_of`` / ``_started``."""
    return found[0] if found else portion


def verdict(row, cue):
    accepted = [row.portion if x is WHOLE else x for x in (row.expect, *row.also)]
    if cue in accepted:
        return 'OK'
    due = position(row.portion, row.portion if row.expect is WHOLE else row.expect)
    at = position(row.portion, cue)
    if at is None:
        return 'OTHER'
    if at == 0:
        return 'WHOLE'
    return 'EARLY' if at < due else 'LATE'

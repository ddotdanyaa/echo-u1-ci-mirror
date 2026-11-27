"""R07, the second half of the table: what happens AFTER a tail was cued, and a repeat that goes on with other words.

``confirm_rows``: the listener says X after the cue of the tail T of the waiting portion: is the portion confirmed (``ControlledMedia._tail_repeated``,
or the plain ``analyze`` of the whole portion)? ``aligned_rows``: the listener repeats the portion and goes on (``_aligned_head``): the head that is
the repeat, or None when there is no repeat to split off (a plain repeat, a wrong one, one that is taken back).
Built from the portion's own text, as in ``helpers_r07_tail``.
"""
from __future__ import annotations

import logging
from collections import namedtuple
from pathlib import Path

from helpers_r07_tail import PORTIONS, WRONG_WORDS, _eligible, clean, cue_of, ear, tail, tokens_of, verdict

# ---- the end-to-end scenarios of the silence timer ---------------------------------------------------------------------------------------
# (answer, its first portion as the portioner cuts it). The first portion of a call is cut by ``first_useful``/``portioner.cue_cuts``, so a row
# names the answer and the test asserts that the first portion is the one the row means.
ANSWERS = {
    'inertia': ('Свойство тела сопротивляться изменению своего движения.', ' Это называется инерцией. Чем больше масса, тем сильнее инерция.'),
    # c23-final: G15 (first_useful._finish_thought, laptop c18 211f329) finishes a first portion 1-4 words short of its sentence end: «Статья 17
    # Налогового кодекса | устанавливает общие условия.» is one thought of 7 words, under the cap of 9. The answer is the same; only the split moved.
    'article': ('Статья 17 Налогового кодекса устанавливает общие условия.', ' Они едины для всей страны.'),
    'budget': ('Бюджет проекта составляет пять миллионов рублей.', ' Из них треть уже потрачена. Остальное уйдёт на запуск.'),
    'road': ('Нужно сначала проверить договор.', ' Потом согласовать смету. Только после этого подписать акт.'),
}

# ---- the confirmation of a tail that was cued (``_tail_repeated``) --------------------------------------------------------------------------
ConfirmRow = namedtuple('ConfirmRow', 'id portion tail said confirmed note')

UNRELATED = 'давайте перейдём к следующему вопросу'


def waiting_state(portion, following='Следующая порция идёт дальше.'):
    return {'revision': 1, 'chunk_index': 0, 'chunks': [portion, following], 'completed': False}


def confirm_rows():
    for key, portion in PORTIONS.items():
        words = tokens_of(portion)
        n = len(words)
        if n < 4:
            continue
        k = 2
        rest = tail(portion, k)
        rest_words = tokens_of(rest)
        cleaned = ' '.join(clean(t) for t in rest_words)

        def make(suffix, said, ok, note, key=key, portion=portion, rest=rest):
            return ConfirmRow(f'confirm-{key}-{suffix}', portion, rest, said, ok, note)

        yield make('tail', cleaned, True, 'the tail as cued')
        yield make('cloud', rest, True, 'the tail as the cloud writes it')
        yield make('filler', f'ну {cleaned}', True, 'a filler before the tail')
        yield make('hesit', f'{cleaned} э-э', True, 'a hesitation after the tail')
        yield make('whole', ' '.join(clean(t) for t in words), True, 'the whole portion instead of the tail')
        yield make('head', ear(portion, k), False, 'the part that was said before the cue')
        if len(rest_words) >= 3:
            yield make('half', ' '.join(clean(t) for t in rest_words[:len(rest_words) // 2]), False, 'the first half of the tail only')
        if _eligible(rest_words[-1]):
            yield make('wrong', ' '.join([clean(t) for t in rest_words[:-1]] + [WRONG_WORDS[len(key) % len(WRONG_WORDS)]]), False, 'the last word of the tail is another')
        yield make('other', UNRELATED, False, 'speech about something else')
        one = tail(portion, n - 1)
        if clean(one):
            yield ConfirmRow(f'confirm-{key}-one', portion, one, clean(one), True, 'a tail of one word, repeated')
            yield ConfirmRow(f'confirm-{key}-one-other', portion, one, WRONG_WORDS[len(key) % len(WRONG_WORDS)], False, 'a tail of one word, another word said')


# (portion key, k, said, confirmed, note)
CONFIRM_HAND = [
    ('lif1', 3, 'рублей и потратили двадцать', True, 'number in words'),
    ('lif1', 3, 'рублей и потратили 20', True, 'number in digits'),
    ('lif1', 3, 'рублей и потратили двадцать пять', False, 'another number'),
    ('lif1', 3, 'рублей и потратили 25', False, 'another number'),
    ('lif1', 3, 'рублей и потратили восемьдесят', False, 'the other number of the portion'),
    ('fin3', 3, 'тринадцать процентов от дохода', True, 'words for 13'),
    ('fin3', 3, '13 процентов от дохода', True, 'digits'),
    ('fin3', 3, '13% от дохода', True, 'percent sign'),
    ('fin3', 3, 'тридцать процентов от дохода', False, 'another number'),
    ('fin3', 3, 'тринадцать от дохода', False, 'the unit is dropped'),
    ('fin3', 3, 'тринадцать копеек от дохода', False, 'another unit'),
    ('his1', 2, 'году при князе владимире', True, 'plain'),
    ('his1', 2, 'году при князе', False, 'one word short'),
    ('his1', 2, 'год при князе владимире', True, 'case of the first word'),
    ('wrk2', 3, 'не пройдёт', True, 'plain'),
    ('wrk2', 3, 'не пройдет', True, 'ё as е'),
    ('wrk2', 3, 'пройдёт', False, 'the negation is dropped'),
    ('wrk2', 3, 'не не пройдёт', False, 'an added «не» is never taken for a stammer (ru_alignment: a changed count of «не» never confirms): the safe refusal'),
    ('lif3', 2, 'а охлаждать жидкость нужно', True, 'plain'),
    ('lif3', 2, 'а нагревать жидкость нужно', False, 'the contrast turned round'),
    ('lif3', 2, 'а не охлаждать жидкость нужно', False, 'a negation added'),
    ('tlk4', 3, 'случай но самый крупный', True, 'plain'),
    ('tlk4', 3, 'случай но не самый крупный', False, 'a negation added'),
    ('tlk4', 3, 'случай ни самый крупный', False, '«но» became «ни»'),
    ('law1', 2, 'налогового кодекса устанавливает', True, 'plain'),
    ('law1', 2, 'налогового кодекса', False, 'one word short'),
    ('tlk1', 5, 'главных причинах', True, 'plain'),
    ('tlk1', 4, 'трёх главных причинах', True, 'the tail from the number'),
    ('tlk1', 4, 'три главных причины', True, 'the tail from the number, the number in another case'),
    ('tlk1', 4, '3 главных причины', True, 'the number in digits'),
    ('tlk5', 5, 'пять процентов', True, 'plain'),
    ('tlk5', 5, '5 процентов', True, 'digit for the word'),
    ('tlk5', 5, 'шесть процентов', False, 'another number'),
    ('tlk5', 5, 'пять', False, 'the unit is dropped'),
]


def confirm_hand_rows():
    for i, (key, k, said, ok, note) in enumerate(CONFIRM_HAND):
        portion = PORTIONS[key]
        yield ConfirmRow(f'confirm-hand-{key}-{i}', portion, tail(portion, k), said, ok, note)


# ---- a repeat that goes on with other words (``_aligned_head``) -------------------------------------------------------------------------
AlignedRow = namedtuple('AlignedRow', 'id portion said head note')

ALIGNED = [
    ('sci1', 'свойство тела сопротивляться изменению своего движения это называется инерцией', 'свойство тела сопротивляться изменению своего движения', 'repeat, then the next words'),
    ('sci1', 'Свойство тела сопротивляться изменению своего движения. Это называется инерцией.', 'Свойство тела сопротивляться изменению своего движения.', 'the cloud\'s writing'),
    ('sci1', 'ну свойство тела сопротивляться изменению своего движения это называется инерцией', 'ну свойство тела сопротивляться изменению своего движения', 'a filler before the repeat'),
    ('sci1', 'свойство тела сопротивляться изменению своего движения', None, 'a plain repeat'),
    ('sci1', 'свойство тела сопротивляться изменению своего движения но это не так', None, 'the repeat is taken back'),
    ('sci1', 'свойство тела сопротивляться изменению своего движения а наоборот нет', None, 'the repeat is taken back'),
    ('sci1', 'свойство тела сопротивляться изменению чужого движения это называется инерцией', None, 'a wrong word in the repeat'),
    ('sci1', 'свойство тела это называется инерцией', None, 'a start of the portion, then the next words'),
    ('sci1', 'тела сопротивляться изменению своего движения это называется инерцией', None, 'the first word is missing'),
    ('his1', 'в 988 году при князе владимире это связало страну с византией', 'в 988 году при князе владимире', 'digits'),
    ('his1', 'в девятьсот восемьдесят восьмом году при князе владимире это связало страну с византией', 'в девятьсот восемьдесят восьмом году при князе владимире', 'words'),
    ('his1', 'в 989 году при князе владимире это связало страну с византией', None, 'another year'),
    ('his1', 'в 898 году при князе владимире это связало страну с византией', None, 'another year, digits swapped'),
    ('his1', 'в 988 году при князе владимире не так', None, 'taken back'),
    ('fin1', 'в россии составляет 20 процентов для некоторых товаров ставка ниже', 'в россии составляет 20 процентов', 'digits'),
    ('fin1', 'в россии составляет двадцать процентов для некоторых товаров ставка ниже', 'в россии составляет двадцать процентов', 'words'),
    ('fin1', 'в россии составляет 25 процентов для некоторых товаров ставка ниже', None, 'another number'),
    ('fin1', 'в россии составляет двенадцать процентов для некоторых товаров ставка ниже', None, 'another number (the usual confusion)'),
    ('his2', 'вторая мировая война шла с 1939 по 1945 год', 'вторая мировая война шла с 1939', 'a portion that ends in a number, then «по»'),
    ('his2', 'вторая мировая война шла с 1939 1945', None, 'a portion that ends in a number, then a bare number'),
    ('his2', 'вторая мировая война шла с 1939 двадцать', None, 'a portion that ends in a number, then a number word'),
    ('lif2', 'останется 60 рублей это обычное вычитание', 'останется 60 рублей', 'digits'),
    ('lif2', 'останется шестьдесят рублей это обычное вычитание', 'останется шестьдесят рублей', 'words'),
    ('lif2', 'останется 16 рублей это обычное вычитание', None, 'another number'),
    ('wrk2', 'без подписи оплата не пройдёт поэтому подпишите заранее', 'без подписи оплата не пройдёт', 'plain'),
    ('wrk2', 'без подписи оплата пройдёт поэтому подпишите заранее', None, 'the negation is dropped'),
    ('lif3', 'не нагревать а охлаждать жидкость нужно иначе она закипит', 'не нагревать а охлаждать жидкость нужно', 'plain'),
    ('lif3', 'нагревать а охлаждать жидкость нужно иначе она закипит', None, 'the opening negation is dropped'),
    ('lif3', 'не охлаждать а нагревать жидкость нужно иначе она закипит', None, 'the contrast is swapped'),
    ('tlk3', 'вопросы можно задавать после доклада сейчас я начну', 'вопросы можно задавать после доклада', 'plain'),
    ('tlk3', 'вопросы можно задавать после доклада а потом нет', None, 'taken back'),
    ('tlk4', 'это не первый случай но самый крупный давайте разберёмся', 'это не первый случай но самый крупный', 'plain'),
    ('tlk4', 'это первый случай но самый крупный давайте разберёмся', None, 'the negation is dropped'),
    ('law2', 'общие условия установления налогов и сборов они едины для всей страны', 'общие условия установления налогов и сборов', 'plain'),
    ('law2', 'общие условия установления налогов и сборов в россии', 'общие условия установления налогов и сборов', 'plain, a preposition after'),
    ('wrk1', 'и только после этого подписать акт после этого платим', 'и только после этого подписать акт', 'a portion with a connector'),
    ('wrk1', 'только после этого подписать акт после этого платим', 'только после этого подписать акт', 'the connector left out'),
    ('tlk2', 'уважаемые коллеги начнём с итогов года первый вопрос', 'уважаемые коллеги начнём с итогов года', 'plain'),
]


def aligned_rows():
    for i, (key, said, head, note) in enumerate(ALIGNED):
        yield AlignedRow(f'aligned-{key}-{i}', PORTIONS[key], said, head, note)


# ---- the production functions, called -------------------------------------------------------------------------------------------------------
ROUTES = ('final', 'ear')


def make_controller(directory):
    """A controller on the production default profile (``CALL_SETTINGS``: meaning portions, the Russian alignment), as ``controlled_host`` builds it."""
    from echo_sync.controlled_media import ControlledMedia
    logging.getLogger('echo-sync').setLevel(logging.ERROR)
    return ControlledMedia(Path(directory) / 'r07-state.sqlite3', session_id='r07-table')


def cue_verdict(controller, row, route):
    """``(verdict, cue)`` of one row: ``final`` is the reader of the cloud's finals (``_said_of``: ``_stuck``, the silence timer ``_missing_part``), ``ear`` the local ear's (``_started``)."""
    read = controller._started
    found = read(row.said, row.portion)
    cue = cue_of(found, row.portion)
    result = verdict(row, cue)
    if result == 'OK' and row.twice is not None and bool(found and found[1]) != row.twice:
        result = 'TWICE'
    return result, cue


def is_confirmed(controller, row):
    """Is the waiting portion confirmed by ``row.said`` after ``row.tail`` was cued and began to play? ``_tail_repeated`` or the plain ACK of the whole portion."""
    from echo_sync.classifier import ACK, analyze
    state = waiting_state(row.portion)
    state['tail_cue'] = [state['revision'], state['chunk_index'], row.tail, True]      # the engine keeps the cued tail with the cursor (``engine.cue_tail``)
    return controller._tail_repeated(row.said, state) is not None or analyze(row.said, state, [], controller.settings).kind == ACK


def head_of(controller, row):
    """The repeat that ``_aligned_head`` splits off ``row.said``, or None."""
    return controller._aligned_head(row.said, waiting_state(row.portion))

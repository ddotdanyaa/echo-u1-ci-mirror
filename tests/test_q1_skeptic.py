"""Q1, the skeptic's round: a wrong figure in the earpiece is the worst failure of this product, a missed sum costs only the model's 2 s. Every case here failed against the code as delivered (see
``.superpowers/sdd/wave2/q1-report.md``, «skeptic»); the rows that passed from the start are the neighbours that must stay. No network, no sleep.
"""
import pytest

from echo_sync import quick_math

# =====================================================================================================================================
# the grammar: what looks like a sum and is none, what is a sum and came out wrong
# =====================================================================================================================================

WRONG_FIGURE = [
    # the sign of a number glued to its digits: ``_TOKEN`` dropped it and the sum came out with the other sign
    '-5 плюс 3', '−5 + 3', '– 5 + 3', '— 5 плюс 3', '5 плюс -3', '5 минус -3', '5 на -3', '-5 на 3', '-10% от 200', '10% от -200', '5 умножить на -3',
    # any mark ``_TOKEN`` does not read was dropped with what it meant: a root, a power, a fraction, a number that is a label, a unit
    '√16 плюс 1', '2² плюс 3', '3½ плюс 1', '№5 плюс 6', '5€ плюс 6€', '5° плюс 6°', '5$ плюс 6$', '10‰ от 200',
    # a thousands separator read as a decimal point: «10,000 плюс 5,000» came out 15, and a dot is a time or a date as often as a point
    '1,000 плюс 1', '10,000 плюс 5,000', '2,500 умножить на 2', '1.000 плюс 1', '12.30 плюс 15', '14.05 плюс 2',
    # two numbers the mark between them keeps apart were read as one: a number split by a pause, a range
    'двадцать, пять на два', 'двадцать. Пять на два.', 'сто, пять плюс пять', 'сто. Пять плюс пять.', 'двести, двадцать плюс три', 'двадцать-пять на два', 'сто-двадцать на два',
    'двадцать… пять на два', 'двадцать - пять на два', 'две тысячи, пятьсот плюс один',
    # «тысячи пять», «миллиона два»: the inverted order of about-so-many, not 1005
    'тысячи пять плюс сто', 'миллиона два плюс сто',
    # «тысячи» with no count is many thousands, not one: it reads as one only after «от»
    'тысячи плюс сто', 'тысячи плюс тысячи', 'сто плюс тысячи', 'миллиона минус один', 'тысячи умножить на два',
    # a sign that stands between no two numbers: the sum goes on, or the sign is the number's
    '5 + 5 +', '5 + 5 ×', '5 * 5 +', '+5 минус 3', '5 + -3', '% от 200',
    # «пять тысяч с половиной» is 5500, ``ru_numbers`` read 5000.5
    'пять тысяч с половиной плюс сто', 'два миллиона с половиной минус один', 'тысяча с половиной плюс один',
]


@pytest.mark.parametrize('text', WRONG_FIGURE)
def test_what_came_out_a_wrong_figure_goes_to_the_model(text):
    assert quick_math.answer(text) is None


NOT_A_SUM = [
    # a figure of speech: nobody multiplies
    'пятьдесят на пятьдесят', 'Пятьдесят на пятьдесят?', '50 на 50', 'сто на сто', 'сто на сто?', 'да сто на сто', 'ну сто на сто', '100 на 100', 'двадцать четыре на семь', '24 на 7', 'один на один',
    'Один на один?', 'одно на одно', 'одного на одного', 'один на сто', 'ноль на ноль',
    # a size or an account said alone: two round numbers, a size the recognizer wrote with a letter
    'шестьдесят на девяносто', '60 на 90', 'девяносто на шестьдесят', 'двести на триста', 'шестьсот на шестьсот', 'тридцать на сорок', '60х90', '60x90', '1200х600', '1920x1080', '60 × 90', '1200 × 600',
    # two numbers of two digits said alone: accounts, a paper size, a photo; with «сколько» they are a sum (below)
    'шестьдесят на пятьдесят один', '51 на 60', 'семьдесят на шестьдесят восемь', 'двадцать один на тридцать', 'десять на пятнадцать', 'двенадцать на двенадцать', 'сорок восемь на десять',
    # a remark in the form of a bare «на»: a confirmation, a conclusion, a claim, not a question
    'пять на шесть, да?', 'пять на шесть да', 'пять на шесть так', 'вот пять на шесть', 'значит пять на шесть', 'получается пять на шесть', 'итак пять на шесть', 'пять на пять же', 'ладно пять на шесть',
    'хорошо пять на шесть', 'да пять на шесть',
]


@pytest.mark.parametrize('text', NOT_A_SUM)
def test_a_figure_of_speech_a_size_a_remark_is_no_sum(text):
    assert quick_math.answer(text) is None


STAYS = [
    # the bare «на» of the owner's list, and with the sum asked for in words: what the rules above must not take away
    ('пять на пять', 'Двадцать пять.'), ('Пять на пять?', 'Двадцать пять.'), ('5 на 5', 'Двадцать пять.'), ('5х5', 'Двадцать пять.'), ('5 x 5', 'Двадцать пять.'), ('5 × 5', 'Двадцать пять.'),
    ('а пять на шесть?', 'Тридцать.'), ('ну пять на шесть', 'Тридцать.'), ('семь на восемь', 'Пятьдесят шесть.'), ('два на два', 'Четыре.'), ('сто на пять', 'Пятьсот.'), ('пять на двенадцать', 'Шестьдесят.'),
    ('сколько будет двенадцать на двенадцать', 'Сто сорок четыре.'), ('посчитай сорок восемь на десять', 'Четыреста восемьдесят.'), ('сколько будет сто на сто', 'Десять тысяч.'), ('сколько будет пятьдесят на пятьдесят', 'Две тысячи пятьсот.'),
    ('сто на сто это сколько', 'Десять тысяч.'), ('посчитай шестьдесят на девяносто', 'Пять тысяч четыреста.'), ('сколько будет 24 на 7', 'Сто шестьдесят восемь.'),
    ('сколько будет один на один', 'Один.'), ('сколько будет 60 × 90', 'Пять тысяч четыреста.'), ('сто умножить на сто', 'Десять тысяч.'), ('один умножить на один', 'Один.'),
    # the marks a recognizer writes around a sum are no part of it
    ('Так, сколько будет пять плюс пять?', 'Десять.'), ('пять плюс пять = ', 'Десять.'), ('ну, 2,5 умножить на 4, пожалуйста', 'Десять.'), ('"пять плюс пять"', 'Десять.'), ('пять на пять — это сколько', 'Двадцать пять.'),
    ('- Пять плюс пять', 'Десять.'), ('1 500 плюс 500', 'Две тысячи.'), ('0,125 плюс 1', 'Одна целая сто двадцать пять тысячных.'), ('пять с половиной плюс три', 'Восемь целых пять десятых.'),
    ('пять с половиной тысячи плюс сто', 'Пять тысяч шестьсот.'), ('тысяча пять плюс сто', 'Одна тысяча сто пять.'), ('миллион два плюс один', 'Один миллион три.'), ('сто двадцать плюс три', 'Сто двадцать три.'),
    ('десять процентов от миллиона', 'Сто тысяч.'), ('5 процентов от тысячи', 'Пятьдесят.'),
    # the sum is a sum whatever is around it, when the operator is said
    ('да пять плюс шесть', 'Одиннадцать.'), ('значит пять плюс шесть', 'Одиннадцать.'), ('пять умножить на шесть, да?', 'Тридцать.'),
]


@pytest.mark.parametrize('text,spoken', STAYS)
def test_what_is_a_sum_stays_a_sum(text, spoken):
    assert quick_math.answer(text) == spoken


# What the attack left standing, pinned: it was None before and must stay so (the model answers).
PINNED_NONE = [
    'счёт шестьдесят на девяносто', 'комната пять на шесть', 'это как два на два', 'всё просто два на два', 'с 5 на 6', 'в ночь с пятого на шестое', 'налог двадцать процентов от прибыли', '20% от выручки',
    '+7 900 123-45-67', '8-900-123-45-67', 'мне сорок плюс', 'восемнадцать плюс', 'ему пять на шесть', 'семь рублей на восемь',
    'пять нет шесть на семь', 'пять, нет, шесть на семь', 'пять на шесть нет на семь', 'пять на шесть ой на семь', 'пять э на шесть', 'то есть шесть на семь',
    'сколько было пять на пять', 'сколько получилось пять на пять', 'сколько вышло пять плюс пять', 'пять плюс пять было десять',
    'поделить на пять', 'поделить двести пополам', 'вычесть пять из десяти', 'десять вычесть пять', 'пять в квадрате', 'пять в квадрате плюс три', 'пять плюс три в квадрате', 'минус пять плюс три',
    'пять минус минус три', 'минус пять на минус три', 'пять плюс минус два', 'плюс минус пять на пять', '2+2*2', '(2+2)*2', 'десять разделить на три с остатком', 'остаток от деления десяти на три',
    'пять процентов от пяти процентов', '10% от 20%', 'десять процентов от десяти процентов от ста', 'двадцать процентов плюс двадцать процентов', 'сто плюс десять процентов', 'сто тысяч минус тринадцать процентов',
    'пять тыщ плюс две тыщи', 'десять процентов от пяти тыщ', 'сто плюс двести тыщ', 'тыща плюс тыща', 'пять штук плюс три штуки', 'пятого на шестое', '5-го на 6-е', 'пять минут на шесть',
]


@pytest.mark.parametrize('text', PINNED_NONE)
def test_what_the_attack_left_standing_stays_the_models(text):
    assert quick_math.answer(text) is None


# =====================================================================================================================================
# the ear's hearing of a number: should a sum wait for the cloud's partial to name the last operand?
# =====================================================================================================================================
# The real NativeMediaSocket, ShadowEar and controller (the rig of H3/H4), on the phone's clock: after the end of speech the ear's text comes at 0.15 s, the cloud's words of the utterance are complete at
# 1.06 s, its final at 2.2 s. A cue of one figure lasts about 0.5 s. As delivered ``same_start`` left the last word of the partial open and a turn with no word yet open altogether, so the wrong figure was said
# to its end at 0.36 s, 1.9 s before the final could cut it. The price of the wait: the cue comes at 1.06 s instead of 0.36 s, against 2.2 s of the final. A missed sum costs the model's 2 s, the wrong one the call.

import helpers_s6_state as S
from test_h3_tempo import TICK, call                  # noqa: F401, E402 - call is the fixture
from test_h4_ear_first import final, speaks           # noqa: E402
from echo_sync.controlled_media import FIGURE_STILL_SECONDS     # noqa: E402

PARTIAL_AT, FINAL_AT = 1.06, 2.2
FIVE, THIRTY = 'Двадцать пять.', 'Тридцать.'
EAR_FIVE, CLOUD_FIVE = 'пять на пять', 'Пять на пять'


@pytest.fixture
def maths(call):
    def make(**profile):
        rig = call(fast_text='on', quick_math='on', **profile)
        rig.c.quick_math = True
        return rig
    return make


def on_the_phone(rig, ear, cloud, turn='u1'):
    """The ear's text, the cloud's words at their time (none when ``cloud`` is empty), up to the moment before the final. Returns when the speech ended."""
    ended = speaks(rig, ear, turn=turn, announced=1.0, speech=1.5)
    rig.pump(max(0.0, ended + PARTIAL_AT - rig.w.clock.t))
    if cloud:
        rig.w.feed(S.turn_delta(turn, cloud, 1))
    rig.pump(max(0.0, ended + FINAL_AT - rig.w.clock.t))
    return ended


# U43(a), commit 832d0778: two witnesses that differ get the answer with its operands named («Пять на тридцать — сто пятьдесят.»)
MISHEARD = [
    ('пять на пять', 'Пять на шесть', THIRTY),
    ('пять на тринадцать', 'Пять на тридцать', 'Пять на тридцать — сто пятьдесят.'),
    ('сорок восемь умножить на десять', 'Сорок восемь умножить на одиннадцать', 'Сорок восемь на одиннадцать — пятьсот двадцать восемь.'),
    ('сто разделить на четыре', 'Сто разделить на пять', 'Сто разделить на пять — двадцать.'),
    ('сколько будет семь умножить на восемь', 'Сколько будет семь умножить на девять', 'Семь на девять — шестьдесят три.'),
    # the ear lost the last word: a scale, the units of the number
    ('десять процентов от двухсот', 'Десять процентов от двухсот тысяч', '10% от 200000 — двадцать тысяч.'),
    ('двадцать плюс двадцать', 'Двадцать плюс двадцать два', 'Сорок два.'),
    ('сто разделить на два', 'Сто разделить на двадцать', 'Сто разделить на двадцать — пять.'),
]


@pytest.mark.parametrize('ear,cloud,spoken', MISHEARD, ids=lambda value: value.replace(' ', '_'))
def test_a_number_the_ear_misheard_never_reaches_the_earpiece(maths, ear, cloud, spoken):
    rig = maths()
    on_the_phone(rig, ear, cloud)
    assert rig.said() == [], 'the cloud names another sum: no figure of the ear goes out'
    final(rig, 'u1', cloud)
    if rig.said()[-1:] and rig.said()[-1].endswith('—'):
        # U43(a), commit 832d0778: the answer may be two portions (operands, figure): the listener says the first back, the second is cued, the whole of it is asserted
        said_back = rig.said()[-1].rstrip(' —')
        speaks(rig, said_back, turn='u2', announced=0.5, speech=1.0)
        final(rig, 'u2', said_back)
    assert ' '.join(rig.said()) == spoken, 'the only figure of this call is the one of the final'


def test_with_no_word_of_the_cloud_the_ear_alone_cues_no_figure(maths):
    """The turn is open and the cloud has shown nothing: as delivered that was «nothing against it», both numbers rested on the ear alone."""
    rig = maths()
    on_the_phone(rig, EAR_FIVE, '')
    assert rig.said() == []
    final(rig, 'u1', 'Пять на шесть?')
    assert rig.said() == [THIRTY]


def test_the_cloud_naming_the_same_sum_cues_it_before_the_final(maths):
    """What is left of the gain: at the cloud's partial, a second before its final."""
    rig = maths()
    ended = on_the_phone(rig, EAR_FIVE, 'Пять на')
    assert rig.said() == [], 'the last number is not named yet'
    rig.w.feed(S.turn_delta('u1', ' пять', 2))
    rig.pump(FIGURE_STILL_SECONDS + 2 * TICK)      # A8-1: «пять» may still be the head of «пятьдесят»
    assert rig.said() == [FIVE] and rig.c.user_boundaries['u1'] == 'ear_first'
    assert not rig.fake.runs
    final(rig, 'u1', 'Пять на пять?')
    assert rig.said() == [FIVE] and not rig.cues()[0].cleared


def test_the_cue_comes_at_the_clouds_partial_on_the_phones_clock(maths):
    rig = maths()
    ended = speaks(rig, EAR_FIVE, turn='u1', announced=1.0, speech=1.5)
    rig.pump(max(0.0, ended + PARTIAL_AT - rig.w.clock.t))
    rig.w.feed(S.turn_delta('u1', CLOUD_FIVE, 1))
    rig.pump(FIGURE_STILL_SECONDS + 2 * TICK)
    assert rig.said() == [FIVE] and rig.cues()[0].t - ended <= PARTIAL_AT + FIGURE_STILL_SECONDS + 3 * TICK


@pytest.mark.parametrize('ear,cloud', [('пять на пять', '5 на 5'), ('пять на пять', 'Сколько будет пять на пять?'), ('сколько будет пять на пять', 'Пять умножить на пять'), ('пять на пять', '5 × 5')])
def test_the_same_sum_in_other_words_is_the_same_sum(maths, ear, cloud):
    rig = maths()
    on_the_phone(rig, ear, cloud)
    assert rig.said() == [FIVE]


def test_a_number_that_goes_on_after_a_breath_is_not_cued_on_its_head(maths):
    """«двадцать плюс двадцать» | «два», a cloud that is quick: both witnesses agree on the head. As for the confirmation of a portion that ends in a number, a number can still grow: the utterance has to be over."""
    rig = maths()
    uid = rig.onset()
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.5)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, 'двадцать плюс двадцать')
    rig.pump(TICK)
    rig.w.feed(S.turn_delta('u1', 'Двадцать плюс двадцать', 1))
    rig.pump(0.3)
    assert rig.said() == []
    speaks(rig, 'два', speech=0.4)
    rig.w.feed(S.turn_delta('u1', ' два', 2))
    rig.pump(0.2)
    final(rig, 'u1', 'Двадцать плюс двадцать два')
    assert rig.said() == ['Сорок два.']


@pytest.mark.parametrize('head,ear,cloud', [('раздели', 'сто на пять', 'Раздели сто на пять'), ('разделите', 'двести на четыре', 'Разделите двести на четыре'), ('комната', 'пять на шесть', 'Комната пять на шесть'),
                                            ('счёт', 'пять на шесть', 'Счёт пять на шесть'), ('итого', 'пять плюс шесть', 'Итого пять плюс шесть'), ('не', 'пять на шесть', 'Не пять на шесть')],
                         ids=lambda value: value.replace(' ', '_'))
def test_the_words_in_front_of_a_sum_in_a_piece_of_their_own_are_no_remark_to_read_past(maths, head, ear, cloud):
    """H4 reads the last piece alone when the longest reading is no hit: right for an article of a code, wrong for a sum. «раздели» | «сто на пять» came out 500, and the final never had to agree with what the ear read."""
    rig = maths()
    speaks(rig, head, speech=0.5)
    rig.pump(0.1)
    speaks(rig, ear, turn='u1', announced=0.2, speech=1.0)
    rig.w.feed(S.turn_delta('u1', cloud, 1))
    rig.pump(1.5)
    assert rig.said() == [], 'the cloud has the whole of it, and that is no plain sum'


def test_a_word_that_goes_on_past_the_sum_in_a_piece_of_its_own(maths):
    """«пять на шесть» | «метров»: the same wait covers what comes after."""
    rig = maths()
    speaks(rig, 'пять на шесть', turn='u1', announced=1.0, speech=1.5)
    rig.w.feed(S.turn_delta('u1', 'Пять на шесть', 1))
    rig.pump(0.3)
    speaks(rig, 'метров', speech=0.5)
    rig.w.feed(S.turn_delta('u1', ' метров', 2))
    final(rig, 'u1', 'Пять на шесть метров')
    assert THIRTY not in rig.said()


def test_a_reference_of_the_base_does_not_wait(maths):
    """The wait is the figure's: a hit of the base is no number worked out from the ear's words (H4 rule 1 stays)."""
    rig = maths()
    speaks(rig, 'семнадцатая статья налогового кодекса', turn='u1', announced=1.0, speech=1.5)
    assert rig.said() and rig.said()[0].startswith('Статья 17')


def test_two_witnesses_can_both_be_wrong_and_the_final_still_cuts(maths):
    rig = maths()
    on_the_phone(rig, EAR_FIVE, CLOUD_FIVE)
    assert rig.said() == [FIVE]
    final(rig, 'u1', 'Пять на шесть?')
    assert rig.said() == [FIVE, THIRTY] and rig.c.question_id == 'u1'


# =====================================================================================================================================
# the early lookup fed from the ear: privacy, half a question, requests per turn, a stale result
# =====================================================================================================================================

import asyncio                                                                                       # noqa: E402

from echo_sync.native_prefetch import EarlyLookup, question_key                                      # noqa: E402

RATE_EAR = 'какая сейчас ключевая ставка банка россии'
RATE_FINAL = 'Какая сейчас ключевая ставка Банка России?'
QUIET = 0.45                                                                                         # the ear's text has stood for EAR_FEED_SETTLE_SECONDS


@pytest.fixture
def lookups(call):
    def make(**profile):
        rig = call(**{'fast_text': 'on', **profile})
        rig.w.wire.early.enabled = True            # the coordinator's switch, on for these tests only
        return rig
    return make


async def _silent(*args, **kwargs):
    pass


def _fetch_of(calls):
    async def fetch(question):
        calls.append(question)
        return [{'text': question}]
    return fetch


@pytest.mark.parametrize('private,public', [('у меня зарплата сто тысяч', 'какая сейчас ставка налога'), ('мой паспорт', 'какой сейчас срок действия паспорта'), ('расскажи обо мне', 'какая сейчас ставка налога')],
                         ids=lambda value: value.replace(' ', '_'))
@pytest.mark.parametrize('gap', [0.1, 0.8, 2.0], ids=lambda value: 'gap_%s' % value)
def test_a_personal_piece_of_an_utterance_keeps_its_other_pieces_from_the_public_lookup(lookups, private, public, gap):
    """The gate reads the utterance, the cloud's partial has it whole. As delivered the ear's refused joined reading fell through to the last piece alone, and a slower speaker never had a joined reading."""
    rig = lookups()
    speaks(rig, private, turn='u1', announced=0.2, speech=1.0)
    rig.pump(gap)
    speaks(rig, public, speech=1.0)
    rig.pump(1.0)
    assert rig.w.lookup_calls == [], rig.w.lookup_calls


def test_the_ears_search_is_off_only_for_the_moment_after_a_personal_piece(lookups):
    rig = lookups()
    speaks(rig, 'у меня зарплата сто тысяч', turn='u1', announced=0.2, speech=1.0)
    final(rig, 'u1', 'У меня зарплата сто тысяч.')
    rig.pump(5.0)
    speaks(rig, RATE_EAR, turn='u2', announced=1.0, speech=1.5)
    rig.pump(1.0)
    assert len(rig.w.lookup_calls) == 1


@pytest.mark.parametrize('heard', ['сколько будет десять процентов от двухсот тысяч', 'десять процентов от двухсот тысяч', 'сколько будет пять процентов от тысячи'],
                         ids=lambda value: value.replace(' ', '_'))
def test_a_sum_is_never_searched(lookups, heard):
    """A public request for what code answers. On the ear's text and on the cloud's partial."""
    rig = lookups(quick_math='on')
    rig.c.quick_math = True
    assert rig.c._reference(heard), 'precondition: it is a sum'
    speaks(rig, heard, turn='u1', announced=1.0, speech=1.5)
    rig.pump(1.0)
    assert rig.w.lookup_calls == []
    other = lookups(quick_math='on')
    other.c.quick_math = True
    other.w.feed(S.turn_created('u1', 'user', ''))
    other.w.feed(S.turn_delta('u1', heard, 1))
    other.pump(1.0)
    assert other.w.lookup_calls == []


def test_what_the_base_answers_is_never_searched(lookups):
    rig = lookups()
    text = 'какая ставка налога на прибыль'
    if not rig.c._reference(text):
        text = 'семнадцатая статья налогового кодекса'
    assert rig.c._reference(text), 'precondition: the base has it'
    speaks(rig, text, turn='u1', announced=1.0, speech=1.5)
    rig.pump(1.0)
    assert rig.w.lookup_calls == []


def test_the_second_half_of_a_question_cut_by_a_breath_is_searched_with_the_first(lookups):
    """The cloud's turn is open during the speech, the call's own order: as delivered the first half alone went out on the tick its text came, one request for nothing and the turn's one preparation gone."""
    rig = lookups()
    joined = 'какая сейчас ключевая ставка банка казахстана'
    speaks(rig, 'какая сейчас ключевая ставка', turn='u1', announced=1.0, speech=1.5)
    rig.pump(0.1)
    speaks(rig, 'банка казахстана', speech=0.7)
    rig.pump(QUIET)
    assert [question_key(question) for question in rig.w.lookup_calls] == [question_key(joined)], rig.w.lookup_calls
    final(rig, 'u1', 'Какая сейчас ключевая ставка Банка Казахстана?')
    assert len(rig.w.lookup_calls) == 1, 'the final adopts it'


def test_speech_that_has_begun_again_holds_the_search_back(lookups):
    """The next piece has begun, its text has not come: the question may go on, nothing is searched yet."""
    rig = lookups()
    speaks(rig, 'какая сейчас ключевая ставка', turn='u1', announced=1.0, speech=1.5)
    rig.pump(0.1)
    uid = rig.onset()
    rig.pump(1.0)
    assert rig.w.lookup_calls == []
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, 'банка казахстана')
    rig.pump(QUIET + TICK)
    assert [question_key(question) for question in rig.w.lookup_calls] == [question_key('какая сейчас ключевая ставка банка казахстана')], 'a long second piece joins by the breath before it'


def test_the_ears_text_starts_the_search_a_second_before_a_partial_would(lookups):
    rig = lookups()
    ended = speaks(rig, RATE_EAR, turn='u1', announced=1.0, speech=1.5, partial='Какая сейчас')
    assert rig.w.lookup_calls == [], 'the quiet after it has not lasted yet'
    rig.pump(QUIET)
    assert len(rig.w.lookup_calls) == 1 and rig.w.clock.t - ended <= 0.15 + QUIET + 2 * TICK


def test_a_turn_the_ear_prepared_nothing_for_has_the_two_requests_of_old():
    """As delivered the ear's text, late for a search the cloud's partial had started, still earned the turn its third request, and took the running search back with nothing to replace it."""
    async def go():
        calls = []
        early = EarlyLookup(_fetch_of(calls), _silent, enabled=True)
        early.observe('u', 'Какая сейчас ключевая ставка', now=0)
        await early.tick(now=1)
        await asyncio.sleep(0)
        assert len(calls) == 1
        early.observe_ear('u', 'какая сейчас ставка банка россии', now=1)
        assert not early.task.cancelled() and early.signature == ('u', question_key('Какая сейчас ключевая ставка')), 'the search that runs stays'
        await early.tick(now=2)
        await early.resolve('u', 'А какой курс доллара сейчас?')
        assert len(calls) == 2
        with pytest.raises(RuntimeError):
            await early.resolve('u', 'А какой курс евро сейчас?')
        assert len(calls) == 2
        await early.close()
    asyncio.run(go())


def test_the_ears_late_text_of_the_same_words_leaves_the_search_to_be_adopted():
    async def go():
        calls = []
        early = EarlyLookup(_fetch_of(calls), _silent, enabled=True)
        early.observe('u', RATE_FINAL, now=0)
        await early.tick(now=1)
        await asyncio.sleep(0)
        early.observe_ear('u', 'какая сейчас ключевая ставка', now=1)
        assert await early.resolve('u', RATE_FINAL) and len(calls) == 1
        await early.close()
    asyncio.run(go())


# What the attack on a stale result left standing, pinned: the final adopts only the same turn and the same words, by ``question_key``. Each of these pairs is one word the ear may mishear.
OTHER_QUESTIONS = [
    ('какой сейчас курс доллара', 'какой сейчас курс евро'), ('какая ставка налога за первый квартал', 'какая ставка налога за второй квартал'), ('какая ставка в две тысячи двадцать пятом году', 'какая ставка в 2026 году'),
    ('статья пять налогового кодекса', 'статья 5 трудового кодекса'), ('статья пять налогового кодекса', 'статья 6 налогового кодекса'), ('пункт один статьи пять', 'пункт 2 статьи 5'),
    ('сколько стоит тонна нефти', 'сколько стоит баррель нефти'), ('сколько стоит килограмм золота', 'сколько стоит грамм золота'), ('какой налог на доход в рублях', 'какой налог на доход в долларах'),
    ('можно ли вернуть налог', 'нельзя ли вернуть налог'), ('можно ли вернуть налог', 'можно ли не вернуть налог'), ('какая ставка ндфл сейчас', 'какая ставка ндс сейчас'), ('какой мрот в москве', 'какой мрот в россии'),
    ('сколько процентов налог на прибыль', 'сколько рублей налог на прибыль'), ('сколько дней отпуск', 'сколько часов отпуск'), ('за сколько лет давность', 'за сколько месяцев давность'),
]


@pytest.mark.parametrize('heard,asked', OTHER_QUESTIONS)
def test_a_word_the_ear_misheard_is_another_question(heard, asked):
    assert question_key(heard) != question_key(asked)


def test_a_search_of_the_ear_is_no_answer_to_the_next_turn_with_the_same_words(lookups):
    rig = lookups()
    speaks(rig, RATE_EAR, turn='u1', announced=1.0, speech=1.5)
    rig.pump(QUIET)
    assert len(rig.w.lookup_calls) == 1
    early = rig.w.wire.early
    assert early.task_signature[0] == 'u1'

    async def other_turn():
        return await early.resolve('u2', RATE_FINAL)
    rig.w.run(other_turn())
    assert len(rig.w.lookup_calls) == 2, 'another turn asks for itself'


def test_a_personal_second_half_takes_the_first_with_it(lookups):
    """«какая сейчас ставка налога» | «у меня зарплата сто тысяч»: as delivered the first half had gone before the second was heard."""
    rig = lookups()
    speaks(rig, 'какая сейчас ставка налога', turn='u1', announced=1.0, speech=1.5)
    rig.pump(0.05)
    speaks(rig, 'у меня зарплата сто тысяч', speech=0.8)
    rig.pump(1.0)
    assert rig.w.lookup_calls == []


# -- the cloud cut the utterance: the words in front of a sum in a final of their own -----------------------------------------------------------

@pytest.mark.parametrize('head,sum_,wrong', [('Раздели.', 'Сто на пять.', 'Пятьсот.'), ('Разделите.', 'Двести на четыре.', 'Восемьсот.'), ('Комната.', 'Пять на шесть.', THIRTY), ('Не.', 'Пять на шесть.', THIRTY)],
                         ids=lambda value: value.replace(' ', '_'))
def test_the_words_in_front_of_a_sum_in_a_final_of_their_own(maths, head, sum_, wrong):
    """``_take_candidate``: «a reference asks nothing of the remark before it». A figure does: «Раздели» | «Сто на пять» is no 500."""
    rig = maths()
    rig.w.feed(S.turn_created('u0', 'user', ''))
    final(rig, 'u0', head, after=0.1)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', sum_)
    assert wrong not in rig.said(), rig.said()


def test_a_sum_of_its_own_after_a_remark_long_before_it_is_a_sum(maths):
    rig = maths()
    rig.w.feed(S.turn_created('u0', 'user', ''))
    final(rig, 'u0', 'Ну давай быстрее уже', after=0.1)
    rig.job_ends(0)
    rig.pump(8.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', 'Пять на шесть.')
    assert rig.said() == [THIRTY]


@pytest.mark.parametrize('ear,head,sum_,figure', [('раздели', 'Раздели.', 'Сто на пять', 'Пятьсот.'), ('разделите', 'Разделите.', 'Двести на четыре', 'Восемьсот.'), ('не', 'Не.', 'Пять на шесть', THIRTY)],
                         ids=lambda value: value.replace(' ', '_'))
def test_the_words_in_front_of_a_sum_the_cloud_and_the_ear_cut_alike(maths, ear, head, sum_, figure):
    """Both witnesses read the sum alone and they agree: the ear's run holds the word in front of it."""
    rig = maths()
    speaks(rig, ear, speech=0.5, turn='u0', announced=0.1)
    rig.w.feed(S.turn_done('u0', 'user', head))
    rig.pump(0.1)
    speaks(rig, sum_.lower(), speech=1.0, turn='u1', announced=0.2, partial=sum_)
    rig.pump(1.0)
    assert rig.said() == []
    final(rig, 'u1', sum_ + '.')
    assert figure not in rig.said()


def test_a_sum_in_the_form_of_a_question_stands_on_its_own_right_after_a_final(maths):
    rig = maths()
    rig.w.feed(S.turn_created('u0', 'user', ''))
    final(rig, 'u0', 'Ну давай быстрее уже', after=0.1)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', 'Сколько будет пять умножить на шесть?')
    assert rig.said() == [THIRTY]


def test_the_final_of_the_same_sum_with_no_partial_answers_once(maths):
    rig = maths()
    on_the_phone(rig, EAR_FIVE, '')
    final(rig, 'u1', 'Пять на пять?')
    rig.pump(1.0)
    assert rig.said() == [FIVE] and rig.c.user_boundaries['u1'] == 'provider_turn_done'


def test_the_word_in_front_of_a_sum_that_only_the_ear_heard(maths):
    """The cloud lost «раздели», so nothing it says contradicts the ear's last piece: the ear's own run is what holds the word (``_ear_opens``). What the final then does with «Сто на пять» is the cloud's alone."""
    rig = maths()
    speaks(rig, 'раздели', speech=0.5)
    rig.pump(0.1)
    speaks(rig, 'сто на пять', speech=1.0, turn='u1', announced=0.2, partial='Сто на пять')
    rig.pump(1.2)
    assert rig.said() == []


def test_a_head_the_job_still_judges_is_read_with_the_sum_however_long_ago_it_came(maths):
    rig = maths()
    rig.w.feed(S.turn_created('u0', 'user', ''))
    final(rig, 'u0', 'Ну давай быстрее уже', after=0.1)
    rig.pump(3.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', 'Пять на шесть.')
    assert rig.said() == [] and rig.c.candidate['text'] == 'Ну давай быстрее уже Пять на шесть.'

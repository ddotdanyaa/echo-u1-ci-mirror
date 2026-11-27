"""WAVE 2 / Task C-seg, item 1 (L2 / L2-long): the FIRST cue is a short, speakable unit, released as soon as it exists.

Live evidence 2026-11-02 (corpus run 20261102-000520 and the 05:51 probe): first cues of 6-9 words
(«При нормальном атмосферном давлении вода кипит при ста», «свойство тела сопротивляться изменению своего движения.») are
slow to arrive (cues of 17 characters or fewer came after ~0.54 s, 26 or more after 1.9-3.4 s) and cannot be said in one
breath. The rule (brief of Task C-seg):

* 2-4 words, 5 only when the 4th and 5th belong together (a term, a number with its unit, «не» + word);
* about 5 syllables, never torn from the unit it is part of;
* released as soon as the word AFTER the cue is known: no waiting for punctuation, no waiting for a second portion;
* still not an echo of the question when a cue of that size can say more; never a stall, never a phone phrase.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                                       # noqa: E402
from echo_sync.first_useful import first_cue                                    # noqa: E402
from echo_sync.textutil import WORDS, is_phone_phrase                           # noqa: E402

S = H.CONTROLLED_SETTINGS


def words(text):
    return len(WORDS.findall(text))


def cue(text, question, *, final=True, last=None):
    return first_cue(text, question, S, final=final, last=final if last is None else last)


# --- the unit: what the cue is on text that has fully arrived ---------------------------------------------------------

TABLE = [
    # (question, answer, cue)
    ('Почему небо днем голубое?', 'солнечный свет, проходя через воздух, рассеивается на молекулах.', 'солнечный свет,'),
    ('Назовите три агрегатных состояния вещества', 'Твёрдое, жидкое и газообразное.', 'Твёрдое, жидкое'),
    ('Как называется запись электрической активности сердца', 'Электрокардиограмма, ЭКГ.', 'Электрокардиограмма, ЭКГ.'),
    ('Как называется переход вещества из газообразного состояния в жидкое?', 'Это конденсация.', 'Это конденсация.'),
    ('В каком году началась Первая мировая война?', 'В 1914 году.', 'В 1914 году.'),
    ('Что такое инерция?', 'Свойство тела сопротивляться изменению своего движения.', 'Свойство тела'),
    ('Верно ли, что звук распространяется в вакууме',
     'Нет, звук распространяется только в среде — воздухе, воде, твёрдых телах.', 'Нет, звук распространяется'),
    ('Что такое плотность вещества', 'Плотность — это масса вещества в единице объёма. Обычно её записывают как ρ.',
     'Плотность — это масса'),
    ('Почему металлическая ложка кажется холоднее деревянной?',
     'металл намного лучше проводит тепло и забирает его у руки.', 'металл намного'),
    ('Правда ли что кит рыба?', 'Нет, кит не рыба, а млекопитающее.', 'Нет, кит не рыба,'),
]


@pytest.mark.parametrize('question,answer,expected', TABLE, ids=[row[2] for row in TABLE])
def test_the_first_cue_of_a_complete_answer(question, answer, expected):
    assert cue(answer, question) == expected


def test_a_restating_opening_is_cued_in_short_units_not_after_the_first_new_word():
    """«При нормальном атмосферном давлении вода кипит при ста…»: nothing short says more than the question here, so the
    first cue is the first short unit - not the 8 words the old gate waited for."""
    q = 'Сколько градусов Цельсия составляет температура кипения воды при нормальном атмосферном давлении'
    answer = 'При нормальном атмосферном давлении вода кипит при ста градусах Цельсия.'
    got = cue(answer, q)
    assert got == 'При нормальном' and 2 <= words(got) <= 4


@pytest.mark.parametrize('question,answer,expected', [
    ('Сколько планет в Солнечной системе', 'В Солнечной системе 8 планет, не считая карликовых.', 'В Солнечной системе 8 планет,'),
    ('Сколько градусов в прямом угле', 'В прямом угле 90 градусов, а в развёрнутом угле 180 градусов.', 'В прямом угле 90 градусов,'),
    ('Сколько кислорода в воздухе', 'Кислорода в воздухе около 21 %, а азота около 78 %.', 'Кислорода в воздухе около 21 %,'),
    ('Сколько градусов в прямом угле', 'В прямом угле девяносто градусов, а в развёрнутом сто восемьдесят.',
     'В прямом угле девяносто градусов,'),
])
def test_five_words_only_to_keep_a_number_with_its_unit(question, answer, expected):
    got = cue(answer, question)
    assert got == expected and words(got) == 5


def test_five_words_are_not_allowed_without_a_reason():
    # an echoing opening whose 4th and 5th words are NOT glued: the cue stops at four
    got = cue('Железо хорошо проводит электрический ток и тепло одновременно, как известно.', 'Проводит ли железо электрический ток?')
    assert got and words(got) <= 4, got


def test_a_negation_stays_with_its_word():
    got = cue('Скорость света в вакууме не зависит от скорости источника света.', 'От чего зависит скорость света?')
    assert got and not got.rstrip(',.').endswith((' не', ' ни')), got
    for text in ('Это не рыба и не птица, как всем известно.', 'Нет, кит не рыба, а млекопитающее.'):
        got = cue(text, 'Что это такое?')
        assert got and not got.rstrip(',.').split()[-1].casefold() in ('не', 'ни'), (text, got)


def test_one_indivisible_unit_longer_than_a_cue_is_still_a_cue():
    text = 'Три тысячи двести пятьдесят километров в секунду — это скорость света в стекле.'
    got = cue(text, 'Какова скорость?')
    assert got and text.startswith(got) and not H.cut_atoms(text, ['Три тысячи двести пятьдесят километров'], [got, text[len(got):]])


# --- released as soon as such a unit is available (streaming: the text grows word by word) ------------------------------------

def test_the_cue_is_released_when_the_word_after_it_is_known_not_when_a_second_portion_exists():
    q = 'Что такое плотность вещества'
    answer = 'Плотность — это масса вещества в единице объёма. Обычно её записывают как ρ равно масса.'
    arrived = ''
    for piece in answer.split(' '):
        arrived += piece + ' '
        got = cue(arrived, q, final=False)
        if got:
            break
    assert got == 'Плотность — это масса'
    assert arrived.rstrip() == 'Плотность — это масса вещества', arrived       # one word after the cue, no more
    assert len(arrived) <= 32


def test_no_wait_for_punctuation_after_a_generic_head_noun():
    q = 'Что такое инерция?'
    assert cue('Свойство тела сопротивляться ', q, final=False) == 'Свойство тела'


def test_a_cue_waits_for_the_word_after_it_to_be_whole():
    q = 'Что такое инерция?'
    assert cue('Свойство тела', q, final=False) is None            # «тела» may still grow, nothing follows it
    assert cue('Свойство тела сопротив', q, final=False) is None   # the following word is only half there
    assert cue('Свойство тела сопротивляться', q, final=False) is None
    assert cue('Свойство тела сопротивляться ', q, final=False) == 'Свойство тела'


def test_the_echo_fallback_waits_only_until_no_short_cue_can_say_more():
    q = 'Сколько градусов Цельсия составляет температура кипения воды при нормальном атмосферном давлении'
    stages = [('При нормальном ', None), ('При нормальном атмосферном ', None), ('При нормальном атмосферном давлении ', None),
              ('При нормальном атмосферном давлении вода ', 'При нормальном')]
    for arrived, expected in stages:
        assert cue(arrived, q, final=False) == expected, arrived


def test_a_provider_final_turn_stops_waiting_but_a_pure_echo_so_far_is_not_cued():
    q = 'Сколько градусов Цельсия составляет температура кипения воды при нормальном атмосферном давлении'
    assert cue('При нормальном атмосферном давлении вода кипит ', q, final=False, last=True) == 'При нормальном'
    assert cue('При нормальном атмосферном давлении ', q, final=False, last=True) is None     # may be nothing else
    assert cue('Инерция — это инерция.', 'Что такое инерция', final=True) is None             # the whole answer is the question


# --- never ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('arrived', ['Понял, сейчас быстро ', 'Понял, сейчас быстро проверю ', 'Хорошо, сейчас гляну ',
                                     'Секунду, сейчас найду информацию ', 'Понял, понял, сейчас ', 'Сейчас быстро '])
def test_a_stall_still_being_spoken_is_not_a_cue_yet(arrived):
    assert cue(arrived, 'Что такое плотность?', final=False) is None


def test_a_cue_comes_from_the_answer_after_a_stall_that_has_ended():
    from echo_sync.textutil import strip_process_prefix
    spoken = strip_process_prefix('Понял, сейчас быстро проверю и скажу. Металл намного лучше проводит тепло и забирает его у руки.')
    assert cue(spoken, 'Почему металлическая ложка кажется холоднее деревянной?') == 'Металл намного'


def test_the_first_cue_is_never_a_phone_phrase():
    for answer in ('До свидания. Всего доброго вам и удачи.', 'Ну, пока. Увидимся завтра на уроке.', 'Стоп, стоп. Нажмите на тормоз.'):
        for final in (True, False):
            got = cue(answer, 'Как попрощаться?', final=final)
            assert got is None or not is_phone_phrase(got), (answer, final, got)


UNITS = ['100 °C', '1941–1945', '10:15', 'Александр Сергеевич Пушкин', 'Иванов И. И.', 'и т. д.', 'т. е.', '70 тыс. человек',
         'км/ч', '500 ₽', '5 × 6 = 30', 'в XIX веке', 'сто восемьдесят градусов']


@pytest.mark.parametrize('text', [
    'Вода кипит при 100 °C на уровне моря, как известно.', 'Война шла с 1941–1945 годов, как известно.',
    'Встреча назначена на 10:15 утра, как известно.', 'Это написал Александр Сергеевич Пушкин в юности, как известно.',
    'Приказ подписал Иванов И. И., а утвердил директор.', 'Яблоки, груши и т. д. продаются на рынке каждый день.',
    'Сокращение «т. е.» значит «то есть» и вводит уточнение.', 'Население города — около 70 тыс. человек, и оно растёт.',
    'Самолёт летит со скоростью 900 км/ч над морем, как известно.', 'Штраф составляет 500 ₽ за нарушение правил.',
    'Пять на шесть будет 30, то есть 5 × 6 = 30, как известно.', 'Это произошло в XIX веке в России, как известно.',
    'В развёрнутом угле сто восемьдесят градусов, как известно.',
])
def test_a_cue_never_cuts_a_unit_whatever_has_arrived(text):
    atoms = [u for u in UNITS if u in text]
    assert atoms
    for end in range(1, len(text) + 1):
        arrived = text[:end]
        if end < len(text) and text[end - 1] != ' ':
            continue                                  # word by word
        got = cue(arrived, 'Расскажи подробнее?', final=end == len(text))
        if got:
            assert arrived.startswith(got), (arrived, got)
            assert not H.cut_atoms(text, atoms, [got, text[len(got):]]), (text, got)


def test_a_final_text_always_gets_a_cue_unless_it_is_an_echo_a_stall_or_a_phone_phrase():
    import random
    from echo_sync.first_useful import _adds_nothing
    from echo_sync.textutil import strip_process_prefix
    rng = random.Random(20261102)
    pool = ('вода железо давление тело движение скорость свет масса плотность температура Москва 15 2026 6,5 не ни и в на при '
            'как если но или 100 °C 10:15 км/с сто двадцать градусов процентов Иванов И. И. Пушкин А. С. XIX веке').split()
    question = 'Что такое система?'
    for _ in range(300):
        text = ' '.join(rng.choice(pool) for _ in range(rng.randint(1, 14))) + rng.choice(['', '.', '!'])
        got = cue(text, question)
        if got is None:
            assert (not strip_process_prefix(text) or is_phone_phrase(text) or _adds_nothing(text, question, S)
                    or not [w for w in WORDS.findall(text)]), text
        else:
            assert text.lstrip().startswith(got) and got.strip(), (text, got)


# --- the corpus ------------------------------------------------------------------------------------------------------------

def test_every_first_cue_of_the_hand_corpus_is_short():
    bad, long5, total = [], 0, 0
    for item in [i for i in H.HAND_CORPUS if i.punctuated]:
        got = cue(item.answer, item.question)
        if got is None:
            continue
        total += 1
        n = words(got)
        long5 += n == 5
        if n > 5:
            bad.append((item.id, got))
    assert not bad and total >= 190, (bad[:6], total)
    assert long5 <= 0.2 * total, (long5, total)       # a 5th word is the exception, not the rule


# --- a provider-final segment without a full stop (ruling 1 of the Task 2 review; e4c04ee) ------------------------------
# The provider's turn is over but its text has no terminal punctuation: the last word may be CUT, and the next segment may go on in
# the middle of it («около 300» + «000 километров»). The first portion before that last word is the cue at once - the listener
# starts, and is still behind the published text when the late segment comes, so the stream stays open for it. The WIP change of
# e4c04ee made first_cue do this for the old gate; the first-cue rule of L2 releases the cue before the cut word by construction.

LATE_SEGMENTS = [  # (question, the provider-final segment, its cue)
    # W1F-A (brief task-w1fix-briefs.md): «это» needs its predicate, so «Да, это» is no cue any more; the cue closes at the comma
    # that has ALREADY arrived («close the cue at clause/sentence punctuation that has already arrived, never waiting»).
    ('Можно ли это делать', 'Да, это можно делать, но', 'Да, это можно делать,'),
    ('С какой скоростью движется свет', 'Свет проходит в вакууме около 300', 'Свет проходит'),
    ('Как устроен термос', 'Двойные стенки с вакуумом между ни', 'Двойные стенки'),
]


@pytest.mark.parametrize('question,segment,expected', LATE_SEGMENTS, ids=['but_not', 'number', 'word'])
def test_a_provider_final_segment_without_a_full_stop_is_cued_at_once_before_its_cut_last_word(question, segment, expected):
    got = cue(segment, question, final=False, last=True)
    assert got == expected and segment.startswith(got)
    assert WORDS.findall(segment)[-1] not in WORDS.findall(got)              # never the word that may be cut


@pytest.mark.parametrize('question,segment,continuation,spoken', [
    ('Можно ли это делать', 'Да, это можно делать, но', ' не при высокой температуре.',
     'Да, это можно делать, но не при высокой температуре.'),
    ('С какой скоростью движется свет', 'Свет проходит в вакууме около 300', ' 000 километров в секунду.',
     'Свет проходит в вакууме около 300 000 километров в секунду.'),
    ('Как устроен термос', 'Двойные стенки с вакуумом между ни', 'ми почти не пропускают тепло.',
     'Двойные стенки с вакуумом между ними почти не пропускают тепло.'),
], ids=['but_not', 'number', 'word'])
def test_the_cue_is_out_before_the_late_continuation_and_the_stream_is_open_for_it(tmp_path, question, segment, continuation, spoken):
    run = H.Stream(tmp_path, question, segment, 'words')
    assert run.cues, 'the listener waits for the grace flush: nothing was cued from the provider-final segment'
    assert run.cues[0][1] == run.chunks[0] and spoken.startswith(run.chunks[0])
    assert run.state['streaming'] and not run.state['completed']             # open: the continuation is still to come
    run._feed(H.created('a2', 'assistant', continuation[:3]))
    run._feed(H.done('a2', 'assistant', continuation))
    assert H.nospace(''.join(run.chunks)) == H.nospace(spoken), run.chunks   # whole, in order, no cut word or number
    assert not H.cut_words(spoken, run.chunks)

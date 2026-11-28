"""W1F-A (branch w1f-shape): what a cue or a portion may end on, and a useful first cue at zero delay.

Evidence: .superpowers/sdd/wave2/w1-analysis-summary.txt, groups G1 (w1_02, w1_01), G3 (sc07) and G7 (w1_16, sc10, corpus
20261103-025815). In the dialogue runs of 3 Nov, 13 of 64 first-heard portions ended on a word that needs its head: «У Меркурия
почти», «Венера — из-за плотной», «происходит, когда природные», «Сапсан — самый», «Внутри компаса есть намагниченная», «масса — это,»,
«Акула. Это», «Например, пустую» ... The rule (brief W1F-A): ONE shared «cannot end a portion» predicate - a degree word (почти,
более, менее, очень ...), an existential «нет»/«есть», a copula («это», «является», «представляет (собой)»), «самый», «такой»,
«этот», «который», an attributive adjective/participle/ordinal that agrees with the noun after it - is glue in the first cue and a
cut penalty in the planner (portions / stable_prefix), where hard glue would break the syllable bounds.

The expected values below are written by hand from the texts; none is computed by the code under test.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_seg as H                                                       # noqa: E402
from echo_sync.first_useful import first_cue                                    # noqa: E402
from echo_sync.portioner import portions, stable_prefix                        # noqa: E402
from echo_sync.textutil import WORDS, normalize, syllables                     # noqa: E402

S = H.CONTROLLED_SETTINGS     # the short-cue profile these W1F-A unit tests are about (the call's profile until F1; F1 made it 'meaning')

# Independent of echo_sync on purpose: the closed words of the brief that cannot end a portion (their head follows them).
HEAD_WORDS = frozenset(
    'почти более менее очень совсем слишком чуть примерно приблизительно весьма крайне довольно наиболее наименее '
    'это является являются представляет представляют собой '
    'самый самая самое самые самого самой самому самым самом самых самую '
    'такой такая такое такие такого такому таким таком таких такую '
    'этот эта эти этого этой этому этим этом этих эту '
    'который которая которое которые которого которой которому которым котором которых которую'.split())


def last_word(text):
    words = normalize(text).split()
    return words[-1] if words else ''


def cue(text, question, *, final=False, last=False):
    return first_cue(text, question, S, final=final, last=last)


SYL5 = {'portion_mode': 'syllables', 'target_syllables': 5, 'max_syllables': 8, 'max_words': 4, 'min_words': 2}


# =====================================================================================================================
# 1. The first cue never ends on a word that needs its head (glue in the cue)
# =====================================================================================================================

# (id, question, the text that has arrived, the first cue). Every text already holds the word after the cue, so the cue
# is out on this text: the head of a dangling word is taken along, never waited for beyond what has arrived.
HEAD_CUES = [
    ('w1_02_degree_and_existential_net', 'А почему не Меркурий? Он же ближе к Солнцу',
     'У Меркурия почти нет атмосферы — тепло не удерживается, поэтому ночами там очень холодно.',
     'У Меркурия почти нет атмосферы'),
    ('w1_02_adjective_before_its_noun', 'Какая планета Солнечной системы самая горячая?',
     'Венера — из-за плотной атмосферы и сильного парникового эффекта.', 'Венера — из-за плотной атмосферы'),
    ('w1_01_adjective_before_its_noun', 'Из-за чего она вообще происходит?',
     'происходит, когда природные силы или деятельность человека ослабляют поверхность: дождь, ветер, течение рек, волны,',
     'происходит, когда природные силы'),
    ('w1_09_superlative_samyi', 'Какая птица самая быстрая в мире?',
     'Сапсан — самый быстрый летающий хищник: в пикировании он разгоняется до 300 километров в час.',
     'Сапсан — самый быстрый'),
    ('compass_existential_est_and_adjective', 'Как устроен компас?',
     'В компасе есть магнитная стрелка, которая всегда поворачивается на север.', 'В компасе есть магнитная стрелка,'),
    ('sc07_copula_before_a_parenthetical', 'А почему',
     'масса — это, по сути, мера инерции: чем больше массы, тем труднее изменить скорость.', 'масса — это, по сути,'),
    ('sc07_copula_at_the_end', 'А почему', 'Масса — это мера инертности тела.', 'Масса — это мера'),
    ('sc07_yavlyaetsya_before_a_parenthetical', 'А почему', 'Масса является, по сути, мерой инерции.',
     'Масса является, по сути,'),
    ('sc07_adjective_object', 'А можно пример?', 'Например, пустую тележку легко сдвинуть, а гружёную — трудно.',
     'Например, пустую тележку'),
    ('sentence_initial_eto', 'Какая рыба самая опасная?', 'Акула. Это хищник, который нападает на человека.',
     'Акула. Это хищник,'),
]


@pytest.mark.parametrize('question,text,expected', [row[1:] for row in HEAD_CUES], ids=[row[0] for row in HEAD_CUES])
def test_the_first_cue_takes_the_head_of_a_word_that_needs_it(question, text, expected):
    got = cue(text, question)
    assert got == expected
    assert last_word(got) not in HEAD_WORDS


def test_a_head_that_has_just_become_whole_is_taken_at_once():
    """Zero delay: before W1F-A the cue «Венера — из-за плотной» was out as soon as «атмосферы» was whole. The cue that keeps the
    adjective with its noun is out on the same text: the noun is whole (a space follows it), nothing after it is waited for."""
    q = 'Какая планета Солнечной системы самая горячая?'
    assert cue('Венера — из-за плотной атмосферы', q) is None            # «атмосферы» may still grow
    assert cue('Венера — из-за плотной атмосферы ', q) == 'Венера — из-за плотной атмосферы'
    assert cue('Венера — из-за плотной атмосферы и', q) == 'Венера — из-за плотной атмосферы'


@pytest.mark.parametrize('question,arrived,expected', [
    # 2+3+1+6 = 12 syllables; the head «стрелка,» would make 14
    ('Как устроен компас?', 'Внутри компаса есть намагниченная стрелка, которая', 'Внутри компаса есть намагниченная'),
    # T-class N14 (finance): «Номинал привилегированной акции» would be 13 spoken syllables
    ('Что такое номинал акции?', 'Номинал привилегированной акции ', 'Номинал привилегированной'),
])
def test_a_head_heavier_than_an_issued_portion_may_be_is_not_taken(question, arrived, expected):
    """N14 (owner contract): an issued portion has at most 12 spoken syllables in the call's profile. Where the head would lengthen
    the cue beyond that, the cue is the one of before W1F-A, out at the same moment: the word after it is known, nothing more."""
    got = cue(arrived, question)
    assert got == expected
    assert syllables(got) <= 12


def test_an_adjective_is_not_glued_to_a_function_word():
    """«и» is also the name of a letter (a noun reading that agrees with «зелёный»): a function word is never the head noun."""
    assert cue('Красный, зелёный и синий цвета смешивают на палитре.', 'Какие цвета основные?', final=True, last=True) \
        == 'Красный, зелёный'


def test_a_word_that_needs_its_head_is_free_before_punctuation():
    """«Нет,» is an answer, not the existential «нет атмосферы»; a copula before a full stop ends its sentence."""
    assert cue('Нет, звук распространяется только в среде — воздухе, воде, твёрдых телах.',
               'Верно ли, что звук распространяется в вакууме', final=True, last=True) == 'Нет, звук распространяется'
    assert portions('Я знаю это. Мы видели это.', SYL5) == ['Я знаю это.', 'Мы видели это.']


def test_never_silent_when_nothing_but_dangling_cuts_fit_the_cue():
    """When glue leaves no other place inside the 2-4 (5) words, the dangling cut is still a last resort: a final answer is never
    left without a cue (test_first_cue_never_silent). «Испарение — это когда самые быстрые молекулы» has no non-dangling cut in four
    words after its echoed head."""
    q = 'Объясни, что такое испарение'
    text = 'Испарение — это когда самые быстрые молекулы покидают поверхность жидкости.'
    got = cue(text, q, final=True, last=True)
    assert got and text.startswith(got)


# =====================================================================================================================
# 2. The planner: a cut PENALTY (not glue) - the syllable bounds hold, a dangling end is taken only when nothing else fits
# =====================================================================================================================

@pytest.mark.parametrize('text,expected', [
    # «Мы видим очень» is exactly the target length, but «очень» needs «яркий»: the cut moves while the bounds still hold.
    ('Мы видим очень яркий свет звезды.', ['Мы видим', 'очень яркий свет звезды.']),
    # an adjective before its noun («плотной | атмосферы»)
    ('Тепло держит плотной атмосферы слой.', ['Тепло держит', 'плотной атмосферы слой.']),
])
def test_the_planner_moves_a_cut_away_from_a_word_that_needs_its_head(text, expected):
    assert portions(text, SYL5) == expected


@pytest.mark.parametrize('settings', [H.CONTROLLED_SETTINGS, {'preset': 'slow'}], ids=['controlled', 'slow'])
def test_the_planner_does_not_trade_a_dangling_adjective_for_a_bare_number(settings):
    """A number needs the word it counts as much as an adjective needs its noun (portioner._counted_marks, the cue's own rule):
    «12 важных показателей» cannot stay whole within 8 syllables, and the plan must not isolate «12» to keep «важных показателей»."""
    got = portions('12 важных показателей помогают учителю объяснить работу системы.', settings)
    assert got[0] != '12', got


def test_the_planner_still_respects_the_bounds_when_only_a_dangling_cut_fits():
    """numeric_forms-12 of the S6 corpus («примерно в 1 500 ₽,»): glue would make one unit of 15 syllables. A penalty leaves the cut
    where the bounds force it."""
    text = 'Обычно берут воду примерно 80 градусов, то есть не кипяток.'
    got = portions(text, H.CONTROLLED_SETTINGS)
    assert H.lossless_problem(text, got) is None
    for portion in got:
        assert syllables(portion) <= 8 or len(WORDS.findall(portion)) == 1 or '80 градусов' in portion, got


def test_stable_prefix_never_commits_a_portion_that_ends_on_a_word_that_needs_its_head():
    """The streamed continuation plans with the same penalty: «Мы видим очень» was committed before W1F-A."""
    text = 'Мы видим очень яркий свет звезды и слышим очень громкий звук грома вдалеке над рекой.'
    committed = stable_prefix(text, SYL5)
    assert committed == 'Мы видим'


# =====================================================================================================================
# 3. Zero delay (a): the cue closes at clause or sentence punctuation that has ALREADY arrived
# =====================================================================================================================

def feed(directory, question, pieces, *, lookup=False):
    """The host-like controller (helpers_s6_seg) fed one question and one assistant turn as exactly these provider deltas.
    Returns ``(cues, controller)`` with ``cues`` = [(index of the assistant event, text)]."""
    c = H.host_controller(directory)
    c.provider(H.created('u1', 'user', question.split()[0]))
    c.provider(H.done('u1', 'user', question))
    if lookup:
        c.provider({'type': 'delegation.created', 'item': {'id': 'd', 'target': 'client', 'user_bidi_turn_id': 'u1'}})
        c.grounding(c.epoch, [{'url': 'https://example.org/source', 'text': 'source'}])
        c.delivery_sent(c.epoch, 'd')
    events = [H.created('a1', 'assistant', pieces[0])] + [H.delta('a1', piece, n) for n, piece in enumerate(pieces[1:], 1)]
    cues = []
    for index, event in enumerate(events):
        cues += [(index, a['text']) for a in c.provider(event) if a['type'] == 'speak']
    return cues, c


VACCINE = ('Расскажи, как работает прививка',
           ['Прививка тренирует ', 'иммунитет', ':', ' в тело', ' вводят', ' безопасный', ' фрагмент', ' вируса', '.'])


def test_w1_16_the_cue_takes_the_word_before_a_colon_that_has_arrived(tmp_path):
    """Live 3 Nov 03:30:30 (w1_16 step 1): the ':' delta released «Прививка тренирует», although «иммунитет:» was already there."""
    cues, c = feed(tmp_path, *VACCINE)
    # F1 (wave F): a call's first cue is a meaning portion - a 3-word clause before its colon waits for the sentence (it was out on
    # the ':' delta, 2); still the clause with the word before the colon, never «Прививка тренирует»
    assert cues[0] == (8, 'Прививка тренирует иммунитет:')
    assert c.state()['chunks'][0] == 'Прививка тренирует иммунитет:'


def test_sc10_the_reference_cue_takes_the_term_before_its_colon(tmp_path):
    """sc10 lookup: «Статья 421 ГК РФ устанавливает принцип свободы договора: …» was cued «принцип свободы» on the delta that brought
    «договора:». The term ends at the colon that has arrived with it."""
    q = 'Что устанавливает статья 421 Гражданского кодекса Российской Федерации?'
    pieces = ['Статья', ' 421', ' ГК', ' РФ', ' устанавливает', ' принцип', ' свободы', ' договора:', ' стороны', ' свободны.']
    cues, _ = feed(tmp_path, q, pieces, lookup=True)
    assert cues[0] == (9, 'принцип свободы договора: стороны свободны.')   # F1: the meaning portion (was (7, «…договора:»))


@pytest.mark.parametrize('question,text,expected', [
    ('Назовите три состояния воды', 'Лёд, вода и пар.', 'Лёд, вода и пар.'),
    # 13 syllables to the full stop: more than an issued portion may carry (N14), so the cue stays as it was
    ('Назовите три агрегатных состояния вещества', 'Твёрдое, жидкое и газообразное.', 'Твёрдое, жидкое'),
    ('Как работает прививка', 'Прививка тренирует иммунитет: в тело вводят безопасный фрагмент вируса.',
     'Прививка тренирует иммунитет:'),
    ('Как работает прививка', 'Прививка тренирует иммунитет — в тело вводят безопасный фрагмент вируса.',
     'Прививка тренирует иммунитет'),
])
def test_the_cue_closes_at_the_first_punctuation_inside_the_word_budget(question, text, expected):
    assert cue(text, question, final=True, last=True) == expected


@pytest.mark.parametrize('question,text,expected', [
    # the first punctuation lies beyond four words: the short cue stays as it is, nothing is waited for
    ('Что такое инерция?', 'Свойство тела сопротивляться изменению своего движения.', 'Свойство тела'),
    # a decimal comma, a time and a range are no clause punctuation: the number goes on
    ('Какая доля расходов?', 'Доля расходов на питание 6,5 процента в бюджете.', None),
    ('Когда начало?', 'Начало встречи в 10:15 утра, как известно.', None),
])
def test_closure_never_ends_a_cue_inside_a_number_or_beyond_four_words(question, text, expected):
    got = cue(text, question, final=True, last=True)
    if expected is not None:
        assert got == expected
    for atom in ('6,5', '10:15'):
        if atom in text and got:
            assert not H.cut_atoms(text, [atom], [got, text[len(got):]]), got


@pytest.mark.parametrize('arrived', ['Доля составила 6,', 'Встреча в 10:', 'Война шла с 1941–', 'Это было в XIX–'])
def test_a_number_before_punctuation_is_never_closed_while_its_rest_may_follow(arrived):
    got = cue(arrived, 'Расскажи подробнее?')
    assert got is None or not got.rstrip(',:–').endswith(('6', '10', '1941', 'XIX')), got


def first_release(item, how='words'):
    """(index of the assistant event, text) of the first cue of a corpus answer streamed through the host-like controller, on the
    short-cue profile whose closure the property below is about (F1: a call runs on the meaning profile, which has no such closure)."""
    with tempfile.TemporaryDirectory(prefix='w1f-') as directory:
        run = H.Stream(directory, item.question, item.answer, how, settings=S)
        return run.cues[0] if run.cues else None


def test_closure_adds_no_wait_the_cue_is_never_later_and_never_longer_than_four_words(monkeypatch):
    """Property twin of the w1_16 test: over the hand corpus streamed word by word, with the closure the first cue is out on the
    same event as without it (or earlier), it only ever ADDS the words up to that punctuation, and never past four words."""
    import echo_sync.first_useful as FU
    import echo_sync.portioner as P
    sample = [item for item in H.HAND_CORPUS if item.punctuated][::3]
    closed = {item.id: first_release(item) for item in sample}
    original = P._last_word_closure

    def without_punctuation_closure(tokens, heads, cfg):
        found = original(tokens, heads, cfg)
        return None if found == 'punct' else found
    monkeypatch.setattr(P, '_last_word_closure', without_punctuation_closure)
    monkeypatch.setattr(FU, '_closed', lambda text, cuts, k, max_words: text[:cuts[k].end].strip())
    later, changed, longer, extended = [], [], [], 0
    for item in sample:
        plain, mine = first_release(item), closed[item.id]
        if plain is None or mine is None:
            assert plain == mine, item.id
            continue
        if mine[0] > plain[0]:
            later.append((item.id, plain, mine))
        elif mine[0] == plain[0] and not mine[1].startswith(plain[1]):
            changed.append((item.id, plain, mine))
        if H.product_words(mine[1]) > max(4, H.product_words(plain[1])):
            longer.append((item.id, mine))
        extended += mine[1] != plain[1]
    assert not later and not changed and not longer, (later[:5], changed[:5], longer[:5])
    assert extended, 'the closure never applied: the property says nothing'


# =====================================================================================================================
# 4. Zero delay (b): head elision instead of the restatement fallback, when the new unit of the same sentence is ready
# =====================================================================================================================

WWI = 'В каком году началась Первая мировая война?'


def test_corpus_date_the_year_is_the_cue_not_the_restated_head(tmp_path):
    """Corpus 20261103-025815 date_world_war_one: deltas 'Первая мировая началась в ', '1914', ' ', 'году.'; the cue «Первая мировая»
    came on the last delta, which had already completed «в 1914 году.». The head is elided on the SAME delta."""
    cues, c = feed(tmp_path, WWI, ['Первая мировая началась в ', '1914', ' ', 'году.'])
    assert cues[0] == (3, 'в 1914 году.')
    assert c.state()['chunks'][0] == 'в 1914 году.'


def test_the_restatement_stays_when_the_new_unit_is_not_ready_yet():
    """Never silent and never a wait: «Великая Отечественная война началась 22 июня…» - when the restatement is due (five words), the
    first new unit («22 июня 1941 года») is not complete, so the restatement is the cue, as before; the whole answer is dictated."""
    run = H.stream('Когда началась Великая Отечественная война', 'Великая Отечественная война началась 22 июня 1941 года.', 'words',
                   walk=False)
    assert run.cues and run.cues[0].startswith('Великая Отечественная')
    assert H.nospace(''.join(run.chunks)) == H.nospace('Великая Отечественная война началась 22 июня 1941 года.')


@pytest.mark.parametrize('how', ['words', 'chars5', 'chars1'])
def test_head_elision_does_not_depend_on_how_the_provider_slices_the_text(how):
    """The decision is made on the first clause once it has ended (and only when it fits the first-cue window), so a published head
    is never elided afterwards and an elided one never comes back: the dictated text is the same for every slicing, nothing rewritten."""
    run = H.stream(WWI, 'Первая мировая началась в 1914 году. Её начало связано с убийством эрцгерцога.', how, walk=False)
    assert run.cues and run.cues[0] == 'в 1914 году.'
    assert H.nospace(''.join(run.chunks)) == H.nospace('в 1914 году. Её начало связано с убийством эрцгерцога.')
    assert not any('Поправка' in chunk for chunk in run.chunks)


def test_a_provider_final_segment_does_not_publish_a_restatement_that_a_later_segment_would_elide():
    """A segment that stops after the new word («…в 1914 ») may be followed by its rest («году.»): the restatement waits for the end of
    the answer (the grace flush, never silent) instead of being published and then contradicted by the elision."""
    assert cue('Первая мировая началась в 1914 ', WWI, final=False, last=True) is None
    # the grace flush declares the text final: never silent, and the year is the cue then (a 5th word keeps «в» with its number)
    assert cue('Первая мировая началась в 1914 ', WWI, final=True, last=True) == 'Первая мировая началась в 1914'
    # a segment that holds no new word yet is no restatement to hold back: nothing to say, as before
    assert cue('Первая мировая началась ', WWI, final=False, last=True) is None


def test_the_held_back_restatement_is_still_spoken_at_the_grace_flush(tmp_path):
    """The real controller on an injected clock (test_task1_review_round2.Session): the provider ends its turn after «…в 1914 », no
    newer segment comes, and the host's 0.1 s tick declares the end of the answer after the grace window - a cue is spoken then."""
    from test_task1_review_round2 import Session
    s = Session(tmp_path)
    s.ask(WWI)
    s.at(0.3, H.created('a1', 'assistant', 'Первая мировая '))
    s.at(0.6, H.done('a1', 'assistant', 'Первая мировая началась в 1914 '))
    s.until(4.0)
    assert s.cues and s.cues[0][1] == 'Первая мировая началась в 1914'
    assert 0.6 < s.cues[0][0] <= 0.6 + 1.2 + 0.2           # the grace window (ANSWER_GRACE_SECONDS) and one tick


LAW = 'Что устанавливает статья 421 Гражданского кодекса Российской Федерации?'


@pytest.mark.parametrize('verb', ['закрепляет', 'регулирует', 'определяет', 'предусматривает', 'устанавливает'])
def test_reference_verbs_are_a_class_the_echoed_reference_is_never_the_cue(tmp_path, verb):
    """Corpus lookup_law_article: «Статья 421 ГК РФ закрепляет принцип…» to «Что устанавливает статья 421…» was cued «Статья 421»
    (echo_only) only because the verb differed from the question's."""
    pieces = ['Статья', ' 421', ' ГК', ' РФ', ' ' + verb, ' принцип', ' свободы', ' договора:', ' стороны', ' свободны.']
    cues, c = feed(tmp_path, LAW, pieces, lookup=True)
    assert cues[0] == (9, 'принцип свободы договора: стороны свободны.')   # F1: the meaning portion (was (7, «…договора:»))


@pytest.mark.parametrize('verb', ['устанавливает', 'закрепляет'])
def test_a_long_echoed_reference_is_never_published_and_then_corrected(tmp_path, verb):
    """Word by word, a reference spelled out in full («Статья 421 Гражданского кодекса Российской Федерации …») is longer than the
    first-cue window: a restatement of its first words must not be spoken and then replaced by «Поправка: …» once the verb arrives."""
    text = f'Статья 421 Гражданского кодекса Российской Федерации {verb} принцип свободы договора: стороны свободны.'
    cues, c = feed(tmp_path, LAW, H.slices(text, 'words'), lookup=True)
    assert cues and cues[0][1] == 'принцип свободы договора: стороны свободны.'      # F1: the meaning portion (was «…договора:»)
    assert not any('Поправка' in chunk for chunk in c.state()['chunks'])


def test_a_reference_that_differs_from_the_question_is_not_elided():
    from echo_sync.first_useful import compact_opening
    body = 'принцип свободы договора: стороны свободны.'
    for opening in ('Статья 422 ГК РФ закрепляет ', 'Статья 421 НК РФ закрепляет ', 'Статья 421 ГК РФ не закрепляет '):
        assert compact_opening(opening + body, LAW) == opening + body


# =====================================================================================================================
# 5. Discourse acknowledgements and stalls are scaffolding (textutil, like the praise lead) - never when they are the whole reply
# =====================================================================================================================

@pytest.mark.parametrize('text,body', [
    ('А, понял — Вторая мировая началась в 1939 году.', 'Вторая мировая началась в 1939 году.'),        # sc03 step 1
    ('Ага. Вторая мировая началась в 1939 году.', 'Вторая мировая началась в 1939 году.'),
    ('Угу, на сфере сумма углов больше.', 'на сфере сумма углов больше.'),
    ('Понятно, тогда это 1939 год.', 'тогда это 1939 год.'),
    ('Хорошо, на сфере сумма углов больше 180 градусов.', 'на сфере сумма углов больше 180 градусов.'),
    ('Ясно — тогда это 1939 год.', 'тогда это 1939 год.'),
    ('Спасибо, понял, на плоскости сумма углов 180 градусов.', 'на плоскости сумма углов 180 градусов.'),
    ('Ладно, другой пример — велосипед и грузовик.', 'другой пример — велосипед и грузовик.'),     # sc07 step 5
])
def test_an_acknowledgement_lead_is_scaffolding(text, body):
    from echo_sync.textutil import strip_process_prefix
    assert strip_process_prefix(text) == body


@pytest.mark.parametrize('text,body', [
    ('Спасибо, понял, сейчас проверю аккуратно. Сумма углов 180 градусов.', 'Сумма углов 180 градусов.'),   # w1_07 step 3
    ('Хорошо, сейчас разложу это по полочкам. Масса — мера инерции.', 'Масса — мера инерции.'),            # w1_07 step 4
    ('Сейчас объясню. Масса — мера инерции.', 'Масса — мера инерции.'),
    ('Сейчас объясню: масса — мера инерции.', 'масса — мера инерции.'),
    ('Давайте разложим. Масса — мера инерции.', 'Масса — мера инерции.'),
    ('Давайте разложим по полочкам. Масса — мера инерции.', 'Масса — мера инерции.'),
    ('Понял, подождите, слушаю. Сумма углов 180 градусов.', 'Сумма углов 180 градусов.'),                  # w1_07 step 3
])
def test_a_stall_phrase_is_scaffolding(text, body):
    from echo_sync.textutil import strip_process_prefix
    assert strip_process_prefix(text) == body


@pytest.mark.parametrize('text', ['Понял, подождите, слушаю.', 'Сейчас объясню.', 'Давайте разложим по полочкам.',
                                  'Хорошо, сейчас разложу это по полочкам.'])
def test_a_lone_stall_phrase_is_nothing(text):
    from echo_sync.textutil import strip_process_prefix
    assert strip_process_prefix(text) == ''


@pytest.mark.parametrize('text', ['Ага.', 'Угу.', 'Хорошо.', 'Хорошо, спасибо.', 'Ладно.'])
def test_a_lone_acknowledgement_is_nothing(text):
    """F3 (the owner's call of 3 Nov, item 1): these five were pinned as "the whole reply: never stripped by the lead rule". A reply made only of
    an acknowledgement («Угу.», «Понял, спасибо.» - the cloud's answer to a remark) is not an answer: nothing is cued for it, and the watchdog
    reports a question nobody answered as before (tests/test_f3_process_sentences.py)."""
    from echo_sync.textutil import strip_process_prefix
    assert strip_process_prefix(text) == ''


@pytest.mark.parametrize('text', [
    'Понятно, что вода кипит при ста градусах.', 'Хорошо, что вы спросили об этом.', 'Понял — это прошедшее время глагола.',
    'Ясно видно, что небо голубое.', 'Хорошо проводит тепло металл.', 'Да, на сфере сумма углов больше.',
    'Ладно, если хочешь, расскажу подробнее.', 'Подождите, пока вода закипит.', 'Сейчас расскажу вам подробно, что такое масса.',
    'Давайте разложим числа на множители.',
])
def test_content_that_looks_like_an_acknowledgement_is_left_alone(text):
    from echo_sync.textutil import strip_process_prefix
    assert strip_process_prefix(text) == text


@pytest.mark.parametrize('how', ['words', 'chars5'])
def test_sc03_the_first_cue_after_a_correction_starts_with_the_answer(how):
    """sc03: the cloud's reply to a corrected question opened «А, понял — Вторая началась в 1939.»; that lead passed the gate as the
    first portion and the year came in portion 2."""
    run = H.stream('Когда началась Вторая мировая война?', 'А, понял — Вторая началась в 1939 году.', how, walk=False)
    assert run.cues and run.cues[0].startswith('Вторая')
    assert '1939' in ' '.join(run.chunks) and not any('понял' in chunk.casefold() for chunk in run.chunks)

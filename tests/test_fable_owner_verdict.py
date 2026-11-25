"""Fable revision 10.11, class «who owns the verdict» (К13 strengthened by a quantity, not by cases).
20:51 (call 20261109-205157): a test question read from a sheet, 26 words, no question form: the job's right answer was wiped by the guess «long and formless is talk».
20:54 (call 20261109-205452): the final of a turn the ear had stood in for 22 s earlier brought a whole new question and nobody judged it; then the ear heard 122,
the cloud 322, and the base answered 322 as if it were sure."""
import pytest
from echo_sync.utterance_judge import not_addressed, reads_text
from test_h1_fast_text import rig, user_says      # noqa: F401 - rig is the fixture

SHEET = ('Та-ак, органы внутренних дел участвуют вместе с налоговыми органами . проведения любых мероприятий налогового контроля, выездных налоговых проверок, '
         'выездных и камеральных налоговых проверок, встречных налоговых проверок. Хм')
CHOICE = 'Органы внутренних дел участвуют вместе с налоговыми органами в проведении выездных налоговых проверок.'
TASK = ('Так, значит, рассчитать долю каждого вида ценных бумаг в общем объеме внутреннего долга на ноль первое, ноль первое две тысячи семнадцатое и на ноль первое, '
        'ноль первое две тысячи восемнадцатое, постройте сравнительную столбчатую, круговую диаграмму')
TALK = ('Вот мы сегодня с другом проверяли это всё целый вечер и снова вернулись, а потом опять всё то же самое, причём уже поздно, '
        'мы поговорили сколько, четырнадцать минут, и опять вернулись к этому')
TALK_EN = 'So yesterday we were talking with my friend about this thing and you know it was kind of late and then we went back to it again and I was like okay whatever it is'
SHEET_EN = ('The company purchased equipment for twelve thousand dollars with useful life five years, residual value two thousand dollars, '
            'annual straight line depreciation expense equals one thousand, two thousand, three thousand, four thousand')


@pytest.mark.parametrize('text,read', [(SHEET, True), (TASK, True), (SHEET_EN, True), (TALK, False), (TALK_EN, False), ('', False)])
def test_text_read_from_a_sheet_is_told_from_talk_by_its_share_of_function_words(text, read):
    assert reads_text(text) is read


def test_a_sheet_read_aloud_is_no_long_talk_and_talk_still_is(rig):
    c = rig.w.controller
    assert not c._long_talk(SHEET, c.state()) and not c._long_talk(SHEET_EN, c.state())
    assert c._long_talk(TALK, c.state()) and c._long_talk(TALK_EN, c.state())
    assert not_addressed(SHEET, []) is None and not_addressed(' '.join(['вот я сейчас смотрю на экран и вижу, идут секунды в телефоне'] * 3), [])[0] == 'long'


def test_the_job_s_answer_to_a_sheet_read_aloud_is_said(rig):
    user_says(rig, 'u1', SHEET)
    rig.pump(0.5)
    rig.say(0, CHOICE)
    rig.fake.run(0).finish()
    rig.pump(4.0)
    assert rig.cues() and rig.cues()[0].startswith('Органы внутренних дел'), rig.cues()


def test_one_option_of_what_was_read_is_an_answer_and_the_whole_said_back_is_not(rig):
    c = rig.w.controller
    assert not c._said_already(CHOICE, SHEET), 'a choice is less than what was read: an answer'
    whole = 'Органы внутренних дел участвуют вместе с налоговыми органами проведения любых мероприятий налогового контроля выездных налоговых проверок выездных и камеральных налоговых проверок встречных налоговых проверок'
    assert c._said_already(whole, SHEET), 'the task said back to the one who read it is no answer (h30, К16)'


def test_a_final_that_brings_a_new_question_after_the_ear_stood_in_is_judged_however_late(rig):
    c = rig.w.controller
    final = {'id': 'u9', 'text': 'Ммм. Лицами. Ммм федеральных федеральных Хорошо. Четыреста двадцать вторая статья Налогового кодекса'}
    c.ear_stood_open = {'tid': 'u9', 'text': 'лицами федеральных', 'at': c.clock() - 22.0, 'hit': None, 'declined': True}
    assert c._ear_stood_short(final)
    c.ear_stood_open = {'tid': 'u9', 'text': 'лицами федеральных', 'at': c.clock() - 22.0, 'hit': None}       # disposed of as said back: nothing was opened either
    assert c._ear_stood_short(final)
    c.ear_stood_open = {'tid': 'u9', 'text': 'лицами федеральных', 'at': c.clock() - 22.0, 'hit': None, 'declined': True}
    assert not c._ear_stood_short({'id': 'u9', 'text': 'Ммм, лицами федеральных, да'}), 'the same words late: it has been judged'


def test_two_witnesses_two_numbers_is_one_exact_question_and_only_once(rig, monkeypatch):
    c = rig.w.controller
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: 'есть сто двадцать вторая статья налогового кодекса')
    cloud = 'триста двадцать вторая статья Налогового кодекса'
    assert c._number_witness('Статья 322 Налогового кодекса — …', cloud, 'u0') == 'Статья 322 Налогового кодекса — …', 'one disagreement is the ear mishearing (a sixth of the numbered finals): the cloud answers'
    asked = c._number_witness('Статья 322 Налогового кодекса — …', cloud, 'u1')
    assert '122' in asked and '322' in asked and '?' in asked, 'the number is said again and the witnesses differ again: asked, both numbers'
    again = c._number_witness('Статья 322 Налогового кодекса — …', cloud, 'u2')
    assert again != 'Статья 322 Налогового кодекса — …', 'a repeated disagreement confirms nothing: no bare answer on one witness'
    assert again.startswith('Если 322') and again.endswith('Статья 322 Налогового кодекса — …') and '?' not in again.split(':')[0], 'the answer names its premise; no loop of clarifications'
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: 'статья сто двадцать два')
    assert c._number_witness('Y', 'статья четыреста двадцать два', 'u3').startswith('Если 422'), 'other numbers, the same doubt: still not bare'
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: 'статья четыреста двадцать два')
    assert c._number_witness('Z', 'статья четыреста двадцать два', 'u4') == 'Z' and c.number_asked is None, 'both hear one number: the doubt is over'
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: 'есть сто двадцать вторая')
    assert c._number_witness('Z', 'статья четыреста двадцать два', 'u5') == 'Z' and '?' in c._number_witness('Z', 'статья четыреста двадцать два', 'u5'), 'a new doubt: trusted once, then asked'
    monkeypatch.setattr(c, '_ear_words', lambda final, floor=None, split=False: '')
    assert c._number_witness('X', 'статья четыреста двадцать два', 'u6') == 'X', 'the ear heard nothing: one witness, the answer goes'


def test_the_cloud_gluing_an_earlier_breath_to_the_question_is_no_disagreement(rig, monkeypatch):
    c = rig.w.controller
    now = c.clock()
    c.ear_said = [{'text': 'хорошо', 'onset': now - 5.0, 'offset': now - 4.5, 'acted': False}, {'text': 'что такое ндфл', 'onset': now - 3.0, 'offset': now - 1.0, 'acted': False}]
    first = {'text': 'что такое ндфл', 'run': [{'onset': now - 3.0, 'offset': now - 1.0}], 'hit': 'Налог на доходы физических лиц.'}
    assert 'Что такое' in c._cloud_tails(first, 'u1', 'Hmm. Хорошо. Что такое')
    monkeypatch.setattr(c, '_ear_said_of', lambda first, tid: ['что такое ндфл'])
    assert c._ear_agrees(first, 'u1', 'Hmm. Хорошо. Что такое')
    assert not c._ear_agrees(first, 'u1', 'Hmm. Хорошо. Сколько стоит'), 'what is left must still go the way the ear heard'
    assert not c._ear_agrees(first, 'u1', 'Посчитай налог. Что такое'), 'words the ear did not hear before are not dropped'
    c.ear_said.insert(0, {'text': 'сто двадцать не', 'onset': now - 8.0, 'offset': now - 7.0, 'acted': False})
    assert c._cloud_tails(first, 'u1', 'Сто двадцать. Что такое') == ['Сто двадцать. Что такое'], 'a number before the question is its condition: kept'
    assert c._cloud_tails(first, 'u1', 'Не. Что такое') == ['Не. Что такое'], 'so is a negation'


@pytest.mark.parametrize('said,asks', [
    ('так а седьмой счёт он активный или пассивный', True),      # the call of 10.11 10:39
    ('это счёт дебетовый или кредитовый', True),
    ('is this account active or passive', True),
    ('седьмой счёт активный', False),
    ('или пассивный', False),      # nothing is named before the choice
    ('активный или пассивный счёт бывает разный по своей природе', False),      # the choice is not what the utterance ends with
])
def test_a_choice_of_two_at_the_end_asks_with_no_question_word(said, asks):
    from echo_sync.classifier import alternative_question
    from echo_sync.textutil import norm_words
    assert alternative_question(norm_words(said)) is asks


def test_the_choice_of_two_is_a_question_for_the_judge(rig):
    from echo_sync.classifier import QUESTION, analyze
    c = rig.w.controller
    assert analyze('Так, а седьмой счёт, он активный или пассивный', c.state(), [], c.settings).kind == QUESTION


def test_a_choice_of_two_said_back_from_the_waiting_portion_is_no_question():
    """Full run of 1597136: «короче говоря вклада или акций» over the portion «… в пределах вклада или акций.» asked instead of going on."""
    from echo_sync.classifier import analyze, QUESTION
    from echo_sync.settings import CALL_SETTINGS
    portion = 'Ограниченная: только в пределах вклада или акций.'
    state = {'chunks': ['Первая часть ответа.', portion], 'chunk_index': 1, 'revision': 1}
    assert analyze('короче говоря вклада или акций.', state, [], CALL_SETTINGS).kind != QUESTION
    assert analyze('а седьмой счёт он активный или пассивный', state, [], CALL_SETTINGS).kind == QUESTION


def test_a_question_word_in_the_portion_said_in_ones_own_way_is_no_question():
    """The call of 11.11 08:45: over «Нужны были мундиры, обувь,» the speaker said «что соответственно нужны были»; its «что» retired the whole talk."""
    from echo_sync.classifier import analyze, QUESTION
    from echo_sync.settings import CALL_SETTINGS
    portion = 'Нужны были мундиры, обувь,'
    state = {'chunks': ['При этом армия не могла существовать без системы снабжения.', portion], 'chunk_index': 1, 'revision': 1}
    assert analyze('что соответственно нужны были', state, [], CALL_SETTINGS).kind != QUESTION
    assert analyze('а что такое рекрутская повинность', state, [], CALL_SETTINGS).kind == QUESTION      # a question about something else still asks
    assert analyze('так что такое нужны были', state, [], CALL_SETTINGS).kind == QUESTION               # «что такое …» asks about the portion's own words
    assert analyze('а почему нужны были', state, [], CALL_SETTINGS).kind == QUESTION                    # another question word is no conjunction


def test_a_question_with_a_word_of_its_own_over_a_portion_that_ends_like_it_still_asks():
    """U85 (chaos search_hang, seeds 0 and 1): over «Статья 21 Налогового кодекса о налогах и сборах.» the question asked again, «что говорит статья 21
    налогового кодекса», ends with two words of the portion and was taken for the portion said back: no answer, no lookup. Its «говорит» is a word of
    meaning of its own; the said-back guard holds only an utterance that adds none (SAID_BACK_OWN) to the portion's words."""
    from echo_sync.classifier import analyze, QUESTION
    from echo_sync.settings import CALL_SETTINGS
    for article in ('21', '17'):
        state = {'chunks': [f'Статья {article} Налогового кодекса о налогах и сборах.'], 'chunk_index': 0, 'revision': 1}
        for heard in (f'что говорит статья {article} налогового кодекса', f'Что говорит статья {article}', f'Что говорит статья {article} Налогового'):
            assert analyze(heard, state, [], CALL_SETTINGS).kind == QUESTION, heard


def test_the_portion_said_back_with_a_pronoun_an_introductory_word_or_another_case_is_no_question():
    """U85 remainder (class K8): the lock counts the speaker's words of meaning by lemmas: a pronoun, an introductory verb and a word of the portion in
    another case carry none, so the portion said back with them is no question; a word of meaning of one's own still asks."""
    from echo_sync.classifier import analyze, QUESTION
    from echo_sync.settings import CALL_SETTINGS
    portion = 'Нужны были мундиры, обувь,'
    state = {'chunks': ['При этом армия не могла существовать без системы снабжения.', portion], 'chunk_index': 1, 'revision': 1}
    for said in ('что это нужны были', 'что он соответственно нужны были', 'что я говорю нужны были', 'что скажем нужны были',
                 'что нужны были мундиров обувь', 'что же нужны были мундирам обуви', 'что нужны были мундиры обувь'):
        assert analyze(said, state, [], CALL_SETTINGS).kind != QUESTION, said
    for said in ('что говорит нужны были', 'что армии нужны были', 'что нужны были пушки обувь'):
        assert analyze(said, state, [], CALL_SETTINGS).kind == QUESTION, said

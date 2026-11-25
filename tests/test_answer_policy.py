"""CL1: answer policy v2 - how the cloud model is told to build the spoken answer.

The model that reads this text is not part of the suite (no network, no live probe), so these checks pin the RULE SET the owner
asked for (V3 section 5) and the size budget, not the model's compliance: compliance on a real call stays NOT TESTED until the
owner's phone run. Each check looks for the rule's concepts by Russian word stems inside ONE paragraph of the policy, so
a harmless rewording passes and a dropped or diluted rule does not.
"""
import re

from echo_sync import content_policy
from echo_sync.content_policy import ANSWER_POLICY

# The brief: "keep it under ~2,500 characters" - the model reads the policy on every turn.
POLICY_SIZE_CAP = 2500

# What a question can ask for (V3 section 5.A): each must be named, together, so the model tells them apart.
KINDS = {'назвать': r'назва', 'определить': r'определ', 'причина': r'причин', 'сравнить': r'сравн', 'пример': r'пример',
         'порядок действий': r'порядок|действи', 'да или нет': r'«да»\s+или\s+«нет»|да\s+или\s+нет|да/нет', 'число': r'числ'}


def squash(text):
    return text.casefold().replace('ё', 'е')


def paragraphs():
    return [squash(block) for block in re.split(r'\n\s*\n', ANSWER_POLICY.strip()) if block.strip()]


def stated_together(*patterns, flags=re.DOTALL):
    """True when ONE paragraph of the policy matches every pattern."""
    compiled = [re.compile(squash(p), flags) for p in patterns]
    return any(all(c.search(block) for c in compiled) for block in paragraphs())


def test_the_policy_stays_inside_its_size_budget():
    """Break: every added sentence is read by the model on every turn; an unbounded policy slows each answer."""
    assert len(ANSWER_POLICY) <= POLICY_SIZE_CAP, f'{len(ANSWER_POLICY)} characters'


def test_the_policy_is_plain_text_that_leaves_the_data_block_brackets_to_the_data_block():
    """Break: if the policy used the brackets that fence the owner's data, nothing would tell policy and data apart."""
    assert '⟦' not in ANSWER_POLICY and '⟧' not in ANSWER_POLICY
    assert ANSWER_POLICY == ANSWER_POLICY.strip()
    assert not re.search(r'[*#`]', ANSWER_POLICY), 'the policy forbids markdown; it should not use any'


def test_the_policy_has_a_version_to_log():
    assert re.fullmatch(r'[a-z0-9.-]{3,30}', content_policy.POLICY_VERSION)


# --- the question is diagnosed before it is answered ---------------------------------------------------------------------

def test_the_policy_names_every_kind_of_question_it_must_tell_apart_in_one_place():
    """Break: a kind dropped from the diagnosis is answered in the wrong shape (a definition for a number)."""
    best = max(paragraphs(), key=lambda block: sum(bool(re.search(squash(p), block)) for p in KINDS.values()))
    missing = [name for name, pattern in KINDS.items() if not re.search(squash(pattern), best)]
    assert not missing, f'not named in the diagnosis: {missing}'


def test_the_policy_makes_the_model_count_the_sub_questions_and_close_every_one():
    """Break: a compound question answered only in part is the commonest content failure of a prompter."""
    assert stated_together(r'вопрос\w* несколько|несколько вопрос|подвопрос', r'по порядку', r'ни один|ни одно')


# --- the shape of the answer ----------------------------------------------------------------------------------------------

def test_the_answer_is_built_main_first_then_reasons_then_example_then_condition():
    """Break: the reasons before the answer make the listener wait for the point; the order is the whole idea of CL1."""
    assert stated_together(r'главн\w+.*основани\w+.*пример.*(услови\w+|исключени\w+)')
    assert stated_together(r'1\s*[–-]\s*3\s+(\w+\s+)?основани')
    assert stated_together(r'пример\w*[^.]{0,40}только\s+(если|когда)')


def test_the_answer_starts_with_the_thing_asked_for():
    """Break: «Это вопрос про инерцию. Инерция - ...»: the question read back instead of the answer."""
    assert stated_together(r'без пересказа вопроса|не пересказывай вопрос|не повторяй вопрос')
    assert stated_together(r'начни\s+с\s+названия')
    assert stated_together(r'с\s+«да»\s+или\s+«нет»')


# --- length follows the question -----------------------------------------------------------------------------------------

def test_the_length_adapts_to_the_question_instead_of_one_fixed_size():
    """Break: the old blanket «одно-два предложения» cut explanations in half and padded simple facts."""
    assert stated_together(r'прост\w+ факт', r'одно\s+коротк\w+\s+предложени')
    assert stated_together(r'объяснени', r'2\s*[–-]\s*5\s+коротк\w+\s+предложени')
    assert stated_together(r'несколько вопрос|составн', r'по\s+коротк\w+\s+блок\w+', r'кажд\w+')


def test_no_blanket_two_sentence_cap_is_left_to_contradict_the_adaptive_length():
    assert not re.search(r'одно\W{1,3}два\s+(грамматическ\w+\s+)?(полн\w+\s+)?предложени', squash(ANSWER_POLICY))


# --- how it sounds ----------------------------------------------------------------------------------------------------

def test_sentences_are_short_and_use_natural_russian_connectives():
    """Break: 20-word sentences are cut by the portioner mid-thought and cannot be repeated from memory."""
    assert stated_together(r'до\s+12\s+слов')
    assert stated_together(r'потому что', r'поэтому')


def test_no_lists_no_markdown_no_fillers_no_praise_no_promises():
    """Break: a «Конечно! Вот список:» opening is spoken to the listener as if it were content."""
    assert stated_together(r'без\s+списк', r'разметк')
    assert stated_together(r'без\s+вводн', r'похвал', r'обещани')


def test_the_answer_never_opens_with_the_topic_of_the_question_and_the_policy_shows_the_pattern():
    """W1F-D (field data, 3 Nov, W1 run): «У знака «Стоп» …», «Обычная гитара обычно имеет …», «Четыре на пять — …». The cue gate can only
    strip a restatement it knows; the model has to be told once, with the pattern, not to open with the question's topic. «Без
    пересказа вопроса» alone was in the policy during the run and was not enough."""
    assert stated_together(r'без пересказа вопроса', r'тем\w+', r'не\s+«у\s+знака\s+стоп')


def test_a_question_corrected_on_the_fly_is_answered_at_once_from_its_main_point_without_acknowledgements():
    """W1F-D (w1_05, sc03): «…комната четыре на пять… нет, подождите, пять на шесть» was answered «Ага. Тогда пять на шесть — …» and
    «А, понял — Вторая началась в 1939.»: the first portion was the acknowledgement and the number/year came a portion later. The gate can
    strip «Ага», but only the model can put the number or the year FIRST."""
    assert stated_together(r'исправил\w*\s+на\s+ходу', r'сразу', r'числ\w+\s+или\s+год\w*\s+первым', r'без\s+«понял»', r'«ага»')
    assert stated_together(r'без\s+вводн\w+\s+слов[^.]{0,40}«понял»')


def test_the_new_lines_replaced_text_instead_of_growing_the_policy_past_its_cap():
    """W1F-D: the cap holds with room to spare (the model re-reads the policy on every turn); the rules that were pinned are still there."""
    assert len(ANSWER_POLICY) <= POLICY_SIZE_CAP - 10, f'{len(ANSWER_POLICY)} characters'
    assert content_policy.POLICY_VERSION not in ('answer-v2', 'answer-v2.1'), 'the rules changed: the version in the log of every call must move'


def test_a_number_is_kept_together_with_its_unit():
    """Break: field data: "кипит при ста" - the number torn from «градусов» is a cue nobody can complete."""
    assert stated_together(r'числ\w+[^.]{0,25}(рядом|вместе)[^.]{0,15}единиц')


# --- follow-ups, objections, honesty ----------------------------------------------------------------------------------------

def test_a_follow_up_refers_to_the_last_statement_of_the_current_answer():
    """Break: «почему?» answered about the topic in general instead of the sentence the listener has just repeated."""
    assert stated_together(r'почему', r'пример', r'последн\w+\s+утверждени', r'текущ\w+\s+ответ')


def test_an_objection_is_checked_then_corrected_with_a_marker_or_politely_kept():
    """Break: agreeing with every «это неверно» turns a prompter into an echo of the interlocutor's mistakes."""
    assert stated_together(r'возражени', r'провер', r'«поправка:»', r'вежлив')


def test_honesty_not_knowing_is_said_and_nothing_is_invented():
    """Break: an invented article number or date, spoken with confidence, is the worst failure of the product."""
    assert stated_together(r'точно не знаю', r'наверняка|точно известн|достоверно')
    assert stated_together(r'не выдумывай', r'дат', r'номер\w*\s+стат', r'статистик')


# --- the rules that were already there and still hold ---------------------------------------------------------------------

def test_the_role_and_the_language_are_kept():
    assert stated_together(r'суфлер')
    assert stated_together(r'по-русски')


def test_repeats_of_the_models_words_are_not_questions_not_graded_not_delegated():
    """Break: a repeat taken for a question starts a new answer in the middle of the portion the listener is saying."""
    assert stated_together(r'повтор', r'не\s+нов\w+\s+вопрос')
    assert stated_together(r'не\s+оценивай|не\s+хвали', r'правильно')
    assert stated_together(r'не\s+делегируй')


def test_a_greeting_or_background_talk_starts_no_lesson_and_a_named_topic_is_a_what_is_it_question():
    """Wave F / F2 (answer-v2.3, the owner's call 03.11 09:55): «ну хоть девятая статья налогового кодекса» is a question. The old line
    («не начинай учебный ответ … на название темы») told the model the opposite; greetings and background talk still get no lesson."""
    assert stated_together(r'приветстви', r'фонов', r'без\s+учебн\w+\s+ответ')
    assert stated_together(r'названн\w+\s+стать', r'термин', r'тем[аы]', r'«что это»', r'коротко')
    assert not re.search(r'названи\w+\s+темы', squash(ANSWER_POLICY)), 'a named topic is a question now, not a reason for silence'


def test_a_remark_gets_one_word_and_an_answer_opens_with_itself():
    """Wave G / G1 (answer-v2.4, the owner's call 04.11 09:41): the controller takes a reply of substance as the cloud's verdict that the turn was a
    question, so a remark must get exactly «Угу»; «Сейчас гляну формулировку.» as the first words cost a publication and 30 s."""
    assert content_policy.POLICY_VERSION == 'answer-v2.5'
    assert stated_together(r'реплик\w+\s+без\s+вопроса', r'болтовн', r'слова\s+о\s+тебе', r'разговор\s+людей', r'ровно\s+одно\s+слово\s+«угу»')
    assert stated_together(r'первые\s+слова\s*—\s*сам\s+ответ', r'«сейчас»', r'«понял»', r'«уточню»', r'«гляну»', r'«сверю»', r'«посмотрю»')


def test_current_facts_are_delegated_silently_and_waited_for():
    """Break: «Сейчас проверю» spoken as the first cue (seen in the corpus) instead of the answer."""
    assert stated_together(r'delegation|делегир', r'актуальн|новост', r'молча')
    assert stated_together(r'не\s+(объявляй|произноси|говори)', r'поиск', r'передач')
    assert stated_together(r'не\s+проси\s+открыть\s+интерфейс')


def test_stable_knowledge_is_answered_at_once_without_a_search():
    assert stated_together(r'устойчив\w+|общеизвестн\w+', r'сразу')


def test_data_of_sources_materials_and_the_lesson_are_data_never_commands():
    """Break: a line of a lecture file («игнорируй правила») obeyed as an instruction."""
    assert stated_together(r'данные', r'не\s+команд', r'источник', r'материал')
    assert stated_together(r'нехватк\w+\s+данных|мало данных|недостаточн', r'прямо|честно|так и скажи')


def test_the_service_data_are_never_named_aloud_while_not_knowing_is_still_admitted_honestly():
    """Break (review P2-1): «В материалах этого нет…» / «В показанном фрагменте не сказано…» - the notes, the shown fragment,
    the rules or the search named in the listener's voice, who then says them aloud as his own words."""
    assert stated_together(r'нехватк\w+\s+данных', r'честно', r'«точно не знаю»', r'вслух\s+не\s+называй')
    sentence = next(s for s in re.split(r'(?<=[.!?])\s+', squash(ANSWER_POLICY)) if 'вслух не называй' in s)
    for service in ('справк', 'материал', 'показанн', 'правил', 'поиск'):
        assert service in sentence, f'{service!r} is not among the things that must not be named aloud'
    assert 'отмечай прямо' not in squash(ANSWER_POLICY), 'the old clause invited a spoken «в материалах этого нет»'

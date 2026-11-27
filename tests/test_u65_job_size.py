"""U65, the size of a job of the reserve road for a typical call with material: the median request is under 1 500 tokens (``reserve_text.TOKENS_PER_CHAR``, the most a character has cost), so that a key's minute of
8 000 tokens holds five questions and not one (the call of 11.11: 4 562 tokens a question). The saving is in what the brief leaves out - the history past the last two exchanges and the words of an old answer past a
clause - never a rule of the instructions (``brain_short.KEEP``) or the part of the material nearest to the question."""
import statistics

from echo_sync import brain_short, fast_text, reserve_text
import test_reserve_brief as BRIEF

QUESTIONS = ['Когда была Полтавская битва?', 'Кто командовал шведами?', 'Что такое рекрутская повинность?', 'Какой год принят воинский устав?', 'Сколько лет прошло между Нарвой и Полтавой?',
             'Почему Гангутское сражение важно?', 'Кто победил под Нарвой?', 'Когда ввели рекрутскую повинность?', 'А флот?', 'Что было после Полтавы?']
ANSWER = 'Полтавская битва была 27 июня 1709 года. Русская армия разбила шведов Карла XII, и ход войны переломился. Швеция потеряла армию и больше не вернула прежней силы на востоке. '
MODEL = 'openai/gpt-oss-120b'


def tokens(body):
    return int(sum(len(message['content']) for message in body['messages']) * reserve_text.TOKENS_PER_CHAR)


def typical_call():
    """The tokens of the request of each question of a call with the owner's material (four parts of about 930 characters, picked for the question), the history growing with the answers."""
    history, sizes = [], []
    for question in QUESTIONS:
        request = fast_text.build_request(question, instructions=BRIEF.instructions(question), history=history)
        sizes.append(tokens(reserve_text.chat_body(request, MODEL)))
        history = history + [{'question': question, 'answer': ANSWER}]
    return sizes


def test_the_median_job_of_a_typical_call_with_material_is_under_1500_tokens_on_the_reserve_road():
    sizes = typical_call()
    assert statistics.median(sizes) < 1500, sizes
    assert max(sizes) < 1600, sizes      # no question of the call is far from it: the history is bounded, it does not grow with the call


def test_the_full_request_of_the_same_call_is_what_the_brief_saves():
    request = fast_text.build_request(QUESTIONS[-1], instructions=BRIEF.instructions(QUESTIONS[-1]), history=[{'question': q, 'answer': ANSWER} for q in QUESTIONS[:6]])
    long, brief = len(request['instructions']), len(brain_short.brief_instructions(request['instructions'], QUESTIONS[-1]))
    assert brief < 0.75 * long, (brief, long)      # the long BRAIN (3 134 characters) alone is two thirds of a short one more, the material is cut to 1 500, the history to two exchanges


def test_the_brief_keeps_every_rule_the_last_exchanges_and_the_revised_mark():
    rows = [{'question': f'Вопрос {n}?', 'answer': f'Ответ {n}.'} for n in range(5)] + [{'question': 'Когда?', 'answer': 'В 1709 году.', 'status': 'revised'}]
    request = fast_text.build_request('Так когда?', instructions=BRIEF.instructions(), history=rows)
    brief = brain_short.brief_instructions(request['instructions'], 'Так когда?')
    assert brain_short.missing(brief) == []
    assert 'Вопрос: Вопрос 4?\nОтвет: Ответ 4.' in brief and 'Вопрос: Когда?\nОтвет: В 1709 году.' + fast_text.REVISED_MARK in brief
    assert 'Вопрос 3?' not in brief      # only the last two


def test_the_history_head_is_the_one_build_request_writes():
    request = fast_text.build_request('Так когда?', instructions='Ты суфлёр.', history=[{'question': 'Когда?', 'answer': 'В 1709 году.'}])
    assert brain_short.HISTORY_HEAD + '\n' in request['instructions']
    assert brain_short.short_history_block('нет блока') == 'нет блока'


def test_an_old_answer_is_cut_at_a_word_and_a_question_that_was_not_answered_stays():
    long = 'слово ' * 80
    rows = [{'question': 'Что было?', 'answer': long}, {'question': 'Это читали как тест', 'unanswered': True}]
    block = brain_short.short_history_block(fast_text.build_request('Так что?', instructions='X', history=rows)['instructions'])
    assert 'Прозвучало без ответа: Это читали как тест' in block and len(block) < 400 and not block.rstrip().endswith('сл')

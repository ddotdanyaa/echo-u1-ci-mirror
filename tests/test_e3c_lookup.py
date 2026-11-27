"""Task E3c, items 4-5: the lookup route.

DEF-T-B15 (T-B N15): the router sent a question to the model's own knowledge, and the model itself asked for sources
(``delegation.created`` for that question). Nothing looked anything up, the model waited for a tool result that never came, and the
question was given up after 8 s («Нет ответа»). Required: the model's request for sources is served with the lookup, like a question the
router had sent there itself.

DEF-T-11 (T-A F33/C12/C20): the lookup returned rows about something else («Кошки любят спать на солнце…», or a 3-character row «см.»);
they were checked for their form only, grounded the question, went to the model as its data, and the model's unsupported answer was
dictated as «source_backed». Amendment R2a (binding): shared stems are a signal, not proof. Mandatory negative pairs - the same stems
with another number or year, another negation, another subject or another condition are no grounding; mandatory positive - a relevant
source in synonyms (no shared stem) is not thrown away (kept as weak grounding rather than a false «Не нашёл»). A row with no content
word is no source; a row about something else is never handed on next to the relevant ones; with nothing left the transport takes its
«Не нашёл. Повторите вопрос.» path.
"""
import asyncio
import json

import pytest

from echo_sync.native_media_socket import NativeMediaSocket
from test_first_cue_never_silent import Clock, created, done, host_controller


def delegation(tid, did='d1'):
    return {'type': 'delegation.created', 'item': {'id': did, 'type': 'delegation', 'target': 'client', 'user_bidi_turn_id': tid}}


def asked(tmp_path, question, tid='u1'):
    c = host_controller(tmp_path, clock=Clock(100.0))
    c.provider(created(tid, 'user', question.split()[0]))
    return c, c.provider(done(tid, 'user', question))


INERTIA_ROWS = [{'url': 'https://example.org/inertia', 'text': 'Инерция — свойство тела сохранять скорость, пока на него не действуют силы.'}]


# --- DEF-T-B15, as changed by F3 item 4 -------------------------------------------------------------------------------------------
# The model's request for sources is always answered (it used to wait for a result that never came). A settled fact (needs_verification
# False: 'Что такое инерция') is answered at once with "no search - answer from what you know" on the item of the delegation, no lookup
# runs; a question that needs a search is on the lookup route from its first word (tests below). The lookup the controller still makes
# for a delegation whose verdict says "verify" is pinned in test_f3_delegation.py.

def test_a_delegation_the_model_makes_on_the_model_knowledge_route_is_answered_at_once_without_a_lookup(tmp_path):
    c, actions = asked(tmp_path, 'Что такое инерция')
    assert {'type': 'route', 'route': 'model_knowledge'} in actions and c.direct_content        # precondition: the router's route
    served = c.provider(delegation('u1'))
    assert [a['type'] for a in served] == ['context'], served                                    # the tool result the model asked for
    assert served[0]['delegation_id'] == 'd1' and served[0]['no_search'] is True and served[0]['sources'] == []
    assert served[0]['epoch'] == c.epoch
    assert not c.lookup_served
    assert c.grounding(c.epoch, INERTIA_ROWS) == []                                              # nothing was asked for: stray rows are ignored
    assert c.delivery_sent(c.epoch, 'd1')
    cues = c.provider(done('a1', 'assistant', 'Инерция — это свойство тела сохранять скорость.'))
    assert [a['type'] for a in cues] == ['speak'], cues
    assert c.state()['retrieval_status'] == 'unverified'                                         # the model's own knowledge, as it is said


def test_a_delegation_that_came_before_the_question_was_accepted_is_answered_too(tmp_path):
    c = host_controller(tmp_path, clock=Clock(100.0))
    c.provider(created('u1', 'user', 'Что такое'))
    assert c.provider(delegation('u1')) == []                       # the model asks while the question is still being spoken
    actions = c.provider(done('u1', 'user', 'Что такое инерция'))
    assert [a['type'] for a in actions] == ['cancel', 'route', 'context'], actions
    assert actions[2]['delegation_id'] == 'd1' and actions[2]['no_search'] is True


def test_a_model_that_answers_without_waiting_for_the_result_is_still_dictated(tmp_path):
    """Answering the request does not close the model-knowledge route: an answer that comes before the result reached the model is the
    answer, and the result that arrives later does not withdraw it."""
    c, _ = asked(tmp_path, 'Что такое инерция')
    assert [a['type'] for a in c.provider(delegation('u1'))] == ['context']
    cues = c.provider(done('a1', 'assistant', 'Инерция — это свойство тела сохранять скорость.'))
    assert [a['type'] for a in cues] == ['speak'] and c.state()['retrieval_status'] == 'unverified', cues
    assert c.delivery_sent(c.epoch, 'd1') and c.direct_content
    assert c.state()['chunks'] and not c.state()['completed'], c.state()


def test_a_second_delegation_for_the_same_question_is_not_answered_twice(tmp_path):
    c, _ = asked(tmp_path, 'Что такое инерция')
    assert [a['type'] for a in c.provider(delegation('u1'))] == ['context']
    assert c.provider(delegation('u1', 'd2')) == []


# --- DEF-T-11 with amendment R2a -------------------------------------------------------------------------------------------------

VERIFY = 'Проверь, пожалуйста, что такое гидравлический удар.'
CATS = {'url': 'https://example.org/cats', 'text': 'Кошки любят спать на солнце и ловить мышей во дворе соседнего дома.'}
HAMMER = {'url': 'https://example.org/hammer',
          'text': 'Гидравлический удар — резкий скачок давления в трубопроводе при внезапной остановке потока жидкости.'}


def lookup_question(tmp_path, question=VERIFY):
    c, actions = asked(tmp_path, question)
    assert any(a['type'] == 'lookup' for a in actions), actions                                  # precondition: the lookup route
    return c


def grounded_by(tmp_path, question, rows):
    """The sources the context hands to the model for ``question`` grounded with ``rows`` ([] when nothing grounds it)."""
    c = lookup_question(tmp_path, question)
    context = c.grounding(c.epoch, rows)
    return c, (context[0]['sources'] if context else [])


def test_a_row_with_no_content_word_is_no_source(tmp_path):
    c, sources = grounded_by(tmp_path, VERIFY, [{'url': 'https://example.org/x', 'text': 'см.'}])
    assert sources == [] and not c.grounded
    assert c.provider(done('a1', 'assistant', 'Это общепринятый термин, введённый в 1920 году.')) == [] and c.state() is None


def test_a_row_about_something_else_is_not_handed_on_with_the_relevant_one(tmp_path):
    _, sources = grounded_by(tmp_path, VERIFY, [CATS, HAMMER])
    assert [s['url'] for s in sources] == [HAMMER['url']] and 'relevance' not in sources[0], sources


# R2a negative pairs: the same stems saying something else are no grounding, whatever they share.
NEGATIVE_PAIRS = [
    ('number', 'Что устанавливает статья 218 Гражданского кодекса?',
     'Статья 219 Гражданского кодекса устанавливает возникновение права собственности на недвижимость.'),
    ('time', 'Какая ставка НДС действует в 2025 году?', 'Ставка НДС в 2018 году составляла 18 процентов.'),
    ('negation', 'Проверь, какие товары не облагаются НДС.', 'Товары, которые облагаются НДС по ставке 20 процентов: одежда, техника, мебель.'),
    ('subject', 'Проверь, что такое гидравлический удар.', 'Гидравлический пресс — машина для сжатия материалов под давлением.'),
    ('condition', 'Проверь, что будет с температурой кипения воды, если давление растёт.',
     'Если давление падает, температура кипения воды становится ниже.'),
]
POSITIVES = {
    'number': 'Статья 218 Гражданского кодекса устанавливает основания приобретения права собственности.',
    'time': 'В 2025 году ставка НДС составляет 20 процентов.',
    'negation': 'Не облагаются НДС медицинские товары, лекарства и продажа жилья.',
    'subject': 'Гидравлический удар — резкий скачок давления в трубопроводе.',
    'condition': 'Если давление растёт, температура кипения воды становится выше.',
}


def test_the_same_stems_saying_something_else_are_no_grounding(tmp_path):
    for kind, question, row in NEGATIVE_PAIRS:
        c, sources = grounded_by(tmp_path / kind, question, [{'url': f'https://example.org/{kind}', 'text': row}])
        assert sources == [] and not c.grounded, (kind, sources)


def test_the_matching_rows_of_the_same_questions_ground_them(tmp_path):
    """The positive half of each pair: the row that says it of the question's number, year, negation, subject and condition."""
    for kind, question, _ in NEGATIVE_PAIRS:
        c, sources = grounded_by(tmp_path / kind, question, [{'url': f'https://example.org/{kind}', 'text': POSITIVES[kind]}])
        assert len(sources) == 1 and 'relevance' not in sources[0] and c.grounded, (kind, sources)


def test_a_relevant_source_in_synonyms_is_kept_as_weak_grounding_not_a_false_not_found(tmp_path):
    """R2a positive: it shares no stem with the question («времена года» / «сезонов»). It goes to the model marked as weak, rather than
    the listener hearing «Не нашёл» for a good source."""
    row = {'url': 'https://example.org/seasons', 'text': 'Наклон земной оси определяет смену сезонов на планете.'}
    c, sources = grounded_by(tmp_path, 'Проверь, почему меняются времена года.', [row])
    assert c.grounded and len(sources) == 1 and sources[0]['relevance'] == 'weak', sources


WHY_HAMMER = 'Проверь, пожалуйста, гидравлический удар: почему так происходит?'
HAMMER_SUMMARY = {'url': 'https://example.org/summary', 'text': 'Краткий конспект. Гидравлический удар — это резкий скачок давления в трубе.'}
HAMMER_CAUSES = [   # passages of the full lecture that give the cause in other words: the subject as a pronoun, or another noun
    {'url': 'https://example.org/full-lecture', 'text': 'Подробность лекции: Он возникает, потому что поток жидкости внезапно останавливается.'},
    {'url': 'https://example.org/full-lecture-2', 'text': 'Давление в трубе подскакивает, так как движущаяся вода не может сжаться.'},
]


@pytest.mark.parametrize('detail', HAMMER_CAUSES, ids=['pronoun', 'noun'])
def test_a_passage_that_gives_the_cause_asked_for_is_handed_on_with_the_rows_that_name_the_subject(tmp_path, detail):
    """INTEG7 (T-A C11, «summary + full lecture, detail in the full text»): the question asks «почему»; the passage of the lecture that
    gives the cause shares no stem with the question. Next to a row that names the subject it was dropped as noise, and the model never got
    the cause. A row that gives a cause («потому что», «так как», …) to a question that asks for one answers what was asked - a signal
    (R2a: no shared stem is a signal, never proof) that it may be about the question's subject: kept, marked weak."""
    _, sources = grounded_by(tmp_path, WHY_HAMMER, [HAMMER_SUMMARY, CATS, detail])
    assert [s['url'] for s in sources] == [HAMMER_SUMMARY['url'], detail['url']], sources
    assert 'relevance' not in sources[0] and sources[1]['relevance'] == 'weak', sources


def test_a_row_whose_subject_is_a_pronoun_names_no_other_subject_it_is_weak_grounding(tmp_path):
    """INTEG7 (found by T-A C11 «лунное затмение»: the passage «Оно случается, потому что Земля оказывается между Луной и Солнцем» was
    dropped). R2a's subject rule drops a row that shares the question's words but none of its nouns («Гидравлический пресс — …» for
    «гидравлический удар»: it names another subject). A row whose leading clause has a pronoun for its subject (after a heading at most)
    names no subject of its own - the rule has no evidence: the row is kept, as weak grounding, never as strong."""
    for text in ('Оно происходит, когда Луна закрывает Солнце.', 'Конспект: Оно происходит, когда Луна закрывает Солнце.'):
        row = {'url': 'https://example.org/eclipse', 'text': text}
        c, sources = grounded_by(tmp_path / str(len(text)), 'Проверь, почему происходит солнечное затмение.', [row])
        assert c.grounded and len(sources) == 1 and sources[0]['relevance'] == 'weak', (text, sources)
    for text in ('Гидравлический пресс — машина для сжатия материалов под давлением. Он работает от насоса.',
                 'Луна закрывает Солнце не каждый месяц. Оно происходит редко.'):
        row = {'url': 'https://example.org/other', 'text': text}
        question = 'Проверь, что такое гидравлический удар.' if text.startswith('Гидр') else 'Проверь, почему происходит солнечное затмение.'
        c, sources = grounded_by(tmp_path / ('n' + str(len(text))), question, [row])
        assert sources == [] and not c.grounded, (text, sources)       # its own subject comes first: the rule stands


def test_a_row_that_gives_no_cause_to_a_why_question_is_still_not_handed_on_next_to_the_relevant_one(tmp_path):
    """The negative half: next to the row that names the subject, a row in other words that does not give the cause asked for is noise."""
    cats = {'url': 'https://example.org/cats', 'text': 'Кошки любят спать на солнце, и они ловят мышей во дворе соседнего дома.'}
    _, sources = grounded_by(tmp_path, WHY_HAMMER, [HAMMER_SUMMARY, cats])
    assert [s['url'] for s in sources] == [HAMMER_SUMMARY['url']], sources


def test_numbers_alone_never_make_a_row_about_something_else(tmp_path):
    """The number rule is about the same stems with another number: a row that shares no stem with the question is not «the same
    thing with another number», whatever numbers it carries - it stays weak grounding like any row in other words (T-B N15's supported
    answer: «Норматив составляет 25 процентов…» for «статья 228»)."""
    row = {'url': 'https://example.org/norm', 'text': 'Норматив составляет 25 процентов и действует с 2025 года.'}
    c, sources = grounded_by(tmp_path, 'Что устанавливает статья 228 Уголовного кодекса?', [row])
    assert c.grounded and len(sources) == 1 and sources[0]['relevance'] == 'weak', sources


def test_a_row_that_conflicts_takes_the_answer_from_memory_path_on_the_wire(tmp_path):
    async def run():
        sent = []

        async def emit(frame):
            sent.append(frame)

        async def lookup(_):
            return [{'url': 'https://example.org/219', 'text': NEGATIVE_PAIRS[0][2]}]
        c = lookup_question(tmp_path, NEGATIVE_PAIRS[0][1])
        wire = NativeMediaSocket(c, emit, lambda: None, lookup, lambda _: None)
        await wire._lookup({'epoch': c.epoch, 'question': c.question_text})
        # c8 (the owner's rule): no source left - the model answers from memory, hedged; nothing is said now (test_c8)
        assert not any(frame.get('type') == 'error' for frame in sent) and c.source_missing, sent
        assert '219' not in json.dumps(sent, ensure_ascii=False)
        await wire.close()
    asyncio.run(run())


def test_a_follow_up_is_grounded_by_rows_about_the_topic_it_inherits(tmp_path):
    """«Приведи пример» says nothing about the subject: the lookup asks about the topic before it (``К вопросу: …``), and rows about that
    topic are relevant although they do not say «пример»."""
    rows = [{'url': 'https://www.consultant.ru/document/cons_doc_LAW_5142/',
             'text': 'Статья 218. Основания приобретения права собственности.'}]
    c = lookup_question(tmp_path, 'Что устанавливает статья 218 Гражданского кодекса')
    assert [a['type'] for a in c.grounding(c.epoch, rows)] == ['context'] and c.delivery_sent(c.epoch, None)
    assert c.provider(done('a1', 'assistant', 'Статья 218 устанавливает основания приобретения права собственности.'))
    actions = c.provider(done('u2', 'user', 'Приведи пример.'))
    lookup = [a for a in actions if a['type'] == 'lookup']
    assert lookup and 'К вопросу:' in lookup[0]['lookup_question'], actions                          # precondition: the inherited topic
    context = c.grounding(c.epoch, rows)
    assert [a['type'] for a in context] == ['context'] and 'relevance' not in context[0]['sources'][0], context

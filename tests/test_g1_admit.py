"""Wave G / G1 (the owner's call 04.11 09:41, audit ECHO_CLAUDE_CONTINUE_20261104 §3-4): the cloud decides what is a question.

The closed grammar threw away good cloud answers («Так, двадцать три, хорошо. Значит, сорок восемь умножить на десять» -> «Четыреста
восемьдесят.», twice, silence), and a publication refused once stayed refused («Сейчас гляну формулировку. По памяти, …» -> NO_REPLY cached
for the turn -> obsolete_turn_retry x8 -> «Не нашёл» 30 s later).

1. A final with no evidence stays a candidate; the reference base, the model's delegation or the model's own reply admit it.
2. A publication refused for its material is not the turn's result: distinct outcomes, one clear end, the conversation goes on.
3. A hit of the local reference base is the answer at once.

REAL: ControlledMedia, EchoEngine, its SQLite file, the classifier, the filters. EMULATED: the cloud (the wire events below).
"""
import logging

from cm_patch import patch_controller
import pytest

import echo_sync.controlled_media as cm
from echo_sync import reference_kb
from echo_sync.classifier import Decision, QUESTION as QUESTION_KIND
from echo_sync.engine import EchoEngine, SILENT
from echo_sync.generator import StreamingAnswer, hedged
from helpers_w1f import Wire
from engine_say import engine_reply

ARTICLE_18 = 'Так, восемнадцатая статья налогового кодекса это'
LONG_48 = 'Так, двадцать три, хорошо. Значит, сорок восемь умножить на десять'
BARE_48 = 'сорок восемь умножить на десять'
ARTICLE_27 = 'Что такое двадцать седьмая статья Налогового кодекса'


def delegation(uid, did='d1'):
    return {'type': 'delegation.created', 'item': {'id': did, 'target': 'client', 'user_bidi_turn_id': uid}}


def lookups(actions):
    return [a for a in actions or [] if a['type'] == 'lookup']


class Recorder(Wire):
    """The wire, with every action the controller gave kept (``seen``)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.seen = []

    def _act(self, actions):
        self.seen.extend(actions or [])
        super()._act(actions)


def with_23(tmp_path, *, reference=None, monkeypatch=None):
    """«Сколько будет десять плюс тринадцать?» -> «Двадцать три.» is cued and waits for its repeat (nobody repeats it)."""
    if reference is not None:
        patch_controller(monkeypatch, 'reference_lookup', reference)
    w = Recorder(tmp_path)
    w.user('u1', 'Сколько будет десять плюс тринадцать?', 0.0, 2.0)
    w.assistant('a1', ' Двадцать три.', 2.05, 2.8)
    w.until(3.5)
    assert w.played_after(0) and 'Двадцать три' in w.played_after(0)[0][0:40], w.played
    return w


def decisions(caplog, kind=None, reason=None):
    rows = [r.getMessage() for r in caplog.records if 'echo-sync decision' in r.getMessage()]
    return [r for r in rows if (kind is None or f'kind={kind} ' in r) and (reason is None or f'reason={reason}' in r)]


@pytest.fixture(autouse=True)
def info_log(caplog):
    caplog.set_level(logging.INFO)
    return caplog


@pytest.fixture(autouse=True)
def no_base(monkeypatch):
    """The admission and the publication are tested on their own; the tests of the real base ask for it (``real_base``)."""
    patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(): None)


@pytest.fixture
def real_base(no_base, monkeypatch):
    patch_controller(monkeypatch, 'reference_lookup', reference_kb.lookup)


# =====================================================================================================================================
# 1. cloud admission
# =====================================================================================================================================

def test_the_reply_to_a_long_sentence_is_the_answer_and_the_waiting_portion_retires(tmp_path, caplog):
    w = with_23(tmp_path)
    w.user('u2', LONG_48, 5.0, 7.0)
    w.assistant('a2', ' Четыреста восемьдесят.', 7.05, 8.0)
    w.until(9.0)
    assert 'Четыреста восемьдесят.' in [text for _, text in w.played], w.played
    assert decisions(caplog, 'question', 'cloud_admitted')
    state = w.state()
    assert state['question'].endswith('умножить на десять') and state['chunks'] == ['Четыреста восемьдесят.']
    assert [e['status'] for e in state['history']][0] in ('interrupted', 'complete'), 'the old answer stays in the history'


def test_the_bare_expression_is_answered_too(tmp_path):
    w = with_23(tmp_path)
    w.user('u2', BARE_48, 5.0, 7.0)
    w.assistant('a2', ' Это будет четыреста восемьдесят.', 7.05, 8.0)
    w.until(9.0)
    assert w.played_after(5.0), w.played
    assert 'четыреста восемьдесят' in w.plan().lower()


def test_a_reply_with_no_end_mark_admits_once_its_grace_window_is_over(tmp_path):
    w = with_23(tmp_path)
    w.user('u2', BARE_48, 5.0, 7.0)
    w.assistant('a2', ' Четыреста восемьдесят', 7.05, 8.0)
    w.until(8.1)
    assert w.played_after(5.0) == []
    w.until(11.0)
    assert any('Четыреста' in text for text in w.played_after(5.0)), w.played


def test_a_reply_cut_by_the_next_turn_admits_nothing(tmp_path, caplog):
    w = with_23(tmp_path)
    w.user('u2', BARE_48, 5.0, 7.0)
    w.assistant('a2', ' Четыреста восемьдесят', 7.05, 8.0)
    w.user('u3', 'Угу, ладно, хорошо', 8.01, 8.8)
    w.until(12.0)
    assert not decisions(caplog, 'question', 'cloud_admitted')


def test_nothing_of_the_reply_is_cued_before_it_admits_the_turn(tmp_path):
    """Until a complete sentence with substance has arrived the reply is nobody's answer; the portion still waits."""
    w = with_23(tmp_path)
    w.user('u2', BARE_48, 5.0, 7.0)
    w.at(7.05, {'type': 'turn.created', 'turn': {'id': 'a2', 'role': 'assistant', 'transcript': ' Четыреста'}})
    w.until(7.5)
    assert w.played_after(5.0) == [] and w.state()['chunks'] == ['Двадцать три.'], w.played


@pytest.mark.parametrize('reply', [' Угу.', ' Угу', ' Понял, сейчас посмотрю.', ' Какой именно?', ' Да.', ' Нет.',
                                   ' Хорошо, вот тебе вопрос. Если бы ты мог получить любую способность, что бы ты выбрал?',
                                   ' Понял, давай разберём по частям.', ' Понял, попробую разобраться по сути и найти корень проблемы.',
                                   ' Да, сейчас коротко разложу, что может влиять на такие паузы.',
                                   ' Понятно, едем.'],
                         ids=['ugu', 'ugu_bare', 'stall', 'ask_back', 'yes', 'no', 'question_to_you', 'lets', 'will_try', 'will_lay_out', 'we'])
def test_a_reply_that_filters_to_nothing_admits_nothing(tmp_path, caplog, reply):
    w = with_23(tmp_path)
    w.user('u2', BARE_48, 5.0, 7.0)
    w.assistant('a2', reply, 7.05, 8.0)
    w.until(12.0)
    assert set(w.played_after(5.0)) <= {'Двадцать три.'}, w.played
    assert not decisions(caplog, 'question', 'cloud_admitted')
    assert w.state()['chunks'] == ['Двадцать три.']


def test_the_models_delegation_admits_the_turn_and_runs_its_lookup(tmp_path, caplog):
    w = Recorder(tmp_path)
    w.user('u1', ARTICLE_18, 0.0, 2.0)
    w.assistant('a1', ' Понял, сейчас посмотрю.', 2.05, 3.0)
    w.at(3.2, delegation('u1'))
    w.until(4.0)
    assert decisions(caplog, 'question', 'cloud_admitted')
    assert w.c.question_id == 'u1' and w.c.delegation_id == 'd1'
    assert lookups(w.seen), 'the verify-class question goes to its lookup, as any accepted one'


def test_a_delegation_that_came_before_the_final_admits_it_at_the_final(tmp_path, caplog):
    w = Recorder(tmp_path)
    w.at(1.0, delegation('u1'))
    w.user('u1', ARTICLE_18, 0.0, 2.0)
    w.until(2.5)
    assert w.c.question_id == 'u1' and decisions(caplog, 'question', 'cloud_admitted')


def test_a_verify_class_reply_is_no_answer_from_memory_the_lookup_decides(tmp_path):
    """No current norms from memory: an admitted question that needs a lookup gets it; the reply already said is not cued."""
    w = Recorder(tmp_path)
    w.user('u1', 'Так, актуальная ставка налога значит', 0.0, 2.0)
    w.assistant('a1', ' Двадцать процентов.', 2.05, 3.0)
    w.until(4.0)
    assert w.played_after(0) == [] and w.c.question_id == 'u1' and lookups(w.seen), w.played


@pytest.mark.parametrize('said', ['Спасибо', 'Привет', 'Стоп'], ids=['thanks', 'greeting', 'stop'])
def test_no_candidate_after_a_verdict_with_evidence(tmp_path, caplog, said):
    w = with_23(tmp_path)
    w.user('u2', said, 5.0, 6.0)
    w.assistant('a2', ' Двести шестьдесят семь тысяч.', 6.05, 7.0)
    w.until(9.0)
    assert not decisions(caplog, 'question', 'cloud_admitted')


def test_a_try_at_the_waiting_portion_is_no_candidate(tmp_path, caplog):
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое экология?', 0.0, 2.0)
    w.assistant('a1', ' Экология изучает связи живых организмов со средой обитания.', 2.05, 3.5)
    w.until(4.5)
    w.user('u2', 'Экология изучает связи', 6.0, 7.0)
    w.assistant('a2', ' Экология — большая наука о природе.', 7.05, 8.0)
    w.until(9.5)
    assert not decisions(caplog, 'question', 'cloud_admitted')


def test_a_remark_to_the_prompter_is_no_candidate(tmp_path, caplog):
    w = with_23(tmp_path)
    w.user('u2', 'Блин, ты опять сломался, суфлёр плохо работает', 5.0, 7.0)
    w.assistant('a2', ' Двести шестьдесят семь тысяч.', 7.05, 8.0)
    w.until(9.0)
    assert not decisions(caplog, 'question', 'cloud_admitted')


def test_a_paused_answer_is_not_replaced_by_a_candidate(tmp_path, caplog):
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое экология?', 0.0, 2.0)
    w.assistant('a1', ' Экология изучает связи живых организмов со средой обитания. Она возникла в девятнадцатом веке.', 2.05, 3.5)
    w.until(4.5)
    w.user('u2', 'Стоп', 5.0, 5.5)
    w.until(6.0)
    assert w.state().get('paused')
    w.user('u3', BARE_48, 7.0, 8.0)
    w.assistant('a3', ' Четыреста восемьдесят.', 8.05, 9.0)
    w.until(10.0)
    assert not decisions(caplog, 'question', 'cloud_admitted') and w.state().get('paused')


def test_the_retired_portion_comes_back_on_prodolzhay(tmp_path):
    """History kept: an interrupted answer can be taken up again, as after any new question."""
    w = Recorder(tmp_path, ack=((7.0, 11.0),))
    w.user('u1', 'Что такое экология?', 0.0, 2.0)
    w.assistant('a1', ' Экология изучает связи живых организмов со средой обитания. Она возникла в девятнадцатом веке.', 2.05, 3.5)
    w.until(4.5)
    w.user('u2', LONG_48, 5.0, 7.0)
    w.assistant('a2', ' Четыреста восемьдесят.', 7.05, 8.0)
    w.until(10.5)
    assert w.state()['chunks'] == ['Четыреста восемьдесят.']
    w.user('u3', 'Продолжай', 12.0, 12.5)
    w.until(14.0)
    assert 'Экология' in w.plan() or 'связи' in w.plan() or 'девятнадцатом' in w.plan(), w.plan()


# the owner's call 03.11 20:10 (owner-call-2010-timeline.txt lines 83-99): a bystander in the car; the cloud goes on with its old answer
BYSTANDER_1 = 'Там он чуть-чуть десять минут проехать, и мы приедем там, где мы забирали'
BYSTANDER_2 = 'Так они сыпут после всех отзывов истории про пистолеты, сигнализации'


def test_a_continuation_of_an_older_answer_never_admits_the_bystander_turn(tmp_path, caplog):
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое пятнадцатая статья налогового кодекса?', 0.0, 2.0)
    w.c.direct_content = False
    w.until(2.2)
    w.c.direct_content = True                # the sources are not the point here: the first answer is on the model-knowledge route
    w.c.question_reason = 'question_word'
    w.c.source_missing = True
    w.assistant('a1', ' По памяти: пятнадцатая статья Налогового кодекса — это местные налоги. Она определяет земельный налог, налог на имущество', 2.5, 4.0)
    w.until(4.5)
    w.user('u2', BYSTANDER_1, 5.0, 7.0)
    w.assistant('a2', ' физлиц, торговый сбор и туристический налог. Если нужен другой кодекс или юрисдикция, уточни, пожалуйста', 7.05, 8.5)
    w.user('u3', BYSTANDER_2, 8.6, 10.0)
    w.assistant('a3', ', страну или документ.', 10.05, 10.4)
    w.until(14.0)
    assert not decisions(caplog, 'question', 'cloud_admitted')
    assert w.c.question_id == 'u1', 'the answer stays the one being dictated'


def test_a_reply_after_a_cut_of_its_own_turn_is_bound_to_that_turn(tmp_path, caplog):
    """A segment that goes on with a segment of the older answer cut on the wire does not admit, whoever owns it."""
    w = with_23(tmp_path)
    w.assistant('a1b', ' а ещё можно посчитать столбиком', 3.6, 4.2)      # its reply to nothing: cut, no end of a sentence
    w.user('u2', BARE_48, 5.0, 7.0)
    w.assistant('a2', ' и получить тот же самый результат.', 7.05, 8.0)
    w.until(9.0)
    assert not decisions(caplog, 'question', 'cloud_admitted')


def test_a_reply_that_retells_the_older_answer_does_not_admit(tmp_path, caplog):
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое экология?', 0.0, 2.0)
    w.assistant('a1', ' Экология изучает связи живых организмов со средой обитания. Она возникла в девятнадцатом веке.', 2.05, 3.5)
    w.until(4.5)
    w.user('u2', BYSTANDER_1, 5.0, 7.0)
    w.assistant('a2', ' Экология изучает связи организмов со средой.', 7.05, 8.0)
    w.until(9.0)
    assert not decisions(caplog, 'question', 'cloud_admitted')


def test_a_retelling_of_the_portion_with_the_model_going_on_keeps_the_cursor(tmp_path, caplog):
    """Speech too long for an attempt that shares the answer's words, the model telling the same answer on: not a new question."""
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое экология?', 0.0, 2.0)
    w.assistant('a1', ' Экология изучает связи живых организмов со средой обитания.', 2.05, 3.5)
    w.until(4.5)
    w.user('u2', 'Ну значит экология это такая наука которая изучает связи организмов со средой где они живут вот и всё по сути', 5.0, 8.0)
    w.assistant('a2', ' Экология изучает связи живых организмов и среды.', 8.05, 9.0)
    w.until(10.0)
    assert not decisions(caplog, 'question', 'cloud_admitted')
    assert w.state()['question'] == 'Что такое экология?'


def test_a_reply_while_the_older_stream_is_open_admits_when_it_is_bound_to_the_turn(tmp_path, caplog):
    """G3, rule 4 (changed on purpose): the blanket refusal while a stream is open lost real questions; what binds a reply to its turn decides."""
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое экология?', 0.0, 2.0)
    w.at(2.05, {'type': 'turn.created', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': ' Экология изучает связи живых организмов со средой обитания, а также '}})
    w.until(2.2)
    w.user('u2', BARE_48, 3.0, 4.0)
    w.assistant('a2', ' Четыреста восемьдесят.', 4.05, 4.5)
    w.until(6.0)
    assert decisions(caplog, 'question', 'cloud_admitted')
    assert 'Четыреста восемьдесят.' in [text for _, text in w.played], w.played


def test_what_goes_on_with_the_open_stream_never_admits(tmp_path, caplog):
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое экология?', 0.0, 2.0)
    w.at(2.05, {'type': 'turn.created', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': ' Экология изучает связи живых организмов со средой обитания, а также '}})
    w.until(2.2)
    w.user('u2', BARE_48, 3.0, 4.0)
    w.assistant('a2', ' с другими видами и с климатом.', 4.05, 4.5)
    w.until(6.0)
    assert not decisions(caplog, 'question', 'cloud_admitted')


def no_source_now(wire):
    actions = wire.c.without_source(wire.c.epoch,'failed')
    for action in actions or []:
        if action['type'] == 'context':
            wire.c.delivery_sent(action['epoch'], action['delegation_id'])
    return []


def test_the_morning_sequence_in_one_call(tmp_path, caplog):
    """The call of 04.11 09:41, its wordings and its cloud lines, on one wire, the base off: the lookup never finds a source. Every question ends
    in its answer and the listener's repeats go on."""
    w = Recorder(tmp_path, ack=((0.0, 200.0),))
    w.user('u1', ARTICLE_18, 26.8, 35.3)
    w.assistant('a1', ' Понял, сейчас посмотрю.', 35.35, 37.9)
    w.at(38.0, delegation('u1'))
    w.at(38.5, no_source_now)
    w.assistant('a2', ' Сейчас уточню. По памяти, статья 18 вводит специальные налоговые режимы.', 39.0, 42.0)
    w.until(50.0)
    assert 'режим' in w.plan(), w.plan()
    w.user('u2', 'Сколько будет десять плюс тринадцать?', 52.0, 54.0)
    w.assistant('a3', ' Двадцать три.', 54.05, 55.0)
    w.until(55.2)
    assert w.plan() == 'Двадцать три.'
    w.ack = ()                                      # the listener moves on without repeating «Двадцать три.»
    w.user('u3', LONG_48, 57.0, 63.0)
    w.assistant('a4', ' Четыреста восемьдесят.', 63.05, 64.5)
    w.until(70.0)
    assert w.plan() == 'Четыреста восемьдесят.' and 'Четыреста восемьдесят.' in w.played_after(63.0), w.played
    for n, (start, reply) in enumerate(((80.0, ' Сейчас гляну формулировку. По памяти, статья 27 — это про законного представителя организации.'),
                                        (110.0, ' Сейчас уточню по источникам. По памяти, это про законного представителя организации.'),
                                        (140.0, ' Да, проверяю формулировку. По памяти, это про законного представителя организации.'))):
        w.user(f'q{n}', ARTICLE_27, start, start + 2.0)
        w.at(start + 2.5, no_source_now)
        w.assistant(f'r{n}', reply, start + 3.0, start + 5.0)
        w.until(start + 9.0)
        assert 'законного представителя' in w.plan() and 'памяти' not in w.plan(), w.plan()
        assert w.played_after(start + 2.0), w.played
    assert not decisions(caplog, 'cached', 'obsolete_turn_retry')
    assert not [a for a in w.seen if a['type'] == 'unanswered']


# =====================================================================================================================================
# 3. the publication contract
# =====================================================================================================================================

QUESTION = 'Что такое статья 27 Налогового кодекса РФ?'
BODY = 'Это справка об указанном предмете.'


def engine(tmp_path, raw):
    """The engine of a real ControlledMedia (route 16.11: what may be published is cm-route's rule, ``_publishable``, read where it hands the text over; the bare engine publishes what it is given)."""
    box = {'raw': raw, 'calls': 0}
    controller = Wire(tmp_path).c
    e, handed = controller.engine, controller.engine.generate

    def generate(*args, **kwargs):
        box['calls'] += 1
        if box['raw'] is None:
            raise RuntimeError('the wire broke')
        return handed(*args, **kwargs)
    e.generate, e.controller, e.box = generate, controller, box
    return e, box


def ask(e, turn='t'):
    return e.controller._reply(QUESTION, turn, decided=Decision(QUESTION_KIND, 'question_word', QUESTION, None),
                               answer=StreamingAnswer(BODY, final=True, retrieval_status='unsourced' if hedged(e.box['raw'] or '') else 'unverified', raw_text=e.box['raw'] or BODY))


@pytest.mark.parametrize('raw', ['Сейчас уточню по источникам. По памяти: ' + BODY,
                                 'Сейчас гляну формулировку. По памяти, статья 27 — это про законного представителя организации.',
                                 'Да, проверяю формулировку. По памяти, это про законного представителя организации.',
                                 'Насколько помню, это про представителя.'])
def test_the_hedge_is_judged_after_the_process_lead(raw):
    assert hedged(raw)


@pytest.mark.parametrize('raw', ['Сейчас уточню по источникам. ' + BODY, BODY, ''])
def test_no_hedge_is_no_hedge(raw):
    assert not hedged(raw)


def test_a_process_lead_does_not_refuse_the_publication(tmp_path):
    e, _ = engine(tmp_path, 'Сейчас уточню по источникам. По памяти: ' + BODY)
    assert ask(e) != SILENT and e.publication(e.controller.session_id, 't') == 'published'


def test_a_refused_publication_is_not_the_final_result_of_the_turn(tmp_path, caplog):
    e, box = engine(tmp_path, BODY)
    assert ask(e) == SILENT and e.publication(e.controller.session_id, 't') == 'refused'
    revision = e.state(e.controller.session_id)['revision']
    box['raw'] = 'По памяти: ' + BODY
    assert ask(e) != SILENT, 'the same turn id, the corrected text'
    assert e.state(e.controller.session_id)['revision'] == revision, 'no new revision for a try of the same turn'
    assert e.publication(e.controller.session_id, 't') == 'published'
    assert not decisions(caplog, 'cached', 'obsolete_turn_retry')


def test_a_refused_turn_never_takes_over_from_a_newer_question(tmp_path):
    e, box = engine(tmp_path, BODY)
    ask(e)
    e.retire(e.controller.session_id, 'new_question')
    box['raw'] = 'По памяти: ' + BODY
    assert ask(e) == SILENT, 'stale audio stays protected: the revision moved on'
    assert e.publication(e.controller.session_id, 't') == 'refused' and box['calls'] == 1


def test_a_technical_failure_ends_the_turn(tmp_path):
    e, box = engine(tmp_path, None)
    assert ask(e) == SILENT and e.publication(e.controller.session_id, 't') == 'failed'
    box['raw'] = 'По памяти: ' + BODY
    assert ask(e) == SILENT and box['calls'] == 1, 'no second model request for the same turn id'


def article_27(tmp_path, reply, **kw):
    """The lookup's rows were unrelated: the model is told to answer from memory; ``reply`` is what it says then."""
    w = Recorder(tmp_path, **kw)
    w.user('u1', ARTICLE_27, 0.0, 2.0)

    def no_source(wire):
        actions = wire.c.without_source(wire.c.epoch,'failed')
        for action in actions or []:
            if action['type'] == 'context':
                wire.c.delivery_sent(action['epoch'], action['delegation_id'])
        return []
    w.at(2.5, no_source)
    w.assistant('a1', reply, 3.0, 5.0)
    return w


def test_the_article_27_round_is_cued_and_no_retry_storm(tmp_path, caplog):
    w = article_27(tmp_path, ' Сейчас гляну формулировку. По памяти, статья 27 — это про законного представителя организации в налоговых отношениях.')
    w.until(9.0)
    assert any('стать' in text.lower() or 'законн' in text.lower() for _, text in w.played), w.played
    assert 'гляну' not in w.plan() and 'памяти' not in w.plan().lower()
    assert not decisions(caplog, 'cached', 'obsolete_turn_retry')


def test_an_answer_from_memory_without_the_hedge_is_played_and_the_call_goes_on(tmp_path, caplog):
    """Candidate 12, w3_01: refusing it was 30 s of silence and «Не нашёл» for words the listener would have heard all the same (the cue carries no hedge)."""
    w = article_27(tmp_path, ' Это про законного представителя организации в налоговых отношениях.')
    w.until(9.0)
    assert any('законного представителя' in text for _, text in w.played), w.played
    assert not [a for a in w.seen if a['type'] == 'unanswered'] and not decisions(caplog, 'publication', 'refused detail')
    assert not decisions(caplog, 'cached', 'obsolete_turn_retry')


# =====================================================================================================================================
# 4. the local reference base
# =====================================================================================================================================

HIT = 'Статья 19 Налогового кодекса — налогоплательщики и плательщики сборов.'


def hit_on(word):
    return lambda text, history=(): HIT if word in text.casefold() else None


def test_a_hit_is_published_in_the_tick_of_the_final(tmp_path, monkeypatch, caplog):
    patch_controller(monkeypatch, 'reference_lookup', hit_on('девятнадцатая'))
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое девятнадцатая статья налогового кодекса', 0.0, 2.0)
    w.until(2.0)
    assert w.issued and w.issued[0][0] == 2.0 and HIT.startswith(w.issued[0][1].rstrip('.,')), w.issued
    assert not lookups(w.seen), 'no lookup for a settled reference'
    assert w.state()['retrieval_status'] == 'local_reference'
    assert decisions(caplog, 'question', 'local_reference')


def test_the_models_turns_for_it_are_not_cued_and_its_delegation_gets_no_search(tmp_path, monkeypatch):
    patch_controller(monkeypatch, 'reference_lookup', hit_on('девятнадцатая'))
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое девятнадцатая статья налогового кодекса', 0.0, 2.0)
    w.at(2.1, delegation('u1'))
    w.assistant('a1', ' Сейчас посмотрю. Это про участников отношений, которые регулируются налоговым законодательством.', 2.2, 3.0)
    w.until(5.0)
    assert not [text for _, text in w.issued if 'участник' in text], w.issued
    contexts = [a for a in w.seen if a['type'] == 'context']
    assert len(contexts) == 1 and contexts[0]['no_search'] is True and contexts[0]['delegation_id'] == 'd1'


def test_a_delegation_that_came_first_is_answered_at_the_final(tmp_path, monkeypatch):
    patch_controller(monkeypatch, 'reference_lookup', hit_on('девятнадцатая'))
    w = Recorder(tmp_path)
    w.at(1.0, delegation('u1'))
    w.user('u1', 'Что такое девятнадцатая статья налогового кодекса', 0.0, 2.0)
    w.until(2.5)
    contexts = [a for a in w.seen if a['type'] == 'context']
    assert w.issued and len(contexts) == 1 and contexts[0]['no_search'] is True


def test_a_hit_on_a_candidate_retires_the_portion_at_once(tmp_path, monkeypatch, caplog):
    w = with_23(tmp_path, reference=hit_on('восемнадцатая'), monkeypatch=monkeypatch)
    w.user('u2', ARTICLE_18, 5.0, 7.0)
    w.until(7.0)
    assert w.issued[-1][0] == 7.0 and HIT.startswith(w.issued[-1][1].rstrip('.,')), w.issued
    assert decisions(caplog, 'question', 'cloud_admitted')


def test_a_question_taken_on_a_partial_is_answered_at_its_final(tmp_path, monkeypatch):
    patch_controller(monkeypatch, 'reference_lookup', hit_on('девятнадцатая'))
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое девятнадцатая статья налогового кодекса', 0.0, 2.0)
    w.at(1.0, delegation('u1'))
    w.until(2.2)
    assert w.issued and HIT.startswith(w.issued[0][1].rstrip('.,')), w.issued


def test_the_history_goes_to_the_base_as_the_questions_of_the_call(tmp_path, monkeypatch):
    calls = []

    def base(text, history=()):
        calls.append((text, tuple(history)))
        return None
    patch_controller(monkeypatch, 'reference_lookup', base)
    w = Recorder(tmp_path)
    w.user('u1', 'Сколько будет десять плюс тринадцать?', 0.0, 2.0)
    w.assistant('a1', ' Двадцать три.', 2.05, 2.8)
    w.until(4.0)
    w.user('u2', 'А сколько будет два плюс два?', 5.0, 6.0)
    w.until(6.2)
    assert calls[-1][1] == ('Сколько будет десять плюс тринадцать?',), calls


def test_a_base_that_raises_changes_nothing(tmp_path, monkeypatch):
    def broken(text, history=()):
        raise ValueError('broken')
    patch_controller(monkeypatch, 'reference_lookup', broken)
    w = Recorder(tmp_path)
    w.user('u1', 'Сколько будет десять плюс тринадцать?', 0.0, 2.0)
    w.assistant('a1', ' Двадцать три.', 2.05, 2.8)
    w.until(4.0)
    assert any('Двадцать три' in text for _, text in w.played)


@pytest.mark.parametrize('said,expected', [(ARTICLE_18, 'специальные налоговые режимы'),
                                           (ARTICLE_27, 'статья 27'),
                                           ('Что такое девятнадцатая статья налогового кодекса', 'статья 19')],
                         ids=['18_chat', '27', '19'])
def test_the_morning_articles_are_answered_by_the_real_base_in_the_tick_of_the_final(tmp_path, real_base, said, expected):
    w = Recorder(tmp_path)
    w.user('u1', said, 0.0, 2.0)
    w.until(2.0)
    assert w.issued and w.issued[0][0] == 2.0 and not lookups(w.seen), w.issued
    assert expected.casefold() in ' '.join(w.state()['chunks']).casefold(), w.state()['chunks']


def test_a_follow_up_of_the_real_base_takes_the_code_from_the_questions_of_the_call(tmp_path, real_base):
    w = Recorder(tmp_path, ack=((2.0, 3.0),))
    w.user('u1', 'Что такое девятнадцатая статья налогового кодекса', 0.0, 2.0)
    w.until(6.0)
    w.user('u2', 'А двадцать седьмая?', 7.0, 8.0)
    w.until(8.0)
    assert 'статья 27' in ' '.join(w.state()['chunks']).casefold(), w.state()['chunks']


def test_a_long_title_goes_through_the_portions(tmp_path, real_base):
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое статья 105.1 налогового кодекса', 0.0, 2.0)
    w.until(2.0)
    state = w.state()
    assert w.issued and state['chunks'] and all(len(chunk.split()) <= 12 for chunk in state['chunks']), state['chunks']


LONG_HIT = ('Статья 19 Налогового кодекса устанавливает, что налогоплательщиками признаются организации и физические лица, на которых '
            'в соответствии с этим кодексом возложена обязанность уплачивать налоги, а также сборы и страховые взносы.')


def test_a_base_answer_opens_with_the_streams_first_cue_one_rule(tmp_path, monkeypatch):
    """portion/first-cue: the first portion of a ready answer of the reference base is the very ``first_cue`` of the stream (one rule), never the plan's
    ``portions()[0]``: the real ControlledMedia publishes the answer and its first chunk is what ``first_cue`` says of that text."""
    from echo_sync.first_useful import first_cue
    patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(): LONG_HIT if 'девятнадцатая' in text.casefold() else None)
    w = Recorder(tmp_path)
    w.user('u1', 'Что такое девятнадцатая статья налогового кодекса', 0.0, 2.0)
    w.until(2.0)
    state = w.state()
    expected = first_cue(LONG_HIT, 'Что такое девятнадцатая статья налогового кодекса', w.c.settings, final=True, last=True)
    assert state['retrieval_status'] == 'local_reference' and expected, state
    assert state['chunks'][0] == expected and ''.join(state['chunks']).replace(' ', '') == LONG_HIT.replace(' ', ''), state['chunks']

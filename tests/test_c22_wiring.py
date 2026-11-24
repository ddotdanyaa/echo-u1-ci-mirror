"""c22-nocloud (g37 «подключение за координатором»): N135 personal_volatile, N136 abbrev_state (always on), N133 question_map wired into ControlledMedia / engine, each behind a profile flag that is OFF by default.
Production code, no network. N135: the owner's honest reply to a personal question about changing data is a local answer (``_reference``): no model, no search, no 8 s of silence."""
import pytest

import helpers_s6_state as S
from echo_sync import engine as E
from echo_sync.personal_volatile import honest_reply, personal_volatile
from echo_sync.settings import DEFAULTS, resolve

PERSONAL = ('Какой у меня баланс на счёте?', 'Что у меня сегодня в календаре?', 'Где моя посылка?')


def controller(**flags):
    w = S.World()
    c = w.controller
    c.settings = {**dict(c.settings), **flags}
    return w, c


@pytest.mark.parametrize('text', PERSONAL)
def test_n135_a_personal_question_about_changing_data_gets_the_honest_reply_from_the_reference(text):
    w, c = controller()
    try:
        assert c._reference(text) == honest_reply(personal_volatile(text))
    finally:
        w.close()


@pytest.mark.parametrize('text', ['Если у меня на счету 5000, сколько останется?', 'Какая погода в Казани?', 'Что такое бухгалтерский учёт?'])
def test_n135_a_task_another_place_or_a_general_question_is_not_taken(text):
    w, c = controller()
    try:
        assert personal_volatile(text) is None
        assert c._reference(text) is None
    finally:
        w.close()


TABLE = {'НДС': 'налог на добавленную стоимость'}


def spoken(c, text, qid):
    c.question_id = qid
    return c._spell(text)


def test_n136_each_abbreviation_is_spelled_out_once_per_call():
    w, c = controller(abbreviations=TABLE)
    try:
        assert 'налог на добавленную стоимость' in spoken(c, 'Ставка НДС двадцать процентов.', 'q1')
        assert 'налог на добавленную' not in spoken(c, 'Ставка НДС двадцать процентов.', 'q2')
    finally:
        w.close()


def test_n136_inside_one_answer_a_stream_grows_without_the_text_changing_under_it():
    w, c = controller(abbreviations=TABLE)
    try:
        first = spoken(c, 'Ставка НДС', 'q1')
        again = spoken(c, 'Ставка НДС двадцать процентов.', 'q1')
        assert again.startswith(first) and 'налог на добавленную стоимость' in again
    finally:
        w.close()


def test_n136_asked_what_it_means_it_is_spelled_out_again():
    w, c = controller(abbreviations=TABLE)
    try:
        spoken(c, 'Ставка НДС двадцать процентов.', 'q1')
        c.question_text = 'Расшифруй НДС'
        assert 'налог на добавленную стоимость' in spoken(c, 'НДС это налог.', 'q2')
    finally:
        w.close()


def test_n133_conversation_map_adds_open_parts_of_a_compound_question(monkeypatch):
    state = {'history': [{'question': 'Сколько стоит и когда привезут?', 'answer': 'Сто рублей.', 'status': 'complete', 'at': 995.0, 'chunks': ['Сто рублей.'], 'spoken': 1}]}
    on = E.conversation_map(state, now=1000.0)
    assert on and on[0].get('open_parts') == ['когда привезут']


# --- NC4: «Что такое статья 46 НК?» - the bank and the law base both answer, and differ: one honest phrase, never silence ---------------------

from tools.replay import no_cloud as N      # noqa: E402

ART46 = 'Что такое статья 46 НК?'


def differ_scene(s):
    s.ask(4.0, ART46)
    s.ask(30.0, 'Что такое бухгалтерский учёт?')


def play(mode):
    import logging
    logging.disable(logging.WARNING)
    try:
        return N.run(mode, differ_scene, length=50.0, model='fail', bank=N.owner_bank(), profile=N.PROFILE)
    finally:
        logging.disable(logging.NOTSET)


def test_reference_says_one_honest_phrase_when_the_bank_and_the_law_base_differ():
    w, c = controller()
    try:
        c.instant = N.index(N.owner_bank()).for_call()
        said = c._reference(ART46)
        assert said is not None and N.honest(said), said
    finally:
        w.close()


@pytest.mark.parametrize('mode', ['cloud', 'deaf', 'refused'])
def test_the_conflict_gets_one_honest_phrase_in_time(mode):
    rec = play(mode)
    assert not [v for v in rec.violations if v[0] == 'NC4'], N.describe(rec)
    told = [c for c in rec.cues if N.honest(c[1]) and not c[5]]
    assert told and len({c[1] for c in told}) == 1 and told[0][0] - 5.65 < {'cloud': 3.0, 'deaf': 5.0, 'refused': 3.0}[mode], N.describe(rec)      # deaf waits the ear's 4 s for a cloud turn that does not come (EAR_FIRST_BIND_SECONDS); one phrase, never two different ones; a portion of an answer is said back by the usual repeat (the bank's answers are too)


def test_one_place_of_abbreviations_the_controllers_first_answer_is_the_engines_plain_answer_and_the_lead_writes_the_same_table():
    """Speech (abbrev-expand): ``abbrev_state`` holds the mechanism, the call's policy and the lead's spelling; the controller's first answer and the engine's plain
    answer (``portions`` of text that is not spoken yet) are one text, and ``question_lead`` has no table of its own."""
    from echo_sync import abbrev_state, portioner, question_lead
    text = 'Ставка НДС двадцать процентов.'
    w, c = controller(abbreviations=TABLE)
    try:
        first = spoken(c, text, 'q1')
    finally:
        w.close()
    cfg = resolve({'abbreviations': TABLE})
    assert ' '.join(portioner.portions(text, cfg)) == ' '.join(portioner.portions(first, cfg, spoken=True)) and 'налог на добавленную стоимость' in first
    assert first == abbrev_state.expand_abbreviations(text, TABLE)
    assert not hasattr(portioner, 'expand_abbreviations') or portioner.expand_abbreviations is abbrev_state.expand_abbreviations
    assert not hasattr(question_lead, '_ABBR') and question_lead.SPELLING is abbrev_state.SPELLING

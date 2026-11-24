"""g31-context: short follow-ups with the memory of the conversation («а КО-2», «а пассивный», «почему»). The question is completed with the topic of
the exchange before it BEFORE the bank and the model see it: a swap («а пассивный» after «Что учитывает активный счёт?») becomes the whole question
with the one slot changed, so the bank answers it; a topic follow-up («почему», «а если нет») goes to the model with the question it is about, and
never to the bank, which would say the old answer again. Numbers, the condition and «не» of the question before stay. Real bank, real classifier."""
import glob
import json
from pathlib import Path

import pytest

from echo_sync import followup
from echo_sync.classifier import QUESTION, QUIET, REPLAY, analyze
from echo_sync.followup import complete
from echo_sync.instant import Instant

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def bank():
    rows = []
    for path in sorted(glob.glob(str(ROOT / 'cloud_context/bank/merged/*.json'))):
        rows += json.loads(Path(path).read_text(encoding='utf-8'))
    if not rows:
        pytest.skip('no bank in cloud_context')
    return Instant(rows)


def asked(bank, text, history):
    """What the bank answers for ``text`` after ``history``: the question of the entry it hits, or None."""
    got = complete(text, history)
    query = text if got is None else got.bank
    if not query:
        return None
    hit = bank.lookup(query, bank_only=True)
    return hit and hit.q


# ---- the ten of the task -------------------------------------------------------------------------------------------------------------------------

def test_a_ko2_swaps_the_form_code():
    got = complete('а КО-2', ['Что указывают в КО-1?'])
    assert got.kind == 'swap' and got.question == 'Что указывают в КО-2?' and got.bank == got.question


def test_a_passive_swaps_the_adjective_and_the_bank_answers_the_new_question(bank):
    got = complete('а пассивный', ['Что такое активный счёт?'])
    assert got.question == 'Что такое пассивный счёт?'
    assert asked(bank, 'а пассивный', ['Что такое активный счёт?']) == 'Что такое пассивный счёт?'


def test_a_v_nalogovom_swaps_the_adjective_after_the_same_preposition():
    got = complete('а в налоговом', ['Какой лимит стоимости основного средства в бухгалтерском учёте?'])
    assert got.question == 'Какой лимит стоимости основного средства в налоговом учёте?'


@pytest.mark.parametrize('said', ['почему', 'А почему?', 'почему так'])
def test_why_goes_to_the_model_with_the_question_and_never_to_the_bank(said):
    got = complete(said, ['Что такое пассивный счёт?'])
    assert got.kind == 'topic' and got.bank == '' and 'Что такое пассивный счёт?' in got.question and got.question.lower().startswith('почему')


def test_an_example_carries_the_topic(bank):
    got = complete('а пример', ['Что такое пассивный счёт?'])
    assert got.bank == '' and 'пассивный счёт' in got.question and 'пример' in got.question.lower()
    assert asked(bank, 'а пример', ['Что такое пассивный счёт?']) is None        # the old answer is not said again


def test_how_much_is_it_keeps_the_numbers_of_the_question():
    got = complete('сколько это', ['Сколько составляет пеня при ставке 16 процентов за 30 дней?'])
    assert '16' in got.question and '30' in got.question and got.bank == ''


def test_and_if_not_keeps_the_condition_whole():
    before = 'Можно ли не платить НДС, если доход до 60 миллионов рублей?'
    got = complete('а если нет', [before])
    assert got.kind == 'topic' and before in got.question and got.question.lower().startswith('а если нет')


def test_and_more_asks_what_else():
    got = complete('и ещё', ['Какие бывают счета по отношению к балансу?'])
    assert got.kind == 'topic' and 'ещё' in got.question.lower() and 'по отношению к балансу' in got.question


def test_that_is_asks_to_explain_the_answer():
    got = complete('то есть', ['Что такое активный счёт?'])
    assert got.kind == 'topic' and 'Что такое активный счёт?' in got.question and got.bank == ''


def test_and_what_is_this():
    got = complete('а это что', ['Что такое счёт 84?'])
    assert got.kind == 'topic' and 'счёт 84' in got.question and got.bank == ''


# ---- new scenarios: break it ---------------------------------------------------------------------------------------------------------------------

def test_a_schet_62_after_an_active_passive_question_is_the_same_question_not_what_is_62(bank):
    """Broke: the bank alone answered «Что такое счёт 62?» to «а счёт 62» asked after «Счёт 51 активный или пассивный?»."""
    history = ['Счёт 51 активный или пассивный?']
    assert complete('а счёт 62', history).question == 'Счёт 62 активный или пассивный?'
    assert asked(bank, 'а счёт 62', history) == 'Счёт 62 активный или пассивный?'


def test_a_number_said_in_words_swaps_the_number(bank):
    history = ['Счёт 51 активный или пассивный?']
    assert complete('а шестьдесят второй', history).question == 'Счёт 62 активный или пассивный?'
    assert complete('а пятидесятый', history).question == 'Счёт 50 активный или пассивный?'


def test_an_abbreviation_swaps_an_abbreviation(bank):
    """Broke: «А РКО?» after «Какие данные в ПКО?» got «Что такое РКО» from the bank, an answer to another question."""
    history = ['Какие данные в ПКО?']
    assert complete('А РКО?', history).question == 'Какие данные в РКО?'
    assert asked(bank, 'А РКО?', history) == 'Что указывают в расходном кассовом ордере?'


def test_the_adjective_takes_the_case_of_the_word_it_replaces(bank):
    assert complete('а пассивный', ['По какой стороне записывают увеличение на активном счёте?']).question == \
        'По какой стороне записывают увеличение на пассивном счёте?'
    history = ['Как посчитать конечное сальдо активного счёта?']
    assert complete('а пассивного', history).question == 'Как посчитать конечное сальдо пассивного счёта?'
    assert asked(bank, 'а пассивного', history) == 'Как посчитать конечное сальдо пассивного счёта?'


def test_an_adjective_swaps_inside_a_longer_phrase():
    assert complete('а расходный', ['Что указывают в приходном кассовом ордере?']).question == 'Что указывают в расходном кассовом ордере?'


def test_a_chain_of_follow_ups_completes_each_on_the_one_before():
    history = ['Что такое активный счёт?', 'а пассивный']
    assert complete('а активно-пассивный', history).question == 'Что такое активно-пассивный счёт?'
    assert complete('а КО-2', ['Что указывают в КО-1?', 'почему']).question == 'Что указывают в КО-2?'


def test_a_preposition_phrase_swaps_and_keeps_the_numbers_and_the_ne():
    got = complete('а у ИП', ['Какие доходы не облагаются НДФЛ по ставке 13 процентов у организаций?'])
    assert got.question == 'Какие доходы не облагаются НДФЛ по ставке 13 процентов у ИП?'
    got = complete('а для ИП', ['Какой срок сдачи декларации по УСН для организаций?'])
    assert got.question == 'Какой срок сдачи декларации по УСН для ИП?'


def test_a_preposition_the_question_had_not_is_the_same_question_about_it():
    got = complete('а для ИП', ['Какая ставка налога на прибыль 25 процентов?'])
    assert got.kind == 'topic' and got.bank == '' and '25' in got.question and 'для ИП' in got.question


def test_a_whole_question_after_a_is_no_follow_up():
    for said in ('а сколько стоит баррель нефти', 'А что такое налог?', 'а как составить бухгалтерскую проводку'):
        assert complete(said, ['Что такое активный счёт?']) is None, said


def test_a_topic_that_stands_alone_and_has_no_slot_is_its_own_question(bank):
    assert complete('а счёт 62', ['Что такое налог?']) is None
    assert asked(bank, 'а счёт 62', ['Что такое налог?']) == 'Что такое счёт 62?'


def test_nothing_is_invented_without_a_question_before():
    for said in ('а пассивный', 'почему', 'а КО-2', 'и ещё'):
        assert complete(said, []) is None and complete(said, ['', None]) is None


def test_the_number_of_the_follow_up_wins_and_the_others_stay():
    got = complete('а за 60 дней', ['Сколько пени при ставке 16 процентов за 30 дней?'])
    assert got.question == 'Сколько пени при ставке 16 процентов за 60 дней?'


def test_the_completion_is_fast_and_never_raises():
    import time
    start = time.perf_counter()
    for _ in range(200):
        complete('а пассивный', ['По какой стороне записывают увеличение на активном счёте?'])
    assert (time.perf_counter() - start) / 200 < 0.005
    for junk in (None, 5, '', '???', 'а', 'а а а а а а а а а а'):
        complete(junk, ['Что такое налог?'])
        complete('а пассивный', junk if not isinstance(junk, str) else [junk])


CHATTER = ['а потом', 'а вообще', 'а так', 'и всё', 'а хорошо', 'и правильно', 'а понятно', 'а да', 'а нет', 'и тогда', 'а дальше', 'а теперь', 'а мы', 'а я',
           'а сегодня', 'и спасибо', 'а ладно', 'а в общем', 'а в целом', 'а кстати', 'а как же', 'и что', 'а что', 'и как', 'а красиво', 'а новый', 'а большой',
           'а другой', 'а какой', 'а тот', 'а следующий', 'а первый', 'а второй', 'а там', 'а у меня', 'и наоборот', 'а вот']


@pytest.mark.parametrize('said', CHATTER)
def test_chatter_after_an_answer_is_no_follow_up_and_no_question(said):
    """Broke: «а потом», «а сегодня» became «the same question», «а новый» became «Что такое новый счёт?». A false cue on chatter is worse than none."""
    assert complete(said, ['Что такое активный счёт?']) is None
    assert complete(said, ['Какой лимит стоимости основного средства в бухгалтерском учёте?']) is None
    assert analyze(said, answered(), []).kind != QUESTION or analyze(said, answered(), []).reason != 'context_followup'


@pytest.mark.parametrize('said', ['А у нас завтра экскурсия.', 'А. С. Пушкин', 'А. С. Пушкин бывал там.', 'и в то же время', 'а в то время'])
def test_a_sentence_with_a_preposition_is_no_follow_up(said):
    """Broke (measured on every short line of the tests and the corpus): a preposition anywhere made «the same question about it»."""
    assert complete(said, ['Что учитывает активный счёт?']) is None


@pytest.mark.parametrize('said', ['почему', 'сколько', 'когда', 'а где', 'сколько процентов', 'а это что', 'и ещё'])
def test_while_a_portion_waits_only_a_swap_is_a_question(said):
    """Broke: a bare «почему», «сколько» while the owner says the portion became a question: the owner thinks aloud. A swap («а пассивный») stays one."""
    state = answered(answer='Активный счёт учитывает имущество организации. Остаток по дебету.', completed=False,
                     chunk='Остаток по дебету.')
    assert analyze(said, state, []).reason != 'context_followup'
    assert analyze('а пассивный', state, []).reason == 'context_followup'


# ---- the classifier: a follow-up after an answer is a question, never silence ---------------------------------------------------------------------

def answered(question='Что учитывает активный счёт?', answer='Активный счёт учитывает имущество организации.', *, completed=True, pending=None,
             chunk=None):
    return {'revision': 1, 'question': question, 'answer': answer, 'chunks': [chunk or answer], 'chunk_index': 0, 'completed': completed,
            'pending_turn': pending, 'history': [{'question': question, 'answer': answer}]}


@pytest.mark.parametrize('said', ['а КО-2', 'а пассивный', 'а в налоговом', 'а у ИП', 'а для РКО', 'и ещё', 'то есть', 'а если нет', 'а счёт 62'])
def test_a_follow_up_after_an_answer_is_a_question_said_as_it_was(said):
    state = answered('Что указывают в КО-1?' if said == 'а КО-2' else 'Какие формы ПКО в бухгалтерском учёте у организаций?' if said in ('а в налоговом', 'а у ИП', 'а для РКО')
                     else 'Счёт 51 активный или пассивный?' if said == 'а счёт 62' else 'Что учитывает активный счёт?')
    decision = analyze(said, state, [])
    assert decision.kind == QUESTION, (said, decision)
    assert followup.complete(decision.question, [state['question']]) is not None, decision


def test_a_follow_up_while_the_answer_is_being_made_waits():
    assert analyze('а пассивный', answered(pending={'turn_id': 't9'}), []).kind == QUIET


def test_words_of_the_portion_said_again_are_a_repeat_not_a_follow_up():
    state = answered(answer='Активный счёт учитывает имущество, а пассивный источники его образования.', completed=False,
                     chunk='Активный счёт учитывает имущество, а пассивный источники')
    assert analyze('а пассивный', state, []).kind != QUESTION


def test_that_is_and_and_more_inside_the_owners_own_words_are_no_question():
    state = answered(completed=False, chunk='Приходный кассовый ордер оформляют при поступлении денег.')
    assert analyze('то есть', state, []).kind != QUESTION
    assert analyze('приходный кассовый ордер, то есть наоборот', state, []).kind != QUESTION or \
        complete('приходный кассовый ордер, то есть наоборот', [state['question']]) is None


# ---- the wiring on the real controller (the H4 rig): ``controlled_media.py`` is the coordinator's file -----------------------------------------------
# These fail on it as it is (xfail strict) and pass with cloud_context/reports/g31-context.wiring.diff applied (checked in a scratch tree, see the report).

import sys

sys.path.insert(0, str(Path(__file__).parent))
from test_h3_tempo import call                                          # noqa: E402,F401 - call is the fixture
from test_h4_ear_first import final, history, speaks                    # noqa: E402

from echo_sync.settings import resolve                                  # noqa: E402


def rig_with_bank(call, bank):
    rig = call(fast_text='on')
    rig.c.instant = bank.for_call()
    return rig


def ask(rig, turn, ear, cloud, speech=1.5):
    speaks(rig, ear, turn=turn, announced=min(1.4, speech - 0.1), speech=speech)
    final(rig, turn, cloud)
    rig.pump(6)


def test_wired_a_schet_62_after_51_is_the_active_passive_question_not_what_is_62(call, bank):
    """Broke on the real controller: «А счёт 62?» after «Счёт 51 активный или пассивный?» cued «Расчёты с покупателями и заказчиками»: the bank hit on the ear's partial."""
    rig = rig_with_bank(call, bank)
    ask(rig, 'u1', 'счёт пятьдесят один активный или пассивный', 'Счёт 51 активный или пассивный?')
    assert rig.said() and rig.said()[-1].startswith('Активный счёт'), rig.said()
    ask(rig, 'u2', 'а счёт шестьдесят два', 'А счёт 62?', speech=0.9)
    assert not any(s.startswith('Расчёты с покупателями') for s in rig.said()), rig.said()
    assert rig.said()[-1].startswith('Активно-пассивный'), rig.said()


def test_wired_a_passive_after_active_cues_the_answer_about_the_passive_account(call, bank):
    rig = rig_with_bank(call, bank)
    ask(rig, 'u1', 'что такое активный счёт', 'Что такое активный счёт?')
    first = list(rig.said())
    assert first, 'the bank answers the first question'
    ask(rig, 'u2', 'а пассивный', 'А пассивный?', speech=0.8)
    passive = bank.lookup('Что такое пассивный счёт?', bank_only=True).answer
    assert rig.said()[len(first):] and passive.startswith(rig.said()[-1].rstrip(',.:;')), rig.said()


def test_wired_the_model_reads_the_follow_up_with_its_question_and_the_bank_does_not_repeat_the_old_answer(call, bank):
    rig = rig_with_bank(call, bank)
    ask(rig, 'u1', 'что такое пассивный счёт', 'Что такое пассивный счёт?')
    said = len(rig.said())
    ask(rig, 'u2', 'а пример', 'А пример?', speech=0.8)
    assert 'пассивный счёт' in rig.c.fast_text and 'пример' in rig.c.fast_text.lower(), rig.c.fast_text
    old = bank.lookup('Что такое пассивный счёт?', bank_only=True).answer
    assert not any(old.startswith(s.rstrip(',.:;')) for s in rig.said()[said:]), rig.said()

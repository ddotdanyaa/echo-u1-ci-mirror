"""h30: the owner's call of 07.11 21:16, what the delays of 8 and 12 s were. Words are his, seconds the rig's clock, not a phone's."""
import pytest

from echo_sync import instant, quick_math
from tools.replay import quantity as Q, repeat_scenes as R

ROWS = Q.BANK + [
    ('Перечислите виды финансовых отношений', 'Шесть видов: между государством и населением, между хозяйствующими субъектами.', ['виды финансовых отношений']),
    ('Что такое страховой риск?', 'Предполагаемое событие, на случай которого проводят страхование.', ['страховой риск']),
]


@pytest.fixture
def rig():
    rig = Q.rig_of()
    rows = [instant.clean_entry({'q': q, 'alt': alt, 'answer': a, 'source': 'scene', 'subject': 'scene'}) for q, a, alt in ROWS]
    rig.c.instant = instant.Instant(rows, adapters=()).for_call()
    yield rig
    rig.close()
    rig._mp.undo()


def asked(rig, text='Что такое инфляция?'):
    Q.ear_only(rig, text)
    rig.pump(1.0)
    assert rig.cues()


def test_the_bank_answers_over_an_old_cue_from_the_ear(rig):
    """96.6 s: the ear held the whole question, the bank knew it, 4 s of waiting for the cloud."""
    asked(rig)
    mark = len(rig.cues())
    ended = Q.ear_only(rig, 'перечисли виды финансово отношений')
    text, at = Q.after(rig, mark)
    assert text and text.startswith('Между государством') and at - ended < 2.0


def test_the_term_in_the_last_clause_is_answered_by_the_base(rig):
    """137.8 s: the cloud cut the head off; the base knew the term; the model's 7 s."""
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, ', предприятия, понятия, страховой риск')
    rig.pump(1.0)
    assert [c.text for c in rig.cues()[mark:] if c.text.startswith('Предполагаемое')]


@pytest.mark.parametrize('said,word', [
    ('Сколько будет семь плюс три? Сколько будет семь плюс три', 'Десять'),
])
def test_a_sum_said_twice_is_a_sum(rig, said, word):
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, said)
    rig.pump(1.0)
    assert [c.text for c in rig.cues()[mark:] if word in c.text]


@pytest.mark.parametrize('said,want', [
    ('сколько будет 1758,09 разделить на 6100,34 и умножить на 100', 'Двадцать восемь целых восемьдесят две сотых.'),
    ('Сколько будет одна тысяча семьсот пятьдесят восемь целых девять сотых разделить на шесть тысяч сто целых тридцать четыре сотых умножить на сто', 'Двадцать восемь целых восемьдесят две сотых.'),
    ('Так, сколько же будет тысяча семьсот пятьдесят восемь девять сотых разделить на шесть тысяч сто целых тридцать четыре сотых и умножить на сто', 'Двадцать восемь целых восемьдесят две сотых.'),
    ('сколько будет 7247,12 разделить на 6100,34', 'Одна целая девятнадцать сотых.'),
    ('сколько будет двенадцать умножить на семь', 'Восемьдесят четыре.'),
])
def test_a_sum_from_the_sheet_is_worked_out(said, want):
    assert quick_math.answer(said) == want


@pytest.mark.parametrize('said', ['Так, сколько же будет тысяча семьсот пятьдесят восемь девять сотых разделить на шесть тысяч сто тридцать четыре сотых и умножить на сто',       # h31 (F17): 6100,34 or 6130,04, the words do not say
                                  'сколько будет сто делить на три', 'пять семь на три', 'разделить на сто', 'сто двадцать пять сотых процента'])
def test_what_is_not_a_plain_sum_stays_unsaid(said):
    assert quick_math.answer(said) is None


def test_a_cue_is_the_answer_not_its_count():
    """h31: the row keeps its count; the hit drops it unless the count was asked (F19)."""
    row = instant.clean_entry({'q': 'Перечислите виды финансовых отношений', 'alt': ['Сколько видов финансовых отношений?'], 'answer': 'Шесть видов: между государством и населением.'})
    assert row['answer'].startswith('Шесть видов')
    engine = instant.Instant([row], adapters=())
    assert engine.lookup('Перечислите виды финансовых отношений').answer.startswith('Между государством')
    assert engine.lookup('Сколько видов финансовых отношений?').answer.startswith('Шесть видов')

"""w9-open-tail (E29.1): pairs «unfinished / finished» of Russian utterances against ``classifier.open_tail``, and mutants of ``open_tail`` that the pairs must kill.
Known gaps (the tail is open, ``open_tail`` says closed: a false release) are listed in ``GAPS`` and pinned as strict xfail, so a fix flips them."""
import inspect
import types

import pytest

from echo_sync import classifier
from echo_sync.classifier import open_tail

# (open, closed): the same breath stopped in the middle and finished.
PAIRS = [
    ('налог на', 'налог на прибыль'), ('расскажи про налог и', 'расскажи про налог'), ('что такое НДС и', 'что такое НДС'),
    ('это нужно для', 'это нужно для отчёта'), ('я хотел спросить про', 'я хотел спросить про вычеты'), ('сколько будет пять', 'сколько будет пять рублей'),
    ('мне нужно сто', 'мне нужно сто рублей'), ('мне нужно двадцать', 'мне нужно двадцать рублей'), ('сколько будет семь', 'сколько будет семь на семь'),
('это нужно потому что', 'это нужно потому что так проще'), ('так как', 'так как это важно'),
    ('то есть', 'то есть это налог'), ('а вот', 'а вот это что'), ('а если', 'а если не платить, что будет'), ('а также', 'а также про вычеты'),
    ('не только', 'не только налог'), ('как бы', 'как бы это правильно'), ('в смысле', 'в смысле как'), ('если я продам квартиру', 'если я продам квартиру, какой налог'),
    ('если он опоздает', 'если он опоздает, то что'), ('хотя', 'хотя ладно, что такое НДС'), ('чтобы', 'чтобы получилось сколько нужно'), ('или', 'или не нужно'),
    ('сколько получится пятнадцать', 'сколько получится пятнадцать на два'), ('ну и', 'ну и что такое НДС'), ('ещё вопрос про', 'ещё вопрос про вычеты'),
]
# open to a listener, closed to ``open_tail`` today (false release): the word the breath stops on is not in its tables.
GAPS = ['ну', 'продали за тысячу']
# w10 item 7: closed in classifier.open_tail (were GAPS): now pinned as open
CLOSED_GAPS = ['и ещё', 'а потом', 'я думаю что', 'мне нужно узнать', 'я хочу понять', 'сколько будет семь плюс', 'статья номер', 'в каком']


@pytest.mark.parametrize('opened,closed', PAIRS)
def test_pair(opened, closed):
    assert open_tail(opened), opened
    assert not open_tail(closed), closed


@pytest.mark.parametrize('text', ['', None, '   ', '...'])
def test_empty_is_not_open(text):
    assert not open_tail(text)


@pytest.mark.parametrize('text', ['а почему это', 'что такое НДС', 'сколько стоит', 'в 1961', 'статья 21', 'сколько будет пять на пять', 'семь плюс восемь', 'в каком году'])
def test_finished_questions_not_held(text):
    assert not open_tail(text)


# closed to a listener, open to ``open_tail`` today (false hold, the extra EAR_TAIL wait): a clause of «если/чтобы/хотя» that ends with no question word.
FALSE_HOLDS = ['нужно, чтобы я заплатил']


@pytest.mark.parametrize('text', FALSE_HOLDS)
@pytest.mark.xfail(strict=True, reason='known false hold')
def test_known_false_hold(text):
    assert not open_tail(text)


@pytest.mark.parametrize('text', CLOSED_GAPS)
def test_closed_gap_is_open(text):
    assert open_tail(text)


@pytest.mark.parametrize('text', ['что такое статья', 'какой у тебя номер', 'в каком году', 'сколько будет семь плюс восемь', 'статья номер 5'])
def test_closed_gaps_hold_no_finished_question(text):
    assert not open_tail(text)


@pytest.mark.parametrize('text', GAPS)
@pytest.mark.xfail(strict=True, reason='known false release: open_tail has no rule for this ending')
def test_known_gap(text):
    assert open_tail(text)


# ---- mutants: one exact replacement in open_tail/_stands_alone; the pairs must notice each ----------------------------------------
MUTANTS = {
    'm1 preposition ending dropped': ("words[-1] in PREPOSITIONS | CONJUNCTIONS and", "words[-1] in CONJUNCTIONS and"),
    'm2 conjunction ending dropped': ("words[-1] in PREPOSITIONS | CONJUNCTIONS and", "words[-1] in PREPOSITIONS and"),
    'm3 question word veto removed': ("words[-1] not in QUESTION_WORDS)", "True)"),
    'm4 two-word ends dropped': ("' '.join(words[-2:]) in _OPEN_ENDS or ", ""),
    'm5 three-word ends dropped': (" or ' '.join(words[-3:]) in _OPEN_ENDS:", ":"),
    'm6 если clause never open': ("if opens and not", "if False and not"),
    'm7 question closes если clause no more': ("(QUESTION_WORDS | {'то'})", "frozenset()"),
    'm8 number with no unit closed': ("return (words[-1].isdigit() or words[-1] in NUMBER_WORDS) and not _stands_alone(words)", "return False"),
    'm9 number always open': ("and not _stands_alone(words)", ""),
    'm10 empty text open': ("if not words:\n        return False", "if not words:\n        return True"),
    'm11 number words not numbers': ("(words[-1].isdigit() or words[-1] in NUMBER_WORDS) and not", "words[-1].isdigit() and not"),
    'm12 operators not operands': ("words[at] in _NUMBERED or words[at] in _OPERATORS or", "words[at] in _NUMBERED or"),
    'm13 «на» operand dropped': ("(words[at] == 'на' and at > 0 and (number(words[at - 1]) or words[at - 1] in _OPERATORS))", "False"),
    'm14 year not alone': ("1000 <= int(words[-1]) <= 2100", "False"),
}


def _mutant(old, new):
    names = ('open_tail', '_stands_alone')
    src = '\n\n'.join(inspect.getsource(getattr(classifier, n)) for n in names)
    assert src.count(old) == 1, f'stale mutant: {old!r} found {src.count(old)} times'
    space = dict(vars(classifier))
    exec(src.replace(old, new), space)
    return space['open_tail']


def _noticed(fn):
    """Does some pair or finished question tell the mutant from the original?"""
    return any(fn(o) != open_tail(o) or fn(c) != open_tail(c) for o, c in PAIRS) or any(fn(t) != open_tail(t) for t in ['', 'а почему это', 'статья 21', 'в 1961', 'сколько будет пять на пять', 'семь плюс восемь'])


# equivalent mutants: _OPEN_ENDS has no three-word entry, so the three-word test never fires alone (m5 changes nothing today).
EQUIVALENT = {'m5 three-word ends dropped'}


@pytest.mark.parametrize('name', sorted(set(MUTANTS) - EQUIVALENT))
def test_mutant_killed(name):
    assert _noticed(_mutant(*MUTANTS[name])), f'survived: {name}'

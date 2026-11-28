"""P04 features for the kind judge (P03 reads them; they decide nothing): «Нужно не X, а Y» without a mark (``contrast_not_but``) and the opener «ну что …» (``what_opener``).

By structure, not by phrase: the contrast is «не» + one to three words + «а» + something, with enough content words around it; the opener is «что» (after leads) followed by nothing or by a
hortative («поехали», «начнём», «давай»), never by a word that asks."""
import itertools

import pytest

from echo_sync.cm_probes import UNKNOWN, probe

MODALS = ['нужно', 'надо', 'необходимо', 'нужны', 'требуется']
THINGS = [('пять', 'шесть'), ('вторник', 'среду'), ('красные', 'синие'), ('Иванов', 'Петров'), ('двадцать', 'тридцать')]
TAILS = ['сотрудников для проекта', 'человек на смену', 'отчётов к понедельнику']


@pytest.mark.parametrize('modal,pair,tail', list(itertools.product(MODALS, THINGS, TAILS)))
def test_not_x_but_y_is_a_contrast_in_every_frame(modal, pair, tail):
    said = f'{modal} не {pair[0]} а {pair[1]} {tail}'
    found = probe('contrast_not_but', said)
    assert found.value == 1 and found.confidence == 1.0, said


@pytest.mark.parametrize('said', [
    'нужно не бояться а делать',                               # four words: a remark to a friend, too little around it to be a question
    'нужно пять сотрудников для проекта',                      # no contrast
    'пять а не шесть сотрудников для проекта нужно',            # «а не»: the other order
    'нужно не пять сотрудников для проекта и ещё чего-то',      # no «а»
    'не знаю а может и знаю про сотрудников проекта',           # «а» after «не» but the first part is no object
])
def test_without_the_frame_or_with_too_little_around_it_it_is_unknown(said):
    assert probe('contrast_not_but', said).value == UNKNOWN, said


@pytest.mark.parametrize('lead', ['', 'ну', 'так', 'а', 'ну вот'])
@pytest.mark.parametrize('rest', ['', 'поехали', 'начнём', 'давай дальше', 'продолжим', 'давайте начнём', 'приступим', 'пойдём', 'погнали'])
def test_what_opener_is_the_hortative_after_what(lead, rest):
    said = ' '.join(part for part in (lead, 'ну что' if not lead else 'что', rest) if part)
    found = probe('what_opener', said)
    assert found.value == 'opener', said


@pytest.mark.parametrize('said', ['ну что такое налог', 'ну что значит амортизация', 'что сказала она', 'ну что ты думаешь про налог', 'что поехали у тебя', 'ну что нового в налоговом кодексе'])
def test_what_that_asks_is_no_opener(said):
    assert probe('what_opener', said).value == UNKNOWN, said

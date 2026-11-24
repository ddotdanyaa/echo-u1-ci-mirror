"""c22-merge: a first cue never ends on a dash, a preposition or a conjunction, whatever rule made it (R21's early «a dash after its own
predicate» too). If the next clause fits the cap of a first portion (9 words, 12 for a question for a number or a date) it is taken;
otherwise the cue is cut at the last place that closes the thought. The owner's broken cues: «Штраф двадцать процентов по статье 123 —»,
«Активные, пассивные и смешанные —», «Перераспределение стоимости на возвратной основе —».
The expectations are written here, not read from echo_sync."""
import re

import pytest

from echo_sync.first_useful import first_cue
from echo_sync.settings import CALL_SETTINGS as S

WORD = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*", re.U)
PREP = frozenset('в во на с со к ко по о об от из за для до при про над под перед между через без у около после среди'.split())
CONJ = frozenset('и а но да или либо ни что чтобы чтоб как когда если хотя пока потому поскольку так также зато однако ибо'.split())
CAP, NUMBER_CAP = 9, 12


def _open_end(cue):
    text = str(cue or '').rstrip()
    if text[-1:] in '.!?…':
        return ''
    body = text.rstrip(',;:').rstrip()
    if body[-1:] in '—–-':
        return 'dash'
    last = (WORD.findall(body) or [''])[-1].casefold().replace('ё', 'е')
    return 'preposition' if last in PREP else 'conjunction' if last in CONJ else ''


def _stream(answer, question):
    parts = answer.split(' ')
    for k in range(1, len(parts) + 1):
        cue = first_cue(' '.join(parts[:k]) + (' ' if k < len(parts) else ''), question, S, final=k == len(parts), last=k == len(parts))
        if cue:
            return cue
    return None


def _cues(question, answer):
    return {'whole': first_cue(answer, question, S, final=True, last=True), 'stream': _stream(answer, question)}


BROKEN = [
    ('Какая ответственность у налогового агента?',
     'Штраф двадцать процентов по статье 123 — за неправомерное неудержание или неперечисление налога, от суммы, подлежащей удержанию '
     'и перечислению. За неисполнение или ненадлежащее исполнение обязанностей налоговый агент несёт ответственность по законодательству России.',
     'Штраф двадцать процентов по статье 123 —'),
    ('Какие бывают счета бухгалтерского учёта?',
     'Активные, пассивные и смешанные — в зависимости от того, что они учитывают: имущество, его источники или и то и другое. '
     'Активные счета учитывают имущество.',
     'Активные, пассивные и смешанные —'),
    ('Что такое кредит?',
     'Перераспределение стоимости на возвратной основе — экономические отношения между кредитором и заёмщиком по поводу предоставления '
     'ссуды. Кредит выдаётся на условиях срочности, платности и возвратности.',
     'Перераспределение стоимости на возвратной основе —'),
]


@pytest.mark.parametrize('question,answer,broken', BROKEN, ids=['penalty_123', 'accounts_kinds', 'credit'])
def test_the_owner_s_broken_cues_end_on_a_closed_thought(question, answer, broken):
    for mode, cue in _cues(question, answer).items():
        assert cue, f'{mode}: silent'
        assert answer.startswith(cue) and not answer[len(cue):len(cue) + 1].isalnum(), (mode, cue)
        assert not _open_end(cue), f'{mode}: {cue!r} ends on a {_open_end(cue)}'
        assert cue.rstrip() != broken, f'{mode}: the cue the owner complained about'
        assert len(WORD.findall(cue)) <= CAP, f'{mode}: {cue!r} is past the cap'
        assert len(WORD.findall(cue)) >= 3, f'{mode}: {cue!r} lost the gist'


def test_a_next_clause_that_fits_the_cap_is_taken():
    """«Активный счёт учитывает имущество, пассивный — источники.»: the clause after the dash fits 9 words, so the cue holds both halves."""
    answer = 'Активный счёт учитывает имущество, пассивный — источники его образования. Это основа двойной записи.'
    assert _cues('Чем отличается активный счёт от пассивного?', answer) == {'whole': answer.split('. ')[0] + '.', 'stream': answer.split('. ')[0] + '.'}


@pytest.mark.parametrize('answer', [
    'Налог платят до 28 числа — это срок для всех организаций и предпринимателей по общему правилу. Иначе начислят пени.',
    'Обычно ставка 22 процента для — большинства товаров и услуг, кроме льготных категорий по закону. Есть и ноль.',
    'Сдают отчёт ежеквартально и — по итогам года отдельно, в электронном виде через оператора. Сроки в кодексе.',
])
def test_no_rule_ends_a_first_cue_open(answer):
    """Whatever made the cue (R21's early dash after a predicate, G15, the cheapest place), it never ends on a dash, a preposition or a
    conjunction."""
    for question in ('Когда платят налог?', 'Расскажи подробнее'):
        for mode, cue in _cues(question, answer).items():
            assert cue and not _open_end(cue), f'{question} {mode}: {cue!r} ends on a {_open_end(cue)}'
            assert len(WORD.findall(cue)) <= NUMBER_CAP, (mode, cue)

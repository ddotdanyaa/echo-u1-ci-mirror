"""c23-final: the ear's early bank answer is silent when its part of the phrase says more than the bank's row (the owner's check of 07.11:
«Куликовская битва она вообще что-то решила или через два года Тохтамыш всё равно Москву сжёг» — the ear cut «куликовская битва она вообще
что-то» and answered the date of the battle, the index on the whole phrase is silent). The index and the ear must agree; an ordinary short
question still hits on the partial as before."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from echo_sync.instant import Instant, load_bank

KUL = {'q': 'Когда была Куликовская битва?', 'answer': 'Куликовская битва была 8 сентября 1380 года.'}
PHRASE = 'Куликовская битва она вообще что-то решила или через два года Тохтамыш всё равно Москву сжёг'


def ear(ix, phrase, step=0.2, cut=None):
    """The ear's partials word by word (each twice), a pause of three partials, then its cut-off final on ``cut`` words (the whole by default). -> the first Hit or None"""
    ix.reset()
    words, t, first = phrase.split(), 0.0, None
    cut = cut or len(words)
    for k in range(1, cut + 1):
        for _ in range(2):
            got = ix.feed(' '.join(words[:k]), t)            # always fed: a hit is followed (and cut) as the controller feeds it
            first = first or got
            t += step
    for _ in range(3):
        got = ix.feed(' '.join(words[:cut]), t)
        first = first or got
        t += step
    got = ix.feed(' '.join(words[:cut]), t, final=True)
    return first or got


@pytest.fixture(scope='module')
def rows():
    root = Path(__file__).resolve().parent.parent / 'cloud_context' / 'bank'
    if not (root / 'instant_bank_2.json').exists():
        pytest.skip('data outside the repository: cloud_context/bank/instant_bank_2.json (not in git; the loud check is tests/test_p14_context_guard.py)')
    return load_bank(root / 'instant_bank_2.json') + load_bank(root / 'gold.json')


@pytest.mark.parametrize('q', ['Когда была Куликовская битва?', 'В каком году была Куликовская битва?', 'Куликовская битва когда была'])
def test_the_kulikovo_question_gets_no_early_date(q, rows):
    ix = Instant(rows + [{**KUL, 'q': q}])
    assert ix.lookup(PHRASE) is None                                     # the index on the whole phrase
    assert ear(ix, PHRASE) is None                                       # the ear on its parts
    words = PHRASE.split()
    for cut in range(3, len(words) + 1):                                  # the ear cut off anywhere after «битва она»: still silent
        assert ear(ix, PHRASE, cut=cut) is None, ' '.join(words[:cut])


def test_the_plain_question_still_hits_early(rows):
    ix = Instant(rows + [KUL])
    hit = ear(ix, 'Когда была Куликовская битва', cut=None)
    assert hit and hit.answer == KUL['answer']
    assert ear(ix, 'Ну а когда была Куликовская битва') is not None      # talk before the question is no extra


@pytest.mark.parametrize('tail', ['она вообще что-то решила', 'и кто там победил', 'вообще', 'она'])
def test_a_word_beyond_the_row_cuts_the_hit_of_the_part(tail, rows):
    """The row said whole, then the speech goes on («… битва она …»): the hit of the part may come (no slower for a plain question), but the
    next word beyond the row cuts it — the controller withdraws an answer not yet sounded (``instant act=cut``), and the ear's cut-off on
    the whole phrase is silent, as the index is."""
    ix = Instant(rows + [KUL])
    phrase = f'Когда была Куликовская битва {tail}'
    words = phrase.split()
    ix.reset()
    for k in range(1, len(words) + 1):
        ix.feed(' '.join(words[:k]), k * 0.2)
    assert ix.hit is None or ix.cut, (phrase, ix.hit)
    ix.reset()
    assert ix.feed(phrase, 0.0, final=True) is None or tail in ('вообще', 'и кто там победил')   # «… и кто …»: W11 answers the first of two questions    # the ear's cut-off on it: a function word beyond the row is speech going on
    # (the index on the cloud's final may still answer «… она» or two questions joined by «и» (W11): the ear is the stricter of the two, never the looser)


def test_no_ordinary_bank_question_loses_its_early_hit(rows):
    """Every question of the repository's banks said as it is written: the ear hits on the same partial as without the rule (no slower)."""
    import echo_sync.instant as instant
    ix = Instant(rows)
    keep, lost = instant._beyond_row, []
    for row in ix.entries[:400]:
        q = row['q'].rstrip(' ?.')
        now = ear(ix, q)
        instant._beyond_row = lambda text, row, partial=True: False
        try:
            before = ear(ix, q)
        finally:
            instant._beyond_row = keep
        if before is not None and (now is None or now.t > before.t):
            lost.append(q)
    assert not lost, f'{len(lost)} slower, first: {lost[:5]}'


@pytest.mark.parametrize('tail', ['она вообще что-то решила', 'или нет'])
def test_the_ear_never_keeps_an_answer_the_index_does_not_give(tail, rows):
    """A sample of the bank (every 16th entry, every form) said with a tail: once the ear has heard the whole phrase, a hit it still holds
    (not cut) is the index's answer on that phrase. On c22-merge 6cdfbc4 the same check (every 4th entry, 4 tails) gave 2434 of 8224."""
    ix, bad = Instant(rows), []
    for row in ix.entries[::16]:
        for q in [row['q']] + list(row['alt']):
            phrase = f"{q.rstrip(' ?.')} {tail}"
            one = ix.lookup(phrase)
            ear(ix, phrase)
            if ix.hit is not None and not ix.cut and (one is None or one.answer != ix.hit.answer):
                bad.append(phrase)
    assert not bad, f'{len(bad)}: {bad[:5]}'

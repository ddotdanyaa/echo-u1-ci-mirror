"""U15-S4: ``keep_ready`` (keep_or_discard): a chatter prefix of the final is tolerated, protected atoms never; exclusive with ``adopt_missing_words``."""
import pytest

from echo_sync import fast_text as FT
from echo_sync import settings as cfg
from echo_sync.fast_text import keep_chatter
from helpers_fast_fake import Fake

KEEPS = [
    ('сколько стоит открыть расчетный счет', 'ну слушайте сколько стоит открыть расчетный счет'),
    ('как открыть расчетный счет', 'короче как открыть расчетный счет'),
]
DISCARDS = [
    ('сколько стоит открыть расчетный счет', 'пять сколько стоит открыть расчетный счет'),
    ('как открыть расчетный счет', 'не как открыть расчетный счет'),
    ('как открыть расчетный счет', 'почему как открыть расчетный счет'),
    ('как открыть расчетный счет', 'слушайте друзья коллеги как открыть расчетный счет'),      # a prefix longer than keep_chatter_words
    ('как открыть расчетный счет', 'как закрыть расчетный счет'),                         # not a prefix: another object
]


@pytest.mark.parametrize('heard,asked', KEEPS)
def test_chatter_prefix_is_kept(heard, asked):
    assert keep_chatter(heard, asked, 2)


@pytest.mark.parametrize('heard,asked', DISCARDS)
def test_protected_atoms_and_long_prefixes_are_discarded(heard, asked):
    assert not keep_chatter(heard, asked, 2)


def test_zero_words_keeps_nothing():
    assert not keep_chatter(*KEEPS[0], 0)


def test_resolve_excludes_adopt_missing_words():
    r = cfg.resolve({'keep_ready': 'on', 'adopt_missing_words': 1})
    assert (r['keep_ready'], r['adopt_missing_words']) == ('on', 0)
    r = cfg.resolve({'keep_ready': 'shadow', 'adopt_missing_words': 1})
    assert (r['keep_ready'], r['adopt_missing_words']) == ('shadow', 1)
    d = cfg.resolve(None)
    assert (d['keep_ready'], d['keep_chatter_words']) == ('off', 2)
    assert cfg.resolve({'keep_ready': 'bogus', 'keep_chatter_words': 9})['keep_ready'] == 'off'


def _channel(mode, notes, request):
    # a first road that is asked and has not answered yet: the job is running, not failed (an empty stream is a failed road, the rule would be 'failed')
    fast = FT.FastText(Fake(), instructions=lambda: 'P', history=lambda: [], clock=lambda: 1000.0, wake=lambda: None, report=lambda ev, **f: notes.append((ev, f)))
    fast.keep = mode
    job = fast._start(KEEPS[0][0])
    request.addfinalizer(fast.close)
    return fast, job


@pytest.mark.parametrize('mode,fits,rules', [('off', False, ['fast_refused']), ('shadow', False, ['fast_keep', 'fast_refused']), ('on', True, ['fast_keep'])])
def test_fits_modes(mode, fits, rules, request):
    notes = []
    fast, job = _channel(mode, notes, request)
    assert fast._fits(job, KEEPS[0][1]) is fits
    assert [ev for ev, _ in notes] == rules


def test_keep_notes_go_through_the_note_cap(request):
    notes = []
    fast, job = _channel('shadow', notes, request)
    for n in range(6):
        fast._fits(job, f'ну слушайте {n} ' + KEEPS[0][1])   # protected atom: discarded, a refusal
        fast._fits(job, ('ну ' * (n % 2 + 1)) + KEEPS[0][0])
    assert sum(1 for ev, _ in notes if ev in ('fast_keep', 'fast_refused')) <= FT.REFUSED_NOTES_PER_JOB + 1

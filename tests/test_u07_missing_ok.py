"""U07-S7: ``refusal(missing_ok=K)`` forgives up to K missing words outside the asking tail; K=0 is the old refusal; exclusive with keep_ready and prepare_wide."""
import json
from pathlib import Path

import pytest

from echo_sync import fast_text as FT
from echo_sync import settings as cfg
from echo_sync.fast_text import refusal
from tools import harvest

PAIRS = [
    ('сколько стоит открыть расчетный счет', 'сколько стоит открыть расчетный счет'),
    ('сколько стоит открыть расчетный счет', 'сколько стоит открыть быстро расчетный счет'),
    ('как открыть расчетный счет', 'как открыть расчетный счет в банке'),
    ('как открыть счет', 'как закрыть счет'),
    ('сколько стоит открыть счет', 'сколько стоит открыть 5 счет'),
    ('открыть расчетный счет', 'не открыть расчетный счет'),
    ('', 'как открыть счет'),
]


@pytest.mark.parametrize('heard,asked', PAIRS)
def test_zero_is_the_old_refusal(heard, asked):
    assert refusal(heard, asked, missing_ok=0) == refusal(heard, asked)


def test_one_missing_word_before_the_ask_is_forgiven_with_k1():
    heard, asked = 'как открыть расчетный счет', 'подробно как открыть расчетный счет'
    assert refusal(heard, asked) == 'words'
    assert refusal(heard, asked, missing_ok=1) is None


def test_two_missing_words_need_k2():
    heard, asked = 'как открыть расчетный счет', 'подробно расскажите как открыть расчетный счет'
    assert refusal(heard, asked, missing_ok=1) == 'words'
    assert refusal(heard, asked, missing_ok=2) is None


def test_a_missing_word_in_the_asking_tail_is_never_forgiven():
    heard, asked = 'как открыть счет', 'как открыть расчетный счет'
    assert refusal(heard, asked) == 'words'
    assert refusal(heard, asked, missing_ok=2) == 'words'


def test_missing_asking_word_negator_and_numbers_are_never_forgiven():
    assert refusal('открыть расчетный счет', 'почему открыть расчетный счет', missing_ok=2) is not None      # roles
    assert refusal('открыть расчетный счет', 'не открыть расчетный счет', missing_ok=2) == 'numbers'
    assert refusal('открыть расчетный счет', 'пять открыть расчетный счет', missing_ok=2) == 'numbers'


def test_settings_lock():
    r = cfg.resolve({'adopt_missing_words': 1, 'keep_ready': 'on'})
    assert r['adopt_missing_words'] == 0
    r = cfg.resolve({'fast_text': 'on', 'local_ear': 'act', 'adopt_missing_words': 1, 'prepare_wide': 'on'})
    assert r['adopt_missing_words'] == 0
    assert cfg.resolve(None)['adopt_missing_words'] == 0


def _fast(k):
    fast = FT.FastText(lambda request, cancelled: iter(('да',)), instructions=lambda: 'P', history=lambda: [], clock=lambda: 1000.0, wake=lambda: None)
    fast.missing_ok = k
    return fast, fast._start('как открыть расчетный счет')


def test_fits_follows_missing_ok():
    for k, fits in ((0, False), (1, True)):
        fast, job = _fast(k)
        assert fast._fits(job, 'подробно как открыть расчетный счет') is fits


def test_wide_ignores_missing_ok():
    fast, job = _fast(2)
    fast.wide = True
    assert fast._why_not(job, 'подробно как открыть расчетный счет') == FT.wide_refusal(job.text, 'подробно как открыть расчетный счет', strip=fast.strip, whole=fast.whole)


def _rows(heard, asked, job=1):
    return [{'t': 1000, 'ev': 'fast_job', 'job': job, 'on': 'x', 'outcome': 'ok'},
            {'t': 2000, 'ev': 'fast_refused', 'job': job, 'rule': 'words', 'heard': heard, 'asked': asked, 'ms': 500}]


def test_whatif_flip_table():
    table = harvest.whatif(_rows('как открыть расчетный счет', 'подробно как открыть расчетный счет'), 1)
    assert [(r['job'], r['before'], r['after'], r['flip']) for r in table] == [(1, 'words', None, True)]
    table = harvest.whatif(_rows('как открыть счет', 'как открыть расчетный счет'), 1)
    assert [r['flip'] for r in table] == [False]
    assert harvest.whatif(_rows('как открыть расчетный счет', 'подробно как открыть расчетный счет'), 0)[0]['flip'] is False


def test_whatif_flag_prints_the_table(tmp_path, capsys):
    path = tmp_path / '20261101-000000-aaaaaaaaaaaa.jsonl'
    path.write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in _rows('как открыть расчетный счет', 'подробно как открыть расчетный счет')), encoding='utf-8')
    assert harvest.main(['--whatif', '1', str(path)]) == 0
    out = capsys.readouterr().out
    assert 'whatif K=1' in out and 'flip' in out

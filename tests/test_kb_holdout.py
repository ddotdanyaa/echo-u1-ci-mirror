"""E96 (1): a bank is never built of the measurement's questions (``tools/build_instant_bank --holdout``). Through the real controller: the question that is in the
holdout is not answered from the bank (it goes the usual way), the same question with no holdout is answered from the bank, the other questions are untouched."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
import build_instant_bank as tool
import helpers_w5_instant as fx
from echo_sync.instant import Instant
from echo_sync.pcm_cache import first_portion
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_h4_ear_first import speaks

ASKED = fx.bank()[0]            # the first row: a plain bank question
OTHER = fx.bank()[1]


def _built(tmp_path, holdout_rows):
    bank = tmp_path / 'bank.json'
    bank.write_text(json.dumps(fx.bank(), ensure_ascii=False), encoding='utf-8')
    held = tmp_path / 'holdout.json'
    held.write_text(json.dumps(holdout_rows, ensure_ascii=False), encoding='utf-8')
    return tool.build([bank], holdout=[held] if holdout_rows else ())


def test_a_holdout_question_is_not_in_the_bank_and_the_counts_say_so(tmp_path):
    rows, counts = _built(tmp_path, [ASKED['q'].upper() + '?'])         # case and the mark do not matter
    assert ASKED['q'] not in {r['q'] for r in rows} and OTHER['q'] in {r['q'] for r in rows}
    assert counts['dropped_holdout'] == 1 and counts['holdout_sha256'] and counts['bank_sha256']
    again = _built(tmp_path, [ASKED['q']])[1]
    assert again['bank_sha256'] == counts['bank_sha256'] and again['holdout_sha256'] == counts['holdout_sha256']


def test_a_row_is_dropped_by_its_alternative_too(tmp_path):
    alt = next(r for r in fx.bank() if r['alt'])
    rows, counts = _built(tmp_path, [{'q': alt['alt'][0]}])
    assert alt['q'] not in {r['q'] for r in rows} and counts['dropped_holdout'] == 1


def test_no_holdout_changes_nothing(tmp_path):
    rows, counts = _built(tmp_path, [])
    assert len(rows) == len(fx.bank()) and counts['dropped_holdout'] == 0 and counts['holdout_sha256'] == ''


def test_the_controller_answers_the_bank_question_with_no_holdout(call, tmp_path):
    rig = call(fast_text='on')
    rig.c.instant = Instant(_built(tmp_path, [])[0])
    speaks(rig, ASKED['q'].lower(), turn='u1', announced=1.0, speech=1.1)
    assert rig.said() and rig.said()[0] == first_portion(ASKED['answer'])


def test_the_controller_does_not_answer_a_holdout_question_from_the_bank(call, tmp_path):
    rig = call(fast_text='on')
    rig.c.instant = Instant(_built(tmp_path, [ASKED['q']])[0])
    speaks(rig, ASKED['q'].lower(), turn='u1', announced=1.0, speech=1.1)
    assert rig.said() == []

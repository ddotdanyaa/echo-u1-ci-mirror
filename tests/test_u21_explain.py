"""U21-S3: Ranker.explain mirrors best (a reason word exactly when best gives none), Instant.explain, the 6 rows of the 68-set."""
import json
from pathlib import Path

import pytest

from echo_sync import instant
from echo_sync.settings import DEFAULTS, resolve
from tools import bank_states as bs

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT.parents[1] / 'МАТЕРИАЛЫ' / 'БАНК' / 'eval'
BANK10 = EVAL.parent / 'instant_bank_10.json'
ROWS = [{'id': 'a1', 'q': 'что такое абсолютная ссылка', 'alt': [], 'answer': 'Ссылка, которая не меняется при копировании формулы.', 'trust': 'Д'},
        {'id': 'a2', 'q': 'что такое относительная ссылка', 'alt': [], 'answer': 'Ссылка, которая сдвигается при копировании формулы.', 'trust': 'Д'},
        {'id': 'a3', 'q': 'какие бывают виды ссылок в таблице', 'alt': [], 'answer': 'Абсолютные, относительные и смешанные.', 'trust': 'Д'}]
QUESTIONS = ['что такое абсолютная ссылка', 'что такое относительная ссылка', 'что такое смешанная ссылка', 'ну да', 'как погода в Казани сегодня',
             'что такое абсолютная ссылка и почему', 'что такое квантовая запутанность', 'виды ссылок в таблице']


@pytest.fixture(autouse=True)
def small_bank(monkeypatch):
    monkeypatch.setattr(instant, 'RANK_MIN_MASS', 0.1)      # three rows weigh little: the floor of a real bank would read every question as nothing


def ranker(rank2=False):
    return instant.Instant([dict(r) for r in ROWS], adapters=(), rank2=rank2).ranker


@pytest.mark.parametrize('rank2', [False, True])
@pytest.mark.parametrize('partial', [False, True])
def test_explain_is_empty_exactly_when_best_answers(rank2, partial):
    r = ranker(rank2)
    for q in QUESTIONS:
        assert (r.best(q, partial=partial) is None) == bool(r.explain(q, partial=partial)), q


def test_the_reasons_of_a_synthetic_bank():
    r = ranker()
    assert r.explain('что такое абсолютная ссылка') == ''
    assert r.explain('что такое абсолютная запутанность') == 'unknown_word'
    assert r.explain('ну да') == 'no_terms'


def test_instant_explain_is_empty_for_a_hit_and_names_a_miss():
    ins = instant.Instant([dict(r) for r in ROWS], adapters=())
    assert ins.explain('что такое абсолютная ссылка') == ''
    assert ins.explain('что такое абсолютная запутанность') == 'unknown_word'
    assert instant.Instant([], adapters=(), rank=False).explain('что такое абсолютная ссылка') == 'no_ranker'


def test_the_reason_of_a_retraction_and_of_a_talk_before_the_question():
    ins = instant.Instant([dict(r) for r in ROWS], adapters=())
    assert ins.explain('что такое относительная ссылка, нет, давай-ка про квантовую запутанность') == 'self_correction'
    assert ins.explain('Заказ отменен. Так, значит, что такое абсолютная ссылка') in ('', 'truncated')


def test_the_log_only_flag_bank_why_is_gone():
    assert 'bank_why' not in DEFAULTS and 'bank_why' not in resolve({'bank_why': 'on'})


@pytest.mark.skipif(not (BANK10.exists() and (EVAL / 'sheet_questions.tsv').exists()), reason='the owner materials are not here')
def test_the_six_lost_rows_of_the_68_give_their_reasons():
    rows = [r for r in (instant.clean_entry(x) for x in json.load(open(BANK10, encoding='utf-8'))) if r]
    qs = bs.read_rows(EVAL / 'sheet_questions.tsv') + bs.read_rows(EVAL / 'real_questions.tsv')
    ins = instant.Instant([dict(r) for r in rows], adapters=(), rank2=True)
    lost = {q: ins.explain(q) for q, state, _, _ in bs.measure(rows, ins, qs) if state == 'S1'}
    assert len(lost) == 6
    assert lost['Виды финансов организаций'] == 'rival' and lost['Вывод об изменении структуры долга'] == 'rival'
    assert lost['Федеральное казначейство Российской Федерации что это'] == 'form_min'
    assert lost['функция денег, нет, давай-ка знаешь что денежная масса и денежная база что это'] == 'self_correction'      # RC3
    assert lost['Так, стимулиру ющая функция'] == 'unknown_word'
    assert lost['Заказ отменен. Так, значит, что такое функция денег'] == 'truncated'      # RC1: the question alone is answered, the talk before it was not cut off in the ear's way
    assert all(lost.values())      # every S1 has a reason

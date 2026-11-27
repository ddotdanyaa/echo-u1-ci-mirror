"""I9 (U151, E66): the bank clean-up and the 30 etalons. The decision of the bank changes through the real matcher (``instant.Instant`` + ``bank_eval.feed``, the ear's way):
a question bound to a day is answered before the clean-up and is silent after; a sentence that points at a paper the listener has not got is no longer spoken.
The owner's bank 11 and the law base are data of the laptop: their tests are skipped where the files are not (the cloud), and the report says so."""
import json
import sqlite3
from pathlib import Path

import pytest

from echo_sync import instant
from tools import bank_accounts_coverage as ac
from tools import bank_clean as bc
from tools import bank_etalons as be
from tools import bank_eval

ROOT = Path(__file__).resolve().parents[1]
BANK11 = ROOT.parents[1] / 'МАТЕРИАЛЫ' / 'БАНК' / 'instant_bank_11.json'
LAW = ROOT.parents[1] / '03_TESTS' / 'reference_kb' / 'law.sqlite'
SRC = 'Лекция по теме'


def row(i, q, a, src=SRC, alt=()):
    return {'id': i, 'q': q, 'alt': list(alt), 'core': a.split('.')[0], 'answer': a, 'source': src, 'subject': 'налоги', 'trust': 'М'}


STALE = row('s1', 'Что задано по налогам на 6 ноября?', 'Заполнить форму расчёта по страховым взносам и сдать до пятницы.')
CONTEXT = row('c1', 'В какой главе Налогового кодекса страховые взносы?', 'В главе 34 Налогового кодекса, часть вторая. В журнале это тема 1.7 «Страховые взносы». Она начинается со статьи 419.')
GOOD = row('g1', 'Какая ставка налога на прибыль организаций?', 'Двадцать процентов от налоговой базы, статья 284 Налогового кодекса.')


def asked(rows, question):
    hit, _ = bank_eval.feed(instant.Instant([dict(r) for r in rows], adapters=()), question)
    return hit


def test_a_question_bound_to_a_day_is_answered_before_the_clean_up_and_silent_after():
    rows = [STALE, GOOD]
    assert asked(rows, STALE['q']) is not None
    kept, dropped, fixed, review = bc.clean(rows)
    assert [i for i, _ in dropped] == ['s1'] and dropped[0][1] == ['stale']
    assert asked(kept, STALE['q']) is None or asked(kept, STALE['q']).id != 's1'
    assert asked(kept, GOOD['q']).id == 'g1'


def test_a_sentence_that_points_at_a_paper_is_cut_and_the_row_stays():
    kept, dropped, fixed, _ = bc.clean([CONTEXT])
    assert not dropped and [i for i, _ in fixed] == ['c1']
    hit = asked(kept, CONTEXT['q'])
    assert hit is not None and 'журнал' not in hit.answer and 'глав' in hit.answer
    assert 'журнал' in (asked([CONTEXT], CONTEXT['q']).answer)


def test_echo_nonanswer_noise_and_short_rows_are_dropped_and_fit_rows_are_not():
    rows = [row('e1', 'Что такое счёт 50?', 'Что такое счёт 50.'), row('n1', 'Какая ставка НДС?', 'Не знаю, в материале нет.'),
            row('z1', 'Заказ отменён, что такое касса?', 'Касса — это место, где хранят наличные деньги организации.'), row('t1', 'Что такое?', 'Да'), GOOD]
    _, dropped, _, _ = bc.clean(rows)
    why = dict(dropped)
    assert why == {'e1': ['echo'], 'n1': ['nonanswer'], 'z1': ['noise'], 't1': ['short']}
    assert bc.reasons(GOOD) == ([], [], [])


def test_a_case_question_and_a_row_without_source_are_listed_never_dropped():
    case = row('k1', 'О чём кейс «Куда вложить деньги»?', 'Супруги выбирают, куда вложить общий доход, и спорят о бизнесе и фонде.')
    nosrc = row('o1', 'Что такое План счетов?', 'Перечень счетов бухгалтерского учёта, утверждённый приказом Минфина.', src='')
    kept, dropped, _, review = bc.clean([case, nosrc])
    assert len(kept) == 2 and not dropped and dict(review) == {'k1': ['casequestion'], 'o1': ['nosource']}


def test_unfit_rate_counts_only_asked_questions():
    assert bc.unfit_rate(['a', None, 'b', 'a'], ['a']) == pytest.approx(2 / 3)
    assert bc.unfit_rate([None], ['a']) == 0.0


@pytest.mark.skipif(not BANK11.exists(), reason='the owner bank is data of the laptop')
def test_the_list_in_the_repository_is_what_the_rules_say_on_bank_11():
    data = json.loads(BANK11.read_text(encoding='utf-8'))
    _, dropped, _, _ = bc.clean(data)
    assert {i: ','.join(w) for i, w in dropped} == bc.read_ids()


# --- E66: the etalons ---
def test_the_etalon_list_has_30_rows_of_every_kind_and_every_calc_row_is_a_number_check():
    rows = be.read()
    assert len(rows) == 30 and {r['kind'] for r in rows} == set(be.KINDS)
    for r in rows:
        assert r['key'] and r['origin'] and r['date'] and r['status'] in ('tool', 'owner'), r['id']
        assert r['kind'] != 'calc' or r['check'].startswith('calc:'), r['id']
        assert r['check'] != 'none' or r['status'] == 'owner', r['id']


def test_calc_refuses_anything_but_numbers():
    assert be.calc('250000+17000+14160+3000+2000+15000+450') == 301610
    with pytest.raises(ValueError):
        be.calc('__import__("os").getcwd()')


def test_an_etalon_fails_when_the_answer_loses_a_key_or_the_number_differs():
    et = {'id': 'x', 'kind': 'calc', 'key': '301 610', 'check': 'calc:250000+17000+14160+3000+2000+15000+450=301610'}
    assert be.check_one(et, {'x': {'answer': '301 610 рублей, шесть ордеров'}}) == 'ok'
    assert be.check_one(et, {'x': {'answer': '300 000 рублей'}}) == 'key-missing'
    assert be.check_one({**et, 'check': 'calc:250000+17000=301610'}, {'x': {'answer': '301 610 рублей'}}) == 'calc-differs'
    assert be.check_one(et, {}) == 'row-missing'


def test_a_law_etalon_is_checked_against_the_article_text_and_not_counted_without_the_base(tmp_path):
    db = tmp_path / 'law.sqlite'
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE rows(id INTEGER PRIMARY KEY, doc TEXT, article TEXT, kind TEXT, text TEXT, seq INTEGER)')
    conn.execute("INSERT INTO rows VALUES(1, 'nk', '346.8', 'body', 'Налоговая ставка устанавливается в размере 6 процентов.', 1)")
    conn.commit()
    et = {'id': 'x', 'kind': 'norm', 'key': 'шесть', 'check': 'law:nk:346.8:в размере 6 процентов'}
    bank = {'x': {'answer': 'Шесть процентов.'}}
    assert be.check_one(et, bank, conn) == 'ok'
    assert be.check_one({**et, 'check': 'law:nk:346.8:в размере 15 процентов'}, bank, conn) == 'law-differs'
    assert be.check_one({**et, 'check': 'law:nk:999:х'}, bank, conn) == 'law-missing'
    assert be.check_one(et, bank, None) == 'no-law-base'


@pytest.mark.skipif(not BANK11.exists(), reason='the owner bank is data of the laptop')
def test_the_30_etalons_hold_on_bank_11_where_no_law_base_is_needed():
    data = json.loads(BANK11.read_text(encoding='utf-8'))
    bad = [(i, k, s) for i, k, s in be.run(data, be.read(), None) if s not in ('ok', 'no-law-base')]
    assert not bad, bad


@pytest.mark.skipif(not (BANK11.exists() and LAW.exists()), reason='the law base is data of the laptop')
def test_the_30_etalons_hold_on_bank_11_with_the_law_base():
    data = json.loads(BANK11.read_text(encoding='utf-8'))
    bad = [(i, k, s) for i, k, s in be.run(data, be.read(), sqlite3.connect('file:%s?mode=ro' % LAW, uri=True)) if s != 'ok']
    assert not bad, bad


# --- S10: the plan of accounts ---
def test_the_account_questions_come_from_the_plan_and_the_fact_is_the_official_name():
    qs = dict(ac.questions({'15': 'Заготовление и приобретение материальных ценностей', '001': 'Арендованные основные средства'}))
    assert qs == {'Что такое счёт 15?': 'заготовление и'}


def test_every_on_balance_account_of_the_plan_is_answered_through_the_real_matcher_with_its_name():
    got = ac.coverage([GOOD])
    assert got['asked'] == len([n for n in ac.ACCOUNTS if len(n) == 2]) >= 60
    assert got['wrong'] == 0 and got['right'] == got['asked'], got['missed']


@pytest.mark.skipif(not BANK11.exists(), reason='the owner bank is data of the laptop')
def test_the_plan_of_accounts_is_answered_with_bank_11_in_the_bank_too():
    got = ac.coverage(instant.load_bank(BANK11))
    assert got['wrong'] == 0 and got['right'] == got['asked'], got['missed']

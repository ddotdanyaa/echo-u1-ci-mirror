"""U14-S1: the ledger core in memory."""
from echo_sync.conversation_ledger import ConversationLedger, LEDGER_HOT, PLAY_LAG_S

TEXT = 'это длинная фраза про то как мы вчера обсуждали договор поставки и сроки оплаты по нему'


def test_verbatim_tail():
    led = ConversationLedger()
    led.user_final('t1', 'раз два три', final_rev=1)
    led.user_final('t2', 'четыре пять шесть семь', final_rev=1)
    assert led.user_words(5) == ['три', 'четыре', 'пять', 'шесть', 'семь']
    assert led.user_words(100) == 'раз два три четыре пять шесть семь'.split()


def test_exact_duplicate_dropped_revision_replaces():
    led = ConversationLedger()
    assert led.user_final('t1', 'привет мир', final_rev=1) is not None
    assert led.user_final('t1', 'привет мир', final_rev=1) is None
    assert led.user_final('t1', 'привет всем людям', final_rev=2) is not None
    assert led.user_words(10) == ['привет', 'всем', 'людям']


def test_echo_is_not_user_words():
    led = ConversationLedger()
    led.user_final('t1', 'моя фраза', final_rev=1)
    led.user_final('t2', 'эхо подсказки', final_rev=1, echo=True)
    assert led.user_words(10) == ['моя', 'фраза']


def test_answer_supersedes_not_played():
    led = ConversationLedger()
    led.answer('a1', 'старый ответ', tid='t1')
    led.answer('a2', 'новый ответ', tid='t1', supersedes='a1')
    assert [r.superseded for r in led._recs] == [True, False]
    assert led.played_words(10) == []          # nothing was played


def test_done_gives_all_words():
    led = ConversationLedger()
    led.play_began('c1', TEXT, 10.0, voiced_s=6.0)
    led.play_done('c1', 16.2)
    assert led.played_words(100) == TEXT.split()
    assert led.play_cut('c1', 17.0) is None     # a cue ends once
    assert led.played_words(100) == TEXT.split()


def test_cut_at_40_percent_minus_lag():
    led = ConversationLedger()
    voiced = 6.0
    led.play_began('c1', TEXT, 10.0, voiced_s=voiced)
    led.play_cut('c1', 10.0 + 0.4 * voiced + PLAY_LAG_S)     # heard_s = 40 % of the voiced length
    n, total = len(led.heard('c1')), len(TEXT.split())
    assert abs(n / total - 0.4) <= 0.15
    assert led.heard('c1') == TEXT.split()[:n]
    led2 = ConversationLedger()
    led2.play_began('c1', TEXT, 10.0, voiced_s=voiced)
    led2.play_cut('c1', 10.0 + 0.4 * voiced)                 # without the lag allowance: fewer words
    assert len(led2.heard('c1')) < n


def test_cut_before_sound_hears_nothing_and_never_exceeds_total():
    led = ConversationLedger()
    led.play_began('c1', TEXT, 10.0, voiced_s=6.0)
    led.play_cut('c1', 10.1)
    assert led.heard('c1') == []
    led.play_began('c2', TEXT, 20.0, voiced_s=6.0)
    led.play_cut('c2', 99.0)
    assert led.heard('c2') == TEXT.split()


def test_hot_cap():
    led = ConversationLedger(hot=5)
    for i in range(20):
        led.user_final('x%d' % i, 'слово', final_rev=1)
    assert len(led) == 5
    assert LEDGER_HOT == 6000


# --- U14-S2: disk tier ---
import datetime
import logging
import time

from echo_sync.conversation_ledger import LEDGER_KEEP_DAYS


def test_reopen_keeps_words(tmp_path):
    a = ConversationLedger(directory=tmp_path)
    a.user_final('t1', 'раз два три', final_rev=1, at=1.0)
    a.user_final('t1', 'раз два три четыре', final_rev=2, at=2.0)
    a.answer('a1', 'ответ', tid='t1', at=3.0)
    a.play_began('c1', TEXT, 4.0)
    a.play_cut('c1', 6.0)
    heard = a.heard('c1')
    b = ConversationLedger(directory=tmp_path)
    assert b.user_words(10) == ['раз', 'два', 'три', 'четыре']
    assert b.heard('c1') == heard and heard
    assert b.user_final('t1', 'раз два три четыре', final_rev=2) is None


def test_unwritable_is_memory_plus_one_warning(tmp_path, caplog):
    blocker = tmp_path / 'file'
    blocker.write_text('x')
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        led = ConversationLedger(directory=blocker / 'sub')
        led.user_final('t1', 'раз два', final_rev=1)
        led.user_final('t2', 'три', final_rev=1)
    assert led.user_words(5) == ['раз', 'два', 'три']
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_prune_old_days_foreign_kept(tmp_path):
    now = time.time()
    old = (datetime.date.fromtimestamp(now) - datetime.timedelta(days=LEDGER_KEEP_DAYS + 1)).isoformat()
    fresh = (datetime.date.fromtimestamp(now) - datetime.timedelta(days=LEDGER_KEEP_DAYS - 1)).isoformat()
    for n in ('ledger-%s.jsonl' % old, 'ledger-%s.jsonl' % fresh, 'notes.txt', 'ledger-old.jsonl', 'x-ledger-%s.jsonl' % old):
        (tmp_path / n).write_text('{}\n')
    ConversationLedger(directory=tmp_path)
    left = set(p.name for p in tmp_path.iterdir())
    assert 'ledger-%s.jsonl' % old not in left
    assert {'ledger-%s.jsonl' % fresh, 'notes.txt', 'ledger-old.jsonl', 'x-ledger-%s.jsonl' % old} <= left


def test_day_cap_stops_disk_not_memory(tmp_path, caplog):
    led = ConversationLedger(directory=tmp_path, day_bytes=300)
    with caplog.at_level(logging.WARNING, logger='echo-sync'):
        for i in range(30):
            led.user_final('t%d' % i, 'слово %d' % i, final_rev=1)
    assert len(led.user_words(1000)) == 60
    assert sum(p.stat().st_size for p in tmp_path.iterdir()) <= 300
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1


def test_torn_line_skipped_tail_load(tmp_path):
    led = ConversationLedger(directory=tmp_path)
    for i in range(5):
        led.user_final('t%d' % i, 'сл%d' % i, final_rev=1)
    f = next(tmp_path.glob('ledger-*.jsonl'))
    with open(f, 'a', encoding='utf-8') as fh:
        fh.write('{"k":"user","tid":\n')
    small = ConversationLedger(hot=3, directory=tmp_path)
    assert len(small) <= 3
    assert small.user_words(10)[-1] == 'сл4'

"""W9-brain (N117, N118): the short BRAIN loses no rule of the long one, the short history is shorter and keeps what matters, the first paragraph has a limit. Production code, no network."""
import pytest

from echo_sync import brain_short as B
from echo_sync import fast_text as FT


def test_the_core_rules_are_in_the_long_brain_too():
    core = ('role', 'dash', 'dash_is_not_idk', 'no_question_cases', 'stop', 'continue', 'repeat', 'next', 'two_records', 'lost_words', 'doubt_line', 'yes_no', 'no_hedge')
    assert B.missing(FT.BRAIN, [r for r in B.KEEP if r[0] in core]) == []


def test_the_short_brain_keeps_every_rule():
    assert B.missing(B.SHORT_POLICY) == []


def test_a_brain_that_drops_the_dash_or_a_mark_is_caught():
    assert B.missing(B.SHORT_POLICY.replace('[повтори]', '')) == ['repeat']
    assert 'dash' in B.missing(B.SHORT_POLICY.replace('выведи ровно один символ: —', 'ничего'))
    assert 'doubt_no_dash' in B.missing(B.SHORT_POLICY.replace('символ — запрещён', ''))


def test_the_short_brain_is_clearly_shorter_and_keeps_the_form_of_the_answer():
    assert len(B.BRAIN_SHORT) <= 0.75 * len(FT.BRAIN)
    assert B.SHORT_POLICY.endswith(FT.BRAIN_KEEP) and 'до 12 слов' in B.SHORT_POLICY


def test_the_breakable_table_is_true_of_the_long_brain_and_names_what_the_short_one_changes():
    assert B.missing(FT.BRAIN, B.BREAKABLE) == []
    changed = B.missing(B.SHORT_POLICY, B.BREAKABLE)
    assert changed and all(isinstance(n, str) for n in changed)       # the tests that read FT.BRAIN by substring fail on the short text: the patch must point them at the variant


ROWS = [{'question': 'q%d ' % i + 'слово ' * 80, 'answer': 'a%d ' % i + 'слово ' * 80, 'status': 'complete'} for i in range(8)]


def test_the_short_history_is_fewer_and_cut_at_a_word():
    rows = B.short_history(ROWS)
    assert len(rows) == 3 and rows[-1]['question'].startswith('q7') and all(len(r['answer']) <= 200 and not r['answer'].endswith(' ') for r in rows)
    assert all(r['answer'].split()[-1] == 'слово' for r in rows)


def test_the_short_history_drops_the_exchange_in_play_and_keeps_the_revised_mark():
    rows = [{'question': 'q', 'answer': '1988 год.', 'status': 'revised'}, {'question': 'p', 'answer': 'pa', 'status': 'complete'}]
    got = B.short_history(rows, played=('p', 'pa'))
    assert got == rows[:1]
    assert FT.REVISED_MARK in B.build_request('x', history=rows)['instructions']


def test_the_request_is_the_same_shape_and_smaller():
    played = ('q7', 'a7')
    long = FT.build_request('ты уверена', instructions=FT.BRAIN_POLICY, history=ROWS, played=played)
    short = B.build_request('ты уверена', history=ROWS, played=played)
    assert set(short) == set(long) and short['input'][-1] == long['input'][-1]
    assert B.input_chars(short) < 0.5 * B.input_chars(long)


def test_no_variant_chooser_is_left():
    assert not hasattr(B, 'variant')      # one/modes: nothing reached it but a laptop script; the run's text is chosen by the setting brain_short alone


def test_w10_the_flag_puts_the_short_brain_and_history_into_the_channel():
    """w10 item 13: ``brain_short`` = on: the channel's instructions have SHORT_POLICY where the host put BRAIN_POLICY, the history is short; off: as before."""
    from types import SimpleNamespace
    from echo_sync import brain_short, fast_text as FT
    rows = [{'question': 'вопрос %d ' % k + 'слово ' * 80, 'answer': 'ответ ' * 100} for k in range(8)]
    controller = SimpleNamespace(fast_exchanges=lambda: rows, fast_in_play=lambda: None, settings={}, ear_ended=None, source_segment_id=None, refuse_deadline=lambda *a: None, decision_due=lambda *a: None)
    host = lambda *a: FT.BRAIN_POLICY + '\nМатериал: лекция.'
    on = FT.for_call({'fast_text': 'on', 'brain_short': 'on'}, controller, stream=object(), instructions=host)
    off = FT.for_call({'fast_text': 'on'}, controller, stream=object(), instructions=host)
    assert brain_short.SHORT_POLICY in on.instructions('q', []) and FT.BRAIN_POLICY not in on.instructions('q', []) and 'Материал' in on.instructions('q', [])
    assert len(on.history()) == 3 and all(len(r['answer']) <= 200 for r in on.history())
    assert off.instructions('q', []) == host() and off.history() == rows
    on.close(); off.close()

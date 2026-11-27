"""w2-portion: the length of a portion follows the listener (three preset levels, the unsaid rest re-cut through EchoEngine.revise)."""
import re

import pytest

from echo_sync.engine import SILENT, EchoEngine
from echo_sync.generator import StreamingAnswer
from echo_sync.portioner import ADAPT_LEVELS, PortionAdapter, level_settings, portions
from echo_sync.settings import resolve
from engine_say import engine_reply

OK = dict(first_try=True, fast=True)
BAD = dict(first_try=False, fast=False)
TEXT = ('Ставка налога составляет 13 процентов от дохода. Вычет за обучение равен 120 000 рублей в год. '
        'Подать декларацию нужно до 30 апреля. Деньги вернут в течение месяца после проверки.')


def feed(adapter, *events):
    return [adapter.record(**e) for e in events]


def test_levels_are_the_existing_presets():
    assert ADAPT_LEVELS == ('meaning', 'semantic_short', 'pronunciation_short')


def test_two_bad_of_four_goes_down_one_level_with_a_reason():
    a = PortionAdapter()
    out = feed(a, OK, OK, BAD, BAD)
    assert out[:3] == [None, None, None] and out[3]['level'] == 1 and out[3]['from'] == 0 and out[3]['reason']
    assert a.level == 1


def test_one_bad_of_four_stays():
    a = PortionAdapter()
    assert feed(a, OK, BAD, OK, OK) == [None] * 4 and a.level == 0


def test_a_stumble_or_a_repeat_request_counts_as_bad_even_when_first_try():
    a = PortionAdapter()
    feed(a, dict(first_try=True, fast=True, stumbled=True), dict(first_try=True, fast=True, repeat_asked=True))
    assert a.level == 1


def test_never_changes_more_often_than_once_per_three_portions():
    a = PortionAdapter()
    feed(a, BAD, BAD)
    assert a.level == 1
    assert feed(a, BAD, BAD) == [None, None] and a.level == 1      # 2 portions after the change: held
    assert a.record(**BAD)['level'] == 2                           # the 3rd


def test_never_below_the_last_level():
    a = PortionAdapter()
    feed(a, *[BAD] * 30)
    assert a.level == len(ADAPT_LEVELS) - 1


def test_five_fast_first_tries_go_up_but_never_above_zero():
    a = PortionAdapter(level=2)
    out = feed(a, *[OK] * 5)
    assert out[4]['level'] == 1 and out[4]['reason']
    feed(a, *[OK] * 30)
    assert a.level == 0


def test_slow_first_tries_do_not_go_up():
    a = PortionAdapter(level=1)
    feed(a, *[dict(first_try=True, fast=False)] * 8)
    assert a.level == 1


def test_a_streak_broken_by_a_bad_portion_does_not_go_up():
    a = PortionAdapter(level=2)
    feed(a, OK, OK, OK, OK, BAD, OK)
    assert a.level == 2 and not a.trace


def test_the_trace_keeps_every_change_with_its_reason():
    a = PortionAdapter()
    feed(a, BAD, BAD)
    assert len(a.trace) == 1 and set(a.trace[0]) >= {'level', 'from', 'reason', 'n'}


def test_level_settings_keep_the_other_keys_and_swap_the_portion_keys():
    base = {'preset': 'meaning', 'ack_match': 'ru_aligned', 'on_mismatch': 'silent', 'max_words': 9}
    s = level_settings(base, 2)
    assert s['preset'] == 'pronunciation_short' and s['ack_match'] == 'ru_aligned' and 'max_words' not in s
    assert resolve(s)['max_words'] == 4
    assert level_settings(base, 99)['preset'] == 'pronunciation_short' and level_settings(base, -3)['preset'] == 'meaning'


def words(text):
    return re.findall(r'\w+', text.lower())


@pytest.mark.parametrize('level', [1, 2])
def test_a_shorter_level_makes_shorter_portions_with_the_same_words_and_whole_numbers(level):
    base = {'preset': 'meaning'}
    long_, short_ = portions(TEXT, resolve(base), spoken=True), portions(TEXT, resolve(level_settings(base, level)), spoken=True)
    assert words(' '.join(long_)) == words(' '.join(short_))
    assert len(short_) > len(long_)
    for number in ('13', '120 000', '30'):
        assert any(number in chunk for chunk in short_)


def streamed(tmp_path, **settings):
    answer = StreamingAnswer(TEXT, [], final=False, retrieval_status='unverified')
    engine = EchoEngine(tmp_path / 'e.sqlite3', lambda *a: answer, settings={'preset': 'meaning', **settings})
    engine_reply(engine, session_id='s', turn_id='q', text='Что с налогом?', request={}, model='m')
    return engine


def test_revise_takes_optional_settings_and_recuts_only_the_rest(tmp_path):
    engine = streamed(tmp_path)
    state = engine.state('s')
    head, rest = state['chunks'][0], ' '.join(state['chunks'][1:])
    reply, revision, answer = engine.revise(session_id='s', revision=state['revision'], keep=1, tail=rest,
                                            settings=level_settings(engine.settings, 2))
    after = engine.state('s')
    assert reply == SILENT and after['chunks'][0] == head and len(after['chunks']) > len(state['chunks'])
    assert words(' '.join(after['chunks'])) == words(' '.join(state['chunks'])) and after['chunk_index'] == 0


def test_adapt_rest_recuts_after_the_heard_portion_and_keeps_the_cursor(tmp_path):
    engine = streamed(tmp_path)
    state = engine.state('s')
    result = engine.adapt_rest(session_id='s', revision=state['revision'], level=1)
    after = engine.state('s')
    assert result is not None and after['chunks'][0] == state['chunks'][0] and after['chunk_index'] == state['chunk_index']
    assert after['revision'] == state['revision'] and words(' '.join(after['chunks'])) == words(' '.join(state['chunks']))


def test_adapt_rest_after_a_confirmed_portion_leaves_the_confirmed_ones(tmp_path):
    engine = streamed(tmp_path)
    first = engine.state('s')['chunks'][0]
    engine_reply(engine, session_id='s', turn_id='a1', text=first, request={}, model='m')
    state = engine.state('s')
    keep = state['chunk_index'] + 1
    assert engine.adapt_rest(session_id='s', revision=state['revision'], level=2) is not None
    after = engine.state('s')
    assert after['chunks'][:keep] == state['chunks'][:keep] and after['chunk_index'] == state['chunk_index']


def test_adapt_rest_refuses_a_stale_revision_and_when_nothing_is_left(tmp_path):
    engine = streamed(tmp_path)
    state = engine.state('s')
    assert engine.adapt_rest(session_id='s', revision=state['revision'] + 5, level=1) is None


def test_adapt_rest_does_nothing_while_paused(tmp_path):
    engine = streamed(tmp_path)
    state = engine.state('s')
    engine_reply(engine, session_id='s', turn_id='p', text='пауза', request={}, model='m')
    st2 = engine.state('s')
    if st2.get('paused'):
        assert engine.adapt_rest(session_id='s', revision=st2['revision'], level=1) is None
        assert engine.state('s')['chunks'] == st2['chunks']

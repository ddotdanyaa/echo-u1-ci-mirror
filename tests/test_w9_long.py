"""W9 long: what r08-r09-long did not do. Р065 an answer of 40+ portions, Р066 a whole article word for word, Р067 27 000 characters (answer and material),
Р068 four subjects in a row, Р069 compression of the history, Р070 two minutes of silence and a question, N149 an hour of long answers (memory, the file),
N150 three hours: tasks, timers, objects. The real controller, wire and engine on the world of helpers_s6_state (helpers_r08_long is the donor of r08-r09-long).
Logic and bounds only; no figure here is a measurement of the laptop or the phone."""
import asyncio
import gc
import json
import sqlite3
import time

import pytest

from echo_sync import materials
from echo_sync.engine import CHUNKED_ENTRIES, HISTORY_LIMIT, model_history, normalize
from echo_sync.portioner import portions
from helpers_r08_long import LongCall, drive, weight
from helpers_s6_state import TOPICS, Topic


@pytest.fixture
def call():
    d = LongCall()
    yield d
    d.close()


def spoken(d, mark=0):
    return [c.text for c in d.w.cues[mark:] if not c.diagnostic]


def say_all(d, limit=3000):
    """Confirm every portion the controller offers, to the end of the plan. Returns the number of portions."""
    n = 0
    while d.cue_ready() is not None:
        assert n < limit, 'the plan never ends'
        d.ack()
        n += 1
    return n


def whole_answer(d, topic, group=5):
    d.ask(topic)
    d.assistant_begin(group)
    while d.assistant_can_stream():
        d.assistant_delta()
    d.assistant_done()


def prose(chars, tag='x'):
    """Varied prose (numbers, names, abbreviations), not one sentence repeated, so that the portioner cuts it in many different places."""
    out, n = [], 0
    while sum(map(len, out)) < chars:
        t = TOPICS[n % len(TOPICS)]
        out.append(f'{t.answer} Пункт {n + 1} из раздела {tag}: в {1900 + n % 120} году выросло на {n % 17 + 3},5 %, примерно {n * 7 + 12} единиц.')
        n += 1
    return ' '.join(out)[:chars].rsplit('.', 1)[0] + '.'


def long_topic(key, chars):
    return Topic(key, f'Расскажи подробно про {key}?', prose(chars, key))


# --- Р065 / Р066 / Р067: a long answer comes out whole, in order, once -----------------------------------------------------------------

def test_p065_an_answer_of_forty_portions_is_spoken_in_order_without_loss(call):
    topic = Topic('forty', 'Расскажи подробно?', ' '.join(f'Подробность номер {i} о длинной теме, которая продолжает ответ ещё немного.' for i in range(40)))
    whole_answer(call, topic)
    n = say_all(call)
    cues = spoken(call)
    assert n >= 40 and len(cues) == n
    assert normalize(' '.join(cues)) == normalize(topic.answer), 'portions lost, doubled or reordered'
    snap = call.snap()
    assert snap['completed'] and snap['index'] == len(snap['chunks']) == n
    entry = call.w.state()['history'][-1]
    assert entry['status'] == 'complete' and entry['spoken'] == n


def test_p066_an_article_is_spoken_word_for_word_with_no_portion_cut_in_a_number(call):
    article = prose(6000, 'статья')
    whole_answer(call, Topic('article', 'Прочитай статью целиком?', article), group=7)
    say_all(call)
    cues = spoken(call)
    assert normalize(' '.join(cues)) == normalize(article)
    words = [w for c in cues for w in c.split()]
    assert len(words) == len(article.split())
    for cue in cues:                                    # «3,5 %» and «в 1990 году» are not cut in two
        assert not cue.rstrip().endswith(('3,', ',5')), cue
    assert not call.violations if hasattr(call, 'violations') else True


def test_p067_an_answer_of_27000_characters_is_spoken_whole_and_the_plan_is_cheap(call):
    topic = long_topic('27k', 27_000)
    assert 26_000 < len(topic.answer) <= 27_000
    started = time.perf_counter()
    whole_answer(call, topic, group=40)
    n = say_all(call, limit=20_000)
    assert normalize(' '.join(spoken(call))) == normalize(topic.answer)
    assert n > 200
    assert time.perf_counter() - started < 120, 'planning 27 000 characters is not linear'
    state = call.w.state()
    assert len(state['history']) == 1 and state['history'][-1]['status'] == 'complete'
    assert state['history'][-1]['spoken'] == n


def test_p067_the_portioner_alone_is_linear_on_27000_characters():
    text = prose(27_000, 'p')
    small, big = prose(3_000, 'p'), text
    t0 = time.perf_counter(); a = portions(small, {'portion_mode': 'meaning'}); t1 = time.perf_counter()
    b = portions(big, {'portion_mode': 'meaning'}); t2 = time.perf_counter()
    assert normalize(' '.join(b)) == normalize(big) and normalize(' '.join(a)) == normalize(small)
    assert (t2 - t1) < (t1 - t0) * 9 * 4 + 1, f'{t1 - t0:.2f} s for 3k, {t2 - t1:.2f} s for 27k: worse than linear'


def test_p067_a_material_of_27000_characters_is_read_back_whole_and_a_bigger_one_is_refused(tmp_path):
    src = tmp_path / 'm.txt'
    body = prose(27_000, 'm')
    src.write_text(body, encoding='utf-8')
    home = tmp_path / 'home'; home.mkdir()
    got = materials.import_materials([src], home)
    assert got['manifest']['sources'][0]['characters'] == len(body.strip())
    text = materials.read_material_context(got['path'])
    assert body.strip() in (text if isinstance(text, str) else str(text))
    huge = tmp_path / 'h.txt'
    huge.write_text('слово ' * (materials.MAX_CHARS // 5), encoding='utf-8')
    with pytest.raises(ValueError):
        materials.import_materials([huge], home)
    again = materials.read_material_context(got['path'])
    assert again == text, 'a refused import changed the published material'


# --- Р068: four subjects in a row --------------------------------------------------------------------------------------------------------

def test_p068_four_subjects_each_new_question_retires_the_old_answer_and_only_its_own_words_come(call):
    keys = [TOPICS[i] for i in (0, 3, 5, 8)]
    for n, topic in enumerate(keys):
        mark = len(call.w.cues)
        call.ask(topic)
        assert not spoken(call, mark), 'audio while a new question was accepted'
        call.assistant_begin(2)
        call.assistant_done()
        assert call.cue_ready() is not None
        call.ack()                                      # the first portion is heard, the rest is left in the air
        words = set(normalize(topic.answer).split())
        for cue in spoken(call, mark):
            assert set(normalize(cue).split()) <= words, f'a word of another subject in {cue!r}'
        call.idle(20)
    history = call.w.state()['history']
    assert [e['question'] for e in history[-4:]] == [t.question for t in keys]
    assert [e['status'] for e in history[-4:-1]] == ['interrupted'] * 3


def test_p068_back_to_the_first_subject_is_a_new_answer_from_its_own_text(call):
    for t in (TOPICS[0], TOPICS[3], TOPICS[5], TOPICS[8], TOPICS[0]):
        mark = len(call.w.cues)
        call.ask(t)
        call.assistant_begin(2)
        call.assistant_done()
        call.idle(10)
    say_all(call)
    got = normalize(' '.join(dict.fromkeys(spoken(call, mark))))        # the engine drops the words that only restate the question, and an unheard portion may be said again
    assert got in normalize(TOPICS[0].answer) and got.endswith(normalize(TOPICS[0].answer.split('. ')[-1]))


# --- Р069 / N149: the history of a long call ---------------------------------------------------------------------------------------------

def test_p069_old_entries_keep_the_question_and_the_answer_but_lose_their_portions(call):
    for n in range(12):
        t = TOPICS[n % len(TOPICS)]
        whole_answer(call, t)
        say_all(call) if n % 2 else None
        call.idle(30)
    history = call.w.state()['history']
    assert len(history) == 12
    old, new = history[:-CHUNKED_ENTRIES], history[-CHUNKED_ENTRIES:]
    assert old and all('chunks' not in e for e in old)
    assert all(e.get('chunks') for e in new)
    assert all(e['question'] and e['answer'] for e in history)
    context = model_history(history)
    assert all(not ({'chunks', 'spoken', 'status', 'at'} & set(e)) for e in context)


def test_p069_compression_never_loses_what_the_listener_did_not_hear(call):
    """The unsaid rest of an interrupted answer is what «вернёмся к теме» needs; after the compression the entry still says how much was heard."""
    whole_answer(call, TOPICS[4], group=2)
    call.ack()
    for n in range(CHUNKED_ENTRIES + 3):
        whole_answer(call, TOPICS[(n + 5) % len(TOPICS)])
        say_all(call)
    entry = call.w.state()['history'][0]
    assert entry['question'] == TOPICS[4].question and normalize(entry['answer']) in normalize(TOPICS[4].answer) and len(entry['answer']) > 40
    assert entry['status'] in ('interrupted', 'paused', 'revised'), entry['status']
    assert type(entry['spoken']) is int


def test_n149_an_hour_of_long_answers_keeps_the_file_and_the_state_bounded(call):
    sizes = []
    for n in range(40):
        whole_answer(call, long_topic(f'k{n}', 4_000), group=60)
        if n % 3 == 0:
            for _ in range(5):
                if call.cue_ready() is not None:
                    call.ack()
        call.idle(90)
        if n in (24, 39):
            sizes.append(call.sizes())
    early, late = sizes
    assert call.minutes() >= 60
    assert late['db_bytes'] < early['db_bytes'] * 2 + 50_000, (early['db_bytes'], late['db_bytes'])
    # w10 item 14: R09-2 (newer than this test, engine._bound) bounds the history by HISTORY_CHAR_BUDGET beside HISTORY_LIMIT: of 4000-char answers exactly
    # as many of the newest as the budget holds stay (at least two), never more than HISTORY_LIMIT
    from echo_sync.engine import HISTORY_CHAR_BUDGET, model_history
    import json
    history = [e for e in call.w.state()['history'] if isinstance(e, dict)]
    size = lambda rows: sum(len(json.dumps(model_history([e])[0], ensure_ascii=False)) for e in rows)
    assert late['state.history'] == len(history) == early['state.history'] and 2 <= len(history) <= HISTORY_LIMIT and late['state.chunked'] <= CHUNKED_ENTRIES
    assert size(history[:-1]) <= HISTORY_CHAR_BUDGET, 'the budget is kept when an entry is added; the newest answer still streams'
    for name in ('ledger', 'seen', 'cloud_acks', 'turn_done_at', 'activity_at', 'announced_at', 'foreign_turns'):
        assert late.get(name, 0) <= early.get(name, 0) + 64, name


# --- Р070: two minutes of silence and a question -------------------------------------------------------------------------------

@pytest.mark.parametrize('waiting', ['plan', 'nothing'])
def test_p070_two_minutes_of_silence_say_nothing_and_the_next_question_is_answered_from_its_own_text(call, waiting):
    if waiting == 'plan':
        whole_answer(call, TOPICS[1], group=2)
        call.ack()
    mark = len(call.w.cues)
    waiting_text = spoken(call)[-1:] 
    call.idle(120)
    by_itself = spoken(call, mark)
    cap = call.w.controller.max_auto_repeats
    assert len(by_itself) <= cap and set(by_itself) <= set(waiting_text), f'the call said something new by itself in two minutes: {by_itself}'
    topic = TOPICS[6]
    mark = len(call.w.cues)
    call.ask(topic)
    assert not spoken(call, mark)
    call.assistant_begin(2)
    call.assistant_done()
    say_all(call)
    assert normalize(' '.join(spoken(call, mark))) == normalize(topic.answer)


# --- N150: three hours, tasks, timers, objects ---------------------------------------------------------------------------------

def live_tasks(d):
    return [t for t in asyncio.all_tasks(d.w.loop) if not t.done()]


def test_n150_three_hours_leave_no_task_and_no_loop_error_behind():
    d = LongCall()
    try:
        before = len(live_tasks(d))
        did = drive(d, seed=1503, minutes=180)
        d.w.settle()
        assert d.minutes() >= 180 and did['question'] > 50
        assert not d.w.loop_errors, d.w.loop_errors[:3]
        assert len(live_tasks(d)) <= before + 3, [t.get_coro().__qualname__ for t in live_tasks(d)]
    finally:
        d.close()


def test_n150_nothing_grows_between_the_first_and_the_third_hour():
    d = LongCall()
    try:
        drive(d, seed=1504, minutes=90)                 # warm-up: the bounded tables fill to their caps
        gc.collect(); first = d.sizes(); objs1 = len(gc.get_objects())
        drive(d, seed=1505, minutes=90)
        d.w.settle(); gc.collect(); last = d.sizes(); objs2 = len(gc.get_objects())
        grown = {k: (first[k], last[k]) for k in first if k not in ('owners', 'blocked') and last.get(k, 0) > first[k] * 1.5 + 200}
        assert not grown, grown
        assert objs2 < objs1 * 1.8 + 50_000, (objs1, objs2)
    finally:
        d.close()


def test_n150_a_stopped_call_holds_no_timer_for_an_hour(call):
    whole_answer(call, TOPICS[2], group=2)
    call.ack()
    call.stop()
    tasks = len(live_tasks(call))
    mark = len(call.w.cues)
    call.idle(3600, step=5)
    call.w.settle()
    assert not spoken(call, mark)
    assert len(live_tasks(call)) <= tasks


# --- Р066 beyond the cap: an article longer than MAX_TURN_CHARS ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason='W9L-1: an answer over MAX_TURN_CHARS (60 000) is cut by the turn ledger, and the plan then stays «streaming» with the last portion never completed: no end, no marker, no error')
def test_p066_an_answer_over_the_turn_cap_ends_cleanly_not_in_a_stuck_stream(call):
    from echo_sync.controlled_media import MAX_TURN_CHARS
    article = prose(MAX_TURN_CHARS + 2_000, 'cap')
    whole_answer(call, Topic('cap', 'Прочитай всё?', article), group=300)
    say_all(call, limit=20_000)
    snap = call.snap()
    assert snap['completed'] and not snap['streaming'], f"stuck: index {snap['index']} of {len(snap['chunks'])}, streaming={snap['streaming']}"

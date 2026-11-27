"""R07 (stall and tail): «на одном слове замолчал, с того же слова и должно подсказываться».

A table of what a listener said of a portion of 3-9 words (the start, the middle, the start twice, a word wrong, a filler, another case, a number in words or in
digits, a word skipped, two swapped, more than the portion) and what must be cued; the production functions are called, nothing is stubbed but the clock and the
model (see ``helpers_r07_tail`` for the rows and for what a verdict is). Rows the production code gets wrong are ``xfail(strict=True)`` with the finding that fixes
them (``r07_known.KNOWN``, written by ``tools/r07_tail_table.py --report``; the findings and their patches are in ``cloud_context/reports/r07-tail.md``): when a
patch lands the strict xfail fails and the entry goes. Nothing here measures a latency, a phone or a model.
"""
import pytest

import helpers_r07_tail as T
import helpers_r07_tails as U
import helpers_s6_ack as H
from r07_known import KNOWN

CUE_ROWS = T.all_rows()
CONFIRM_ROWS = list(U.confirm_rows()) + list(U.confirm_hand_rows())
ALIGNED_ROWS = list(U.aligned_rows())


@pytest.fixture(scope='module')
def controller(tmp_path_factory):
    import logging
    level = logging.getLogger('echo-sync').level
    yield U.make_controller(tmp_path_factory.mktemp('r07'))
    logging.getLogger('echo-sync').setLevel(level)      # w3-integ: the table quiets the controller for itself only; left at ERROR it silenced the WARNING the diagnostics tests after it read


def marked(row_id, *args):
    code = KNOWN.get(row_id)
    marks = [pytest.mark.xfail(strict=True, reason=f'{code}: cloud_context/reports/r07-tail.md')] if code else []
    return pytest.param(*args, id=row_id, marks=marks)


def test_the_table_has_hundreds_of_rows():
    assert len(CUE_ROWS) >= 900 and len(CONFIRM_ROWS) >= 250 and len(ALIGNED_ROWS) >= 35
    cats = {row.cat for row in CUE_ROWS}
    for wanted in ('start', 'middle', 'repeat', 'error-word', 'error-mangled', 'cut', 'filler-lead', 'filler-mid', 'filler-trail', 'case', 'number', 'skip', 'swap', 'more',
                   'negation', 'spelling', 'connector'):
        assert wanted in cats, wanted
    assert all(3 <= len(p.split()) <= 9 for p in T.PORTIONS.values()), 'portions are 3-9 words'


def test_every_known_failure_names_a_row_of_the_table():
    ids = {f'{row.id}@{route}' for row in CUE_ROWS for route in U.ROUTES} | {row.id for row in CONFIRM_ROWS} | {row.id for row in ALIGNED_ROWS}
    assert not set(KNOWN) - ids, sorted(set(KNOWN) - ids)[:5]


@pytest.mark.parametrize('row,route', [marked(f'{row.id}@{route}', row, route) for row in CUE_ROWS for route in U.ROUTES])
def test_what_is_cued_after_what_the_listener_said(controller, row, route):
    result, cue = U.cue_verdict(controller, row, route)
    assert result == 'OK', f'{route}: said {row.said!r} of {row.portion!r}: cued {cue!r}, due {row.expect!r} {row.also} ({result}); {row.note}'


@pytest.mark.parametrize('row', [marked(row.id, row) for row in CONFIRM_ROWS])
def test_a_repeat_of_the_cued_tail_confirms_the_portion_and_nothing_else_does(controller, row):
    assert U.is_confirmed(controller, row) is row.confirmed, f'tail {row.tail!r} was cued; said {row.said!r}; {row.note}'


@pytest.mark.parametrize('row', [marked(row.id, row) for row in ALIGNED_ROWS])
def test_a_repeat_that_goes_on_is_split_where_the_repeat_ends(controller, row):
    assert U.head_of(controller, row) == row.head, f'said {row.said!r} of {row.portion!r}; {row.note}'


# ---- the silence timer, end to end: a real controller, a real plan, the clock injected ------------------------------------------------------

def start(tmp_path, name):
    first, rest = U.ANSWERS[name]
    d = H.Dictation(tmp_path / name, first + rest, play_first=True)
    assert d.chunks[0] == first, d.chunks
    return d


def wait_cue(d, within=15.0, step=0.25):
    """Silence until the controller speaks on its own; the texts it said (the cue is played: it can be heard back and a tail confirmed), or None."""
    c, spent = d.controller, 0.0
    while spent < within:
        d.clock.advance(step)
        spent += step
        actions = c.tick(now=d.clock())
        spoken = [a for a in actions if a['type'] == 'speak']
        if spoken:
            for a in spoken:
                c.cue_started(a, voiced_seconds=1.0)
            d.play(actions, seconds=1.0)
            return [a['text'] for a in spoken]
    return None


def tail_of(d, k):
    return T.tail(d.chunks[0], k)


@pytest.mark.parametrize('name,k', [('inertia', 1), ('inertia', 2), ('inertia', 4), ('inertia', 5), ('article', 1), ('article', 3), ('budget', 3), ('budget', 5), ('road', 2)])
def test_silence_after_a_start_cues_the_rest(tmp_path, name, k):
    d = start(tmp_path, name)
    d.say(T.cloud(d.chunks[0], k), gap=0.5)
    assert wait_cue(d) == [tail_of(d, k)]


@pytest.mark.parametrize('name,said,k', [
    pytest.param('inertia', 'свойство тела э-э', 2, id='hesitation-after'),
    pytest.param('inertia', 'свойство ну тела', 2, id='filler-between'),
    pytest.param('article', 'статья семнадцать', 2, id='number-in-words'),
    pytest.param('budget', 'бюджет проекта составляет 5 миллионов', 5, id='digit-for-a-word'),
])
def test_what_the_finals_say_is_read_as_the_ear_reads_it(tmp_path, name, said, k):
    """The silence timer reads the cloud's finals (``heard_since_portion`` -> ``_said_of``), the production path while ``prompt_tempo`` is off."""
    d = start(tmp_path, name)
    d.say(said, gap=0.5)
    assert wait_cue(d) == [tail_of(d, k)]


def test_a_start_cut_into_two_finals_is_one_start(tmp_path):
    """«свойство» | «тела»: the cloud cuts one breath into two finals; the newest alone is no start, the older one is not the whole of it."""
    d = start(tmp_path, 'inertia')
    d.say('свойство', gap=0.5)
    d.say('тела', gap=0.3)
    assert wait_cue(d) == [tail_of(d, 2)]


def test_a_second_stall_inside_the_cued_tail_cues_what_is_left_of_the_tail(tmp_path):
    d = start(tmp_path, 'inertia')
    d.say('свойство тела', gap=0.5)
    assert wait_cue(d) == [tail_of(d, 2)]
    d.say('сопротивляться', gap=0.5)
    assert wait_cue(d) == [tail_of(d, 3)]


def test_a_wrong_word_is_never_cued_past(tmp_path):
    d = start(tmp_path, 'inertia')
    d.say('свойство тела собака', gap=0.5)
    (cue,) = wait_cue(d)
    assert cue in (d.chunks[0], tail_of(d, 2)), cue


def test_a_wrong_number_is_never_cued_past(tmp_path):
    d = start(tmp_path, 'article')
    d.say('статья восемнадцать', gap=0.5)
    (cue,) = wait_cue(d)
    assert cue in (d.chunks[0], tail_of(d, 1)), cue        # c23-final: the portion from «17» (G15 made the portion the whole sentence: helpers_r07_tails.ANSWERS)


def test_nothing_said_cues_the_whole_portion(tmp_path):
    d = start(tmp_path, 'inertia')
    assert wait_cue(d, within=30.0) == [d.chunks[0]]


@pytest.mark.parametrize('said', ['сопротивляться изменению своего движения', 'свойство тела сопротивляться изменению своего движения'], ids=['the-tail', 'the-whole'])
def test_a_repeat_of_the_tail_or_of_the_whole_moves_the_cursor_exactly_once(tmp_path, said):
    d = start(tmp_path, 'inertia')
    d.say('свойство тела', gap=0.5)
    assert wait_cue(d) == [tail_of(d, 2)]
    outcome = d.say(said, gap=0.5)
    assert (outcome.before, outcome.after, outcome.speaks) == (0, 1, [d.chunks[1]])
    assert d.index == 1


def test_the_silence_after_the_tail_is_bounded(tmp_path):
    d = start(tmp_path, 'inertia')
    d.say('свойство тела', gap=0.5)
    spoken = []
    for _ in range(8):
        cue = wait_cue(d, within=30.0)
        if cue is None:
            break
        spoken.append(cue[0])
    assert 1 <= len(spoken) <= 1 + d.controller.max_auto_repeats, spoken
    assert spoken[0] == tail_of(d, 2) and d.index == 0


def test_resuming_a_word_early_confirms_the_portion(tmp_path):
    """After the cue of the tail the listener goes back one word («тела сопротивляться…»): they have said the whole portion between the two breaths."""
    d = start(tmp_path, 'inertia')
    d.say('свойство тела', gap=0.5)
    assert wait_cue(d) == [tail_of(d, 2)]
    outcome = d.say('тела сопротивляться изменению своего движения', gap=0.5)
    assert (outcome.before, outcome.after) == (0, 1)


def test_the_tail_repeated_and_the_next_words_after_it_move_the_cursor_once(tmp_path):
    d = start(tmp_path, 'inertia')
    d.say('свойство тела', gap=0.5)
    assert wait_cue(d) == [tail_of(d, 2)]
    outcome = d.say('сопротивляться изменению своего движения это называется инерцией', gap=0.5)
    assert outcome.after == 1 and d.chunks[0] not in outcome.speaks

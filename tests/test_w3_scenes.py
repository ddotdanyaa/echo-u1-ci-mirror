"""w3-scenes: four situations of the owner's list, each on the real ControlledMedia through the rig of ``w3_scenes_rig`` (the stand of tools/replay).

A red test here is a finding: ``xfail(strict=True)`` with the reason, the first cause and the patch in cloud_context/reports/w3-scenes.md. Nothing here is a measurement of time on a laptop
or a phone: the clock is the stand's.
"""
import json
import logging
import re
from pathlib import Path

import pytest

import w3_scenes_rig as R
from echo_sync.textutil import normalize



@pytest.fixture(scope='module', autouse=True)
def quiet_logs():
    was = logging.root.manager.disable            # module-level logging.disable leaked into the whole suite and silenced assertLogs tests collected after it
    logging.disable(logging.WARNING)
    yield
    logging.disable(was)


Q1 = Q2 = Q3 = None
BILL = ('Что такое двойная запись в бухучёте?', 'Каждая операция записывается дважды. По дебету одного счёта и по кредиту другого. Так сумма не теряется.')
RATE = ('Сколько будет семь умножить на восемь?', 'Пятьдесят шесть. Это семь раз по восемь. Проверьте по таблице.')
YEAR = ('В каком году крестили Русь?', 'В девятьсот восемьдесят восьмом году. Крестил князь Владимир. Это было в Киеве.')
CHATTER = ('Слушай, ты вчера видел, что в столовой опять только гречка и котлеты.', 'Да я бы заказал обед в офис, но Лена на диете, а Паша носит еду из дома.',
           'Ну ладно, потом решим, а ты в отпуск когда собираешься, летом или как всегда в ноябре.', 'Мы с женой хотим на юг, к морю, пока вода ещё тёплая.',
           'Принтер на третьем этаже опять завис, я полчаса стоял и ждал одну страницу.')


@pytest.fixture
def rig():
    r = R.Rig()
    yield r
    r.close()


def ask(rig, pair, *, at=None):
    text, answer = pair
    return rig.utter(text, 'question', ('q', R.Ref(text, answer)), at=at)


def quiet_until_idle(rig, limit=40.0):
    rig.run_until(rig.idle, limit)


def test_ten_to_twenty_seconds_of_others_talking_without_a_question_then_a_real_question(rig):
    """Silence while the others talk (no cue in 10-20 s, no job asked to answer), then the answer to the question, begun after the question ended."""
    for text in CHATTER:
        rig.utter(text, 'chatter')
        rig.run_to(rig.free + 1.0)
    talked = rig.now()
    assert 10 <= talked <= 30, talked
    assert not rig.cues(), f'the controller sounded something over talk with no question: {[c.text for c in rig.cues()]}'
    asked = ask(rig, BILL)
    rig.run_until(lambda: bool(rig.cues(asked.onset)), 20.0)
    cues = rig.cues(talked)
    assert cues, 'a real question after the talk got no answer'
    assert cues[0].t - rig.zero >= asked.offset - 0.01, 'the answer began before the question ended'
    assert normalize(cues[0].text) in normalize(' '.join(rig.snapshot()['chunks'])), cues[0].text
    assert 'двойн' in normalize(rig.snapshot()['question'] or '') or 'двойн' in normalize(rig.w.controller.state()['question'])


@pytest.mark.parametrize('late', [(0.4, 1.0), (3.0, 4.0)], ids=['quick model', 'model 3-4 s to the first word'])
def test_three_questions_in_twenty_seconds_the_last_one_is_answered(late):
    """Three questions, 7 s apart; the answer sounding after the third question is the third's, and nothing of the first two begins once the third was known."""
    rig = R.Rig(job=late)
    try:
        said = [ask(rig, pair, at=at) for pair, at in ((BILL, 1.0), (RATE, 8.0), (YEAR, 15.0))]
        rig.run_to(said[-1].offset + 30.0)
        known = said[-1].final_at if said[-1].final_at is not None else said[-1].ear_at
        assert known is not None and known - said[0].onset < 25
        state = rig.snapshot()
        assert normalize(state['question'] or '').startswith('в каком году'), state['question']
        after = [c for c in rig.cues() if c.t - rig.zero > known + 0.21]
        assert after, 'nothing sounded after the third question'
        mine = [normalize(x) for x in re.split(r'(?<=[.!?])\s+', YEAR[1])]
        for cue in after:
            assert any(normalize(cue.text) in x or x in normalize(cue.text) for x in mine), f'a cue that is not of the last answer, after it was asked: {cue.text!r} at {cue.t - rig.zero:.1f}'
        assert state['chunks'] and 'восемьдесят' in normalize(' '.join(state['chunks']))
    finally:
        rig.close()


def test_a_stranger_says_repeat_the_current_portion_sounds_again_and_the_cursor_stays(rig):
    """«Повторите» from anyone (the text has no voice): the portion at the cursor sounds again, the cursor does not move, the plan is the same."""
    ask(rig, BILL)
    rig.run_until(lambda: bool(rig.cues()), 20.0)
    rig.settle(4.0)
    before = rig.snapshot()
    heard = [c for c in rig.cues()]
    current = heard[-1].text
    mark = rig.now()
    rig.mind.learn('повторите', ('cmd', 'again'))
    rig.utter('Повторите.', 'again', ('cmd', 'again'))
    rig.run_to(rig.free + 12.0)
    rig.settle(2.0)
    after = rig.snapshot()
    new = rig.cues(mark)
    assert new, 'nothing sounded after «повторите»'
    assert {normalize(c.text) for c in new} == {normalize(current)}, f'not the current portion {current!r}: {[c.text for c in new]}'
    assert (after['revision'], after['index']) == (before['revision'], before['index']), (before, after)
    assert after['chunks'] == before['chunks']


@pytest.mark.parametrize('after_cue', [0.8, 0.9, 1.0], ids=lambda x: f'{x} s after the cue')
def test_a_stammer_that_fell_into_the_closed_microphone_loses_nothing(after_cue, rig):
    """The listener is stuck on the head of the portion («Это свойство, это свойство, ну») 0.8-1.0 s after the cue began, while the phone's microphone is still closed under it.
    Nothing is lost: the plan and the cursor are the same, no failure phrase sounds, and the help that follows is the portion from the stuck word."""
    ask(rig, BILL)
    rig.run_until(lambda: bool(rig.cues()), 20.0)
    cue = rig.cues()[-1]
    current = cue.text
    before = rig.snapshot()
    mark = rig.now()
    said = R.sc.repeat_text(current, 'stammer')
    spoken = rig.utter(said, 'partial', None, at=cue.t - rig.zero + after_cue, lossy=True)
    assert spoken is not None
    assert (spoken.text != said) == (cue.t - rig.zero + after_cue < rig.closed_until()), 'the rig must cut the head that fell into the closed microphone, and only that'
    rig.run_to(rig.free + 15.0)
    rig.settle(2.0)
    after = rig.snapshot()
    assert after['revision'] == before['revision'] and after['chunks'][:len(before['chunks'])] == before['chunks'], 'the plan changed under a stammer (it may only grow: it was still being written)'
    assert after['index'] == before['index'], f'the cursor moved: {before["index"]} -> {after["index"]}'
    assert not [c for c in rig.w.cues if c.diagnostic and c.t - rig.zero > mark], 'a failure phrase sounded'
    help_ = rig.cues(mark)
    assert help_, 'no help followed the stammer'
    words, stuck = normalize(current).split(), len(normalize(said.split(',')[0]).split())          # the head the listener got stuck on: the first `stuck` words
    for c in help_:
        have = normalize(c.text).split()
        starts = [k for k in range(len(words) - len(have) + 1) if words[k:k + len(have)] == have]
        assert starts, f'the help {c.text!r} is not a piece of the portion {current!r}'
        assert starts[0] <= stuck, f'the help {c.text!r} begins at word {starts[0]}, after the word {stuck - 1} the listener stopped on: a word they did not say is taken as said'


# =====================================================================================================================================
# the scenes of scenarios_n1.json / scenarios_n2.json, every step, through the real controller
# =====================================================================================================================================

KNOWN = json.loads(Path(__file__).with_name('w3_scenes_known.json').read_text(encoding='utf-8'))        # scene -> step -> checks the controller does not meet (cloud_context/reports/w3-scenes.md)
SCENES = R.load()
_ROWS = {}


def rows_of(scene_id):
    if scene_id not in _ROWS:
        name, scene = next(item for item in SCENES if item[1]['id'] == scene_id)
        _ROWS[scene_id] = R.run_scene(name, scene)
    return _ROWS[scene_id]


def row_of(scene_id, n):
    return next(row for row in rows_of(scene_id) if row.n == n)


@pytest.mark.parametrize('scene_id', [scene['id'] for _, scene in SCENES])
def test_every_step_of_the_scene_is_as_the_table_of_known_mismatches_says(scene_id):
    """A step that the controller does not meet is in tests/w3_scenes_known.json (and has its cause in the report); a new mismatch fails here, and so does a known one that was cured
    (take it out of the table then).
    Cured by the said-again locks (``_says_again`` / ``_said_already`` / ``_said_back``: a dispute, a re-ask, a recount that the job answered with the answer in play is answered, not dropped): n2_d06 10, n2_d15 12,
    n2_c05 10 and 12, n2_c06 10 and 12 are out of the table. n1_h1_physics_exam_holdout 7, 9 (the second a cascade of the first): the repeat of «Равноускоренное движение - …» whose head word was lost under the closed microphone goes on as a try once the listener stops (the
    c20 rule: most of the portion said is a try that goes on, ``_try_went``, a_try_counts); the scene expects no advance for it. The rule is the owner's, the scene's step stays as the corpus has it."""
    actual = {str(row.n): sorted({f[0] for f in row.product}) for row in rows_of(scene_id) if row.verdict == 'product'}
    assert actual == KNOWN.get(scene_id, {})


def test_the_scenes_are_all_there_and_none_was_dropped():
    """900 steps in 46 scenes (16 + 30); every step has a verdict; a step the stand cannot judge is named, not counted as met."""
    steps = sum(len(scene['steps']) for _, scene in SCENES)
    assert (len(SCENES), steps) == (46, 900)
    for scene_id in (scene['id'] for _, scene in SCENES[:2]):
        assert {row.verdict for row in rows_of(scene_id)} <= {'match', 'product', 'ref', 'na', 'unknown', 'cascade'}


# -- the causes found, each as the behaviour the scene asks for (red now: xfail(strict=True), the patch is in the report) ----------------------------------------------------------

def test_a_number_cut_by_a_pause_in_a_repeat_advances_once():
    row = row_of('n1_01_exam_accounting', 17)
    assert row.verdict == 'match', row.failures


@pytest.mark.xfail(strict=True, reason='w3-scenes P2: a stammer on the only word of the only portion («Канб, канб, ну» for «Канберра.») is read as unrelated speech, never as a try; '
                                       'the portion is abandoned after 7 s (portion_abandoned tried=False) and the answer is closed with nothing left')
def test_a_stammer_on_the_only_portion_keeps_the_plan():
    row = row_of('n1_h2_geography_defence_holdout', 2)
    assert row.verdict == 'match', row.failures


def test_a_repeat_with_a_new_question_in_the_tail_answers_the_question():
    row = row_of('n1_03_tax_consultation', 6)
    assert row.verdict == 'match', row.failures


@pytest.mark.xfail(strict=True, reason='w3-scenes P4: «продолжайте» after a stop at the second portion restores the answer from its first portion (engine.py plan "restore": '
                                       'unfinished_answer_restored, index 0), not from the cursor')
def test_a_return_after_a_stop_goes_on_from_the_cursor():
    row = row_of('n2_d11_history_exam', 16)
    assert row.verdict == 'match', row.failures


def test_a_question_in_parts_is_not_answered_by_the_old_portion_in_its_pauses():
    """w3-scenes P5, cured by g17-go-on: a part of the question the ear heard said words of the waiting portion and was taken for a try at it, and the old answer went on in the pauses."""
    row = row_of('n2_d10_finance_startup', 9)
    assert row.verdict == 'match', row.failures


def test_a_question_with_conditions_in_three_parts_gets_its_answer():      # fix5 cured w3-scenes P6: one anchor (the end of the speech) and a drop of an older part no longer takes the newer part's job
    row = row_of('n2_d10_finance_startup', 2)
    assert row.verdict == 'match', row.failures

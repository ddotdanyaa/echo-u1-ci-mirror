"""The universal scenario: ONE call of about four minutes (the stand's clock) through the REAL ControlledMedia, on the rig of w3_scenes_rig (tools/replay stand), that passes 16 independent decisions
in a row. Each step carries the label ``family/owner`` of the decision it exercises (the families and owners of tools/owner_census_owners.json): a red step names the family at once.

    talk -> question from the base -> pause (the timer) -> a correct repeat -> a stranger's «повторите» -> stop -> the presentation told aloud -> «продолжай» -> a question that needs a search, asked over the
    answer that sounds -> the question changed -> mumbling -> a question in parts -> a source that fails -> the question after it -> a question about what was said -> the call is whole.

REAL: ControlledMedia, NativeMediaSocket, the ear and the fast channel (as in w3_scenes_rig). SCRIPTED: the text model (it returns the reference answer of each step), the cloud's user turns, the detector.
The stand tells a base answer from a search or an internet one only by the question and its reference answer (the model is one scripted mind): a step labelled route/answer checks that the answer of THAT
question arrives and the old one stops, not which road brought it. Nothing here measures time on a laptop or a phone. The data is made up. The mechanisms of classes/catalog.json under each step are in STEP_CATALOG (>= 12 classes of the catalog). Run: ``bash lt.sh <worktree> tests/test_universal_scenario.py``.
"""
import json
import logging
from pathlib import Path

import pytest

import w3_scenes_rig as R
from echo_sync.textutil import normalize
from tools.replay import stand as T

OWNERS = json.loads((Path(__file__).resolve().parents[1] / 'tools' / 'owner_census_owners.json').read_text(encoding='utf-8'))

BASE = ('Что такое двойная запись в бухучёте?', 'Каждая операция записывается дважды. По дебету одного счёта и по кредиту другого. Так сумма не теряется.')
LOOKUP = ('Какой сегодня курс евро к рублю?', 'Сегодня евро стоит около девяноста рублей. Это данные из поиска. Курс меняется в течение дня.')
FIXED = ('Нет, подскажи, какая столица Австралии?', 'Канберра. Это не Сидней. Столицей она стала в тысяча девятьсот тринадцатом году.')
PARTS = (('Подскажи, в каком году крестили Русь,', 'и кто это сделал.'), 'В девятьсот восемьдесят восьмом году. Крестил князь Владимир. Это было в Киеве.')
AFTER_FAIL = ('Сколько будет семь умножить на восемь?', 'Пятьдесят шесть. Это семь раз по восемь. Проверьте по таблице.')
MEMORY = ('А что я говорил про двойную запись?', 'Вы говорили, что каждая операция записывается дважды. По дебету и по кредиту. Это про двойную запись.')
TALK = ('Слушай, ты вчера видел, что в столовой опять только гречка и котлеты.', 'Да я бы заказал обед в офис, но Лена на диете, а Паша носит еду из дома.')
SLIDES = ('Итак, на втором слайде у нас динамика выручки по кварталам, она растёт уже три квартала подряд.',
          'На третьем слайде показана структура расходов, и самая большая доля приходится на закупку материалов.',
          'Теперь переходим к четвёртому слайду, там планы на следующий год и основные риски проекта.')
MUMBLE = ('Э-э-э.', 'Хм.', 'Ну-у.')

STEPS = []                                                  # (label, function): the order is the scenario


def step(label):
    family, owner = label.split('/')
    assert owner in OWNERS[family], f'{label}: no such owner in tools/owner_census_owners.json'
    def mark(fn):
        STEPS.append((label, fn))
        return fn
    return mark


class Ctx:
    """What the steps share: the rig, the cues each step heard, the plan the cursor stood in."""

    def __init__(self):
        self.rig = Rig()
        self.keep = {}


class Rig(R.Rig):
    """The rig, and a model that can be told to fail the next job (a source that refuses)."""
    fail_next = False

    def _born(self, job, thread):
        if not self.fail_next:
            return super()._born(job, thread)
        self.fail_next = False
        run = T.Run(job, thread, self.now())
        self.runs[id(job.request)] = run
        self.out.jobs.append({'at': round(self.now(), 2), 'answer': None, 'fail': True})
        self.later(self.now() + 0.6, lambda: run.end(True), call=None)


def ask(rig, pair, *, at=None):
    text, answer = pair
    return rig.utter(text, 'question', ('q', R.Ref(text, answer)), at=at)


def answered(rig, said, limit=25.0):
    rig.run_until(lambda: bool(rig.cues(said.onset)), limit)
    return rig.cues(said.onset)


def check(name, held, message):
    return (name, bool(held), message)


def own(rig, text):
    return normalize(text) in normalize(' '.join(rig.snapshot()['chunks']))


# =====================================================================================================================================
# the steps
# =====================================================================================================================================

@step('kind/classifier')
def talk_without_a_question(c):
    """Others talk 8-10 s, nobody asks: no sound (the model may be asked and say «—»: that is its decline, not a defect)."""
    rig = c.rig
    for text in TALK:
        rig.utter(text, 'chatter')
        rig.run_to(rig.free + 1.0)
    return [check('silence', not rig.cues(), f'sound over talk: {[x.text for x in rig.cues()]}')]


@step('question/cm-open')
def question_from_the_base(c):
    rig = c.rig
    said = ask(rig, BASE)
    cues = answered(rig, said)
    rig.settle(1.0)
    s = rig.snapshot()
    c.keep['base'] = s
    return [check('answers', cues, 'no answer'), check('after_the_question', cues and cues[0].t - rig.zero >= said.offset - 0.01, 'began before the question ended'),
            check('of_this_question', cues and own(rig, cues[0].text), 'the first sound is not of the plan'), check('about_it', 'двойн' in normalize(s['question'] or ''), s['question'])]


@step('timers/cm-tick')
def pause_the_timer_repeats_only_the_waiting_portion(c):
    rig = c.rig
    s0, mark = rig.snapshot(), rig.now()
    rig.run_for(14.0)
    waiting = normalize(s0['chunks'][s0['index']]) if s0['chunks'] and s0['index'] is not None and s0['index'] < len(s0['chunks']) else None
    other = [x.text for x in rig.cues(mark) if normalize(x.text) != waiting]
    s1 = rig.snapshot()
    return [check('only_the_waiting_portion', not other, f'another text sounded in the pause: {other[:2]}'), check('cursor_stays', (s1['revision'], s1['index']) == (s0['revision'], s0['index']), f'{s0["index"]} -> {s1["index"]}')]


@step('portion/engine-cursor')
def a_correct_repeat_moves_the_cursor_once(c):
    rig = c.rig
    s0, mark = rig.snapshot(), rig.now()
    current = rig.cues()[-1].text
    said = R.sc.repeat_text(current, 'full')
    u = rig.utter(said, 'repeat')
    u.cue = (current, s0['revision'], s0['index'])
    rig.run_to(u.offset + 8.0)
    rig.settle(2.0)
    s1 = rig.snapshot()
    moved = R.Scene.advance(s0, s1)
    return [check('advance_by_one', moved == 1, f'the cursor moved {moved} ({s0["index"]} -> {s1["index"]})'), check('same_plan', s1['revision'] == s0['revision'], 'a new answer took the plan'),
            check('no_failure_phrase', not [x for x in rig.w.cues if x.diagnostic and x.t - rig.zero > mark], 'a failure phrase sounded')]


@step('kind/classifier')
def a_stranger_says_repeat(c):
    rig = c.rig
    rig.settle(1.0)
    s0, mark = rig.snapshot(), rig.now()
    waiting = normalize(s0['chunks'][s0['index']]) if s0['chunks'] and s0['index'] is not None and s0['index'] < len(s0['chunks']) else None
    rig.mind.learn('повторите', ('cmd', 'again'))
    rig.utter('Повторите.', 'again', ('cmd', 'again'))
    rig.run_to(rig.free + 12.0)
    rig.settle(2.0)
    s1, new = rig.snapshot(), rig.cues(mark)
    return [check('sounds_again', new, 'nothing after «повторите»'), check('the_waiting_portion', all(normalize(x.text) == waiting for x in new), f'{[x.text for x in new][:2]} is not {waiting!r}'),
            check('cursor_stays', (s1['revision'], s1['index']) == (s0['revision'], s0['index']), f'{s0["index"]} -> {s1["index"]}')]


@step('speech/cm-speech')
def stop_is_silence(c):
    rig = c.rig
    c.keep['before_stop'] = rig.snapshot()
    rig.mind.learn('стоп', ('cmd', 'stop'))
    rig.utter('Стоп.', 'stop', ('cmd', 'stop'))
    rig.run_to(rig.free + 1.0)
    mark = rig.now()
    rig.run_for(9.0)
    return [check('silent_after_stop', not rig.cues(mark), f'sound after stop: {[x.text for x in rig.cues(mark)][:2]}')]


@step('kind/classifier')
def the_presentation_told_aloud_is_not_a_question(c):
    rig, mark = c.rig, c.rig.now()
    jobs = len(rig.out.jobs)
    for text in SLIDES:
        rig.utter(text, 'chatter', seconds=7.0)
        rig.run_to(rig.free + 1.5)
    rig.run_for(5.0)
    return [check('silence', not rig.cues(mark), f'sound over the told presentation: {[x.text for x in rig.cues(mark)][:2]}')]


@step('portion/engine-cursor')
def go_on_returns_from_the_cursor(c):
    rig, mark = c.rig, c.rig.now()
    before = c.keep['before_stop']
    rig.mind.learn('продолжай', ('cmd', 'resume'))
    rig.utter('Продолжай.', 'resume', ('cmd', 'resume'))
    rig.run_to(rig.free + 12.0)
    new = rig.cues(mark)
    want = normalize(before['chunks'][before['index']]) if before['chunks'] and before['index'] < len(before['chunks']) else None
    return [check('sounds', new, 'nothing after «продолжай»'), check('from_the_cursor', new and normalize(new[0].text) == want, f'{new[0].text if new else None!r} is not the portion at the cursor {want!r}')]


@step('answer/cm-route')
def a_question_that_needs_a_search_over_the_answer_that_sounds(c):
    rig = c.rig
    rig.settle(2.0)
    cue = rig.cues()[-1]
    said = ask(rig, LOOKUP, at=cue.t - rig.zero + 0.5)
    cues = answered(rig, said, 30.0)
    rig.settle(2.0)
    c.keep['lookup_end'] = said.offset
    state = rig.snapshot()
    after = [x for x in rig.cues() if x.t - rig.zero > said.offset + 0.3]
    mine = [normalize(x) for x in LOOKUP[1].replace('.', '.|').split('|') if x.strip()]
    return [check('answers', cues, 'no answer'), check('only_the_new_answer', after and all(any(normalize(x.text) in m or m in normalize(x.text) for m in mine) for x in after), f'after the question: {[x.text for x in after][:3]}'),
            check('the_plan_is_the_new_one', 'евро' in normalize(' '.join(state['chunks'])), state['chunks'][:1])]


@step('question/cm-overtaken')
def the_question_is_changed_the_last_one_wins(c):
    rig = c.rig
    rig.settle(2.0)
    first = ask(rig, ('Подскажи, какая столица Франции?', 'Париж. Это крупнейший город страны. Он стоит на реке Сене.'))
    second = ask(rig, FIXED, at=first.offset + 2.0)
    rig.run_to(second.offset + 30.0)
    state = rig.snapshot()
    after = [x for x in rig.cues() if x.t - rig.zero > second.offset + 0.3]
    return [check('last_plan', 'канберр' in normalize(' '.join(state['chunks'])), state['chunks'][:1]), check('nothing_of_the_first_after_the_second', after and all('париж' not in normalize(x.text) for x in after), [x.text for x in after][:3])]


@step('kind/classifier')
def mumbling_is_not_a_question(c):
    rig = c.rig
    rig.run_until(rig.idle, 40.0)
    rig.settle(3.0)
    mark, jobs = rig.now(), len(rig.out.jobs)
    for text in MUMBLE:
        rig.utter(text, 'chatter')
        rig.run_to(rig.free + 1.0)
    rig.run_for(6.0)
    new = rig.cues(mark)
    state = rig.snapshot()
    return [check('no_new_answer', len(rig.out.jobs) == jobs, 'a job was started for mumbling'), check('plan_kept', 'канберр' in normalize(' '.join(state['chunks'])), state['chunks'][:1]),
            check('no_new_plan', not [x for x in new if x.snap.get('revision') != state['revision']], 'a sound of another answer')]


@step('question/question-part')
def a_question_in_two_parts(c):
    rig = c.rig
    rig.settle(2.0)
    (head, tail), answer = PARTS
    rig.utter(head, 'chatter')
    rig.run_to(rig.free + 1.2)
    last = rig.utter(tail, 'question', ('q', R.Ref(head + ' ' + tail, answer)))
    cues = answered(rig, last, 30.0)
    rig.settle(2.0)
    state = rig.snapshot()
    return [check('answers', cues, 'no answer'), check('after_the_last_part', cues and cues[0].t - rig.zero >= last.offset - 0.01, 'began before the last part ended'),
            check('the_plan', 'восемьдесят' in normalize(' '.join(state['chunks'])), state['chunks'][:1])]


@step('route/cm-route')      # lookup-fallback was merged into cm-route (the lookup decision is cm-route's; the socket only carries it)
def a_source_that_fails_leaves_the_call_alive(c):
    rig = c.rig
    rig.run_until(rig.idle, 40.0)
    rig.settle(3.0)
    rig.fail_next = True
    mark = rig.now()
    said = ask(rig, ('Какая сегодня погода в Хабаровске?', 'Сегодня в Хабаровске ясно. Температура около десяти градусов. Ветер слабый.'))
    rig.run_to(said.offset + 20.0)
    heard = rig.cues(mark)
    return [check('no_loop_error', not rig.w.loop_errors, rig.w.loop_errors[:1]), check('not_the_old_answer', not [x for x in heard if 'девятьсот восемьдесят' in normalize(x.text)], [x.text for x in heard][:2]),
            check('said_something_or_left_a_state', bool(heard) or rig.snapshot()['question'] is not None, 'a refused source left neither a sound nor a state')]


@step('route/cm-route')
def the_next_question_is_answered_after_the_failure(c):
    rig = c.rig
    rig.run_until(rig.idle, 40.0)
    rig.settle(3.0)
    said = ask(rig, AFTER_FAIL)
    cues = answered(rig, said, 30.0)
    rig.settle(2.0)
    return [check('answers', cues, 'no answer after the failed source'), check('the_plan', 'пятьдесят' in normalize(' '.join(rig.snapshot()['chunks'])), rig.snapshot()['chunks'][:1])]


@step('memory/engine-history')
def a_question_about_what_was_said(c):
    rig = c.rig
    rig.run_until(rig.idle, 40.0)
    rig.settle(3.0)
    said = ask(rig, MEMORY)
    cues = answered(rig, said, 30.0)
    rig.settle(2.0)
    return [check('answers', cues, 'no answer'), check('the_plan', 'двойн' in normalize(' '.join(rig.snapshot()['chunks'])), rig.snapshot()['chunks'][:1])]


@step('modes/host-call-settings')
def the_call_is_whole_and_the_scenario_is_short(c):
    rig = c.rig
    return [check('wire', not rig.w.violations and not rig.w.loop_errors, f'{rig.w.violations[:1]} {rig.w.loop_errors[:1]}'),
            check('three_to_five_minutes', 120 <= rig.now() <= 300, f'the scenario ran {rig.now():.0f} s of the stand clock')]


# =====================================================================================================================================
# the classes: every step names the mechanisms of classes/catalog.json that its scene exercises
# =====================================================================================================================================

CATALOG = {c['id']: c for c in json.loads((Path(__file__).resolve().parents[1] / 'classes' / 'catalog.json').read_text(encoding='utf-8'))}
STEP_CATALOG = {                                            # step function -> ids of classes/catalog.json (the mechanism the scene stands on)
    'talk_without_a_question': ('M-029', 'M-024', 'M-020'),
    'question_from_the_base': ('M-178', 'M-050'),
    'pause_the_timer_repeats_only_the_waiting_portion': ('M-139', 'M-133'),
    'a_correct_repeat_moves_the_cursor_once': ('M-140', 'M-118'),
    'a_stranger_says_repeat': ('M-027', 'M-157'),
    'stop_is_silence': ('M-030', 'M-093'),
    'the_presentation_told_aloud_is_not_a_question': ('M-177', 'M-186'),
    'go_on_returns_from_the_cursor': ('M-129', 'M-110'),
    'a_question_that_needs_a_search_over_the_answer_that_sounds': ('M-107', 'M-324', 'M-321'),
    'the_question_is_changed_the_last_one_wins': ('M-050', 'M-107'),
    'mumbling_is_not_a_question': ('M-006', 'M-037'),
    'a_question_in_two_parts': ('M-043', 'M-053'),
    'a_source_that_fails_leaves_the_call_alive': ('M-089', 'M-079', 'M-319'),
    'the_next_question_is_answered_after_the_failure': ('M-079', 'M-244'),
    'a_question_about_what_was_said': ('M-156', 'M-155'),
    'the_call_is_whole_and_the_scenario_is_short': ('M-205', 'M-143'),
}
MIN_CLASSES = 12                                            # of the 16 letters of the catalog (L, N, O, P are about install, training, devices, security: not a scene of one call)


def test_every_step_stands_on_mechanisms_of_the_catalog():
    names = {fn.__name__ for _, fn in STEPS}
    assert names == set(STEP_CATALOG), (sorted(names - set(STEP_CATALOG)), sorted(set(STEP_CATALOG) - names))
    for name, ids in STEP_CATALOG.items():
        assert ids and all(i in CATALOG for i in ids), (name, [i for i in ids if i not in CATALOG])


def test_the_scenario_gathers_at_least_twelve_classes_of_the_catalog():
    classes = {CATALOG[i]['class_id'] for ids in STEP_CATALOG.values() for i in ids}
    assert len(classes) >= MIN_CLASSES, sorted(classes)


# =====================================================================================================================================
# the run: once, on one rig; one test per step
# =====================================================================================================================================

_RUN = {}


def played():
    if not _RUN:
        was = logging.root.manager.disable
        logging.disable(logging.WARNING)
        cap, root = R.Capture(), logging.getLogger()
        c = Ctx()
        try:
            for n, (label, fn) in enumerate(STEPS, 1):
                cap.lines = []
                root.addHandler(cap)
                root.setLevel(logging.INFO)
                logging.disable(logging.NOTSET)
                try:
                    results, error = fn(c), None
                except Exception as exc:                                          # a step that breaks is red on its own, the rest are judged on what is left
                    results, error = [], f'{type(exc).__name__}: {exc}'
                finally:
                    root.removeHandler(cap)
                    logging.disable(logging.WARNING)
                _RUN[n] = {'label': label, 'name': fn.__name__, 'results': results, 'error': error, 'journal': list(cap.lines), 't': round(c.rig.now(), 1)}
        finally:
            c.rig.close()
            logging.disable(was)
    return _RUN


@pytest.mark.parametrize('n', range(1, len(STEPS) + 1), ids=lambda n: f'{n:02d}-{STEPS[n - 1][0]}-{STEPS[n - 1][1].__name__}')
def test_the_step_of_the_universal_scenario(n):
    row = played()[n]
    assert row['error'] is None, f'[{row["label"]}] step {n} {row["name"]} broke: {row["error"]}'
    red = [(name, msg) for name, held, msg in row['results'] if not held]
    assert not red, f'[{row["label"]}] step {n} {row["name"]} at {row["t"]} s: {red}\njournal of the step: {row["journal"][-6:]}'


def test_the_scenario_covers_every_family_of_the_census():
    """Every one of the nine families of tools/owner_census has at least one labelled step; the labels name real owners (checked when the steps are declared)."""
    assert {label.split('/')[0] for label, _ in STEPS} == set(OWNERS), sorted(set(OWNERS) - {label.split('/')[0] for label, _ in STEPS})

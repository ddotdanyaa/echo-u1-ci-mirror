"""P03 (family kind): the scenes of U153, U47 and the follow-up class, driven through the real ControlledMedia (``helpers_night_memory.Call``: an answer of three portions is in play, then the remark is heard).
CLASS, NOT CASE: each scene is generated (particles x forms) and decided by structure; no list of phrases is in the code."""
import itertools
import logging
import re

import pytest

import helpers_night_memory as M

QUESTION_IN_PLAY = 'Что такое инерция?'
ANSWER = 'Первая часть ответа про инерцию. Вторая часть ответа про силу. Третья часть ответа про массу.'


class Lines(logging.Handler):
    def __init__(self):
        super().__init__()
        self.rows = []

    def emit(self, record):
        self.rows.append(record.getMessage())

    def verdict(self, tid):
        rows = [dict(re.findall(r'(\w+)=(\S+)', r)) for r in self.rows if r.startswith('echo-sync judge ') and ('tid=%s ' % tid) in r]
        return rows[-1] if rows else None


@pytest.fixture
def lines():
    log, handler, level = logging.getLogger('echo-sync'), Lines(), logging.getLogger('echo-sync').level
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    yield handler
    log.removeHandler(handler)
    log.setLevel(level)


@pytest.fixture
def make(tmp_path):
    calls = []

    def build(**over):
        call = M.Call(tmp_path / ('c%d' % len(calls)), mind=lambda request: ANSWER, **{'fast_text': 'on', **over})
        calls.append(call)
        call.say(QUESTION_IN_PLAY)
        call.pump(5.0)
        return call
    yield build
    for call in calls:
        call.close()


def asked(call, said):
    """(the verdict row of the final, the requests the model got because of it)."""
    before = len(call.all_requests())
    tid = call.say(said)
    call.pump(3.0)
    return tid, call.all_requests()[before:]


# U153: a repeat of the question, a request to hear the answer again and a new question are three different things.
RELISTEN = ['повтори', 'можешь повторить', 'ещё раз', 'ещё разок пожалуйста', 'давай заново', 'дай переслушать', 'можно ещё раз послушать', 'ещё раз с начала', 'переслушать', 'хочу переслушать ответ',
            'ну дай ещё раз послушать', 'не расслышал, скажи ещё раз', 'я не расслышал', 'повтори пожалуйста последнюю часть']
SAME_QUESTION = ['Что такое инерция?', 'я спрашиваю что такое инерция', 'ну что такое инерция', 'так что такое инерция']
NEW_QUESTION = ['а что такое сила?', 'что такое масса?', 'объясни про давление', 'а почему яблоко падает?']


@pytest.mark.parametrize('said', RELISTEN)
def test_u153_a_request_to_hear_it_again_is_a_repeat_and_asks_the_model_nothing(make, lines, said):
    call = make()
    tid, requests = asked(call, said)
    row = lines.verdict(tid)
    assert row is not None and row['kind'] in ('repeat', 'replay'), row
    assert requests == [], 'no new generation for a request to hear it again'


@pytest.mark.parametrize('said', SAME_QUESTION + NEW_QUESTION)
def test_u153_a_question_is_a_question(make, lines, said):
    call = make()
    tid, _ = asked(call, said)
    row = lines.verdict(tid)
    assert row is not None and row['kind'] == 'question', row


def test_u153_the_set_of_twenty_is_classified_at_least_eighteen_right(make, lines):
    right = 0
    scenes = [(said, ('repeat', 'replay')) for said in RELISTEN[:10]] + [(said, ('question',)) for said in (SAME_QUESTION + NEW_QUESTION)[:8]] + [('ну дай ещё раз послушать', ('repeat',)), ('переслушать', ('repeat',))]
    assert len(scenes) == 20
    for said, kinds in scenes:
        call = make()
        row = lines.verdict(call.say(said))
        right += bool(row and row['kind'] in kinds)
    assert right >= 18, right


# The follow-up class: a short turn with no topic of its own continues the last question; particles x forms, never a phrase list in the code.
PARTICLES = ['а', 'и', 'ну', 'так', 'вот', 'а вот', 'ну а', 'так, а', 'тогда', 'ну и']
FORMS = ['пример', 'подробнее']


@pytest.mark.parametrize('particles,form', list(itertools.product(PARTICLES, FORMS)))
def test_a_short_turn_with_no_topic_of_its_own_continues_the_question_before_it(make, lines, particles, form):
    call = make()
    tid, requests = asked(call, '%s %s' % (particles, form))
    row = lines.verdict(tid)
    assert row is not None and row['kind'] == 'question', row
    assert len(requests) == 1 and 'К вопросу: ' + QUESTION_IN_PLAY in str(requests[0]), requests      # the model reads the follow-up WITH the question it is about


@pytest.mark.parametrize('said', ['ну ладно', 'так хорошо', 'и вот', 'ну а', 'ага понятно', 'ну да'])
def test_a_short_turn_of_particles_only_asks_nothing(make, lines, said):
    call = make()
    tid, requests = asked(call, said)
    row = lines.verdict(tid)
    assert requests == [] and row is not None and row['kind'] != 'question', (row, requests)


# U47: the begin phrases of a talk invite the room to ask; they are no question to the prompter, so no cue and no job.
BEGIN_LEADS = ['Ну что,', 'Итак,', 'Так,', 'Хорошо,', 'Ну,']
BEGIN_BODY = ['давайте задавайте любой вопрос', 'задавайте вопросы', 'спрашивайте что хотите', 'есть вопросы?', 'у кого есть вопрос']


@pytest.mark.parametrize('lead,body', list(itertools.product(BEGIN_LEADS, BEGIN_BODY)))
def test_u47_a_begin_phrase_gets_no_cue(tmp_path, lines, lead, body):
    call = M.Call(tmp_path, mind=lambda request: ANSWER, fast_text='on')
    try:
        tid = call.say('%s %s' % (lead, body))
        call.pump(5.0)
        row = lines.verdict(tid)
        assert row is not None and row['kind'] == 'silent', row
        assert call.all_requests() == [] and call.cues() == [], (call.all_requests(), [c.text for c in call.cues()])
    finally:
        call.close()


def test_u47_a_real_question_after_the_begin_words_is_still_answered(tmp_path, lines):
    call = M.Call(tmp_path, mind=lambda request: ANSWER, fast_text='on')
    try:
        tid = call.say('Ну что, давайте начнём. Что такое инерция?')
        call.pump(5.0)
        row = lines.verdict(tid)
        assert row is not None and row['kind'] == 'question', row
        assert call.all_requests() != []
    finally:
        call.close()


# G7 and P21: a question put to a person («Слушай, ты домашку сделал?», «Миша, ты зарядку не видел?») gets no cue, while no answer of ours is in play.
@pytest.mark.parametrize('said', ['Слушай, ты домашку сделал?', 'Миша, ты зарядку не видел?', 'Лена, ты уже ужинала?', 'Саша, а ты завтра придёшь?'])
def test_g7_a_question_to_a_person_gets_no_cue(tmp_path, lines, said):
    call = M.Call(tmp_path, mind=lambda request: ANSWER, fast_text='on')
    try:
        tid = call.say(said)
        call.pump(5.0)
        row = lines.verdict(tid)
        assert row is not None and row['kind'] == 'silent' and row['reason'] == 'gate_talk', row
        assert call.all_requests() == [] and call.cues() == []
    finally:
        call.close()


# harvest11 #6 (BRAIN V1-V13, the doubt window N=2): a bare doubt word is a doubt of the answer in play only while it is among the first lines said after it; three lines later it is other people's talk.
from test_h1_fast_text import rig, user_says      # noqa: E402,F401 - rig is the fixture
from test_h2_brain import decline      # noqa: E402
from test_r05_admission import said_and_repeated, talk      # noqa: E402

SHORT_TALK = ['Прямо всем.', 'Директор так сказал.']      # lines the text gate leaves to the job (too short to be called talk): the job declines each, the doubt rule is what is measured


@pytest.mark.parametrize('word', ['Правда?', 'Серьёзно?', 'Точно?', 'Неужели?', 'Разве?'])
def test_a_bare_doubt_word_as_the_third_line_after_the_answer_does_not_say_the_answer_again(rig, word):
    said_and_repeated(rig)
    n = talk(rig, SHORT_TALK)      # two lines of talk, then the doubt word: the third line after the answer, no pause long enough for the freshness of the answer to run out
    user_says(rig, 'c9', word)
    decline(rig, n)
    assert rig.cues() == ['988 год.'], rig.cues()


@pytest.mark.parametrize('word', ['Правда?', 'Точно?'])
def test_a_bare_doubt_word_in_the_second_line_after_the_answer_still_confirms_it(rig, word):
    said_and_repeated(rig)
    n = talk(rig, SHORT_TALK[:1])
    user_says(rig, 'c9', word)
    decline(rig, n)
    assert rig.cues() == ['988 год.', '988 год.'], rig.cues()

"""ROOT-2 (the owner's call of 09.11 20:51): a test question read with its options was declined (no question form), then «и что выбрать?» went to a job
that saw nothing of it and said «—»: three follow-ups, three silences, while the cloud (it hears the whole call) had the answer. The class: the job's
context was the answered exchanges only, so any question said in two breaths lost its first one. Not a phrase list: whatever was said and declined
since the last answer is the next job's context, for a while, and never the answer in play."""
from echo_sync import controlled_media as cm
from echo_sync import fast_text as FT
from test_h1_fast_text import rig, user_says      # noqa: F401 - rig is the fixture
from test_h2_brain import decline

STEM = 'Органы внутренних дел участвуют вместе с налоговыми органами в проведении выездных налоговых проверок, камеральных налоговых проверок, встречных проверок'
FOLLOW = 'И что выбрать?'


def instructions(rig, n):
    return rig.fake.run(n).request['instructions']


def test_a_follow_up_job_is_told_the_declined_utterance_before_it(rig):
    user_says(rig, 'u1', STEM)
    rig.pump(0.5)
    decline(rig, 0)
    c = rig.w.controller
    assert c.question_id is None and rig.cues() == []
    user_says(rig, 'u2', FOLLOW)
    rig.pump(0.5)
    assert len(rig.fake.runs) == 2, 'the follow-up has a job of its own'
    told = instructions(rig, 1)
    assert 'Прозвучало без ответа:' in told and 'встречных проверок' in told, told[-400:]
    assert c.fast_in_play() is None, 'an unanswered row is context, never the answer in play'


def test_a_short_remark_declined_is_no_context(rig):
    user_says(rig, 'u1', 'Ну наконец-то.')
    rig.pump(0.5)
    decline(rig, 0)
    user_says(rig, 'u2', FOLLOW)
    rig.pump(0.5)
    assert 'Прозвучало без ответа:' not in instructions(rig, len(rig.fake.runs) - 1)


def test_the_unanswered_row_goes_once_an_answer_is_given_or_its_time_is_over(rig):
    c = rig.w.controller
    c._keep_unanswered(STEM)
    assert [row['question'] for row in c.fast_exchanges() if row.get('unanswered')] == [STEM]
    c.unanswered = [(STEM, 0, c.engine.clock() - cm.UNANSWERED_SECONDS - 1)]
    assert not [row for row in c.fast_exchanges() if row.get('unanswered')], 'older than the window: gone'
    c.unanswered = [(STEM, -1, c.engine.clock())]
    assert not [row for row in c.fast_exchanges() if row.get('unanswered')], 'an answer came after it: gone'


def test_the_prompt_says_unanswered_and_never_as_an_answer():
    body = FT.build_request('И что выбрать?', instructions='P', history=[{'question': 'Вопрос раз', 'answer': 'Ответ раз'}, {'question': STEM, 'answer': '', 'unanswered': True}])
    text = body['instructions']
    assert 'Вопрос: Вопрос раз\nОтвет: Ответ раз' in text and f'Прозвучало без ответа: {STEM}' in text and text.count('Ответ:') == 1

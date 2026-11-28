"""Lane B: one owner of the kind of an utterance and of the answer (КАРТА_РЕШЕНИЙ §8). The engine carries out the verdict it is given; the answer belongs to one question.
Words are invented (the shape of the call of 13.11 08:11, not its words)."""
import logging

import pytest

from echo_sync import instant
from echo_sync.classifier import ACK, NEXT, QUESTION, QUIET, REPEAT, RESUME, STOP, Decision
from echo_sync.engine import EchoEngine, SILENT
from tools.replay import quantity as Q, repeat_scenes as R

REMARK = ('Вот сегодня ты отвечал заметно медленнее, и пока непонятно, справится ли вообще эта схема с длинным разговором, '
          'но в целом работы ещё много, хотя ты молодец')
NO_QUESTION = ('Вот сегодня мы снова вернулись к схеме и поговорили сколько, четырнадцать минут, ну а дальше вроде всё нормально работает, '
               'хотя местами ещё есть шероховатости и странные паузы')
TAIL_QUESTION = REMARK + ', кстати, в каком году построили первый мост'
TAIL_SUM = NO_QUESTION + ', так, семь умножить на восемь'
FAR_QUESTION = 'Вот сегодня ты отвечал заметно медленнее, и пока непонятно, в каком году построили первый мост, но работы ещё очень много, молодец, молодец'
SKY = ('Какого цвета небо днём?', 'Голубое.', ['цвет неба днём'])
LONG_SKY = ('Какого цвета небо ночью?', 'Тёмно-синее, почти чёрное. Звёзды видны хорошо. Луна светит ярко.', ['цвет неба ночью'])


# ---- the engine carries out the verdict -------------------------------------------------------------------------------------------------

class Calls:
    def __init__(self, tmp_path, answer='Первый второй третий, четвёртый пятый шестой. Седьмой восьмой.'):
        self.questions = []

        def generate(question, history, context, request, model):
            self.questions.append(question)
            return answer

        self.engine = EchoEngine(tmp_path / 's.sqlite3', generate, settings={'words_per_portion': 3})
        self.n = 0

    def say(self, text, **kw):
        self.n += 1
        return self.engine.reply(session_id='s', turn_id=f't{self.n}', text=text, request={}, model='m', **kw)

    @property
    def state(self):
        return self.engine.state('s')


def asked(calls, text='Что это такое?'):
    return calls.say(text, decided=Decision(QUESTION, 'question_word', text, None))


def test_a_quiet_ruling_claims_nothing(tmp_path):
    c = Calls(tmp_path)
    assert asked(c) == 'Первый второй третий,'
    before = c.state['revision']
    got = c.say('Ну и непонятно, почему так долго, сколько ещё ждать этого автобуса', decided=Decision(QUIET, 'long_talk', None, None))
    assert got == SILENT and c.state['revision'] == before and len(c.questions) == 1


def test_a_stale_basis_is_not_carried_out(tmp_path, caplog):
    c = Calls(tmp_path)
    asked(c)
    state = c.state
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        got = c.say('первый второй третий', decided=Decision(ACK, 'ack_ru_canonical', None, None), basis=(state['revision'], state['chunk_index'] + 1))
    assert got == SILENT and c.state['chunk_index'] == state['chunk_index'] and 'reason=stale_ruling' in caplog.text
    good = c.say('первый второй третий', decided=Decision(ACK, 'ack_ru_canonical', None, None), basis=(state['revision'], state['chunk_index']))
    assert good == 'четвёртый пятый шестой.'


def test_the_going_ruling_is_carried_out_as_given(tmp_path):
    """The words say nothing of going on: the verdict and the plan given are what the engine does."""
    c = Calls(tmp_path)
    asked(c)
    assert c.say('абракадабра', decided=Decision(NEXT, 'next_command', None, None), going=('next', None)) == 'четвёртый пятый шестой.'
    assert c.state['chunk_index'] == 1
    assert c.say('абракадабра', decided=Decision(RESUME, 'resume_continue', None, None), going=('reissue', None)) == 'четвёртый пятый шестой.'


def test_the_engine_needs_a_verdict(tmp_path):
    c = Calls(tmp_path)
    with pytest.raises(TypeError):
        c.say('Что это такое?')


def test_a_question_ruling_without_its_text_takes_the_text_given(tmp_path):
    c = Calls(tmp_path)
    c.say('Что это такое?', decided=Decision(QUESTION, 'question_word', None, None))
    assert c.questions == ['Что это такое?']


def test_plain_ruling_keeps_the_plugin_path(tmp_path):
    """The plugin has no controller: ``plain_ruling`` is the engine's former own reading of the text, in the judge's module."""
    from echo_sync.utterance_judge import plain_ruling
    c = Calls(tmp_path)

    def ruling(text):
        return plain_ruling(c.engine, 's', text)
    assert ruling('Что это такое?')['decided'].kind == QUESTION
    c.say('Что это такое?', **ruling('Что это такое?'))
    assert ruling('первый второй третий')['decided'].kind == ACK
    assert ruling('повтори')['decided'].kind == REPEAT
    assert ruling('Стоп')['decided'].kind == STOP
    nxt = ruling('Дальше')
    assert nxt['decided'].kind == NEXT and nxt['going'] == ('next', None)
    assert nxt['basis'] == (c.state['revision'], None)
    assert c.say('Дальше', **nxt) == 'четвёртый пятый шестой.'


def test_going_verdict_is_the_old_engine_rule():
    from echo_sync.utterance_judge import going_verdict
    question = Decision(QUESTION, 'topic_change', 'x', None)
    assert going_verdict(question, None) is question
    got = going_verdict(question, 'restore')
    assert (got.kind, got.reason) == (RESUME, 'resume_topic')
    got = going_verdict(Decision(REPEAT, 'repeat_command', None, None), 'restore')
    assert (got.kind, got.reason) == (RESUME, 'resume_abandoned')
    got = going_verdict(Decision(RESUME, 'resume_continue', None, None), 'question')
    assert (got.kind, got.reason) == (QUESTION, 'resume_continue:nothing_to_resume')
    assert going_verdict(Decision(NEXT, 'next_command', None, None), 'next').kind == NEXT


def test_command_ruling_names_what_the_engine_used_to_write():
    from echo_sync.utterance_judge import command_ruling
    assert (command_ruling(ACK).kind, command_ruling(ACK).reason) == (ACK, 'ack_ru_canonical')
    assert (command_ruling(STOP).kind, command_ruling(STOP).reason) == (STOP, 'stop_command')
    assert (command_ruling(REPEAT).kind, command_ruling(REPEAT).reason) == (REPEAT, 'repeat_command')


# ---- the tail of a long remark: a count of words, not a list of phrases ----------------------------------------------------------------

def test_the_tail_feature_counts_words_not_phrases():
    from echo_sync.utterance_judge import asked_tail
    from echo_sync import settings
    assert asked_tail(TAIL_QUESTION).endswith('в каком году построили первый мост') and asked_tail(TAIL_QUESTION).startswith('в каком году')
    assert asked_tail(TAIL_SUM).endswith('семь умножить на восемь')
    assert asked_tail(NO_QUESTION) == ''
    assert asked_tail(REMARK) == ''
    far = FAR_QUESTION                      # the question word is 12th from the end
    assert len(far.split()) - far.split().index('каком') == 12
    assert asked_tail(far) == '' and settings.ASK_TAIL_WORDS == 8
    assert asked_tail(far, tail_words=12) and not asked_tail(far, tail_words=11)       # the border moves with the count


# ---- scenes through the real chain (the stand of test_h29_call) -----------------------------------------------------------------------

@pytest.fixture
def rig():
    rig = Q.rig_of()
    rows = [instant.clean_entry({'q': q, 'alt': alt, 'answer': a, 'source': 'scene', 'subject': 'scene'}) for q, a, alt in Q.BANK + [SKY, LONG_SKY]]
    rig.c.instant = instant.Instant(rows, adapters=()).for_call()
    yield rig
    rig.close()
    rig._mp.undo()


def model_says(rig, text):
    if rig.fake.runs:
        last = len(rig.fake.runs) - 1
        rig.job_says(last, text)
        rig.job_ends(last)


def answered_and_repeated(rig):
    """The base answered in one portion and the owner said it back: no portion waits (the shape of the call: the answer was shorter than the pause)."""
    Q.ear_only(rig, SKY[0])
    rig.pump(1.0)
    assert [c.text for c in rig.cues()] == [SKY[1]], 'precondition: the base answered'
    R.utter(rig, 'Голубое')
    rig.pump(1.0)
    state = rig.c.state()
    assert state['completed'], 'precondition: nothing waits'
    return state


def stale(rig, mark, old):
    return [c.text for c in rig.cues()[mark:] if c.text == old]


def test_a_long_remark_without_a_question_says_nothing(rig):
    state = answered_and_repeated(rig)
    assert rig.c._long_talk(NO_QUESTION, state), 'precondition: the judge takes it for talk'
    mark, qid = len(rig.cues()), rig.c.question_id
    R.utter(rig, NO_QUESTION)
    rig.pump(0.5)
    model_says(rig, 'Римляне, около двух тысяч лет назад.')
    rig.pump(4.0)
    assert [c.text for c in rig.cues()[mark:]] == [], 'no question stands in it: nothing is said, least of all an answer to another question'
    assert rig.c.state()['revision'] == state['revision'] and rig.c.question_id == qid


def test_a_question_at_the_tail_of_a_long_remark_is_opened(rig):
    state = answered_and_repeated(rig)
    mark = len(rig.cues())
    R.utter(rig, TAIL_QUESTION)
    rig.pump(0.5)
    model_says(rig, 'Римляне, около двух тысяч лет назад.')
    rig.pump(4.0)
    said = [c.text for c in rig.cues()[mark:]]
    assert said and said[0].startswith('Римляне') and not stale(rig, mark, SKY[1]), said
    assert rig.c.state()['revision'] > state['revision']


def test_a_sum_at_the_tail_of_a_long_remark_is_worked_out(rig):
    answered_and_repeated(rig)
    mark = len(rig.cues())
    R.utter(rig, TAIL_SUM)
    rig.pump(0.5)
    model_says(rig, 'Не знаю.')
    rig.pump(4.0)
    said = [c.text for c in rig.cues()[mark:]]
    assert said and said[0] == 'Пятьдесят шесть.' and not stale(rig, mark, SKY[1]), said


def waiting(rig):
    """The base answered in three portions; the first was said and nobody repeated it for longer than the portion keeps its claim."""
    Q.ear_only(rig, LONG_SKY[0])
    rig.pump(1.0)
    assert rig.cues(), 'precondition: the base answered'
    rig.pump(40.0)
    state = rig.c.state()
    assert not state['completed'], 'precondition: a portion waits'
    return state


def test_a_question_at_the_tail_is_opened_over_a_waiting_portion(rig):
    waiting(rig)
    mark = len(rig.cues())
    R.utter(rig, TAIL_QUESTION)
    rig.pump(0.5)
    model_says(rig, 'Римляне, около двух тысяч лет назад.')
    rig.pump(4.0)
    said = [c.text for c in rig.cues()[mark:]]
    assert any(t.startswith('Римляне') for t in said), said


def test_an_answer_lives_one_reply(rig):
    answered_and_repeated(rig)
    assert rig.c._answer is None, 'the answer of a question is bound to the one reply that publishes it'


def test_an_answer_of_another_turn_fails_the_turn(rig):
    from echo_sync.generator import StreamingAnswer
    answered_and_repeated(rig)
    c = rig.c
    c._bind_answer(StreamingAnswer('Старый ответ.', final=True, retrieval_status='local_reference'), 'turn-A')
    got = c.engine.reply(session_id=c.session_id, turn_id='turn-B', text='Что такое налог?', request={}, model='m',
                         decided=Decision(QUESTION, 'question_word', 'Что такое налог?', None))
    assert got == SILENT
    assert c.engine.publication(c.session_id, 'turn-B') == 'failed'
    assert 'Старый ответ' not in (c.state() or {}).get('answer', '')


def test_publication_takes_the_kind_of_the_question(rig):
    """The publication does not read the text again: it carries the kind and the reason the question was opened with (or the admission that settled it)."""
    answered_and_repeated(rig)
    R.utter(rig, 'Что такое налог на прибыль организаций?')
    rig.pump(0.5)
    model_says(rig, 'Налог на прибыль платят организации с дохода.')
    rig.pump(4.0)
    c = rig.c
    ruled = c._asked_ruling('Что такое налог на прибыль организаций?')
    assert (ruled.kind, ruled.reason) == (c.question_kind, c.question_reason) and ruled.question == 'Что такое налог на прибыль организаций?'
    admitted = c._asked_ruling('Что такое налог на прибыль организаций?', 'admitted_answer')
    assert (admitted.kind, admitted.reason) == (QUESTION, 'admitted_answer')

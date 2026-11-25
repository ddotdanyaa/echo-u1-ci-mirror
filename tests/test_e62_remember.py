"""E62: ``PreparedAnswers.remember`` has ONE caller: ``AnswerMixin._remember_answer``, at the end of a job's whole text (``done``). A standalone public question answered by the job is a hit of
``_prepared`` afterwards; a question of the listener's own affairs, a time-bound one and a failed job leave the cache empty. Real ControlledMedia (rig ``call``), the job's stream scripted."""
import re
from pathlib import Path

from echo_sync.prepared_answers import PreparedAnswers
import helpers_s6_state as S
from test_h3_tempo import TICK, call      # noqa: F401 - the fixture

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = 'Что такое амортизация основных средств'
ANSWER = 'Амортизация переносит стоимость основного средства на расходы по частям.'


def rig_with_cache(call, tmp_path):
    rig = call(fast_text='on')
    rig.c.prepared = PreparedAnswers(cache_path=tmp_path / 'cache.json')
    return rig


def test_a_public_answer_of_the_job_is_kept_and_found_again(call, tmp_path):
    rig = rig_with_cache(call, tmp_path)
    assert rig.c.prepared.lookup(PUBLIC) is None
    rig.asks('u1', PUBLIC, 0, ANSWER)
    assert rig.c.prepared.lookup(PUBLIC) == ANSWER
    assert PreparedAnswers(cache_path=tmp_path / 'cache.json').lookup(PUBLIC) == ANSWER, 'it is on disk for the next call'


def test_a_question_of_the_listeners_own_affairs_is_never_kept(call, tmp_path):
    rig = rig_with_cache(call, tmp_path)
    rig.asks('u1', 'Что такое моя амортизация основных средств', 0, ANSWER)
    assert len(rig.c.prepared) == 0 and not (tmp_path / 'cache.json').exists()


def test_a_time_bound_question_is_never_kept(call, tmp_path):
    rig = rig_with_cache(call, tmp_path)
    rig.asks('u1', 'Какая сейчас ставка рефинансирования центрального банка', 0, 'Шестнадцать процентов.')
    assert len(rig.c.prepared) == 0


def hears(rig, uid, text):
    rig.w.feed(S.turn_created(uid, 'user', text.split()[0]))
    rig.w.feed(S.turn_done(uid, 'user', text))
    rig.pump(TICK * 3)


def test_the_first_call_with_no_kept_answer_goes_to_the_job(call, tmp_path):
    """The premise: with an empty cache the same question gets no answer of code (``_prepared`` and ``_reference`` say None) and is the job's: it is asked, nothing is said before it speaks."""
    rig = rig_with_cache(call, tmp_path)
    assert rig.c._prepared(PUBLIC) is None and rig.c._reference(PUBLIC) is None
    hears(rig, 'u1', PUBLIC)
    assert rig.fast.count == 1 and rig.said() == []


def test_the_next_call_answers_from_the_kept_answer_with_no_job(call, tmp_path):
    """The reader, by the call's own decision: call 1 gets the answer from the job and the cache keeps it; call 2 (a new controller, the same cache file) hears the question and says the kept answer, the job never asked."""
    first = rig_with_cache(call, tmp_path)
    first.asks('u1', PUBLIC, 0, ANSWER)
    assert first.said() == [ANSWER]
    second = call(fast_text='on')
    second.c.prepared = PreparedAnswers(cache_path=tmp_path / 'cache.json')
    assert second.c._prepared(PUBLIC) == ANSWER, 'the cache is the source (the question is in no base)'
    hears(second, 'u1', PUBLIC)
    assert second.said() == [ANSWER] and second.fast.count == 0, 'no job: the code answers'


def test_the_cache_has_one_writer():
    callers = [p.name for p in (ROOT / 'echo_sync').glob('*.py') if re.search(r'\.remember\(', p.read_text(encoding='utf-8')) and p.name not in ('prepared_answers.py', 'pcm_cache.py')]
    assert callers == ['cm_answer.py'], callers

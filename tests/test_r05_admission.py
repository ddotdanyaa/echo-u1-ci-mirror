"""R05 (r05-admission): when to speak. What the product itself does with the finals of a talk that ask nothing of the prompter, found by the corpus brain_eval_n2 (cloud_context/scripts/corpus) and reproduced here with
production code and a scripted job (no model): the job says «—» to every line, and the question is what the controller does AROUND that verdict.

Findings (the patch of each is in cloud_context/reports/r05-admission.md; the owner of controlled_media.py is the coordinator, so the tests that need the patch are xfail(strict=True) with the finding's number):
  R05-F1  fast_in_play keeps the last exchange in play for the WHOLE call, so every later final is shown to the job as «Вопрос / Твой ответ / Сейчас прозвучало» and the BRAIN's last rule («сомнение — отвечай всегда,
          «—» запрещён») applies to chatter.
  R05-F2  the controller's own doubt rule (_doubt_held: one doubt word and no subject of its own) turns the job's «—» to a bare «Правда?» of other people's talk into the first sentence of the old answer, said again.
"""
import pytest

from test_h1_fast_text import acked, rig, user_says      # noqa: F401 - rig is the fixture
from test_h2_brain import decline, year

CHATTER = ['Говорят, премию в этом квартале отменили.', 'Прямо всем.', 'Директор так сказал.']


def later(rig, seconds):
    """``seconds`` of the call go by: the world's clock (the controller's) and the engine's wall clock (the stamps of the history) both move; the rig advances only the first."""
    engine = rig.w.controller.engine
    real = engine.clock
    engine.clock = lambda: real() + seconds
    rig.pump(seconds)


def said_and_repeated(rig):
    """An answer of one portion, cued and repeated by the listener: it is done, nothing of it waits (a waiting portion is cued again by the plan itself after a long silence, and that is not what is measured here)."""
    year(rig, '988 год.')
    acked(rig, 0.5)
    assert rig.w.controller.state()['completed'] and rig.cues() == ['988 год.']


def talk(rig, lines, first=1):
    """Lines of other people's talk one after another, each declined by the job (run ``first``, ``first`` + 1 ...)."""
    for n, line in enumerate(lines, first):
        user_says(rig, f'c{n}', line)
        decline(rig, n)
        rig.pump(6.0)          # a pause between the lines: finals of one breath are joined into one question
    return first + len(lines)


def test_a_line_of_talk_right_after_an_answer_is_shown_to_the_job_with_the_answer_in_play(rig):
    """The design of H2 (rule 4), pinned: what is said at once after an answer may be a doubt of it, so the job sees the answer."""
    year(rig, '988 год.')
    user_says(rig, 'c1', 'Говорят, премию в этом квартале отменили.')
    assert rig.fake.run(1).question.startswith('Вопрос: ') and 'Твой ответ: 988 год.' in rig.fake.run(1).question


def test_a_declined_line_of_talk_cues_nothing_and_leaves_the_answer_as_it_was(rig):
    said_and_repeated(rig)
    talk(rig, CHATTER)
    assert rig.cues() == ['988 год.'] and rig.w.controller.state()['answer'] == '988 год.'


def test_a_line_of_talk_a_minute_after_an_answer_is_shown_to_the_job_without_it(rig):
    said_and_repeated(rig)
    later(rig, 60.0)
    talk(rig, CHATTER)
    last = rig.fake.run(3).question
    assert 'Твой ответ' not in last and last == CHATTER[-1], last


def test_the_answer_in_play_is_kept_for_a_doubt_that_comes_soon(rig):
    """What the freshness patch must not break: «ты уверена» seconds after the answer is still a doubt of it."""
    said_and_repeated(rig)
    later(rig, 8.0)
    user_says(rig, 'u2', 'ты уверена')
    assert 'Твой ответ: 988 год.' in rig.fake.run(1).question


@pytest.mark.parametrize('word', ['Правда?', 'Серьёзно?', 'Точно?', 'Неужели?', 'Разве?'])
def test_a_bare_doubt_word_in_other_peoples_talk_a_minute_after_an_answer_does_not_say_the_answer_again(rig, word):
    said_and_repeated(rig)
    later(rig, 60.0)
    n = talk(rig, CHATTER)
    user_says(rig, 'c9', word)
    decline(rig, n)
    assert rig.cues() == ['988 год.'], rig.cues()


def test_a_bare_doubt_word_right_after_the_answer_still_confirms_it(rig):
    """The H6 item 7 behaviour that must survive: «Точно?» at once is a doubt, and the job's «—» is answered with the first sentence of the answer."""
    said_and_repeated(rig)
    user_says(rig, 'u2', 'Точно?')
    decline(rig, 1)
    assert rig.cues() == ['988 год.', '988 год.'], rig.cues()


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

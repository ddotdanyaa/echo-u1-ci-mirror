"""V2 E73.1: ``question_part`` is a form rule. «Нынешний закон о бухучёте, какой год принятия» read as «какой год принятия» and the route went to memory; the history held the PART, not the utterance, and the follow-up saw less.
The backlog's check: a table of pairs where the preface IS the subject (it stays with the question), and the follow-up's context is not lost.

A table on the pure ``classifier.question_part`` and the whole order through the real ControlledMedia (rig ``call``). Not run on the laptop: the verdict is the cloud's.
"""
import pytest

from echo_sync.classifier import question_part
from question_kit import CALL_1027, SAID_15, TICK, answered, call, entry_of, job_input, user_turn      # noqa: F401 - call is the fixture

# (the utterance, a stem of the SUBJECT that the question's part must keep)
SUBJECT_IN_PREFACE = [
    ('Нынешний закон о бухгалтерском учёте, какой год принятия', 'бухгалтер'),
    ('Налоговый кодекс, какая там статья про вычеты', 'налогов'),
    ('Закон о персональных данных, какой там штраф за нарушение', 'персональн'),
    ('Трудовой кодекс, сколько длится испытательный срок', 'трудов'),
]
# (the utterance, a stem of an ASIDE that must NOT be the question's topic)
ASIDE_IN_PREFACE = [
    (SAID_15, 'третья минута'),
    ('Так, секунду, я сейчас микрофон поправлю, что такое амортизация', 'микрофон'),
]


@pytest.mark.parametrize('said, subject', SUBJECT_IN_PREFACE, ids=[row[1] for row in SUBJECT_IN_PREFACE])
def test_the_subject_said_before_the_question_word_stays_in_the_question_part(said, subject):
    part = question_part(said).lower()
    assert subject in part, f'the part {part!r} lost the subject of {said!r}'


@pytest.mark.parametrize('said, aside', ASIDE_IN_PREFACE, ids=['third_minute', 'microphone'])
def test_the_aside_before_the_question_word_does_not_become_its_topic(said, aside):
    assert aside not in question_part(said).lower()


def test_the_history_keeps_the_subject_the_follow_up_sees(call):
    """The call's order: the question with the subject in its preface, the answer, a follow-up that has no subject of its own."""
    rig = call(**CALL_1027)
    user_turn(rig, 'u1', 'Нынешний закон о бухгалтерском учёте, какой год принятия')
    assert 'бухгалтер' in rig.fake.run(0).question.lower() or 'бухгалтер' in str(rig.fake.run(0).request).lower(), 'the job heard the subject'
    answered(rig, 0, 'Закон о бухгалтерском учёте принят в 2011 году.')
    rig.pump(3.0)
    entry = entry_of(rig, 'бухгалтер')
    assert entry is not None, 'the history entry of the question holds the subject, not only «какой год принятия»'
    user_turn(rig, 'u2', 'А кем он подписан')
    assert rig.fake.runs[1:], 'the follow-up reached the job'
    assert 'бухгалтер' in job_input(rig, 1).lower(), 'the follow-up\'s context holds the subject'

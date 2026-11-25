"""C7, W4 addition (live run 20261103-171237, w4_05_exam_kant_number_corrected, step 6): «Напомните, какое число | получилось» - the
cloud ASR cut the question into two finals, the model began its answer after the first one («Шестьдесят») and the transport closed that
segment when the second piece started; the rest of the sentence came as the next segment, « лет.». The second piece continued the
utterance, the question was re-opened, the reply to the first piece was blocked with the old question, and « лет.» became the first cue:
a bare unit, the number lost (not said: шестьдесят|60).

The class: a number never leaves its unit and a cue is never the bare remainder of a number phrase. The reply to the unfinished question
stays that question's (W1F-B: a guess at an unfinished question is no answer to the whole one), so the segment that goes on with its number
(«Шестьдесят» | « лет.») is the rest of ANOTHER question's sentence: it is skipped through its sentence end (``_interrupted_head``), as the
rest of a word or of a sentence cut between two words already is. What the cloud says after it is the answer.
"""
import re

from test_first_cue_never_silent import created, delta, done
from test_task1_review_round2 import Session

T1 = 1.0


def kant(tmp_path, **session):
    s = Session(tmp_path, **session)
    s.at(T1 - 0.4, created('u6', 'user', 'Напомните'))
    s.at(T1, done('u6', 'user', 'Напомните, какое число'))
    s.at(T1 + 0.25, created('a6', 'assistant', 'Шестьдесят'))
    s.at(T1 + 0.5, created('u7', 'user', 'получилось'))
    s.at(T1 + 0.5, done('a6', 'assistant', 'Шестьдесят'))          # the listener speaks again: the segment is closed
    s.at(T1 + 1.0, done('u7', 'user', 'получилось'))
    s.at(T1 + 1.2, created('a7', 'assistant', ' лет.'))
    s.at(T1 + 1.3, done('a7', 'assistant', ' лет.'))
    return s


def test_the_remainder_of_a_number_phrase_is_never_cued_alone(tmp_path):
    s = kant(tmp_path)
    s.until(12)
    assert not any(re.fullmatch(r'\W*лет\W*', text) for text in s.texts), s.cues


def test_an_answer_the_cloud_gives_after_the_remainder_is_still_cued(tmp_path):
    s = kant(tmp_path)
    s.at(T1 + 1.6, created('a8', 'assistant', 'Получилось'))
    s.at(T1 + 1.8, done('a8', 'assistant', 'Получилось 60 лет.'))
    s.until(12)
    assert any('60 лет' in text for text in s.texts), s.cues
    assert not any(re.fullmatch(r'\W*лет\W*', text) for text in s.texts), s.cues

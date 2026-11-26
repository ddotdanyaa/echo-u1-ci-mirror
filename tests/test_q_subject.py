"""E73.1 (family question, package Q): a preface that names a DOCUMENT is the subject of the question after it, not talk around it. «Нынешний закон о бухгалтерском учёте, какой год принятия» read as
«какой год принятия» sent the route to memory and the history held the part, so the follow-up saw less. ``question_part.extract`` now keeps such a preface (``Part.subject``) and puts it into the public query;
an aside before the question word stays dropped. Pure table, plus the real order on the real ControlledMedia in ``tests/verify/question/test_v_E73_1.py`` (it needs ``classifier.question_part`` to read ``Part.subject``:
proposals/Q/E73_1_classifier_subject.patch, package K). Not run on the laptop."""
import pytest

from echo_sync.question_part import extract

SUBJECT = [
    ('Нынешний закон о бухгалтерском учёте, какой год принятия', 'закон о бухгалтерском учёте'),
    ('Налоговый кодекс, какая там статья про вычеты', 'налоговый кодекс'),
    ('Закон о персональных данных, какой там штраф за нарушение', 'закон о персональных данных'),
    ('Трудовой кодекс, сколько длится испытательный срок', 'трудовой кодекс'),
]


@pytest.mark.parametrize('said, subject', SUBJECT, ids=[row[1] for row in SUBJECT])
def test_the_preface_that_names_a_document_stays_with_the_question(said, subject):
    part = extract(said)
    assert part.kind == 'question' and not part.dropped, part
    assert any(subject in body.lower() for body in part.subject), part
    assert subject in part.text.lower() and subject in part.public_query.lower(), part


ASIDE = [
    'Вот сейчас третья минута идёт, что такое пятнадцатый счёт',
    'Так, секунду, я сейчас микрофон поправлю, что такое амортизация',
    'Я вчера плохо спал, что такое проводка',
    'Он закончил, сколько это будет',
]


@pytest.mark.parametrize('said', ASIDE)
def test_an_aside_before_the_question_word_is_still_dropped(said):
    part = extract(said)
    assert not part.subject, part
    assert part.dropped, part


def test_a_personal_preface_with_a_document_is_no_public_subject():
    part = extract('Мой трудовой договор, какой там срок')
    assert not part.public_query or 'мой' not in part.public_query.lower(), part


def test_a_topic_after_a_remark_is_read_as_before():
    """The check of ``extract`` for a bare topic (no question word) passes no ``subject``: «Мне немного страшно. Семнадцатая статья налогового кодекса» stays a topic."""
    assert extract('Мне немного страшно. Семнадцатая статья налогового кодекса').kind == 'topic'

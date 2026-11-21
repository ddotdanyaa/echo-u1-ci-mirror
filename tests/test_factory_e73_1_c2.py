# factory-backlog-id: E73.1#2
from echo_sync.question_part import extract


def test_question_part_subject_stored_in_history_and_follow_up():
    text = "Трудовой кодекс, сколько длится испытательный срок?"
    res = extract(text)
    assert res.subject == ("Трудовой кодекс",)
    assert res.public_query == "Трудовой кодекс сколько длится испытательный срок?"

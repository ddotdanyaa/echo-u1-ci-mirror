# factory-backlog-id: U47
from echo_sync import classifier

PORTION = 'Нужны были мундиры, обувь,'


def test_portion_words_behind_a_question_word_and_a_hesitation_are_not_a_question():
    state = {
        'chunks': [PORTION],
        'chunk_index': 0,
        'waiting_portion': PORTION,
    }
    decision = classifier.analyze('Что соответственно нужны были, э-э', state, [])
    assert decision.kind == classifier.QUIET, decision
    assert decision.question is None, decision

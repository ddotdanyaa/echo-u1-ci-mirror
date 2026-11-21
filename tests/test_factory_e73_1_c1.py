# factory-backlog-id: E73.1#1
from echo_sync.classifier import question_part

def test_question_part_reads_as_memory_route_and_history():
    # The defect: 'читается как' is a form rule, but the current implementation 
    # of question_part treats the whole text as part of the question.
    # After the fix, the part "Операция читается как облагаемая по нулевой ставке"
    # should be treated as memory/context, and only "Какова ставка?" should remain.
    text = "Операция читается как облагаемая по нулевой ставке. Какова ставка?"
    res = question_part(text)
    
    # The defect causes the full text to be returned.
    # We assert that the memory-route part is removed.
    assert "Операция читается как" not in res
    assert "облагаемая по нулевой ставке" not in res
    assert res.strip() == "Какова ставка?"

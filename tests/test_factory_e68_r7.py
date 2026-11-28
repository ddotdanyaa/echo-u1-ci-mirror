# factory-backlog-id: E68
from unittest.mock import MagicMock
from echo_sync.cm_question import QuestionMixin

class MockQuestion(QuestionMixin):
    def __init__(self):
        self.question_id = 'q1'
        self.question_text = 'test question'
        self.fast_on = True
        self.fast_asked = None
        self.local_answer = None
        self.user_boundaries = {}
        self.epoch = 1
        self.fast_n = 0
        self.fast_text = 'test question'
        self.candidate = None
        self.fast_handed = None
        self.engine = MagicMock()
        self.session_id = 's1'
        self.ledger = MagicMock()
        self.owners = {}
        self.fast_turn = False
        self.fast_also = lambda asked, qid: {}
        self._fast_tail_waits = lambda asked, route, extra: False
        self._ear_safely = lambda words, text, floor, split, default: ''
        self._ear_words = ''
        self._ear_floor = lambda tid: None
        self._split_after = lambda tid: None

def test_unsourced_route_does_not_lose_question():
    q = MockQuestion()
    # The defect R7: refusal "—" on 'sources'/'unsourced' route silently loses the question.
    # We simulate a call to _fast_release with route='sources'.
    # If the implementation incorrectly returns [] for certain refusal scenarios, fails.
    
    # To trigger the R7/R6 logic, we simulate the condition where the question
    # is considered to have a "tail" that waits, or where the route/extra 
    # combination causes an early return [].
    
    # We force _fast_tail_waits to return True to see if it's used incorrectly 
    # for 'sources' or 'unsourced' routes.
    q._fast_tail_waits = lambda asked, route, extra: route in ('sources', 'unsourced')
    
    res = q._fast_release(route='sources', extra={})
    
    assert len(res) > 0, f"Question was lost (returned empty list) on 'sources' route. Result: {res}"

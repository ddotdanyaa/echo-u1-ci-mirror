# factory-backlog-id: E87-arith-by-code
from echo_sync.speech_text import _Engine

class MockEngine(_Engine):
    def __init__(self, tokens):
        self.tokens = tokens
    def kind(self, i):
        if i < 0 or i >= len(self.tokens): return 'none'
        return self.tokens[i][1]
    def text(self, i):
        if i < 0 or i >= len(self.tokens): return ''
        return self.tokens[i][0]
    def emit(self, s): pass
    def next_sig(self, i): return -1
    def one_case(self, i): return 0
    def prev_ref(self): return -1

def test_course_code_before_double_separator():
    # Case: "МДК . 03.01" -> tokens: [('МДК', 'word'), (' ', 'sp'), ('.', 'ch'), ('03', 'num'), ('.', 'ch'), ('01', 'num')]
    # i is index 3 (the '03')
    # p = 2 (the '.')
    # current code: p becomes 1 (the ' '). kind(1) is 'sp', not 'word'. Returns False.
    tokens = [('МДК', 'word'), (' ', 'sp'), ('.', 'ch'), ('03', 'num'), ('.', 'ch'), ('01', 'num')]
    engine = MockEngine(tokens)
    assert engine.course_code_before(3) is True

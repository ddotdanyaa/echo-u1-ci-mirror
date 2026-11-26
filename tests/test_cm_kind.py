# factory-backlog-id: XS-gated-w5x7
import pytest
from echo_sync.cm_kind import KindMixin

class MockKind(KindMixin):
    def __init__(self):
        self.ear_lexicon = None
        self.turn_lang = type('Lang', (), {'lang': 'ru'})
        self.tempo_live = True
        self.ear_words_at = 0
        self.lang_gated = 0
        self._lang_logged = {}
    def clock(self): return 100
    def _input_feed(self, *args, **kwargs): pass
    def _tempo_safely(self, func, record): return 'gated'

def test_tempo_heard_gates_empty_record():
    m = MockKind()
    res = m.tempo_heard({'text': ''})
    assert res == 'gated'
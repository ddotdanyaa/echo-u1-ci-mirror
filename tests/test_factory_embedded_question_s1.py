# factory-backlog-id: MUT-attempts.s1
# restated 27.11 per the coordinator decision (BRIEF.md, "Решение координатора 27.11 ... (П2)", rel-b09b0cf0-1):
# "ведь" without "?" and without an interrogative is no question evidence; with "?" it is.
from echo_sync.classifier import _question_evidence

def test_embedded_question_recognized():
    # cfg must contain 'question_window' to avoid KeyError in _trigger
    cfg = {'question_window': 10}
    raw = 'я думаю об этом, но ведь причина есть'
    words = ['я', 'думаю', 'об', 'этом', 'но', 'ведь', 'причина', 'есть']
    ev = _question_evidence(raw, words, None, cfg, False)
    assert ev is None
    ev = _question_evidence(raw + '?', words, None, cfg, False)
    assert ev is not None and ev.asked == raw + '?'

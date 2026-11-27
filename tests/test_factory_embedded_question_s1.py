# factory-backlog-id: MUT-attempts.s1
from echo_sync.classifier import _question_evidence

def test_embedded_question_recognized():
    # cfg must contain 'question_window' to avoid KeyError in _trigger
    cfg = {'question_window': 10}
    raw = 'я думаю об этом, но ведь причина есть'
    words = ['я', 'думаю', 'об', 'этом', 'но', 'ведь', 'причина', 'есть']
    # Currently returns None because it doesn't end with '?' and isn't a known trigger.
    ev = _question_evidence(raw, words, None, cfg, False)
    assert ev is not None
    assert ev.asked == 'я думаю об этом, но ведь причина есть'

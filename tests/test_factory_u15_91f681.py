# factory-backlog-id: U15
from echo_sync.cm_kind import KindMixin, QUESTION


def _bare():
    obj = object.__new__(KindMixin)
    obj.question_id = None
    obj.published = None
    obj.diagnosed_epoch = None
    obj.epoch = 0
    obj.settings = None
    obj.quiet_pieces = []
    obj.fast_on = False
    obj.state = lambda: None
    return obj


def test_the_one_form_verdict_combines_the_classifier_and_the_text_gate():
    obj = _bare()
    verdict = getattr(obj, '_form_verdict', None)
    assert verdict is not None, 'the form verdict has no single place: _cloud_asks combines the layers by hand'
    for text in ('Когда было крещение Руси?', 'Спасибо.', 'Что такое мотив?', 'Ну ладно.'):
        expected = obj._classify(text, obj._heard_with(None)).kind == QUESTION and not obj._gate_talk(text)
        assert verdict(text, None) is expected, text
        assert obj._cloud_asks(text) is expected, text

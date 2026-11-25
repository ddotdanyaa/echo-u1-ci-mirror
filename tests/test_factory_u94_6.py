# factory-backlog-id: U94.6
from types import SimpleNamespace
from echo_sync.controlled_media import ControlledMedia

def test_authorized_qid_checking():
    # When: authorized is called with a cue whose 'qid' is 'q1' while owner's question_id is 'q2'.
    self_mismatched = SimpleNamespace(question_id='q2', _act=lambda act, reason, **args: ('do', []))
    assert ControlledMedia.authorized(self_mismatched, {'qid': 'q1'}) is False

    # When: called with the same qid 'q1' (matching)
    self_matching = SimpleNamespace(question_id='q1', _act=lambda act, reason, **args: ('do', []))
    assert ControlledMedia.authorized(self_matching, {'qid': 'q1'}) is True

    # When: called with a cue that has no 'qid' key
    self_no_qid = SimpleNamespace(question_id='q2', _act=lambda act, reason, **args: ('do', []))
    assert ControlledMedia.authorized(self_no_qid, {}) is True

    # When: called with question_id None while cue carries 'q1'
    self_none_qid = SimpleNamespace(question_id=None, _act=lambda act, reason, **args: ('do', []))
    assert ControlledMedia.authorized(self_none_qid, {'qid': 'q1'}) is True

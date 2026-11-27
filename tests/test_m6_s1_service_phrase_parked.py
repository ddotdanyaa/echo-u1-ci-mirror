# factory-backlog-id: M6.s1
from echo_sync.controlled_media import ControlledMedia


def test_service_phrase_parked_while_cue_plays(monkeypatch):
    cm = ControlledMedia.__new__(ControlledMedia)
    cm.question_id = 'q1'
    cm.cue_heard = False
    cm._cue_playing = lambda now: True
    ctx = {}
    cm._step_may_sound(ctx, {'what': 'say'})
    assert ctx.get('stop') == 'park'

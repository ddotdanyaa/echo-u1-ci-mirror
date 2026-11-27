"""V3 E16: stable knowledge against current data: a question about current data (a rate that changes) with no source is not answered from memory as a verified fact (``needs_current_data`` fails closed), and an answer from
knowledge is ``unsourced``, never ``source_backed`` (no_source does not become verified).

Real ControlledMedia and wire (rig of test_h1_fast_text). The unit rows are in test_w9_fast_no (personal_volatile) and the wire row «current data without a source gets no job» in test_h1_fast_text; these rows add the state of the
answer and the silence of the memory. Not run on the laptop."""
import helpers_s6_state as S
from echo_sync import fast_text as FT
from test_h1_fast_text import CURRENT, VERIFY, rig      # noqa: F401 - rig is the fixture


def test_current_data_with_no_source_is_not_answered_from_memory_as_a_fact(rig, monkeypatch):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', CURRENT))
    rig.pump(10.0)
    assert rig.fake.runs == [], 'no job: its answer would be the model\'s memory of a rate'
    state = rig.w.controller.engine.state(rig.w.session_id) or {}
    assert state.get('retrieval_status') != 'source_backed'
    assert not any(any(ch.isdigit() for ch in text) for text in rig.cues()), rig.cues()


def test_stable_knowledge_with_no_source_is_answered_and_marked_unsourced(rig, monkeypatch):
    monkeypatch.setattr(S, 'SOURCE_ROWS', [])
    rig.w.feed(S.turn_created('u1', 'user', 'Проверь'))
    rig.w.feed(S.turn_done('u1', 'user', VERIFY))
    rig.pump()
    assert rig.fake.run(0).request['input'][0]['content'][0]['text'] == FT.NO_SOURCE_BRAIN
    rig.say(0, 'Гидравлический удар — резкий скачок давления в трубопроводе. Он возникает при остановке потока.')
    assert rig.cues()
    assert (rig.w.controller.engine.state(rig.w.session_id) or {}).get('retrieval_status') == 'unsourced'

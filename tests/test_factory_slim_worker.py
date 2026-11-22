"""<id>: the gate trace of a red base (up to factory_gate.PATH_MAX lines) lives in traces/<tid>.json beside the state,
not inside it: the state is read and rewritten on every action of every worker and must not grow with traces."""
from tools import agent_factory as F
from test_factory_loop import _plan, task_row
import dataclasses
from test_factory_runtime import Rig, _kilo_engine, gr  # noqa: <id>  (_kilo_engine: autouse)
from test_factory_base_cache import SHA_A, _released_then_resumed


def test_a_trace_lives_in_its_own_file_and_old_states_are_moved(tmp_path):
    tasks = _plan(task_row(1)); s = F.initial_state(tasks)
    s["tasks"]["T1"]["base_red"] = {"result": {"path": [["echo_sync/a.py", "f", i] for i in range(5000)]}}
    F.save_atomic(tmp_path / "state.json", s)
    st = F.load_state(tmp_path / "state.json", tasks)
    assert "path" not in st["tasks"]["T1"]["base_red"]["result"]
    assert len(F.get_trace(tmp_path, st["tasks"]["T1"])) == 5000
    F.save_atomic(tmp_path / "state.json", st)
    assert (tmp_path / "state.json").stat().st_size < 50_000


def test_a_missing_trace_file_reads_as_empty(tmp_path):
    row = {"base_red": {"result": {"path_file": "T1.json"}}}
    assert F.get_trace(tmp_path, row) == ()
    assert F.get_trace(tmp_path, {}) == ()


def test_ids_that_clean_to_one_name_get_their_own_files(tmp_path):
    assert F.put_trace(tmp_path, "T/1", [("a.py", "f", 1)]) != F.put_trace(tmp_path, "T_1", [("b.py", "g", 2)])
    assert F.put_trace(tmp_path, "T1", [("a.py", "f", 1)]) == "T1.json"


def test_a_garbled_trace_file_means_the_base_is_measured_again(tmp_path, monkeypatch):
    from tools import agent_factory_runner as w
    monkeypatch.setattr(w, '_now', lambda: 1000.0)
    name = F.put_trace(tmp_path, "T1", [("a.py", "f", 1)])
    result = {k: v for k, v in dataclasses.asdict(gr(False)).items() if k != 'path'}
    row = {'base_red': {'key': 'k', 'at': 990.0, 'result': dict(result, path_file=name)}}
    assert w._held_base(row, 'k', 'code', tmp_path) is not None
    (tmp_path / F.TRACE_DIR / name).write_text('{"path": [', encoding='utf-8')      # a torn write
    assert w._held_base(row, 'k', 'code', tmp_path) is None
    (tmp_path / F.TRACE_DIR / name).write_text('garbage', encoding='utf-8')
    assert w._held_base(row, 'k', 'code', tmp_path) is None


def test_the_red_base_is_reused_with_its_trace_kept_in_a_file(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _, second, _ = _released_then_resumed(rig, SHA_A)
    row = rig.state()['tasks']['T1']
    assert 'path' not in row['base_red']['result'] and row['base_red']['result']['path_file']
    assert (tmp_path / F.TRACE_DIR / row['base_red']['result']['path_file']).is_file()
    assert 'base_reused' in second['events']                 # the red base is not measured again


def test_a_deleted_trace_file_means_the_base_is_measured_again(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    _, second, _ = _released_then_resumed(
        rig, SHA_A, between=lambda: [p.unlink() for p in (tmp_path / F.TRACE_DIR).glob('*.json')])
    assert 'base_reused' not in second['events']

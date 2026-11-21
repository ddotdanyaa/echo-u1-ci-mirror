"""The runner hands the router its sticky names and the live quota state (one task keeps its channel while it has room)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_factory_runtime import Rig, _kilo_engine, THREE_CHANNELS  # noqa: <id>,<id>  (_kilo_engine: autouse)


def _cfg(tmp_path):
    cfg = tmp_path / 'sticky.json'
    cfg.write_text(json.dumps(dict(channels=THREE_CHANNELS)))
    return cfg


def _spy(rig):
    seen = {'choose': [], 'reserve': [], 'order': []}
    real_choose, real_reserve, real_order = rig.w.channels.choose, rig.w.channels.reserve, rig.w.channels.route_order

    def choose(*a, **kw):
        seen['choose'].append(kw.get('affinity'))
        return real_choose(*a, **kw)

    def reserve(*a, **kw):
        seen['reserve'].append(kw.get('affinity'))
        return real_reserve(*a, **kw)

    def order(*a, **kw):
        seen['order'].append(kw.get('state'))
        return real_order(*a, **kw)
    rig.mp.setattr(rig.w.channels, 'choose', choose)
    rig.mp.setattr(rig.w.channels, 'reserve', reserve)
    rig.mp.setattr(rig.w.channels, 'route_order', order)
    return seen


def test_the_call_passes_the_task_and_family_names_and_the_state(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    seen = _spy(rig)
    rig.once(channel_config=_cfg(tmp_path))
    assert seen['choose'] and seen['choose'] == seen['reserve']
    assert seen['choose'][0] == ['task:T1', 'family:calc']
    assert any(a == ['task:T1:review', 'family:calc:review'] for a in seen['choose'])    # the reviewer's own memory
    assert all(isinstance(s, dict) for s in seen['order'])


def test_a_second_attempt_after_a_rejection_goes_to_another_model(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.coder_script = ['bad', 'good']
    cfg = _cfg(tmp_path)
    first = rig.once(channel_config=cfg, small_model='google/y', large_model='google/x')
    assert first['calls'][0]['model'] == 'google/y'        # the first attempt starts on the small model
    rig.edit_state(lambda s: s['tasks']['T1'].update(not_before=0))      # the memory in channel_quotas stays
    second = rig.once(channel_config=cfg, small_model='google/y', large_model='google/x')
    # 21.11 (OLD_RULES_AUDIT item 6): the model that failed is left out while the router has another one
    assert second['calls'][0]['model'] == 'google/x' != first['calls'][0]['model']


def test_a_channel_cooled_on_its_own_is_skipped(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch)
    rig.once(channel_config=_cfg(tmp_path))
    rig.edit_state(lambda s: (s['tasks']['T1'].update(not_before=0, status='READY'),
                              s.__setitem__('channel_quotas', {'channel_cool': {'c1': 10 ** 12}})))
    result = rig.once(channel_config=_cfg(tmp_path), small_model='google/x', large_model='google/x')
    assert result['calls'][0]['channel'] != 'c1' and result['calls'][0]['model'] != 'google/x'


def test_the_runner_rejects_a_new_unit_test_that_is_green_on_the_base(tmp_path, monkeypatch):
    rig = Rig(tmp_path, monkeypatch, kind='unit_test')
    two = '# factory-backlog-id: BL1\ndef test_red(): assert 1 == 2\n\n\ndef test_green(): assert 1 == 1\n'
    rig.coder_script = [lambda d: ((d / 'tests').mkdir(exist_ok=True), (d / 'tests/test_new.py').write_text(two),
                                   (0, __import__('test_factory_runtime').ev(
                                       __import__('test_factory_runtime').finish()), b''))[-1]]
    from tools import factory_gate as G
    rig.run_tests_fn = lambda root, tests, t: G.GateResult(1, 2, 1, 1, 0, 0, True, diag='one red',
                                                           failed_ids=('tests.test_new::test_red',))
    result = rig.once()
    assert result['status'] == 'READY' and 'test_green' in json.dumps(result) and 'passes on the base code' in json.dumps(result)

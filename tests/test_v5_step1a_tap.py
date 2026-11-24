"""V5 step 1a: one entry and the record, in shadow (echo_sync/v5_tap.py, setting ``v5_tap`` = off | shadow, default off).

(1) with the tap off the replay of the call of 10:27 gives exactly the actions it gave, and no file is written; (2) in shadow the actions are still
identical and every line of the record validates against the JSON Schema of contract 1 (tests/fixtures/v5_contract_schemas.json, extracted from
contracts/v5); (3) two threads calling entries at once never interleave inside the controller. Nothing here measures a call.
"""
import json
import re
import threading
import time
from pathlib import Path

import pytest

from echo_sync import ear_shadow, settings as cfg
from echo_sync import v5_tap
from echo_sync.controlled_media import ControlledMedia
from test_h3_tempo import call      # noqa: F401 - the fixture
from test_h7 import CALL_1027_REPLAY, replay_1027      # noqa: F401

SCHEMAS = json.loads((Path(__file__).parent / 'fixtures' / 'v5_contract_schemas.json').read_text(encoding='utf-8'))
HEX = re.compile(r'[0-9a-f]{32}')


def plain(x):
    return HEX.sub('#', json.dumps(x, sort_keys=True, default=str))


def lines(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def validator():
    jsonschema = pytest.importorskip('jsonschema')
    referencing = pytest.importorskip('referencing')
    from referencing.jsonschema import DRAFT202012
    registry = referencing.Registry().with_resources([(s['$id'], DRAFT202012.create_resource(s)) for s in SCHEMAS.values()])
    return jsonschema.Draft202012Validator(SCHEMAS['echo/v5/event.json'], registry=registry)


def actions_in(text):
    value = json.loads(text)
    return sum(isinstance(x, dict) for x in value) if isinstance(value, list) else int(isinstance(value, dict))


def taps(directory):
    return sorted(Path(directory).glob('*.v5tap*.jsonl'))


# -- the setting ------------------------------------------------------------------------------------------------------------------------------------------------------

def test_the_size_is_the_only_setting_and_there_is_no_switch():
    assert 'v5_tap' not in cfg.DEFAULTS and 'v5_tap' not in cfg.resolve({'v5_tap': 'shadow'}) and cfg.DEFAULTS['v5_tap_mb'] == 48
    assert cfg.resolve({'v5_tap_mb': 100})['v5_tap_mb'] == 100 and cfg.resolve({'v5_tap_mb': 1})['v5_tap_mb'] == 48


# -- (1) no folder: nothing changes, no file --------------------------------------------------------------------------------------------------------------------------------

def test_without_a_folder_nothing_is_wrapped_and_no_file_is_written(call, tmp_path):
    rig = call(fast_text='on')
    assert v5_tap.attach(rig.c, rig.settings, None, 'abc', clock=rig.w.clock.now) is None, 'no folder, no record'
    assert not [name for name in vars(rig.c) if name in v5_tap.ENTRIES + v5_tap.LOCKED], 'the controller keeps its own methods'
    rig.pump(1.0)
    assert list(tmp_path.iterdir()) == []


# -- (1)+(2) the replay of the call of 10:27, off and in shadow -------------------------------------------------------------------------------------------------------

class Returns:
    """What the controller gave back at its entries, outermost call by outermost call (the class-level recorder sits under the tap)."""

    def __init__(self, monkeypatch):
        self.rows, self.depth = [], 0
        for name in v5_tap.ENTRIES:
            original = getattr(ControlledMedia, name, None)
            if callable(original) and not isinstance(original, property):
                monkeypatch.setattr(ControlledMedia, name, self.wrap(name, original))

    def wrap(self, name, original):
        def seen(controller, *args, **kw):
            self.depth += 1
            try:
                result = original(controller, *args, **kw)
            finally:
                self.depth -= 1
            if not self.depth:
                self.rows.append((name, plain(args), plain(kw), plain(result)))
            return result
        return seen


def run_1027(call, monkeypatch, tmp_path, returns):
    """As the host does it: the tap is attached to the controller before the ear is built (the ear keeps ``ear_speech`` and ``ear_onset`` of the controller)."""
    returns.rows, made = [], []
    original = ear_shadow.for_call

    def build(settings, controller, **kw):
        made.append(v5_tap.attach(controller, settings, tmp_path, 'c1027', clock=kw.get('clock')))
        return original(settings, controller, **kw)
    with monkeypatch.context() as scope:
        scope.setattr(ear_shadow, 'for_call', build)
        rig = call(fast_text='on', max_auto_repeats=3)
    [tap] = made
    cues = replay_1027(rig, monkeypatch)
    rig.fast.close()
    if tap:
        tap.close()
    frames = [(round(t, 3), plain(f)) for _, t, f in rig.w.frames]
    return list(returns.rows), frames, [(round(a, 3), text) for a, text, _ in cues], tap


def test_the_replay_gives_the_same_actions_off_and_in_shadow_and_the_record_is_valid(call, monkeypatch, tmp_path):
    off_dir, shadow_dir = tmp_path / 'off', tmp_path / 'shadow'
    off_dir.mkdir(), shadow_dir.mkdir()
    returns = Returns(monkeypatch)
    base = run_1027(call, monkeypatch, None, returns)
    assert list(off_dir.iterdir()) == [] and base[3] is None and base[0] and base[1] and base[2]
    shadow = run_1027(call, monkeypatch, shadow_dir, returns)
    assert shadow[0] == base[0], 'every action the controller returned is the same'
    assert shadow[1] == base[1], 'and every frame the phone got'
    assert shadow[2] == base[2]
    [path] = taps(shadow_dir)
    assert path.name.endswith('-c1027.v5tap.jsonl'), 'next to the call journal, with the same call id'
    rows = lines(path)
    check = validator()
    bad = [(r['id'], [e.message for e in check.iter_errors(r)][:2]) for r in rows if not check.is_valid(r)]
    assert not bad, bad[:3]
    assert [r['id'] for r in rows] == list(range(len(rows))), 'ids in order'
    ins = [r for r in rows if r['payload'].get('flags', {}).get('tap') == 'in']
    outs = [r for r in rows if r['payload'].get('flags', {}).get('tap') == 'out']
    assert rows[0]['kind'] == 'capability' and rows[0]['key'] == ['server'] and rows[0]['payload']['flags']['call'] == 'c1027'
    assert {'tick', 'provider'} <= {r['payload']['flags']['entry'] for r in ins}
    assert len(ins) == len(base[0]), 'one input record per outermost entry call'
    assert outs and {'speak', 'cancel'} & {r['payload']['flags']['action'].get('type') for r in outs}
    ids = {r['id'] for r in ins}
    assert all(r['causes'] and set(r['causes']) <= ids for r in outs), 'an effect is caused by the entry that returned it'
    assert all(r['t_event'] <= r['t_seen'] for r in rows) and all(b['t_seen'] >= a['t_seen'] for a, b in zip(rows, rows[1:]))
    returned = sum(actions_in(r[3]) for r in base[0])
    assert len(outs) == returned, 'one effect per action dictionary returned'


def test_the_record_has_the_shape_of_the_contract_even_without_the_validator(tmp_path):
    class Fake:
        def tick(self, *, now):
            return [{'type': 'cancel', 'epoch': 1}, {'type': 'speak', 'text': 'да'}]
    fake = Fake()
    tap = v5_tap.attach(fake, {}, tmp_path, 'k', clock=lambda: 10.0)
    fake.tick(now=10.5)
    tap.close()
    rows = lines(taps(tmp_path)[0])
    assert [r['payload']['flags']['tap'] for r in rows] == ['open', 'in', 'out', 'out']
    for r in rows:
        assert set(r) == {'v', 'id', 'kind', 'key', 'rev', 't_event', 't_seen', 'source', 'payload', 'causes'} and r['v'] == 2
        assert re.match(SCHEMAS['echo/v5/event.json']['properties']['source']['pattern'], r['source'])
        assert re.match(SCHEMAS['echo/v5/event.json']['properties']['kind']['pattern'], r['kind'])
        assert isinstance(r['key'], list) and r['key'] and all(isinstance(x, int) and x >= 0 for x in (r['id'], r['rev'], r['t_event'], r['t_seen']))
    assert rows[1]['payload']['flags']['args'] == [] and rows[1]['payload']['flags']['kw'] == {'now': 10.5}
    assert [r['payload']['flags']['action']['type'] for r in rows[2:]] == ['cancel', 'speak'] and rows[2]['causes'] == [rows[1]['id']]


# -- (3) one lock: entries never interleave ---------------------------------------------------------------------------------------------------------------------------

class Probe:
    """A controller whose entries each hold a flag and look at it: two inside at once is a failure."""

    def __init__(self):
        self.inside, self.worst, self.order = 0, 0, []

    def _in(self, name):
        self.inside += 1
        self.worst = max(self.worst, self.inside)
        self.order.append(('in', name))
        time.sleep(0.0005)
        self.order.append(('out', name))
        self.inside -= 1

    def tick(self, *, now):
        self._in('tick')
        return []

    def provider(self, event):
        self._in('provider')
        self.tick(now=0)            # an entry that calls another entry: one lock, taken twice by one thread
        return [{'type': 'cancel'}]

    def mic_packet(self, nbytes, dbfs=None, now=None):
        self._in('mic_packet')

    def ear_heard(self, record):
        self._in('ear_heard')
        return [{'type': 'speak', 'text': record}]

    def authorized(self, cue):
        self._in('authorized')
        return True


def test_two_threads_never_interleave_inside_the_controller(tmp_path):
    probe = Probe()
    tap = v5_tap.attach(probe, {}, tmp_path, 'thr')
    assert tap is not None
    errors = []

    def hammer(calls):
        try:
            for _ in range(60):
                for name, args, kw in calls:
                    getattr(probe, name)(*args, **kw)
        except Exception as error:      # noqa: BLE001
            errors.append(error)
    threads = [threading.Thread(target=hammer, args=(calls,)) for calls in (
        [('tick', (), {'now': 1.0}), ('provider', ({'type': 'x'},), {})],
        [('ear_heard', ('слово',), {}), ('mic_packet', (480,), {'dbfs': -30.0}), ('authorized', ({'text': 'a'},), {})],
        [('provider', ({'type': 'y'},), {}), ('tick', (), {'now': 2.0})])]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    tap.close()
    assert not errors and not any(t.is_alive() for t in threads), 'no deadlock, no error'
    assert probe.worst == 1, 'never two entries inside at once'
    depth = 0
    for kind, _ in probe.order:
        depth += 1 if kind == 'in' else -1
        assert 0 <= depth <= 1, 'an entry is left before the next is entered'
    rows = lines(taps(tmp_path)[0])
    ins = [r for r in rows if r['payload']['flags']['tap'] == 'in']
    assert len(ins) == 60 * 6, 'the locked-only entry (authorized) is not recorded; the tick inside a provider is not an entry of its own'
    assert {r['payload']['flags']['entry'] for r in ins} == {'tick', 'provider', 'ear_heard', 'mic_packet'}
    assert 'authorized' not in {r['payload']['flags'].get('entry') for r in rows}


def test_an_exception_of_the_controller_goes_through_and_is_recorded(tmp_path):
    class Boom:
        def tick(self, *, now):
            raise ValueError('x')
    boom = Boom()
    tap = v5_tap.attach(boom, {}, tmp_path, 'bm')
    with pytest.raises(ValueError):
        boom.tick(now=1)
    with pytest.raises(ValueError):
        boom.tick(now=2)
    tap.close()
    assert [r['payload']['flags']['tap'] for r in lines(taps(tmp_path)[0])] == ['open', 'in', 'raised', 'in', 'raised']


# -- bounds and isolation ----------------------------------------------------------------------------------------------------------------------------------------------

def test_the_record_is_a_ring_of_two_halves_and_never_outgrows_its_cap(tmp_path):
    class Fake:
        def tick(self, *, now):
            return [{'type': 'speak', 'text': 'я' * 80}]
    fake = Fake()
    tap = v5_tap.attach(fake, {}, tmp_path, 'ring', max_bytes=6000)
    for n in range(400):
        fake.tick(now=float(n))
    tap.close()
    [current], [previous] = [f for f in taps(tmp_path) if '.prev.' not in f.name], [f for f in taps(tmp_path) if '.prev.' in f.name]
    assert current.stat().st_size + previous.stat().st_size <= 6000 + 600
    rows = lines(previous) + lines(current)
    assert rows[-1]['payload']['flags']['action']['text'] == 'я' * 80 and rows[-1]['payload']['flags']['tap'] == 'out', 'the newest is kept'
    head = lines(current)[0]
    assert head['payload']['truncated'] is True and head['id'] > 0, 'the fresh half says it is a fragment'
    ids = [r['id'] for r in rows]
    assert ids == sorted(ids) and len(set(ids)) == len(ids) and ids[0] > 0, 'the oldest are gone, the order is kept'


def test_old_record_files_are_pruned_and_the_journal_files_are_not_touched(tmp_path):
    for n in range(8):
        (tmp_path / f'20261101-00000{n}-old{n}.v5tap.jsonl').write_text('{}\n')
    (tmp_path / '20261101-000000-jour.jsonl').write_text('{}\n')
    v5_tap.attach(object(), {}, tmp_path, 'new', keep=3).close()
    assert len(taps(tmp_path)) == 3 and (tmp_path / '20261101-000000-jour.jsonl').exists()


def test_a_record_that_cannot_be_written_never_costs_the_call(tmp_path):
    blocker = tmp_path / 'file'
    blocker.write_text('x')

    class Fake:
        def tick(self, *, now):
            return [{'type': 'speak', 'blob': object(), 'bytes': b'\x00' * 10}]
    fake = Fake()
    assert v5_tap.attach(fake, {}, blocker / 'sub', 'z') is None, 'a folder that cannot be made: no tap, nothing wrapped'
    assert 'tick' not in vars(fake)
    tap = v5_tap.attach(fake, {}, tmp_path, 'odd')
    assert fake.tick(now=1)[0]['type'] == 'speak'      # an action that cannot be written as JSON is still returned
    tap._file.close()                                   # the file goes away under the tap: the call goes on, the tap switches itself off
    assert fake.tick(now=2)[0]['type'] == 'speak' and tap.failure
    tap.close()


def test_the_host_attaches_the_tap_and_closes_it():
    source = (Path(__file__).parent.parent / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')
    assert source.count('v5_tap.attach(') == 1 and 'v5tap.close()' in source
    assert source.index('v5_tap.attach(') < source.index('wire=NativeMediaSocket('), 'attached before the wire takes its first method'


import pytest as _pytest_mic  # noqa: E402


@_pytest_mic.fixture(autouse=True)
def _own_microphone(monkeypatch):
    """This file feeds its own microphone packets (or none: a lost line): the live line of the world stays off (helpers_live_line)."""
    import helpers_s6_state
    monkeypatch.setattr(helpers_s6_state.World, 'mic_stream', False)

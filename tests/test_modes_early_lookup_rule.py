"""One rule for the early lookup (modes, conduit-prefetch): the call's ``ear_lookup`` turns it on. The host key ``controlled_prefetch_enabled`` and the probe's
own switch are gone; a probe asks for the same rule with ``echo_prefetch=0|1`` (settings.resolve(raw, probe)). A real ``ControlledMedia`` hands the wire its modes."""
import asyncio
from pathlib import Path

from echo_sync import controlled_host, native_media_socket
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket
from echo_sync.settings import resolve
from tools.replay import stand as A

EAR = {'local_ear': 'act', 'fast_text': 'on', 'prepare_wide': 'on', 'ear_job': 'on'}


def early(profile):
    st = A.Stand(0, profile={**EAR, **profile})
    try:
        return st.w.wire.early.enabled
    finally:
        st.close()


def test_the_calls_ear_lookup_turns_the_early_lookup_on_and_off_is_off():
    assert early({'ear_lookup': 'on'}) is True and early({}) is False


def test_the_stand_key_still_turns_it_on_for_the_speed_sets():
    assert early({'prefetch': 'on'}) is True


def _wire(tmp_path, settings):
    async def emit(event):
        pass
    c = ControlledMedia(tmp_path / 's.db', session_id='s', source_delivery='delegation', settings=settings)
    return NativeMediaSocket(c, emit, None, None, None)


def test_a_real_controller_gives_the_wire_the_rule(tmp_path):
    assert _wire(tmp_path, {**EAR, 'ear_lookup': 'on'}).early.enabled is True
    assert _wire(tmp_path, {}).early.enabled is False
    assert _wire(tmp_path, {'ear_lookup': 'on'}).early.enabled is False      # no ear job, no early lookup: resolve turns it off (the dependency is the rule's)


def test_a_probe_asks_for_the_rule_and_a_phone_call_cannot():
    on = resolve(resolve(EAR), {'echo_prefetch': '1'})
    off = resolve(resolve({**EAR, 'ear_lookup': 'on'}), {'echo_prefetch': '0'})
    assert on['ear_lookup'] == 'on' and off['ear_lookup'] == 'off'
    phone = resolve(EAR)
    assert resolve(phone) is phone and phone['ear_lookup'] == 'off'


def test_the_host_key_and_the_probe_switch_are_gone_from_the_code():
    root = Path(controlled_host.__file__).parent
    text = ''.join(p.read_text(encoding='utf-8') for p in root.glob('*.py') if p.name != 'ear_prefetch.py')
    assert 'controlled_prefetch_enabled' not in text and 'prefetch=prefetch' not in text

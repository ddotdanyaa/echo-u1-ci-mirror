"""V6 E92.1: «the order of the ICE attempts and the 8 s timeout: half of nine opens of 02.11 waited out the timeout of the first try; the probe could take another order, the live call could not». On the base the
order is ONE rule (``controlled_host.ice_tries``: host candidates first, STUN the retry; commit 90e99056 «ICE order is one rule»), the loop is ``open_with_retry`` (a0e87599). Guard through the real loop of the host on
the virtual clock (the Rig of test_stun_first): a first try that does not connect is cut at the connect timeout and the retry is the STUN one; both tries are bounded. The 15.29 s open of 02.11 is a
measurement of the network of that day: it stays with the phone."""
import pytest

from test_stun_first import RUNTIME, STUN, Rig          # noqa: F401
from echo_sync import controlled_host


def test_host_candidates_first_the_stun_retry_when_the_first_try_does_not_connect(monkeypatch):
    assert controlled_host.ice_tries(__import__('types').SimpleNamespace(WATCH_AUDIO_STUN=STUN)) == ((), STUN)
    rig = Rig({'stun'}, connect_timeout=5)
    result, spent = rig.open(monkeypatch)
    assert [bridge.stun for bridge in rig.bridges] == [[], list(STUN)] and result is rig.bridges[1]
    assert 5 <= spent < 12, 'the first try is cut at its own timeout, not at a longer one'


def test_the_cut_of_one_try_is_one_number_and_the_tries_are_two():
    assert controlled_host.UPSTREAM_OPEN_ATTEMPTS == 2 and controlled_host.UPSTREAM_OPEN_TIMEOUT_S > 0

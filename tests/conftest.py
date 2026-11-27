"""h28: ``logging.disable`` is process-wide. A test that silences the log for speed left it silenced for every test after it (test_classifier, test_decision_privacy: «no logs of level INFO»)."""
import logging
import sys
import threading

import pytest


@pytest.fixture(autouse=True)
def _logging_comes_back():
    yield
    logging.disable(logging.NOTSET)


_FIRST = {}


@pytest.fixture(autouse=True)
def _stand_patches_come_back():
    """h31: tools.replay.stand.Stand patches helpers_s6_state.host_kwargs and echo_sync.fast_text.threading until close().
    A test that never closed its Scene (test_c25_a_live, test_c25_b_cases; integ-c19 was half_hour) left them for every test
    after it: 351 false reds in the full run (S14 «given up after 1.64 s», IndexError in test_t_new_classes, h1 fast_text default)."""
    S = sys.modules.get('helpers_s6_state')
    if S is not None:
        _FIRST.setdefault('host_kwargs', S.host_kwargs)
    yield
    S, FT = sys.modules.get('helpers_s6_state'), sys.modules.get('echo_sync.fast_text')
    if S is not None and 'host_kwargs' in _FIRST:
        S.host_kwargs = _FIRST['host_kwargs']
    if FT is not None:
        FT.threading = threading


@pytest.fixture(autouse=True)
def _the_rests_of_the_roads_do_not_outlive_a_test():
    """The rests of the roads (``reserve_text._REST``, ``_PRIMARY``) and what the providers last said (``_BUDGET``) live in the process, as they do for the calls of one server: a test starts with none and leaves none
    (a job thread of an earlier test that rests the first road late would put the next test's channel to rest on another clock)."""
    def clear():
        RT = sys.modules.get('echo_sync.reserve_text')
        if RT is not None:
            RT._REST.clear()
            RT._BUDGET.clear()
            RT._PRIMARY['until'] = 0.0
    clear()
    yield
    clear()

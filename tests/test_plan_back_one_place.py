"""portion / suspended-plan (16.11): the plan a question took over has ONE keeper (``_suspend_plan``) and ONE way back (``_plan_back``: ``engine.resume_entry``).
Words said to the plan, «продолжай», the cloud's decline, an overruled ear and the fast text's command all go through it; the lock counts places, it lists no phrase."""
import re

import pytest
from cm_patch import controller_source

import echo_sync.controlled_media as cm
from test_g3_arbiter import FIRST, Q, SECOND, admitted_intruder      # noqa: F401  (the scene of the wire: an admitted intruder over a waiting plan)


def _methods():
    """``{method name: text}`` of the controller's modules."""
    text = controller_source()
    parts = re.split(r'(?m)^    (?:@staticmethod\n    )?def (\w+)\(', text)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def test_the_engine_gives_a_plan_back_in_one_place_and_it_is_kept_in_one():
    methods = _methods()
    callers = sorted(name for name, body in methods.items() if '.resume_entry(' in body)
    assert callers == ['_plan_back', '_speech_resumes'], callers      # the speech is the plan of the call, no plan a question took over
    keepers = sorted(name for name, body in methods.items() if re.search(r'self\.suspended=\{', body))
    assert keepers == ['_suspend_plan'], keepers
    for old in ('_plan_stands',):
        assert old not in methods, old


@pytest.mark.parametrize('text, explicit', [(FIRST, False), ('Продолжай', True)])
def test_words_and_prodolzhay_take_the_plan_back_through_the_one_way(tmp_path, monkeypatch, text, explicit):
    calls = []
    original = cm.ControlledMedia._plan_back

    def counted(self, held, **kwargs):
        calls.append(kwargs.get('explicit', False))
        return original(self, held, **kwargs)
    monkeypatch.setattr(cm.ControlledMedia, '_plan_back', counted)
    w = admitted_intruder(tmp_path)
    w.user('u3', text, 7.5, 8.2)
    w.until(10.0)
    assert calls == [explicit], calls
    assert w.state()['question'] == Q and w.played_after(7.5) == ([SECOND] if not explicit else [FIRST]), w.played

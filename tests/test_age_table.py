"""cm-age-thresholds: the ages of the call (how old a thing may be to count) are numbers of timer_policy, defined once; no module of echo_sync writes its own."""
import ast
import re
from pathlib import Path

from echo_sync import timer_policy as tp

AGES = ('WITNESS_SLACK_SECONDS', 'FIGURE_STILL_SECONDS', 'NO_AFTER_CUE_SECONDS', 'FIGURE_HEAD_SECONDS', 'ABANDON_SECONDS', 'PLAN_BACK_SECONDS',
        'PLAYED_FRESH_S', 'READ_USER_WINDOW_S', 'CONTEXT_AGE_S')
GONE = ('UNANSWERED_SECONDS', 'READ_WINDOW_S')
SRC = Path(tp.__file__).resolve().parent


def _assigned(path):
    return {t.id for n in ast.parse(path.read_text(encoding='utf-8')).body if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}


def test_every_age_is_defined_in_timer_policy_only():
    for path in sorted(SRC.glob('*.py')):
        mine = _assigned(path) & (set(AGES) | set(GONE))
        assert mine == (set(AGES) if path.name == 'timer_policy.py' else set()), (path.name, mine)


def test_the_old_names_are_gone_from_the_code():
    text = '\n'.join(p.read_text(encoding='utf-8') for p in SRC.glob('*.py'))
    assert not re.search(r'\b(%s)\b' % '|'.join(GONE), text)


def test_the_readers_see_the_one_number_and_the_registry_holds_it():
    import cm_patch
    for name in AGES:
        key = 'timer_policy.' + name
        assert key in tp.TIMERS, key
        for module in cm_patch.controller_modules():
            if hasattr(module, name):
                assert getattr(module, name) == tp.value(key), (module.__name__, name)
    assert (tp.CONTEXT_AGE_S, tp.READ_USER_WINDOW_S) == (120.0, 60)
    assert tp.unregistered() == [] and tp.stale() == [] and tp.unscanned_modules() == []
    assert not [v for v in tp.validate({}) if v.rule == 'R12']

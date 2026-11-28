"""U94.5 / U40 (M5): ``repeat_at`` has one writer, ``_arm``, in the timers module; the writers still elsewhere are counted and the count only goes down; a timer armed for a question does not fire after the question changed."""
import ast
import pathlib

import helpers_s6_state as S
from echo_sync import timer_policy as tp
from test_h3_tempo import call      # noqa: F401 - the fixture

ECHO = pathlib.Path(tp.__file__).parent


def answered(rig, question='Сколько будет сорок на два', answer='Восемьдесят. Это ответ.'):
    rig.w.feed(S.turn_created('u1', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('u1', 'user', question))
    rig.w.feed(S.turn_done('a1', 'assistant', answer))
    return rig.c


# --- U94.5 / U40: one writer of repeat_at --------------------------------------------------------------------------------------------------

def _writes(path, slot='repeat_at'):
    """[(function, line)] of the stores ``self.<slot> = ...`` in a file (the AST: a comment or a string does not count)."""
    found = []

    def walk(node, function):
        for child in ast.iter_child_nodes(node):
            name = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if isinstance(child, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for t in targets:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Attribute) and x.attr == slot and isinstance(x.ctx, ast.Store):
                            found.append((function, child.lineno))
            walk(child, name)
    walk(ast.parse(path.read_text(encoding='utf-8')), None)
    return found


# Writers outside ``_arm`` at P08 (file -> count). Moving a writer to ``self._arm(...)`` is striking its row; a new one is red. The goal is {}; the one left is ``ControlledMedia.__init__`` (the slot's first value, not a writer of a moment).
REPEAT_AT_WRITERS = {}      # the goal of the count is reached: the last store left, in the class body of controlled_media.py, is the slot's declaration (``repeat_at=Stamped('epoch',None)``), not a write of a moment


def test_repeat_at_has_one_writer_in_the_timers_module_and_the_rest_only_go_down():
    timers = _writes(ECHO / 'cm_timers.py')
    assert timers == [('_arm', timers[0][1])], timers
    now = {}
    for path in sorted(ECHO.glob('*.py')):
        if path.name == 'cm_timers.py':
            continue
        n = len(_writes(path))
        if n:
            now[path.name] = n
    assert now == REPEAT_AT_WRITERS, ('a writer moved to _arm: strike it; a new one: use _arm', now)


def test_a_silence_timer_armed_for_a_question_is_gone_when_the_question_is_(call):
    """U40 through the tick: the repeat armed before the question changed does not fire after it (the slot is stamped with the reply token; the owner drops it)."""
    rig = call()
    c = answered(rig)
    c._arm(c.clock() + 1.0)
    assert c.repeat_at is not None
    c._new_epoch('open_question')
    assert c.repeat_at is None
    rig.w.clock.t += 30
    assert c.tick(now=c.clock()) == [], 'nothing is said again for the old question'

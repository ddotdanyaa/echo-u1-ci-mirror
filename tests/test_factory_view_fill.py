"""<id> step 1 (skeptic verdict light-view-bound, 20.11): 86 of 143 kept no-change answers (60%) needed code the model
was not shown, while those prompts used a median of 12-19K of their 28K characters and the hidden targets were 0.2-2.9K
each. The coordinator's replay of 96 failed SEARCH blocks (20.11 07:10) agrees: 34 aimed at a definition the rebuilt
view did not show at all, 29 at one it showed only in part, 5 at one it showed whole. The room left after the named
parts now goes to WHOLE definitions the shown code uses (what it calls or reads, then what those use), never past the
room, never one larger than a fragment, never one already visible; a definition the shown code does not use stays
hidden."""
from tools import factory_context as X

SRC = ('def other(x):\n    return x * 3\n\n\n'
       'def helper_b(x):\n    return x - 1\n\n\n'
       'def helper_a(x):\n    return helper_b(x) + 2\n\n\n'
       'def target(x):\n    return helper_a(x)\n')


def test_the_room_left_is_filled_with_what_the_shown_code_calls_and_what_that_calls():
    view = X._fragments(SRC, {'target'}, 5000)
    assert 'def target(x):\n    return helper_a(x)' in view
    assert 'def helper_a(x):\n    return helper_b(x) + 2' in view
    assert 'def helper_b(x):\n    return x - 1' in view
    assert 'def other' not in view                     # nothing shown uses it


def test_the_fill_never_passes_the_room_and_takes_the_nearer_relation_first():
    for room in range(30, 400, 7):
        view = X._fragments(SRC, {'target'}, room)
        assert len(view) <= room
        assert 'def helper_b' not in view or 'def helper_a' in view


def test_a_used_definition_larger_than_a_fragment_is_not_pulled_in():
    huge = 'def helper_a(x):\n' + ''.join('    x += %d\n' % i for i in range(X.FRAGMENT_MAX_CHARS // 8)) + '    return x\n'
    src = huge + '\n\ndef target(x):\n    return helper_a(x)\n'
    view = X._fragments(src, {'target'}, 50000)
    assert 'def target(x)' in view and 'def helper_a' not in view


def test_a_method_called_through_self_is_shown_and_an_unused_one_is_not():
    src = ('class Worker:\n'
           '    def run(self):\n        return self._step() + 1\n\n'
           '    def _step(self):\n        return 41\n\n'
           '    def unrelated(self):\n        return 0\n')
    view = X._fragments(src, {'run'}, 5000)
    assert 'def _step(self):\n        return 41' in view
    assert 'def unrelated' not in view


def test_a_module_constant_the_shown_code_reads_is_shown():
    src = 'LIMIT = 5\nOTHER = 7\n\n\n' + ''.join('def f%d():\n    return %d\n\n\n' % (i, i) for i in range(20)) + \
        'def target(x):\n    return min(x, LIMIT)\n'
    view = X._fragments(src, {'target'}, 5000)
    assert 'LIMIT = 5' in view and 'OTHER = 7' not in view


def test_a_definition_already_visible_inside_a_shown_one_is_not_shown_twice():
    src = 'def outer(a):\n    def inner(b):\n        return b\n    return inner(a)\n'
    view = X._fragments(src, {'outer'}, 5000)
    assert view.count('def inner(b)') == 1


def test_the_light_coder_prompt_of_a_large_file_shows_the_helpers_of_the_named_function():
    from tools import agent_factory_runner as W
    from tools.agent_factory import read_plan
    task = read_plan([dict(id='T1', title='fix target', touch_files=['big.py'], read_files=[],
                           tests=['tests/test_big.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    smalls = ''.join('def small_%d(x):\n    return x + %d\n\n\n' % (i, i) for i in range(500))
    visible = {'big.py': (smalls + SRC).encode(), 'tests/test_big.py': b'def test_x():\n    assert True\n'}
    prompt = W.build_coder_prompt(task, visible, None, light=True)
    assert 'def helper_b(x):\n    return x - 1' in prompt
    assert 'return x + 17\n' not in prompt                # an unrelated small function stays in the outline only

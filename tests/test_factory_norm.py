"""One normalizer of a model answer (light engine): a repeated block is applied once, the reasoning before the answer
is dropped, a CANNOT after the '# WHY:' line is a CANNOT, CRLF is matched as LF and kept on write. Two equal changes
at different places of a file stay two changes."""
import json
from dataclasses import replace

import pytest

from tools import agent_factory as F
from tools import agent_factory_runner as W


def task(touch=('calc.py',)):
    base = F.read_plan([dict(id='T1', title='Fix sum', touch_files=['calc.py'], read_files=[],
                             tests=['tests/test_calc.py'], privacy_safe=True, estimated_tokens=100)])['T1']
    return replace(base, touch_files=tuple(touch))


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError('a test reached the network')
    monkeypatch.setattr(W, '_light_post', refuse)
    monkeypatch.setenv('GOOGLE_GENERATIVE_AI_API_KEY', 'synthetic')


def reply(content, finish='stop'):
    body = dict(choices=[dict(message=dict(content=content), finish_reason=finish)],
                usage=dict(prompt_tokens=500, completion_tokens=20))
    return lambda url, key, payload, timeout: (200, json.dumps(body).encode())


def answer(text, folder):
    return W.light_attempt(task(), folder, 'google/gemma-4-31b-it', prompt_override='p', post=reply(text))


def block(search, new, name='calc.py'):
    return '%s\n<<<<<<< SEARCH\n%s\n=======\n%s\n>>>>>>> REPLACE\n' % (name, search, new)


SOURCE = 'def gate():\n    open_gate()\n    return 1\n'


def test_an_anchor_block_given_three_times_adds_its_line_once(tmp_path):
    (tmp_path / 'calc.py').write_text(SOURCE)
    insert = block('    open_gate()', '    open_gate()\n    gate_talk()')
    rc, _, note = answer('# WHY: the gate must talk\n' + insert * 3, tmp_path)
    assert (tmp_path / 'calc.py').read_text() == 'def gate():\n    open_gate()\n    gate_talk()\n    return 1\n'
    assert rc == 0 and 'repeated block applied once x2' in note.decode()


def test_a_replacement_block_given_twice_is_applied_once_not_refused(tmp_path):
    (tmp_path / 'calc.py').write_text(SOURCE)
    change = block('    return 1', '    return 2')
    _, _, note = answer(change + change, tmp_path)
    assert 'SEARCH not found' not in note.decode()
    assert (tmp_path / 'calc.py').read_text() == SOURCE.replace('return 1', 'return 2')


def test_two_equal_changes_at_different_places_are_both_applied(tmp_path):
    (tmp_path / 'calc.py').write_text('def a():\n    first()\n\ndef b():\n    second()\n')
    text = (block('    first()', '    first()\n    gate_talk()') + block('    second()', '    second()\n    gate_talk()'))
    _, _, note = answer(text, tmp_path)
    assert (tmp_path / 'calc.py').read_text() == \
        'def a():\n    first()\n    gate_talk()\n\ndef b():\n    second()\n    gate_talk()\n'
    assert 'repeated' not in note.decode()


def test_the_same_block_applied_again_at_a_new_place_is_a_second_change(tmp_path):
    """foo -> baz, then bar -> foo makes a new foo: the same foo -> baz block meets another place and is applied."""
    (tmp_path / 'calc.py').write_text('foo\nbar\n')
    text = block('foo', 'baz') + block('bar', 'foo') + block('foo', 'baz')
    answer(text, tmp_path)
    assert (tmp_path / 'calc.py').read_text() == 'baz\nbaz\n'


def test_the_same_block_for_two_files_changes_both(tmp_path):
    for name in ('a.py', 'b.py'):
        (tmp_path / name).write_text(SOURCE)
    blocks, _ = W.parse_edit_blocks(block('    return 1', '    return 2', 'a.py') +
                                    block('    return 1', '    return 2', 'b.py'), ('a.py', 'b.py'))
    applied, failed = W.apply_edit_blocks(tmp_path, blocks)
    assert not failed and sorted(applied) == ['a.py', 'b.py']


def test_a_cannot_after_the_why_line_is_a_cannot(tmp_path):
    (tmp_path / 'calc.py').write_text(SOURCE)
    _, _, note = answer('# WHY: the shown code has no such branch\nCANNOT: _route_turn', tmp_path)
    assert note.decode() == 'the model answered CANNOT: _route_turn'


def test_an_unclosed_thought_keeps_the_answer_after_it(tmp_path):
    (tmp_path / 'calc.py').write_text(SOURCE)
    draft = block('    return 1', '    return 7')
    final = '# WHY: the value must be 2\n' + block('    return 1', '    return 2')
    answer('<thought>maybe\n' + draft + final, tmp_path)
    assert (tmp_path / 'calc.py').read_text() == SOURCE.replace('return 1', 'return 2')


def test_a_crlf_answer_on_a_crlf_file_matches_and_the_file_stays_crlf(tmp_path):
    (tmp_path / 'calc.py').write_bytes(SOURCE.replace('\n', '\r\n').encode())
    change = block('    return 1', '    return 2').replace('\n', '\r\n')
    answer(change + change, tmp_path)
    assert (tmp_path / 'calc.py').read_bytes() == SOURCE.replace('return 1', 'return 2').replace('\n', '\r\n').encode()


@pytest.mark.parametrize('line', ['    # cannot: reach the gate here', '    msg = (\n        "Cannot find the file %s" % name)'])
def test_a_cut_answer_with_a_cannot_line_inside_its_code_is_still_cut(tmp_path, line):
    (tmp_path / 'calc.py').write_text(SOURCE)
    cut = '# WHY: the gate must talk\n' + block('    return 1', line + '\n    return 2')[:-30]
    rc, err, _ = W.light_attempt(task(), tmp_path, 'google/gemma-4-31b-it', prompt_override='p',
                                 post=reply(cut, finish='length'))
    assert rc == 1 and b'cut by the output limit' in err
    assert (tmp_path / 'calc.py').read_text() == SOURCE


def test_a_cut_cannot_answer_before_any_block_is_a_cannot_not_a_cut():
    assert W.answer_cannot('# WHY: no such branch\nCANNOT: _route_turn') == '_route_turn'
    assert W.answer_cannot('calc.py\n<<<<<<< SEARCH\nx\n=======\n# CANNOT: y\n>>>>>>> REPLACE\n') is None


def test_a_function_block_met_again_after_another_one_is_applied_again(tmp_path):
    """A(f -> v1), B(f -> v2), A again: the last word is v1, as before the normalizer (critic W-norm 3)."""
    (tmp_path / 'calc.py').write_text(SOURCE)

    def func(value):
        return 'REPLACE FUNCTION calc.py gate\n```python\ndef gate():\n    open_gate()\n    return %d\n```\n' % value
    blocks, _ = W.parse_edit_blocks(func(3) + func(4) + func(3), ('calc.py',))
    W.apply_edit_blocks(tmp_path, blocks)
    assert (tmp_path / 'calc.py').read_text() == SOURCE.replace('return 1', 'return 3')
    blocks, _ = W.parse_edit_blocks(func(5) + func(5), ('calc.py',))
    applied, failed = W.apply_edit_blocks(tmp_path, blocks)
    assert not failed and applied.repeats == 1 and 'return 5' in (tmp_path / 'calc.py').read_text()


def test_the_loop_reads_a_cannot_of_the_last_answer_by_the_one_parse():
    assert W.said_cannot('', '# WHY: x\nCannot find the file echo_sync/a.py') == 'Cannot find the file echo_sync/a.py'
    assert W.said_cannot('', 'calc.py\n<<<<<<< SEARCH\nx\n=======\n# CANNOT: y\n>>>>>>> REPLACE\n') is None
    assert W.said_cannot('the model answered CANNOT: _route_turn', 'CANNOT: other') == '_route_turn'
    assert W.said_cannot('', '# WHY: w\nCANNOT: _route_turn\nmore') == '_route_turn'


def test_one_stripper_for_every_reasoning_tag_and_the_architect_uses_it():
    from tools import factory_architect as A
    assert W.strip_thought('<thinking>draft</thinking>\n# WHY: w\nCANNOT: x') == '# WHY: w\nCANNOT: x'
    assert W.strip_thought('<thinking>never closed ["Engine"]', last=None, first=None) == ''
    assert A._keyword_candidates('<thinking>["Input"]</thinking>\n["Engine"]') == ['Engine']
    assert 'Engine' not in (A._keyword_candidates('<thinking>never closed ["Engine"]') or [])

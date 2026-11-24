"""fac-context-budget (live 19.11 21:24): the loop blocked <id>_test, <id>_test, <id> and <id> as
context_too_large although their files fit the light prompt easily (<id>_test: 3 491 + 8 171 bytes against a
prompt limit of 28 000 characters). The files shown whole were capped by the task's context_budget, whose default is
8 000 bytes, so render() refused them. Files shown whole are capped by the prompt's own budget when the task's
budget is smaller, for the coder and for the reviewer alike."""
import json
from dataclasses import replace

from tools import agent_factory as F
from tools import agent_factory_runner as W
from tools import factory_channels as C

TEST = b'from tools.link_check import check_1\n\n\ndef test_one():\n    assert check_1(1) == 2\n'


def _task(**kw):
    base = F.read_plan([dict(id='T1', title='Fix the link check', touch_files=['tools/link_check.py'],
                             read_files=['tools/gate/registry.py'], tests=['tests/test_link.py'],
                             privacy_safe=True, estimated_tokens=100)])['T1']
    return replace(base, **kw)


def _module(prefix, n):
    return ''.join('def %s_%d(x):\n    return x + %d\n' % (prefix, i, i) for i in range(n)).encode()


def _files():
    return {'tools/link_check.py': _module('check', 260), 'tools/gate/registry.py': _module('reg', 110),
            'tests/test_link.py': TEST}


def test_the_coder_sees_files_whole_when_they_fit_the_prompt_even_above_the_default_budget():
    visible = _files()
    assert sum(len(v) for v in visible.values()) > _task().context_budget        # above the default 8 000
    try:
        prompt = W.build_coder_prompt(_task(), visible, light=True)
    except F.InvalidPlan as error:
        prompt = 'refused: %s' % error
    assert 'FILE tools/link_check.py\n' in prompt and 'FILE tools/gate/registry.py\n' in prompt
    assert 'def check_259(x):' in prompt and 'def reg_109(x):' in prompt
    assert len(prompt) <= C.PROMPT_LIMIT_CHARS


def test_the_reviewer_sees_the_same_files_whole(tmp_path):
    for name, data in _files().items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(data)
    seen = []

    def invoke(reviewer, root, model, prompt_override):
        seen.append(prompt_override)
        return 0, (json.dumps({'type': 'text', 'part': {'text': '{"approved": true}'}}) + '\n').encode(), b''
    try:
        verdict = W.review_candidate(_task(), tmp_path, 'google/y', invoke, baseline={'tools/link_check.py': b'old\n'})
    except F.InvalidPlan as error:
        verdict = 'refused: %s' % error
    assert verdict == (True, []) and 'def reg_109(x):' in seen[0]


def test_a_task_budget_above_the_prompt_budget_still_counts():
    """Raising the cap never lowers a task's own larger budget."""
    prompt = W.build_coder_prompt(_task(context_budget=10 ** 6), _files(), light=True)
    assert 'def check_259(x):' in prompt

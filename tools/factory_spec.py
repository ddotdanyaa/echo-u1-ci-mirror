"""<id>, the spec stage: before a test is written, one cheap call turns a backlog row into a spec (is it a code defect testable by calling the code shown, which function, called how, what it gives now, what it must give, one assertion); a row that is not testable keeps its reason; a function name not in the code shown is refused."""

import json
import re

FIELDS = ('function', 'call', 'now', 'expected', 'assert')

RULES = """You turn ONE row of a project backlog into a precise spec for ONE unit test of the code shown.
Return ONLY a JSON object, no prose, no code fence:
{"testable": true|false, "why": "<one sentence>", "function": "<name of a function or method defined in the code shown>", "call": "<one Python call with concrete inputs>", "now": "<what the current code returns or does for that call>", "expected": "<what it must return or do after the fix>", "assert": "<one Python assert line>"}
Read the code: "now" must be what this code really gives, "expected" what the row asks for.
A row that is not a code defect testable by calling the code shown (a process rule, a merge of another branch, a device or phone check, something the code already does) gives {"testable": false, "why": "<the reason>"}."""


def prompt(row, code, example='') -> str:
    code_text = ''
    if isinstance(code, dict):
        code_text = '\n'.join(f'--- {k} ---\n{v}' for k, v in code.items())
    else:
        code_text = str(code)
    
    res = RULES + '\n\nROW:\n' + row + '\n\nCODE:\n' + code_text
    if example:
        res += '\n\nEXAMPLE:\n' + example
    return res


def parse(response, code):
    """The spec, or None. The first JSON object of the answer (free models wrap it in prose or a fence); the function
    named must be defined in the code shown (module.func and func(...) are reduced to the name)."""
    m = re.search(r'\{.*\}', response or '', re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or type(data.get('testable')) is not bool:
        return None
    if data['testable'] is False:
        return {'testable': False, 'why': str(data.get('why') or '')}
    if any(not str(data.get(k) or '').strip() for k in FIELDS):
        return None
    name = str(data['function']).strip().split('(')[0].split('.')[-1]
    texts = code.values() if isinstance(code, dict) else [str(code)]
    if not any(re.search(r'\bdef\s+' + re.escape(name) + r'\b', text) for text in texts):
        return None
    spec = {'testable': True, 'why': str(data.get('why') or '')}
    spec.update({k: str(data[k]).strip() for k in FIELDS})
    spec['function'] = name
    return spec


def goal(spec, backlog_id) -> str:
    """The goal of the test task: the spec in words, the red reason, and the rules a written test breaks most."""
    return ('Write a test from this spec. First line of the file: the comment # factory-backlog-id: %s. '
            'Call: %s. Now the code gives: %s. It must give: %s. Assertion: %s. '
            'The test must fail on the current code because of this assertion and pass after the fix; '
            'import the function from its module; no network, no audio, no sleeps.'
            % (backlog_id, spec['call'], spec['now'], spec['expected'], spec['assert']))

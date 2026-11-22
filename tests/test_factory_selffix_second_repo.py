"""<id> clause 4 (backlog <id>: «Реестр живёт в фабрике, а не в ECHO; проверено на втором репозитории»): the failure
class register and the self-fix ledger work for any project. A tiny second repository (calc) with its own state dir
and telemetry goes through classify -> count -> due -> run (materialize): the plan, its source tree and the ledger land
in the factory's self dir, nothing names ECHO; a second project that shares the factory sees the class open and does
not open it twice."""
import json
import sys
from pathlib import Path

from tools import factory_classes as K
from tools import factory_selffix as X

PY = sys.executable
TEST = "from tools.calc_fix import fix\n\ndef test_fix():\n    assert fix('a') == 'b'\n"
VARIATION = "from tools.calc_fix import fix\n\ndef test_fix_other():\n    assert fix('c') == 'b'\n"
FORBIDDEN = ('echo', 'hermes', 'agent-factory')


def _calc_repo(root):
    (root / 'src').mkdir(parents=True)
    (root / 'src' / 'calc.py').write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
    (root / 'tests').mkdir()
    (root / 'tests' / 'test_calc.py').write_text('from src.calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n',
                                                encoding='utf-8')
    return root


def _factory_src(root):
    """A minimal copy of the factory files a search-miss self-fix may touch, plus the module its test imports."""
    (root / 'tools').mkdir(parents=True)
    (root / 'tools' / '__init__.py').write_text('', encoding='utf-8')
    for rel in X.WHERE['search-miss']:
        (root / rel).write_text('def outline_row():\n    return 1\n', encoding='utf-8')
    (root / 'tools' / 'calc_fix.py').write_text('def fix(text):\n    return text\n', encoding='utf-8')
    (root / 'tests').mkdir()
    return root


def _state(root, project):
    state = root / project / 'state'
    state.mkdir(parents=True)
    rows = [{'ts': '2026-11-20T10:0%d:00+03:00' % i, 'span': 'run', 'task_id': '%s_%d' % (project, i), 'attempt': 1,
             'reason': 'gate:no_changes', 'reason_detail': 'block 1 (src/calc.py) SEARCH not found: def add(a, b):'}
            for i in (1, 2)]
    with (state / 'telemetry.jsonl').open('w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r) + '\n')
    return state


def _rows(state):
    return [json.loads(line) for line in (state / 'telemetry.jsonl').read_text(encoding='utf-8').splitlines()]


def _answer():
    return json.dumps({'title': 'fix the search copy', 'touch_files': ['tools/calc_fix.py'],
                       'test_file': 'tests/test_selffix_calc.py', 'test_code': TEST, 'variation_code': VARIATION,
                       'goal': 'Change fix in tools/calc_fix.py so that it returns the letter b for any input text.'})


def _clean(text, base):
    return str(text).replace(str(base), '').replace(str(base).replace('\\', '/'), '').lower()


def test_the_register_and_ledger_work_on_a_second_repository(tmp_path):
    _calc_repo(tmp_path / 'calc')
    src = _factory_src(tmp_path / 'other' / 'factory_src')
    state = _state(tmp_path, 'other')
    self_dir = tmp_path / 'other' / 'self'
    self_dir.mkdir()
    rows = _rows(state)
    assert [K.classify(r['reason'], r['reason_detail']) for r in rows] == ['search-miss', 'search-miss']
    assert K.count(rows, None)['search-miss']['tasks'] == ['other_1', 'other_2']
    ledger = X.load_ledger(self_dir)
    assert [c for c, _ in X.due(rows, ledger, self_dir=self_dir, now_iso='2026-11-20T11:00:00+03:00',
                                repo_root=src)] == ['search-miss']
    prompts = []
    rep = X.run(rows, ledger, ask=lambda p: prompts.append(p) or _answer(), repo_root=src, src_root=src,
                self_dir=self_dir, base_sha='c0ffee', python=PY, now_iso='2026-11-20T11:00:00+03:00', stamp='s1')
    assert rep['status'] == 'open', rep
    X.save_ledger(self_dir, ledger, {})
    written = sorted(p for p in self_dir.rglob('*') if p.is_file())
    assert (self_dir / rep['plan']).is_file() and (self_dir / 'selffix_ledger.json').is_file()
    assert (self_dir / 'src_fx_search-miss_s1' / 'tests' / 'test_selffix_calc_variation.py').is_file()
    assert all(self_dir in p.parents for p in written)
    for p in written:
        rel = _clean(p, tmp_path)
        assert not any(w in rel for w in FORBIDDEN), rel
    for text in [(self_dir / 'selffix_ledger.json').read_text(encoding='utf-8'),
                 (self_dir / rep['plan']).read_text(encoding='utf-8'), prompts[0]]:
        assert not any(w in _clean(text, tmp_path) for w in FORBIDDEN)
    assert X.load_ledger(self_dir)['search-miss']['status'] == 'open'

    # a second project sharing the factory: the same class is open in the shared register, not opened again
    state2 = _state(tmp_path, 'third')
    shared = X.load_ledger(self_dir)
    asked = []
    rep2 = X.run(_rows(state2), shared, ask=lambda p: asked.append(p) or _answer(), repo_root=src, src_root=src,
                 self_dir=self_dir, base_sha='c0ffee', python=PY, now_iso='2026-11-20T11:05:00+03:00', stamp='s2')
    assert rep2 == {'status': 'none'} and not asked and shared['search-miss']['status'] == 'open'

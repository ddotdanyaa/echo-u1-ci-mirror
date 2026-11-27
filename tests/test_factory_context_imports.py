"""fac-context-imports (live 19.11 22:30): the task 'module constants' failed four passes. Its goal asked for an import,
and the large view never shows the module's imports, so the model guessed them ('from typing import Optional', then
a block that began with the real 'import ast' and went on with lines that are not there). The large view of a
python file shows its top-level import statements before the outline."""
from tools import factory_context as C

SRC = ('"""doc"""\nimport ast\nimport os\nfrom pathlib import Path\n\nfrom .agent_factory import InvalidPlan\n\n\n'
       + ''.join('def f%d(x):\n    return x + %d\n\n\n' % (i, i) for i in range(600)))


def test_the_large_view_shows_the_module_imports():
    view = C.large_view('m.py', SRC, {'f3'}, 8000, frozenset({'f3'}), tools=False)
    assert 'import ast\nimport os\nfrom pathlib import Path\nfrom .agent_factory import InvalidPlan' in view
    assert view.index('import ast') < view.index('OUTLINE')


def test_a_file_that_does_not_parse_still_gets_its_view():
    view = C.large_view('m.py', 'import os\ndef broken(:\n' + 'x = 1\n' * 3000, {'broken'}, 4000, tools=False)
    assert 'OUTLINE' in view

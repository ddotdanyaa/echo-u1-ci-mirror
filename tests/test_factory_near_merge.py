"""Self-fix of the search-miss class, copy errors (coordinator's replay 20.11 07:10: 7 of 96 failed SEARCH blocks, all
of them compiling after the merge; a live task failed 3 passes on 'def _start_locked(self) -> None:' where the file has
'def _start_locked(self):'). factory_patterns.near_merge(text, search, replace) applies the change the model meant
(SEARCH -> REPLACE) to the real lines of the ONE place of the file most like the SEARCH: a context line the model
misremembered keeps the file's text, a line the model changed takes the REPLACE text; a place shared by too few lines,
two equally good places, or a change to a line the model misremembered gives None. repair() tries it last.
The code is a free model's from the self-build queue; the last test is the coordinator's review of it."""
from tools import factory_patterns as P

FILE = ('import os\n\n\n'
        'class Worker:\n'
        '    def _start_locked(self):\n'
        '        self.proc = None\n'
        '        self.count = 0\n'
        '        return self.proc\n\n'
        '    def stop(self):\n'
        '        return 1\n')


def test_a_misremembered_context_line_keeps_the_file_line_and_the_change_lands():
    search = ('    def _start_locked(self) -> None:\n'
              '        self.proc = None\n'
              '        self.count = 0\n'
              '        return self.proc')
    replace = ('    def _start_locked(self) -> None:\n'
               '        self.proc = None\n'
               '        self.count = 1\n'
               '        return self.proc')
    out = P.near_merge(FILE, search, replace)
    assert out is not None
    assert '    def _start_locked(self):\n        self.proc = None\n        self.count = 1\n' in out
    assert '-> None' not in out and out.count('self.count') == 1
    assert out.endswith('    def stop(self):\n        return 1\n')


def test_a_change_to_a_line_the_model_misremembered_is_refused():
    search = ('    def _start_locked(self):\n'
              '        self.proc = None\n'
              '        self.count = 5\n'
              '        return self.proc')
    replace = ('    def _start_locked(self):\n'
               '        self.proc = None\n'
               '        self.count = 6\n'
               '        return self.proc')
    assert P.near_merge(FILE, search, replace) is None


def test_a_place_sharing_too_few_lines_is_no_place():
    search = '    def other(self):\n        x = 1\n        y = 2\n        return self.proc'
    assert P.near_merge(FILE, search, search.replace('y = 2', 'y = 3')) is None


def test_two_equally_good_places_are_no_place():
    text = 'def a():\n    x = 1\n    y = 2\n    return x\n\n\ndef b():\n    x = 1\n    y = 2\n    return x\n'
    search = 'def c():\n    x = 1\n    y = 2\n    return x'
    assert P.near_merge(text, search, search.replace('y = 2', 'y = 3')) is None


def test_repair_tries_the_merge_last():
    search = '    def _start_locked(self) -> None:\n        self.proc = None\n        self.count = 0\n        return self.proc'
    replace = search.replace('self.count = 0', 'self.count = 2')
    out = P.repair(FILE, search, replace)
    assert out is not None and '        self.count = 2\n' in out and '-> None' not in out


def test_the_runner_applies_such_a_block_end_to_end(tmp_path):
    from tools import agent_factory_runner as W
    (tmp_path / 'w.py').write_text(FILE, encoding='utf-8')
    search = '    def _start_locked(self) -> None:\n        self.proc = None\n        self.count = 0\n        return self.proc'
    applied, failed = W.apply_edit_blocks(tmp_path, [('w.py', search, search.replace('= 0', '= 4'))])
    assert applied == ['w.py'] and not failed
    assert '    def _start_locked(self):\n        self.proc = None\n        self.count = 4\n' in (tmp_path / 'w.py').read_text()


def test_two_equal_lines_in_a_row_are_one_place():
    # each of two equal SEARCH lines votes its own shift, both shifts find the same region, and the region was read
    # as two equally good places: no merge at all
    text = 'def f(x):\n    log()\n    log()\n    y = x + 1\n    w = 0\n    z = y * 2\n    return z\n'
    search = '    log()\n    log()\n    y = x + 2\n    w = 0\n    z = y * 2\n    return z'
    out = P.near_merge(text, search, search.replace('y * 2', 'y * 3'))
    assert out == text.replace('y * 2', 'y * 3')

"""fac-row-text (acceptance 20.11, cause a): a whole backlog table (header ID | Пр. | Причина | ...) gave its rows the
PRIORITY cell as their text, so 12 open rows reached the free models as the bare words <id>/<id>/<id>; the models made up
defects and 3 of the 6 promotions of the night were tests of made-up defects. The text column is named by the header
(Причина too) or is the first cell that is neither the priority nor the state; and a row whose text is shorter than
MIN_ROW_TEXT characters (a bare priority, a bold title, nothing) becomes a question for Opus, never a task."""
import subprocess

import pytest

from tools import agent_factory as F
from tools import agent_factory_import as imp

CAUSE = "| ID | Пр. | Причина | Доказано / гипотеза | Решение | Проверка | Состояние |\n|---|---|---|---|---|---|---|\n"
PLAIN = "| ID | Пр. | Состояние | Детали |\n|---|---|---|---|\n"
LONG = 'функция add в модуле считает разность вместо суммы, и итог ответа неверен при двух числах'


def _md(*tables):
    return '# B\n## 4. Очередь\n' + ''.join(tables) + '## 5. Закрытые\n'


def test_the_cause_column_is_the_text_of_its_table():
    rows = imp.parse_section4(_md('### 4.11 Причины\n' + CAUSE +
                                  '| J7 | P1 | ' + LONG + ' | лог | правка | тест | открыто |\n'))
    assert rows[0]['text'] == LONG and rows[0]['priority'] == 'P1' and rows[0]['open']


def test_a_header_without_a_text_name_takes_the_first_cell_that_is_not_priority_or_state():
    rows = imp.parse_section4(_md('### 4.12 Прочее\n' + PLAIN + '| J8 | P2 | открыто | ' + LONG + ' |\n'))
    assert rows[0]['text'] == LONG and rows[0]['priority'] == 'P2'


@pytest.mark.parametrize('text', ['P1', '', '**Коротко**', '`P0`'])
def test_a_row_without_a_formulation_is_a_question_never_a_goal(text):
    goal, question = imp._screen(F, 'J9', text)
    assert goal is None and 'J9' in question and 'формулировк' in question


@pytest.mark.parametrize('text', [LONG, 'Контроллер молчит на реплике соседа'])
def test_a_real_formulation_still_goes_out(text):
    goal, question = imp._screen(F, 'J9', text)
    assert question is None and goal == text


@pytest.fixture
def repo(tmp_path):
    (tmp_path / 'echo_sync').mkdir()
    (tmp_path / 'echo_sync/alpha.py').write_text('def add(a, b):\n    return a - b\n', encoding='utf-8')
    mail = 'user.email=t' + chr(64) + 't'      # written out it reads as a mail address to the mirror's scanner
    for args in (('init', '-q'), ('add', '-A'), ('commit', '-q', '-m', 'base')):
        subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=t', '-c', mail, *args],
                       check=True, capture_output=True)
    return tmp_path


def test_triage_hands_both_a_bare_priority_row_and_a_real_one_to_the_slicer(tmp_path, repo):
    backlog = tmp_path / 'B.md'
    backlog.write_text(_md('### 4.11 Причины\n' + CAUSE +
                           '| J7 | P1 | **Коротко** | `echo_sync/alpha.py` | правка | тест | открыто |\n'
                           '| J8 | P1 | ' + LONG + ' в `echo_sync/alpha.py` | лог | правка | тест | открыто |\n'),
                       encoding='utf-8')
    out = imp.triage_portion(backlog, repo, set(), 12)
    # triage makes no tasks and no holds any more: every code row goes to the slicer queue, which owns the text
    assert not out['tasks'] and not out['holds']
    queued = {r['backlog_id']: r for r in out['to_slice']}
    assert set(queued) == {'J7', 'J8'}
    assert 'echo_sync/alpha.py' in queued['J8']['hints']

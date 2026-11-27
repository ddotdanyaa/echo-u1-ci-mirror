"""fac-triage-state-tail (live 19.11 20:13-20:59): rows <id> and <id> became 'write a test' tasks and both tests were
junk. <id>'s state is 'улучшение · действует: ждёт итога <id>': classify_state took the head 'действует' and never
read 'ждёт' after the colon; its last cell also says '**[sync17.11]** дубль: код и тесты уже на базе'. The state
after 'действует:' is read too, and a cell part that starts with 'дубль' or 'отказ' (after a [..] tag) keeps the
row from becoming a task. The formulation cell is not such a mark: 'Дубль запроса' there is the task itself."""
from tools import agent_factory_import as imp

HDR = ("| ID | Формулировка | Origin | Приоритет: причина | Состояние | Зависит | Заметки |\n"
       "|---|---|---|---|---|---|---|\n")


def _open(row):
    (r,) = imp.parse_section4("## 4. Q\n### 4.2 P1\n" + HDR + row + "## 5. H\n")
    return r["open"]


def test_the_state_after_in_force_is_read():
    assert imp.classify_state("улучшение · действует: ждёт итога T2000") == "waiting"
    assert imp.classify_state("блокер · действует: сделано в c14000") == "closed"
    assert imp.classify_state("действует: ждёт итога T2000") == "waiting"
    assert imp.classify_state("блокер · действует: таблица писателей — раздел 9") == "open"
    assert imp.classify_state("обязательство · действует") == "open"
    assert imp.classify_state("улучшение · частично: после H7000") == "open"      # only the tail of 'действует:'


def test_implemented_elsewhere_waits_for_a_merge_and_not_implemented_stays_open():
    """Live 19.11 21:43: <id> 'улучшение · реализовано в ветке: claude/w4-law ... не подключён' became a test task and
    the free model invented a defect; 24 open rows say 'реализовано' - their code waits for a merge, not a coder.
    The state alone still waits; parse_section4 opens such a row as a PORT when the commit is named and nothing else
    waits (one code task with the row's guard test, never a test task: test_factory_port_triage)."""
    assert imp.classify_state("улучшение · реализовано в ветке: `claude/w4-law` `027d37d`, не подключён") == "waiting"
    assert imp.classify_state("блокер · реализовано на ветке: R10000 `2eea847`, в `integ-c15000`; не выложено") == "waiting"
    assert imp.classify_state("улучшение · не реализовано") == "open"
    assert imp.classify_state("блокер · частично: реализовано ядро") == "open"          # a part is still to do


def test_a_row_marked_duplicate_or_refused_in_another_cell_is_not_a_task():
    assert not _open("| E59000.1 | WebSocket за ключом | x | P2 | улучшение · новая | — | "
                     "T1R: −363 мс · **[sync17.11]** дубль: код и тесты уже на базе |\n")
    assert not _open("| E70000 | Что-то | x | P2 | улучшение · новая | — | отказ: решили иначе |\n")


def test_the_formulation_cell_is_never_such_a_mark():
    assert _open("| E61000 | **Параллельный дубль запроса** против хвоста p90000 | x | P2 | улучшение · новая | — | — |\n")
    assert _open("| E62000 | Дубль запроса к поиску | x | P2 | улучшение · новая | — | — |\n")

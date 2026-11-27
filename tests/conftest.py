"""h28: ``logging.disable`` is process-wide. A test that silences the log for speed left it silenced for every test after it (test_classifier, test_decision_privacy: «no logs of level INFO»)."""
import importlib
import logging
import sys
import types

import pytest

# CONF: the libraries without which the engine takes a silent fallback and hundreds of tests go red for the environment, not for the code
# (cloud_context/SETUP_CLOUD.sh installs them; tests/test_env_deps.py names the same four). A session without one stops at once with ONE line.
REQUIRED_LIBRARIES = ('rapidfuzz', 'razdel', 'pymorphy3', 'snowballstemmer', 'hypothesis', 'httpx')


def missing_libraries(names=REQUIRED_LIBRARIES):
    out = []
    for name in names:
        try:
            importlib.import_module(name)
        except ImportError:
            out.append(name)
    return out


def pytest_sessionstart(session):
    missing = missing_libraries()
    if missing:
        raise pytest.UsageError('среда без обязательных пакетов: ' + ', '.join(missing) + ' (без них порции и слова расходятся молча, сотни красных не про код); bash cloud_context/SETUP_CLOUD.sh первой строкой сессии')


@pytest.fixture(autouse=True)
def _logging_comes_back():
    yield
    logging.disable(logging.NOTSET)


# R31-1 / R9: a registry of the process-wide substitutions, not a list of the two that were found.
# What a test leaves behind is found by comparing the module-level callables, classes and modules of the code under test with what they were at its start.
SCOPE = ('echo_sync', 'tools', 'helpers_')          # the product, its tools and the helper modules of the tests
KEPT = (types.FunctionType, types.BuiltinFunctionType, types.ModuleType, type)
GONE = object()
LEAKS = []                                            # (test id, "module.name") of every substitution a test left; shown at the end of the run, never hidden


def in_scope(name):
    return name.startswith(SCOPE)


def snapshot():
    """``{module name: (module, {name: object})}`` of the substitutable names (callables, classes, modules) of every module in scope."""
    state = {}
    for name, module in list(sys.modules.items()):
        if module is None or not in_scope(name):
            continue
        try:
            state[name] = (module, {key: value for key, value in list(vars(module).items()) if isinstance(value, KEPT) and not key.startswith('__')})
        except TypeError:
            continue
    return state


def restore(before, who=''):
    """Put back every name whose object differs from the snapshot (a module that was reloaded or dropped is left alone). -> ``["module.name", ..]``."""
    put = []
    for name, (module, names) in before.items():
        if sys.modules.get(name) is not module:
            continue
        now = vars(module)
        for key, value in names.items():
            if now.get(key, GONE) is not value:
                setattr(module, key, value)
                put.append(f'{name}.{key}')
    LEAKS.extend((who, item) for item in put)
    return put


@pytest.fixture(autouse=True)
def _substitutions_come_back(request):
    """h31 and R31-1: ``tools.replay.stand.Stand`` patches ``helpers_s6_state.host_kwargs`` and ``echo_sync.fast_text.threading`` until close(); a test that never closed
    its Scene left them for every test after it (351 false reds in the full run, three times since). The third such patch would leak the same way, so the fixture
    does not know the names: whatever callable, class or module of the product, the tools or the helpers a test left rebound is put back (after monkeypatch, which undoes its own)."""
    before = snapshot()
    yield
    restore(before, request.node.nodeid)


def pytest_terminal_summary(terminalreporter):
    import helpers_fake_voice as FV
    if FV.USED['cues']:
        terminalreporter.section('synthetic voice')
        terminalreporter.write_line(f"{FV.MARK}: {FV.USED['cues']} cues in {FV.USED['tests']} tests (no SAPI on this machine, tests/helpers_fake_voice.py); a test of the real voice cannot pass on it: tools/data/cloud_env_red.txt")
    if LEAKS:
        terminalreporter.section('substitutions that tests left behind (restored)')
        for who, item in LEAKS[:40]:
            terminalreporter.write_line(f'{item}  <- {who}')
        if len(LEAKS) > 40:
            terminalreporter.write_line(f'... and {len(LEAKS) - 40} more')


@pytest.fixture(autouse=True)
def _the_rests_of_the_roads_do_not_outlive_a_test():
    """The rests of the roads (``reserve_text._REST``, ``_PRIMARY``) and what the providers last said (``_BUDGET``) live in the process, as they do for the calls of one server: a test starts with none and leaves none
    (a job thread of an earlier test that rests the first road late would put the next test's channel to rest on another clock)."""
    def clear():
        RT = sys.modules.get('echo_sync.reserve_text')
        if RT is not None:
            RT._REST.clear()
            RT._BUDGET.clear()
            RT._PRIMARY['until'] = 0.0
    clear()
    yield
    clear()


@pytest.fixture(autouse=True)
def _a_machine_without_sapi_gets_the_synthetic_voice(request):
    """SYNTH: off Windows ``SapiWorkerManager`` cannot start its child (``windows_only``), so every scenario that drives the real worker owner ended in ``controlled_synthesis_failed`` before
    the decision under test. Here only the child is stood in (``helpers_fake_voice``: silent PCM as long as the text, the SAPI tail included); the manager, ``render_cue_pcm``, the cache and the
    trims stay the product's, nothing in ``echo_sync`` changes. On Windows nothing is installed. A test with its own fake worker or Popen never reaches it. The class is re-checked every test
    (a test that reloads ``echo_sync.sapi_worker`` gets a fresh class), the first import of the product is swallowed when the product cannot be imported at all."""
    import helpers_fake_voice as FV
    if not FV.available():
        try:
            from echo_sync.sapi_worker import SapiWorkerManager
        except Exception:
            SapiWorkerManager = None
        if SapiWorkerManager is not None:
            FV.install(SapiWorkerManager)
    FV.begin_test()
    yield
    FV.end_test(request.node)


# f84a05a9: the lead of the question («X —», question_lead.py) is the owner's rule of fast_text on (the key ``lead_cue`` is deleted). The modules that name this fixture were written when
# it was off and are about something else (the hold on speech, the portions and their repeat, the stop, the silence): the lead is taken out of THEIR scenes only; the lead has its own scenes
# (test_w5_lead*, registry 4.10b, test_one_answer), and every assertion of these scenes stays as it was.
WITH_THE_LEAD = ('test_e44_are_you_sure_after_a_right_answer_gets_a_short_confirmation',
                 'test_g_when_the_roads_never_say_the_question_is_over_the_cells_without_the_guard_are_red',
                 'test_a_doubt_that_confirms_says_the_answer_once_and_marks_nothing',
                 'test_a_number_as_digits_is_cued_repeated_in_words_and_confirmed')      # scenes about the lead itself, or that read it
NO_LEAD_ONE_SCENE = {'test_h5_live': ('test_a_final_of_the_first_piece_does_not_judge_the_second_for_a_first_cue',)}      # a module whose other scenes keep the lead


@pytest.fixture
def no_lead(request, monkeypatch):
    name = getattr(request.node, 'originalname', None) or request.node.name
    only = NO_LEAD_ONE_SCENE.get(request.module.__name__.rsplit('.', 1)[-1])
    if (name in only) if only else (name not in WITH_THE_LEAD):
        from echo_sync import cm_answer
        monkeypatch.setattr(cm_answer, 'lead', lambda *args, **kwargs: None)
    yield

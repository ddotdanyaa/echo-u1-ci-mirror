"""w2-t-check (R02): one short obligation test per T01-T15 of BACKLOG_ECHO.md §6, on the real code. ``xfail(strict=True)`` = the behaviour is not there:
the test states the obligation, the reason and the patch are in cloud_context/reports/w2-t-check.md. A strict xfail that starts to pass fails the run: remove the mark then."""
import pathlib
import re

import pytest

from helpers_w1f import Wire
from engine_say import engine_reply

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'echo_sync'


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def test_t01_loaded_package_names_its_own_build():
    import echo_sync
    build = getattr(echo_sync, 'build_id', None)
    assert callable(build) and re.fullmatch(r'[0-9a-f]{7,40}|unknown', str(build()))


def test_t02_new_question_replaces_the_old_answers_tail(tmp_path):
    q1, a1 = 'Что такое инерция', ' Инерция — это свойство тела сохранять своё состояние движения или покоя, пока внешняя сила не заставит его изменить.'
    w = Wire(tmp_path)
    w.user('u1', q1, 0.0, 2.0)
    w.assistant('a1', a1, 2.01, 6.0)
    w.user('u2', ' Сколько будет двадцать пять умножить на четыре', 8.0, 10.0)
    w.assistant('a2', ' Сто.', 10.01, 10.8)
    w.until(40.0)
    later = ' '.join(w.played_after(10.0))
    assert 'Сто' in later and 'изменить' not in later, w.played


def test_t03_compound_question_keeps_unclosed_parts():
    from echo_sync.engine import conversation_map
    state = {'history': [{'question': 'Расскажи про НДС, про УСН и про патент', 'status': 'complete', 'at': 1.0, 'chunks': ['НДС — налог.'], 'spoken': 1}]}
    rows = conversation_map(state, now=2.0)
    assert rows and any(k in rows[0] for k in ('open_parts', 'unanswered_parts', 'subquestions'))




def test_t04_context_note_is_bounded_whatever_the_answer_size():
    from echo_sync import progress_notes as pn
    huge = 'слово ' * 5000
    rows = [{'question': huge, 'status': 'interrupted', 'spoken_text': huge, 'unspoken_text': huge}] * 3
    frames = pn.split_frames(pn.reconnect_note(rows))
    assert frames and len(frames) <= pn.RECONNECT_FRAMES and all(len(f.encode()) <= pn.NOTE_BYTES + 4 * 30 for f in frames)


def test_t05_material_context_is_read_and_manifest_checked(tmp_path):
    from echo_sync.materials import import_materials, read_material_context, material_body
    src = tmp_path / 'm.txt'
    src.write_text('Ставка НДС по общему правилу 20 процентов.', encoding='utf-8')
    home = tmp_path / 'home'
    home.mkdir()
    result = import_materials([str(src)], home)
    ctx = next(p for p in home.rglob('*') if p.is_file() and 'context' in p.name.lower() and p.suffix in ('.md', '.txt'))
    body = material_body(read_material_context(ctx))
    assert '20 процентов' in body
    ctx.write_text(ctx.read_text(encoding='utf-8').replace('20 процентов', '22 процента'), encoding='utf-8')
    with pytest.raises(Exception):
        read_material_context(ctx)


def test_t06_generated_text_carries_sources_and_status():
    from echo_sync.generator import SourcedAnswer
    t = SourcedAnswer('Ответ', [{'url': 'https://x.test/a', 'title': 'a'}])
    assert t.sources[0]['url'] == 'https://x.test/a' and t.retrieval_status == 'source_backed'
    assert SourcedAnswer('Ответ').sources == ()


def test_t07_unfounded_objection_does_not_replace_a_correct_answer():
    from echo_sync.fast_text import revises
    ans, q = 'Ставка НДС двадцать процентов.', 'Какая ставка НДС'
    assert not revises(ans, 'Да, ставка двадцать процентов.', heard='Ты ошибся, неправильно', question=q)   # objection, answer holds


def test_t07_real_error_is_revised():
    from echo_sync.fast_text import revises
    assert revises('Ставка НДС 18 процентов.', 'Ставка НДС 20 процентов.', heard='Не верно, это неправильно', question='Какая ставка НДС', disputed=True)


def test_t08_portion_size_adapts_to_listener_signals():
    from echo_sync.settings import resolve
    from echo_sync import portioner
    text = 'Налог на добавленную стоимость начисляется на каждом этапе производства и продажи товаров. Ставка равна двадцати процентам.'
    easy = portioner.portions(text, resolve({'portion_mode': 'syllables', 'target_syllables': 8}))
    assert easy
    sig = getattr(portioner, 'adapt_to_listener', None)
    assert callable(sig)




def test_t09_ack_advances_only_on_the_words_of_the_portion(tmp_path):
    import tempfile
    from pathlib import Path
    from echo_sync.engine import EchoEngine
    d = tempfile.mkdtemp()
    e = EchoEngine(Path(d) / 's.db', lambda *a: 'Первый второй третий, четвёртый пятый шестой.', context='x')
    e.settings = {}
    turn = lambda t, n: engine_reply(e, session_id='s', turn_id=n, text=t, request={}, model='m')
    assert turn('Почему так?', '1') == 'Первый второй третий,'
    assert turn('Пятый шестой', '2') == 'NO_REPLY'                    # other words: no advance
    assert turn('Первый второй третий', '3') == 'четвёртый пятый шестой.'


def test_t09_symbols_alone_do_not_compare_words():
    from echo_sync.ack_semantics import ack_symbols_compatible as ok
    assert ok('15-20', '15-20') and not ok('15 - 20', '15, 20')


def test_t10_stop_is_exact_and_silences_the_phone(tmp_path):
    from echo_sync.user_intents import is_stop
    assert is_stop(['стоп'], frozenset()) and not is_stop(['стоит', 'подождать', 'до', 'вечера'], frozenset())
    a = ' Первое: берут воду. Второе: настаивают пять минут. Третье: добавляют лимон. Четвёртое: пьют тёплым.'
    w = Wire(tmp_path)
    w.user('u1', 'Как заварить чай', 0.0, 2.0)
    w.assistant('a1', a, 2.01, 5.0)
    w.user('u2', ' Стоп', 6.0, 6.5)
    w.until(40.0)
    assert not w.played_after(6.6), w.played


def test_t11_audible_first_word_time_is_measured():
    src = (SRC / 'controlled_media.py').read_text(encoding='utf-8')
    assert re.search(r'audible_ms|first_audible|heard_latency|audible_latency', src) is not None




def test_t12_scenario_runner_has_mutation_hook():
    assert (ROOT / 'tests' / 'helpers_t_classes_mutants.py').is_file()
    assert 'mutant' in (ROOT / 'tests' / 'helpers_t_classes_mutants.py').read_text(encoding='utf-8').lower()


def test_t13_engine_has_no_test_name_branches():
    import ast
    bad = []
    for p in SRC.glob('*.py'):
        tree = ast.parse(p.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Compare):
                for c in [node.left, *node.comparators]:
                    for k in ast.walk(c):
                        if isinstance(k, ast.Constant) and isinstance(k.value, str) and re.fullmatch(r'(?:n1|w1|g\d|f\d\d|n\d\d|sc\d\d)[_\d]\w*', k.value, re.I):
                            bad.append(f'{p.name}:{k.lineno}:{k.value}')
    assert not bad, bad


def test_t14_rollback_to_stock_provider_is_kept():
    src = (SRC / 'plugin.py').read_text(encoding='utf-8')
    assert 'rollback' in src.lower()


def test_t15_reuse_of_answers_is_in_one_place_only():
    assert not (SRC / 'answer_cache.py').exists() and not (SRC / 'answer_reuse.py').exists()
    assert 'answer_reuse_key' not in (SRC / 'engine.py').read_text(encoding='utf-8')


# ---- w3-integ (item 8): the patches of the «нет» points, tested by behaviour, not only by name -------------------------------------------------------------

def test_t01_build_id_names_the_checkout_or_says_unknown(tmp_path, monkeypatch):
    import echo_sync
    (tmp_path / 'BUILD').write_text('0123456789ab\n', encoding='utf-8')
    assert echo_sync.build_id(tmp_path) == '0123456789ab', 'the BUILD file the deploy writes wins'
    assert echo_sync.build_id(tmp_path / 'nowhere') == 'unknown', 'no file, no git: unknown, never an exception'


def test_t03_open_parts_are_the_parts_not_said_yet():
    from echo_sync.engine import conversation_map
    row = conversation_map({'history': [{'question': 'Расскажи про НДС, про УСН и про патент', 'status': 'interrupted', 'at': 1.0, 'chunks': ['НДС — налог на добавленную стоимость.', 'УСН — упрощённая система.'], 'spoken': 1}]}, now=2.0)[0]
    assert row['open_parts'] == ['про УСН', 'про патент']
    plain = conversation_map({'history': [{'question': 'Что такое НДС', 'status': 'complete', 'at': 1.0, 'chunks': ['НДС — налог.'], 'spoken': 1}]}, now=2.0)[0]
    assert 'open_parts' not in plain, 'a plain question has no parts'


def _asked(tmp_path, end_ms):
    import helpers_s6_ack as H
    d = H.Dictation(tmp_path / 'audible', None)
    c, sent = d.controller, {'ms': 0}
    c.bind_input_clock(lambda: sent['ms'])
    c.speech_started()
    c.provider(H.created('q1', 'user', ''))
    turn = H.done('q1', 'user', 'Что такое инерция')
    if end_ms is not None:
        turn['turn'].update(start_ms=end_ms - 1500, end_ms=end_ms)
    sent['ms'] = (end_ms or 0) + 400
    c.provider(turn)
    cues = [a for a in c.provider(H.done('a1', 'assistant', 'Свойство тела сохранять скорость. Это называется инерцией.')) if a['type'] == 'speak']
    sent['ms'] += 1200
    return c, cues, sent


def test_t11_the_first_cue_of_an_answer_measures_what_the_listener_waited(tmp_path):
    c, cues, sent = _asked(tmp_path, end_ms=10_000)
    c.cue_started(cues[0], voiced_seconds=1.0)
    assert c.audible_ms == 1600, 'input clock: first frame at 11 600 ms, the question ended at 10 000 ms'
    sent['ms'] += 5000
    c.cue_started(cues[0], voiced_seconds=1.0)
    assert c.audible_ms == 1600, 'the same answer is measured once'


def test_t11_no_clock_no_number(tmp_path):
    c, cues, _ = _asked(tmp_path, end_ms=None)
    c.cue_started(cues[0], voiced_seconds=1.0)
    assert c.audible_ms is None


def test_t15_the_generator_keeps_no_answer_cache_and_no_diskcache_dependency():
    """memory/answer-cache: the old disk cache of PrivateCodexGenerator (cache_path, answer_key, 300 s) is gone; the same question is generated again."""
    import inspect
    from echo_sync import generator
    assert 'cache_path' not in inspect.signature(generator.PrivateCodexGenerator.__init__).parameters
    for path in SRC.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        assert 'diskcache' not in text, path.name
    assert 'diskcache' not in (SRC / 'plugin.yaml').read_text(encoding='utf-8')

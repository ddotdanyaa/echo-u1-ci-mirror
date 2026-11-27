"""U78: the journal of swallowed failures; every unavailable capability is a line «недоступно: …» in the check before a call."""
import asyncio
import json
import sqlite3
import subprocess
import sys
import threading

import pytest

from echo_sync import degradation as dg


@pytest.fixture(autouse=True)
def clean():
    dg.reset()
    yield
    dg.reset()


def test_note_records_type_and_never_the_message():
    dg.note('law_base', ValueError('слово слушателя пароль=123'), what='открытие базы')
    (row,) = dg.snapshot()
    assert row['component'] == 'law_base' and row['reason'] == 'ValueError' and row['count'] == 1 and row['what'] == 'открытие базы'
    assert 'пароль' not in repr(dg.snapshot()) and row['first'] <= row['last']
    dg.note('law_base', KeyError('x'))
    assert dg.snapshot()[0]['count'] == 2 and dg.snapshot()[0]['reason'] == 'KeyError'


def test_note_never_raises():
    class Bad(Exception):
        def __str__(self):
            raise RuntimeError('boom')
    dg.note('x', Bad()); dg.note(None, None); dg.note(object(), 'plain text', what=object()); dg.note('y', KeyboardInterrupt())
    assert {r['component'] for r in dg.snapshot()} >= {'x', 'y'}


def test_readiness_ready_and_unavailable():
    assert dg.readiness({'a': lambda: True}) == ['готово: a']
    dg.note('b', OSError('disk'))
    lines = dg.readiness({'a': lambda: True})
    assert lines[0] == 'готово: a' and lines[1].startswith('недоступно: b — OSError')


def test_probe_exception_and_false_become_unavailable():
    def boom():
        raise ImportError('no sherpa')
    lines = dg.readiness({'ear': boom, 'law': lambda: False, 'ok': lambda: None})
    assert lines[0].startswith('недоступно: ear — ImportError') and 'no sherpa' not in lines[0]
    assert lines[1].startswith('недоступно: law') and lines[2] == 'готово: ok'


def test_probe_that_works_now_hides_old_note():
    dg.note('law', OSError())
    assert dg.readiness({'law': lambda: True}) == ['готово: law']


def test_check_before_call_reports_ok_flag():
    ok, lines = dg.check_before_call({'a': lambda: True})
    assert ok and lines == ['готово: a']
    ok, lines = dg.check_before_call({'a': lambda: 1 / 0})
    assert not ok and lines[0].startswith('недоступно: a — ZeroDivisionError')


def test_threads():
    def work():
        for _ in range(200):
            dg.note('c', ValueError('x'))
            dg.snapshot()
    ts = [threading.Thread(target=work) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert dg.snapshot()[0]['count'] == 1600


def test_component_table_is_bounded():
    for i in range(500):
        dg.note(f'c{i}', ValueError())
    assert len(dg.snapshot()) <= dg.MAX_COMPONENTS


# --- injected errors in real components -------------------------------------------------------------------------------------------------

def test_bank_broken_file_is_noted(tmp_path):
    from echo_sync.instant import load_bank
    p = tmp_path / 'bank.json'
    p.write_text('{not json', encoding='utf-8')
    assert load_bank(p) == []
    assert any(r['component'] == 'instant.bank' and r['reason'] == 'JSONDecodeError' for r in dg.snapshot())
    assert any(line.startswith('недоступно: instant.bank') for line in dg.readiness({}))


def test_bank_good_file_is_silent(tmp_path):
    from echo_sync.instant import load_bank
    p = tmp_path / 'bank.json'
    p.write_text('[]', encoding='utf-8')
    load_bank(p)
    assert dg.snapshot() == []


def test_material_entries_noted(monkeypatch):
    from echo_sync import instant, prepared_answers
    monkeypatch.setattr(prepared_answers, 'parse_pairs', lambda t: (_ for _ in ()).throw(RuntimeError('x')))
    assert instant.material_entries('В: а О: б') == []
    assert dg.snapshot()[0]['component'] == 'instant.material'


def test_stem_missing_is_noted(monkeypatch):
    from echo_sync import instant, textutil
    monkeypatch.setattr(textutil, 'stem', lambda w: (_ for _ in ()).throw(ImportError('snowball')), raising=False)
    assert instant._stem('слово') == 'слово'
    assert dg.snapshot()[0]['component'] == 'instant.stem'


def test_law_lookup_failure_is_noted(monkeypatch):
    from echo_sync import law_base
    monkeypatch.setattr(law_base, '_lookup', lambda *a: (_ for _ in ()).throw(sqlite3.OperationalError('no such table')))
    assert law_base.lookup('статья 5') is None
    assert dg.snapshot()[0]['component'] == 'law_base.lookup' and dg.snapshot()[0]['reason'] == 'OperationalError'


def test_silero_missing_is_noted():
    from echo_sync import local_ear

    def factory():
        raise ImportError('sherpa_onnx')
    onset = local_ear.make_onset('silero', model_factory=factory)
    assert type(onset).__name__ == 'SpeechOnset'
    assert dg.snapshot()[0]['component'] == 'local_ear.silero' and dg.snapshot()[0]['reason'] == 'ImportError'


def test_pcm_cache_damaged_file_is_noted(tmp_path):
    from echo_sync.pcm_cache import PcmCache
    c = PcmCache(tmp_path)
    p = c.path('привет', 'v', 24000)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b'junk')
    assert c.get('привет', 'v', 24000) is None
    assert dg.snapshot()[0]['component'] == 'pcm_cache'


def test_pcm_first_portion_failure_is_noted(monkeypatch):
    from echo_sync import pcm_cache, portioner
    monkeypatch.setattr(portioner, 'portions', lambda *a: (_ for _ in ()).throw(ValueError('x')))
    assert pcm_cache.first_portion('Привет. Как дела?') == ''
    assert dg.snapshot()[0]['component'] == 'pcm_cache.portion'


def test_diag_prerender_failure_is_noted():
    from echo_sync.diagnostics import DiagnosticAudio

    def synth(text, end=None):
        raise OSError('sapi')
    asyncio.run(DiagnosticAudio().prerender(synth))
    assert any(r['component'] == 'diag_audio' and r['reason'] == 'OSError' for r in dg.snapshot())


def test_cli_prints_lines():
    out = subprocess.run([sys.executable, '-m', 'echo_sync.degradation'], capture_output=True, text=True, timeout=60)
    assert out.returncode in (0, 1)
    lines = out.stdout.strip().splitlines()
    assert lines and all(line.startswith(('готово: ', 'недоступно: ')) for line in lines)


def test_plugin_registers_echo_ready_command(capsys):
    from echo_sync import plugin
    assert callable(plugin._ready_info)
    code = plugin._ready_info(None)
    out = capsys.readouterr().out
    assert code in (0, 1) and out.startswith(('готово: ', 'недоступно: '))


# --- the host prints readiness at the start of each call ----------------------------------------------------------------------------------

def _call_start(tmp_path, monkeypatch, *, before=None, trace=False):
    """One call through the real host: (log lines after the handshake, nothing asked yet; the records of the call trace)."""
    import json
    import helpers_s6_fault as F
    box = {}

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            if trace:
                (host.home / 'materials').mkdir(parents=True, exist_ok=True)
                (host.home / 'materials' / 'echo_settings.json').write_text(json.dumps({'call_trace': 'on'}), encoding='utf-8')
            if before:
                before()
            await host.handshake()
            box['log'] = [text for _, text in host.logger.lines]
            box['sent'] = len(host.ws.frames)
            folder = host.home / 'logs' / 'echo_calls'
            box['trace'] = [json.loads(x) for f in sorted(folder.glob('*.jsonl')) for x in f.read_text(encoding='utf-8').splitlines()] if folder.is_dir() else []
    F.run(main)
    return box


def test_host_prints_unavailable_before_the_first_answer(tmp_path, monkeypatch):
    box = _call_start(tmp_path, monkeypatch, before=lambda: dg.note('bank', ValueError()), trace=True)
    lines = [t for t in box['log'] if t.startswith('недоступно: bank')]
    assert lines and 'ValueError' in lines[0]
    assert any('недоступно: bank' in json.dumps(r, ensure_ascii=False) for r in box['trace'])


def test_host_prints_a_failing_probe_line_too(tmp_path, monkeypatch):
    box = _call_start(tmp_path, monkeypatch, before=lambda: monkeypatch.setattr(dg, 'default_checks', lambda: {'ear': lambda: 1 / 0}))
    assert any(t.startswith('недоступно: ear — ZeroDivisionError') for t in box['log'])


def test_host_with_a_clean_journal_prints_no_unavailable_line(tmp_path, monkeypatch):
    box = _call_start(tmp_path, monkeypatch, before=lambda: monkeypatch.setattr(dg, 'default_checks', lambda: {'a': lambda: True}), trace=True)
    assert not [t for t in box['log'] if 'недоступно' in t]
    assert not any('недоступно' in json.dumps(r, ensure_ascii=False) for r in box['trace'])


def test_a_broken_degradation_check_never_costs_the_call(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError('x')
    box = _call_start(tmp_path, monkeypatch, before=lambda: monkeypatch.setattr(dg, 'check_before_call', boom))
    assert box['log']

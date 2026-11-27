"""Реестр 8.11 «Телеметрия времени модели и голоса»: время каждого запроса модели и каждого синтеза пишется без слов разговора.

Настроек у функции нет (реестр: «—»), все ключи по умолчанию кода. Обе половины идут настоящим входом, без самодельных реализаций.
Модель: echo_sync.register(ctx Hermes), затем хук pre_llm_call и промежуточное звено llm_execution, как это делает Hermes;
подставлены только внешние границы (hermes_constants, учётные данные, клиент облачной модели, заголовки).
Голос: настоящий EchoSapiProvider.synthesize с настоящим диспетчером рабочего процесса SAPI; подставлены только внешние границы
(hermes_constants/hermes_cli/tools/agent, «система Windows», сам дочерний процесс SAPI).
"""
import json
import os
import queue
import subprocess
import sys
import types
import wave
from pathlib import Path
from types import SimpleNamespace as S

QUESTIONS = ['Расскажи про квазары подробно.', 'А что такое пульсары?']
ANSWER = 'Фиолетовые капибары живут у тёплых озёр и любят мармеладные закаты.'
SPOKEN = ['Эвкалиптовый мёд пахнет лугом.', 'Лимонные облака плывут над морем.']
CODEX = dict(provider='openai-codex', api_mode='codex_responses', base_url='https://chatgpt.com/backend-api/codex', model='m', session_id='s')
MODEL_PHASES = ['credentials_resolve_ms', 'client_setup_ms', 'request_create_ms', 'first_event_ms', 'first_delta_ms', 'completed_ms', 'total_ms']
TTS_PHASES = ['lock_wait_ms', 'startup_ms', 'write_wait_ms', 'synth_wait_ms', 'validate_ms', 'total_ms']


def rows_of(path):
    assert Path(path).is_file(), f'журнал времени не создан: {path}'
    return [json.loads(x) for x in Path(path).read_text(encoding='utf-8').splitlines() if x.strip()]


def fake_modules(monkeypatch, home, names):
    for name, attrs in names.items():
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setitem(sys.modules, 'hermes_constants', S(get_hermes_home=lambda: home))


def test_every_model_request_leaves_a_timing_row_without_words(tmp_path, monkeypatch):
    class Client:
        def __init__(self, **kw):
            self.responses = self
        def create(self, **kw):
            done = S(type='response.completed', response=S(output=[S(type='message', content=[S(type='output_text', text=ANSWER)])]))
            return iter([S(type='response.created'), S(type='response.output_text.delta'), done])
        def close(self):
            pass
    fake_modules(monkeypatch, tmp_path, {'hermes_cli': {}, 'agent': {}, 'openai': {'OpenAI': Client},
                                         'hermes_cli.auth_codex': {'resolve_codex_runtime_credentials': lambda: {'api_key': 'aaa.bbb.ccc'}},
                                         'agent.codex_headers': {'codex_cloudflare_headers': lambda *a, **k: {}}})
    hooks, middleware = {}, {}
    ctx = S(get_config=lambda key, default=None: default, register_hook=hooks.__setitem__, register_middleware=middleware.__setitem__,
            register_cli_command=lambda *a, **k: None)
    import echo_sync
    echo_sync.register(ctx)
    replies = []
    for i, question in enumerate(QUESTIONS):
        hooks['pre_llm_call'](user_message=question, turn_id=f't{i}', **CODEX)
        reply = middleware['llm_execution'](request={}, next_call=lambda request: 1 / 0, turn_id=f't{i}', **CODEX)
        replies.append(reply.output_text)
    assert all('капибары' in r for r in replies), f'ответ модели не дошёл до человека (запрос не состоялся): {replies!r}'

    path = tmp_path / 'echo-sync' / 'generation-latency.jsonl'
    rows = rows_of(path)
    assert len(rows) == len(QUESTIONS), 'на каждый запрос модели должна быть ровно одна строка'
    for row in rows:
        assert row['outcome'] == 'success' and len(row['trace_id']) == 32
        times = [row[k] for k in MODEL_PHASES]
        assert all(type(v) in (int, float) and v >= 0 for v in times) and times == sorted(times), 'отсчёты не числа или не по порядку'
    assert rows[0]['trace_id'] != rows[1]['trace_id']
    text = json.dumps(rows, ensure_ascii=False).lower()     # журнал пишет \uXXXX: сравниваем с раскодированным
    for word in ('квазар', 'пульсар', 'капибар', 'мармелад', 'aaa.bbb', 'bearer'):
        assert word not in text, f'в журнале времени слова разговора или ключ: {word}'


class Child:
    """Подставной дочерний процесс SAPI: говорит ready, на запрос пишет настоящий wav и отвечает result."""
    voice = {'voice': 'Microsoft Irina Desktop', 'culture': 'ru-RU'}

    def __init__(self, *a, **k):
        self.lines, self.returncode = queue.Queue(), None
        self.stdin = self.stdout = self
        self.lines.put(json.dumps(dict(self.voice, type='ready')) + '\n')
    def readline(self):
        line = self.lines.get()
        return '' if line is None else line
    def __iter__(self):
        return iter(self.readline, '')
    def write(self, line):
        request = json.loads(line)
        with wave.open(request['output_path'], 'wb') as wav:
            wav.setnchannels(1), wav.setsampwidth(2), wav.setframerate(24000), wav.writeframes(b'\0\0' * 100)
        self.lines.put(json.dumps(dict(self.voice, type='result', id=request['id'], ok=True, error=None)) + '\n')
    def flush(self):
        pass
    def poll(self):
        return self.returncode
    def terminate(self):
        self.returncode = 0
        self.lines.put(None)
    close = kill = terminate
    def wait(self, timeout=None):
        return self.returncode or 0


def test_every_synthesis_leaves_one_timing_row_without_words(tmp_path, monkeypatch):
    fake_modules(monkeypatch, tmp_path, {
        'agent': {}, 'agent.tts_provider': {'TTSProvider': object}, 'hermes_cli': {}, 'hermes_cli.config': {'load_config_readonly': lambda: {'tts': {}}},
        'hermes_cli._subprocess_compat': {'windows_hide_flags': lambda: 0}, 'tools.tts_command_provider': {'_resolve_command_provider_config': lambda n, s: {'type': 'command'}},
        'tools.environments': {}, 'tools.environments.local': {'hermes_subprocess_env': lambda **k: {}}})
    class Nt:                                       # граница: «система Windows» для провайдера и диспетчера, остальное настоящий os
        name = 'nt'
        def __getattr__(self, attr):
            return getattr(os, attr)
    monkeypatch.setitem(sys.modules, 'echo_sync.sapi_provider', None)   # модуль со слепком чужого базового класса не должен остаться другим тестам
    sys.modules.pop('echo_sync.sapi_provider')
    from echo_sync import sapi_provider, sapi_worker
    monkeypatch.setattr(sapi_provider, 'os', Nt())
    monkeypatch.setattr(sapi_worker, 'os', Nt())
    monkeypatch.setattr(subprocess, 'Popen', Child)
    try:
        provider = sapi_provider.EchoSapiProvider()
        for i, words in enumerate(SPOKEN):
            assert provider.synthesize(words, str(tmp_path / f'cue{i}.wav')).endswith(f'cue{i}.wav')
    finally:
        sapi_worker.profile_sapi_worker(tmp_path).close()
    assert len(list(tmp_path.glob('cue*.wav'))) == len(SPOKEN), 'синтез не дал звука'

    path = tmp_path / 'echo-sync' / 'tts-latency.jsonl'
    rows = rows_of(path)
    assert len(rows) == len(SPOKEN), 'на каждый синтез должна быть ровно одна строка'
    for row in rows:
        assert row['outcome'] == 'success' and len(row['trace_id']) == 32 and not row['fallback']
        assert all(type(row[k]) in (int, float) and row[k] >= 0 for k in TTS_PHASES if k in row) and 'total_ms' in row
    text = json.dumps(rows, ensure_ascii=False).lower()
    for word in ('эвкалипт', 'лимонн', 'облака'):
        assert word not in text, f'в журнале времени голоса слова синтеза: {word}'

"""Supported Hermes pre_llm_call + llm_execution integration, scoped by profile install."""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from types import SimpleNamespace as S

from .engine import EchoEngine, SILENT
from .generator import PrivateCodexGenerator, official_codex
from .settings import SETTINGS_FILE, load as load_settings
from .utterance_judge import plain_ruling
from .materials import read_material_context
logger = logging.getLogger('echo-sync')


def raw_response(text, model='', *, api_mode='codex_responses'):
    usage = S(input_tokens=0, output_tokens=0, prompt_tokens=0, completion_tokens=0, total_tokens=0)
    return S(output=[S(type='message', role='assistant', status='completed', content=[S(type='output_text', text=text)])],
             output_text=text, status='completed', model=model, usage=usage,
             # Also valid as a terminal local error after an accidental model switch.
             choices=[S(message=S(role='assistant', content=text, tool_calls=None), finish_reason='stop')],
             content=[S(type='text', text=text)], stop_reason='end_turn')


class EchoPlugin:
    def __init__(self, home, *, generate=None, qa_file=None, context_file=None, settings_file=None):
        self.home = Path(home)
        self.qa_file = Path(qa_file) if qa_file else self.home / 'materials' / 'qa.json'
        self.context_file = Path(context_file) if context_file else self.home / 'materials' / 'context.md'
        self.settings_file = Path(settings_file) if settings_file else self.home / 'materials' / SETTINGS_FILE
        self._texts = {}
        self._lock = threading.RLock()
        self._generate = generate or PrivateCodexGenerator(trace_path=self.home / 'echo-sync' / 'generation-latency.jsonl')
        self._engine = None

    @property
    def engine(self):
        with self._lock:
            if self._engine is None:
                self._engine = EchoEngine(self.home / 'echo-sync' / 'state.sqlite3', self._generate, context=self._context)
            return self._engine

    def _context(self):
        if not self.context_file.exists():
            return ''
        return read_material_context(self.context_file)

    def capture(self, *, user_message, session_id='', turn_id='', **kwargs):
        if isinstance(user_message, str):
            text = user_message
        elif isinstance(user_message, list):
            text = ' '.join(str(item.get('text', '')) for item in user_message if isinstance(item, dict) and item.get('type') in {'text', 'input_text'})
        else:
            text = ''
        with self._lock:
            self._texts[(session_id, turn_id)] = text
            # Captures are only needed for current/retried turns; durable replies
            # remain in SQLite. Bound transient data for a long practice session.
            while len(self._texts) > 1000:
                self._texts.pop(next(iter(self._texts)))

    def execute(self, *, request, next_call, session_id='', turn_id='', provider='', api_mode='', base_url='', model='', **kwargs):
        # Middleware is fail-open on a raised exception. EVERYTHING in this
        # managed callback is converted to a local terminal provider response.
        try:
            if provider != 'openai-codex' or api_mode != 'codex_responses' or not official_codex(base_url):
                logger.warning('Echo requires openai-codex/codex_responses at the official subscription endpoint')
                return raw_response(SILENT, model)
            with self._lock:
                text = self._texts.get((session_id, turn_id))
            if text is None or not session_id or not turn_id:
                logger.warning('Echo input hook or session identity missing; refusing provider fall-through')
                return raw_response(SILENT, model)
            qa = None
            if self.qa_file.exists():
                qa = json.loads(self.qa_file.read_text(encoding='utf-8-sig'))
                if not isinstance(qa, list) or any(not isinstance(item, dict) or not isinstance(item.get('question'), str) or not isinstance(item.get('answer'), str) for item in qa):
                    raise ValueError('qa.json must contain question/answer objects')
                self.engine.qa = qa
            # Like qa.json, the settings are re-read on every turn. A broken file never stops the session.
            settings = load_settings(self.settings_file)
            text = self.engine.reply(session_id=session_id, turn_id=turn_id, text=text, request=request, model=model, settings=settings,
                                     **plain_ruling(self.engine, session_id, text, qa=qa, settings=settings))      # B: no controller here: the kind of the text is read by the judge's module
            return raw_response(text, model)
        except Exception:
            logger.warning('Echo turn failed locally; refusing provider fall-through')
            return raw_response(SILENT, model)


def register(ctx):
    from hermes_constants import get_hermes_home
    plugin = EchoPlugin(get_hermes_home(), qa_file=ctx.get_config('qa_file', None), context_file=ctx.get_config('context_file', None),
                        settings_file=ctx.get_config('settings_file', None))
    from .build_info import fingerprint
    loaded = fingerprint()
    logger.info('echo-sync build=%s code=%s prompt=%s modules=%s', loaded['build'], loaded['digest'], loaded['prompt'], len(loaded['modules']))      # T01, W03: the loaded code names itself
    ctx.register_hook('pre_llm_call', plugin.capture)
    try:       # w9-warm: what the first call loads is loaded now, on a thread (profile setting warm_start, off by default)
        from . import warm, ear_shadow
        from .sapi_worker import profile_sapi_worker
        warm.start_server_warm(plugin.home, settings=load_settings(plugin.settings_file), voice=profile_sapi_worker(plugin.home),
                               ear=ear_shadow.shared_worker if load_settings(plugin.settings_file).get('local_ear') != 'off' else None)
    except Exception as error:
        from . import degradation
        degradation.note('warm_start', error, what='прогрев при старте')
        logger.warning('Echo warm start unavailable', exc_info=True)
    ctx.register_middleware('llm_execution', plugin.execute)
    ctx.register_cli_command('echo-host-info', 'Show the active Hermes Python, checkout and profile paths', lambda parser: None, _host_info)
    ctx.register_cli_command('echo-ready', 'Before a call: готово / недоступно и почему', lambda parser: None, _ready_info)      # U78
    from .materials import add_arguments, run_cli
    ctx.register_cli_command('echo-import', 'Import local reference materials without LLM/OCR calls', add_arguments, run_cli)
    register_tts_provider = getattr(ctx, 'register_tts_provider', None)
    if callable(register_tts_provider):
        try:
            # Check the platform before importing the optional registry interface, preserving compatibility with older Hermes/plugin hosts.
            import os
            if os.name == 'nt':
                from .sapi_provider import EchoSapiProvider
                register_tts_provider(EchoSapiProvider())
        except Exception as error:
            from . import degradation
            degradation.note('sapi_register', error, what='регистрация голоса')
            logger.warning('Echo Windows SAPI provider could not be registered for this profile', exc_info=True)


def _ready_info(args):
    from . import degradation
    return degradation.main()


def _host_info(args):
    import sys
    import gateway.response_filters
    from hermes_constants import get_hermes_home
    print(json.dumps({'hermes_root':str(Path(gateway.response_filters.__file__).resolve().parents[1]), 'python':sys.executable, 'profile_home':str(get_hermes_home())}, ensure_ascii=False))

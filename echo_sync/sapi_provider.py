"""The one Hermes TTS provider of ECHO outside a call: the profile's resident SAPI worker, the text said the way a call says it (speech_text.speak)."""
from __future__ import annotations

import os
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from agent.tts_provider import TTSProvider

from . import degradation

logger = logging.getLogger('echo-sync')


class EchoSapiProvider(TTSProvider):
    """Native Echo provider backed by one profile-owned reusable SAPI child."""

    def __init__(self, manager=None):
        self._manager_override = manager

    @property
    def name(self) -> str:
        return 'echo_sapi'

    @property
    def display_name(self) -> str:
        return 'ECHO — Ирина (быстрый локальный голос)'

    @staticmethod
    def _is_windows() -> bool:
        return os.name == 'nt'

    def _manager(self):
        if self._manager_override is not None:
            return self._manager_override
        from hermes_constants import get_hermes_home
        from .sapi_worker import profile_sapi_worker

        return profile_sapi_worker(get_hermes_home())

    def get_setup_schema(self) -> dict[str, Any]:
        return {
            'name': self.display_name,
            'badge': 'local',
            'tag': 'Offline Russian speech using the installed Microsoft Irina voice.',
            'env_vars': [],
        }

    def is_available(self) -> bool:
        if not self._is_windows():
            return False
        try:
            from .sapi_worker import SapiWorkerManager
            return SapiWorkerManager.VOICE == 'Microsoft Irina Desktop'
        except Exception as error:
            degradation.note('sapi', error, what='настройка голоса')
            return False

    def warm(self) -> None:
        if not self._is_windows():
            return
        try:
            manager = self._manager()
        except Exception:
            logger.warning('Echo reusable SAPI worker could not be prepared for warm-up')
            return
        # Hermes calls provider warm hooks inline from the lease path. Start in
        # the background so toggling speech never waits for PowerShell startup.
        def start_worker() -> None:
            try:
                manager.warm()
            except Exception:
                logger.warning('Echo reusable SAPI worker could not be warmed')

        thread = threading.Thread(target=start_worker, name='echo-sapi-warm', daemon=True)
        thread.start()

    def release(self) -> None:
        try:
            self._manager().release()
        except Exception:
            pass

    def synthesize(
        self, text: str, output_path: str, *, voice: Optional[str] = None,
        model: Optional[str] = None, speed: Optional[float] = None,
        format: str = 'wav', **extra: Any,
    ) -> str:
        if not self._is_windows():
            raise RuntimeError('Echo reusable SAPI is available only on Windows')
        wav_path = str(Path(output_path).expanduser().with_suffix('.wav'))
        trace = None
        token = None
        if self._manager_override is None:
            try:
                from hermes_constants import get_hermes_home
                from .tts_telemetry import TtsLatencyCollector, TtsLatencyTrace, use_trace, safe_trace_finish, safe_trace_set
                trace = TtsLatencyTrace(TtsLatencyCollector(Path(get_hermes_home()) / 'echo-sync' / 'tts-latency.jsonl'))
                token = use_trace(trace)
            except Exception:
                trace = None
        try:
            from .sapi_worker import say
            result = say(self._manager(), text, wav_path)      # the way a call says a cue (tts-render): one function
            try:
                from .tts_telemetry import safe_trace_finish
                safe_trace_finish(trace, 'success')
            except Exception:
                pass
            return result
        except Exception as exc:
            from .diagnostics import reason_of
            # The cause: the exception type and, for the worker's own errors, its fixed code (never free text). There is no second road: the caller learns of the failure.
            cause = reason_of(exc) + (':' + reason_of(exc.args[0]) if type(exc).__name__ == 'SapiWorkerError' and exc.args else '')
            logger.warning('Echo reusable SAPI worker failed (%s)', cause)
            try:
                from .tts_telemetry import safe_trace_finish
                safe_trace_finish(trace, 'error', exc.args[0] if exc.args else None)
            except Exception:
                pass
            raise
        finally:
            if token is not None:
                try:
                    from .tts_telemetry import reset_trace
                    reset_trace(token)
                except Exception:
                    # Restore the neutral context after a token/reset mismatch or hot reload.
                    try:
                        from .tts_telemetry import use_trace
                        use_trace(None)
                    except Exception:
                        # Context cleanup is diagnostic bookkeeping; never replace a TTS result.
                        pass

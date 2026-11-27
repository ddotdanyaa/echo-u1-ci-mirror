"""Profile-owned, single-flight Windows SAPI worker manager."""
from __future__ import annotations

import atexit
import builtins
import json
import logging
import os
import queue
import re
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from typing import Callable, Optional
from xml.sax.saxutils import escape as _xml_escape

logger = logging.getLogger('echo-sync')

# E76: the end of an answer is heard. Irina ignores the mark at the end of a text (a WAV is byte for byte the same for every mark), but
# a <prosody pitch> on a word moves that word. ``end`` of a cue names a style; the only style is the fall of the last portion's last word.
# Measured 5 Nov on this laptop, 20 endings (U1/05_WORK/ANALYSIS_20261105/15_TTS_END.md): pitch -30% = the last word 3.1 semitones lower,
# length, final level and synthesis time unchanged. ``contour``, ``range`` and ``volume="-6dB"`` are not honoured by this voice.
END_STYLES = {'fall': {'pitch': '-30%'}}
_SSML_HEAD = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ru-RU">'
# characters XML 1.0 cannot carry at all (SpeakSsml throws on them); lone surrogates cannot be encoded to UTF-8 either
_XML_BAD = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]')
_BEFORE_WORD = '\u00ab([{"\'\u201c\u201e\u2018\u2014'                         # may precede the first word of the span and stays outside it
_EDGE = ' \u00a0\u2009\u202f.!?\u2026,;:)]}\u00bb"\'\u201d\u2019\u00ab([{\u201c\u201e\u2018\u2014\u2013-'
_TOKEN = re.compile(r'\S+')
_WORDY = re.compile(r'\w')
_DIGIT = re.compile(r'\d')
_ROMAN = re.compile(r'[IVXLCDM]{1,6}')
_MONTHS = frozenset('января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split())
_SCALES = frozenset('тыс млн млрд трлн'.split())


def _ssml_text(text: str) -> str:
    """Text for an XML text node: & < > escaped, characters XML 1.0 forbids replaced by a space."""
    return _xml_escape(_XML_BAD.sub(' ', text))


def _sticky(token: str) -> bool:
    """A token the engine reads together with the word after it: a number, a roman numeral, a month, a scale word («млн»), a short
    abbreviation with its dot («тыс.», «руб.»). It must stay in the same element as that word, or the reading changes."""
    core = token.strip(_EDGE)
    return bool(_DIGIT.search(token) or _ROMAN.fullmatch(core) or core.lower() in _MONTHS or core.lower() in _SCALES
                or (token.endswith('.') and 0 < len(core) <= 4 and core.islower()))


def end_ssml(text: str, pitch: Optional[str] = '-30%', rate: Optional[str] = None, words: int = 1) -> Optional[str]:
    """``text`` as SSML with its last ``words`` words inside ``<prosody pitch=...>``; None when there is no word to mark.

    The span runs to the end of the text, so the closing punctuation and an abbreviation's dot stay inside it (the voice ignores the mark at
    the end anyway); opening quotes and brackets stay outside. A number, a month, a scale word or a dotted abbreviation just before the span
    goes into it, and so does the one word before a span that begins with a number: the engine reads a number by the text of the same element
    («2011 | года» is not «две тысячи одиннадцатого года», «до | 18:00» is not «до восемнадцати ноль-ноль»).
    The text itself is not changed (numbers stay digits); only ``& < >`` are escaped and what XML cannot carry is blanked."""
    core = text.rstrip()
    tokens = list(_TOKEN.finditer(core))
    last = max((i for i, t in enumerate(tokens) if _WORDY.search(t.group())), default=None)
    if last is None:
        return None
    first = max(0, last - (max(1, words) - 1))
    while first > 0 and _sticky(tokens[first - 1].group()):
        first -= 1
    if first > 0 and _DIGIT.search(tokens[first].group()):
        first -= 1                    # the word before a number governs its case («до 18:00», «около 500»): it goes into the span too
    start = tokens[first].start()
    head, span, tail = core[:start], core[start:], text[len(core):]
    k = 0
    while k < len(span) and span[k] in _BEFORE_WORD:
        k += 1
    head, span = head + span[:k], span[k:]
    attrs = (f'pitch="{pitch}"' if pitch else '') + (f' rate="{rate}"' if rate else '')
    if not attrs.strip():
        return None
    return f'{_SSML_HEAD}{_ssml_text(head)}<prosody {attrs.strip()}>{_ssml_text(span)}</prosody>{_ssml_text(tail)}</speak>'


# U19-S5: a foreign-language span of a cue is read by that language's voice, inside the Irina SSML (``tts_lang``). Only English today.
LANG_VOICES = {'en': ('Microsoft Zira Desktop', 'en-US')}


def lang_ssml(text: str) -> Optional[str]:
    """``text`` as SSML with every English run (lang_hint.lang_spans) inside ``<voice name=Zira>``; None when no run is English
    (a single Latin word in Russian speech joins the Russian run, so «Ссылка в Excel.» stays plain Irina). The text itself is not changed;
    what lies between the runs (spaces, marks) stays outside the elements. Language wins over the end intonation: the caller prefers this."""
    from .lang_hint import lang_spans
    spans = lang_spans(text)
    if not any(lang == 'en' for lang, _, _, _ in spans):
        return None
    out, pos = [], 0
    for lang, start, end, _ in spans:
        voice = LANG_VOICES.get(lang)
        if voice is None:
            continue
        out.append(_ssml_text(text[pos:start]))
        out.append(f'<voice name="{voice[0]}" xml:lang="{voice[1]}">{_ssml_text(text[start:end])}</voice>')
        pos = end
    out.append(_ssml_text(text[pos:]))
    return f'{_SSML_HEAD}{"".join(out)}</speak>'


class SapiWorkerError(RuntimeError):
    """Worker startup, protocol, timeout, or WAV validation failure."""


class SapiWorkerManager:
    """One reusable PowerShell/System.Speech child per profile, single-flight.

    A manager is either lease-style (default: the child exits ``idle_timeout`` s after its last use,
    the next cue pays the 0.7-1.6 s start) or *resident* (``resident=True`` / ``keep_resident()``): one
    primed child for the life of the process, watched by a single daemon thread that restarts it in
    the background after a crash, a timeout or a protocol error, so no cue has to pay for a start.
    """
    VOICE = 'Microsoft Irina Desktop'
    CULTURE = 'ru-RU'
    SAMPLE_RATE = 24000
    MAX_TEXT = 5000
    MAX_PROTOCOL_LINE = 16384
    # Resident-mode supervision. One thread, one worker, no busy loop: the thread sleeps on an Event
    # for KEEPALIVE_INTERVAL_S (a healthy pass is one poll() call) or until a failure wakes it.
    KEEPALIVE_INTERVAL_S = 15.0
    # Pause before the next (re)start attempt after the 1st, 2nd, ... consecutive attempt that did not
    # prove itself (failed, or died again before the next healthy pass); the last value repeats.
    RESTART_BACKOFF_S = (0.5, 2.0, 5.0, 15.0)
    MAX_AUTO_RESTARTS = 5  # then stay quiet until keep_resident()/warm() asks again; cues still start it lazily
    MIN_PASS_S = 0.05      # the supervisor never wakes more often than this, whatever a step returns
    PRIME_TEXT = 'Да.'     # throwaway first utterance: the voice's first Speak costs ~+80-220 ms
    PRIME_LANG_SSML = (f'{_SSML_HEAD}<voice name="{LANG_VOICES["en"][0]}" xml:lang="{LANG_VOICES["en"][1]}">Yes.</voice></speak>')  # U19-S5: one English word
    prime_lang = False     # ``tts_lang`` on: the priming also speaks one word with the English voice
    lang_fallbacks = 0     # U19-S5: cues whose language markup the voice refused (spoken plain); call_trace reads it

    def __init__(self, profile_key: str, *, script_path: Optional[str] = None,
                 popen_factory: Optional[Callable] = None, startup_timeout: float = 8,
                 request_timeout: float = 30, idle_timeout: float = 45, telemetry=None,
                 resident: bool = False, keepalive_interval: Optional[float] = None,
                 clock: Optional[Callable[[], float]] = None, timer_factory: Optional[Callable] = None):
        self.profile_key = str(profile_key)
        self.script_path = Path(script_path) if script_path else Path(__file__).with_name('sapi_worker.ps1')
        self._popen_factory = popen_factory or subprocess.Popen
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self.idle_timeout = idle_timeout
        self.keepalive_interval = self.KEEPALIVE_INTERVAL_S if keepalive_interval is None else keepalive_interval
        self._resident = bool(resident)
        # Idle bookkeeping and restart back-off read this clock and arm these timers; tests inject fakes.
        self._clock = clock or time.monotonic
        self._timer_factory = timer_factory or threading.Timer
        self._telemetry = telemetry
        self._lock = threading.RLock()
        self._process = None
        self._responses = None
        self._reader = None
        self._eof = False  # the current child's stdout reached EOF: no response can ever arrive again
        self._idle_timer = None
        self._last_used = 0.0
        self._primed = False
        self._supervisor = None
        self._supervisor_lock = threading.Lock()  # guards the supervisor's registration only, never held across I/O
        self._wake = threading.Event()
        self._closed = False
        self._failures = 0
        self._next_attempt_at = 0.0
        atexit.register(self.close)

    @property
    def resident(self) -> bool:
        return self._resident

    def keep_resident(self):
        """Keep ONE primed worker alive for the life of the process; repair it in the background.

        Returns at once and never takes the worker lock, so it is safe to call on the event loop.
        Idempotent; also the explicit "someone needs it again" signal that re-arms a supervisor that
        gave up after MAX_AUTO_RESTARTS failed attempts.
        """
        with self._supervisor_lock:
            self._resident = True
            self._closed = False
            self._failures = 0
            self._next_attempt_at = 0.0
        self._touch_supervisor()
        self._wake.set()

    def _touch_supervisor(self):
        """Make sure the supervisor thread exists (resident managers only). Cheap, never blocks."""
        if not self._resident:
            return
        with self._supervisor_lock:
            if self._closed or self._supervisor is not None:
                return
            thread = threading.Thread(target=self._supervise, name='echo-sapi-keepalive', daemon=True)
            self._supervisor = thread
            thread.start()

    def _supervise(self):
        delay = 0.0
        try:
            while True:
                self._wake.wait(delay)
                self._wake.clear()
                with self._supervisor_lock:
                    if self._closed or not self._resident:
                        return
                try:
                    delay = max(self.MIN_PASS_S, self._supervise_step())
                except Exception as exc:  # a bug here must not end supervision silently or spin
                    logger.warning('Echo SAPI keep-alive pass failed: %s', type(exc).__name__)
                    delay = max(self.MIN_PASS_S, self.keepalive_interval)
        finally:
            with self._supervisor_lock:
                if self._supervisor is threading.current_thread():
                    self._supervisor = None

    def _supervise_step(self):
        """One keep-alive pass: leave a running, primed worker alone, otherwise (re)start it.

        Returns the seconds to sleep before the next pass. A restart that is asked for too soon after
        the previous attempt is held back (``RESTART_BACKOFF_S``), and after ``MAX_AUTO_RESTARTS``
        attempts that never proved themselves the supervisor stays quiet instead of spawning forever.
        """
        if not self._resident or self._closed:
            return self.keepalive_interval
        with self._lock:
            if not self._resident or self._closed:
                return self.keepalive_interval
            if self._alive_locked() and self._primed:
                self._failures = 0
                self._next_attempt_at = 0.0
                return self.keepalive_interval
            if self._failures >= self.MAX_AUTO_RESTARTS:
                return self.keepalive_interval
            now = self._clock()
            if now < self._next_attempt_at:
                return self._next_attempt_at - now
            self._failures += 1
            pause = self.RESTART_BACKOFF_S[min(self._failures, len(self.RESTART_BACKOFF_S)) - 1]
            self._next_attempt_at = now + pause
            try:
                self._ensure_ready_locked()
            except Exception as exc:
                code = exc.args[0] if isinstance(exc, SapiWorkerError) and exc.args else type(exc).__name__
                logger.warning('Echo SAPI worker background (re)start failed: %s', code)
                return pause
            return self.keepalive_interval

    def _alive_locked(self):
        """The child can still answer: it is running AND its stdout has not reached EOF.

        After a crash the pipe EOF is seen a few ms before Popen.poll() reports the exit (measured on
        the real worker), and a reader that stopped for any reason can no longer deliver responses.
        """
        process = self._process
        return process is not None and process.poll() is None and not self._eof

    def _on_reader_closed(self, process):
        if self._process is process:
            self._eof = True
        self._wake.set()

    def _ensure_ready_locked(self):
        """A running, primed worker; a no-op when it already is. The caller holds the lock."""
        self._start_locked()
        if not self._primed:
            self._prime_locked()

    def _prime_locked(self):
        """Speak one throwaway word so the first real cue does not pay the voice's first-Speak cost."""
        fd, name = tempfile.mkstemp(prefix='.echo-sapi-prime-', suffix='.wav')
        os.close(fd)
        os.unlink(name)
        path = Path(name)
        try:
            self._request_locked(self.PRIME_TEXT, path)
            if self.prime_lang:
                try:
                    self._request_locked('Yes.', path, None, self.PRIME_LANG_SSML)
                except SapiWorkerError:
                    pass                  # the English voice is an extra: the Russian one is primed and ready
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _cancel_idle_locked(self):
        timer, self._idle_timer = self._idle_timer, None
        if timer is not None:
            timer.cancel()

    def _schedule_idle_locked(self):
        self._cancel_idle_locked()
        if self._process is None or self.idle_timeout <= 0 or self._resident:
            return
        timer = self._timer_factory(self.idle_timeout, self._expire_idle)
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _expire_idle(self):
        with self._lock:
            self._idle_timer = None
            if self._resident:
                return  # pinned after this timer was armed: it must not cool the worker
            remaining = self.idle_timeout - (self._clock() - self._last_used)
            if remaining > 0:
                self._schedule_idle_locked()
            else:
                self._stop_locked()

    @staticmethod
    def _read_lines(stream, target, on_close=None):
        try:
            for line in stream:
                target.put(line)
        except Exception:
            pass
        finally:
            target.put(None)
            if on_close is not None:
                on_close()

    def _stop_locked(self, *, force=False):
        self._cancel_idle_locked()
        process, self._process = self._process, None
        self._responses = None
        self._primed = False
        if process is None:
            return
        try:
            if process.poll() is None:
                if force:
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=1)
                else:
                    try:
                        # The worker exits its read loop and disposes SpeechSynthesizer
                        # when stdin reaches EOF. Give it that clean shutdown first.
                        stdin = getattr(process, 'stdin', None)
                        if stdin is not None:
                            stdin.close()
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=1)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass
        for pipe in (getattr(process, 'stdin', None), getattr(process, 'stdout', None)):
            try:
                if pipe is not None:
                    pipe.close()
            except Exception:
                pass
        if self._resident and not self._closed:
            # A resident worker that went away (error, timeout, crash) is replaced in the background.
            self._wake.set()

    def _read_response_locked(self, timeout):
        try:
            line = self._responses.get(timeout=timeout)
        except queue.Empty as exc:
            self._stop_locked()
            raise SapiWorkerError('worker_timeout') from exc
        if line is None or len(line) > self.MAX_PROTOCOL_LINE:
            self._stop_locked()
            raise SapiWorkerError('worker_protocol_closed_or_oversized')
        try:
            value = json.loads(line)
        except (ValueError, TypeError) as exc:
            self._stop_locked()
            raise SapiWorkerError('worker_protocol_invalid_json') from exc
        if not isinstance(value, dict):
            self._stop_locked()
            raise SapiWorkerError('worker_protocol_invalid_shape')
        return value

    def _start_locked(self):
        if self._alive_locked():
            return
        self._stop_locked()
        if os.name != 'nt':
            raise SapiWorkerError('windows_only')
        if not self.script_path.is_file():
            raise SapiWorkerError('worker_script_missing')
        from hermes_cli._subprocess_compat import windows_hide_flags
        from tools.environments.local import hermes_subprocess_env

        env = hermes_subprocess_env(inherit_credentials=False)
        command = ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                   '-File', str(self.script_path.resolve())]
        try:
            process = self._popen_factory(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf-8', errors='strict', bufsize=1, shell=False,
                creationflags=windows_hide_flags(), env=env,
            )
        except Exception as exc:
            raise SapiWorkerError('worker_start_failed') from exc
        self._process = process
        self._primed = False
        self._eof = False
        self._responses = queue.Queue()
        # EOF on the child's stdout (it exited or crashed, even while idle) ends this worker
        # and wakes the supervisor.
        self._reader = threading.Thread(target=self._read_lines, daemon=True,
                                        args=(process.stdout, self._responses, partial(self._on_reader_closed, process)))
        self._reader.start()
        ready = self._read_response_locked(self.startup_timeout)
        if (ready.get('type') != 'ready' or ready.get('voice') != self.VOICE
                or ready.get('culture') != self.CULTURE):
            self._stop_locked()
            raise SapiWorkerError('worker_ready_mismatch')
        self._last_used = self._clock()

    @staticmethod
    def _validate_wav(path: Path):
        try:
            with wave.open(str(path), 'rb') as audio:
                if (audio.getframerate() != SapiWorkerManager.SAMPLE_RATE
                        or audio.getnchannels() != 1 or audio.getsampwidth() != 2
                        or audio.getcomptype() != 'NONE'):
                    raise SapiWorkerError('wav_format_mismatch')
                frames = audio.getnframes()
                if frames <= 0 or len(audio.readframes(frames)) != frames * 2:
                    raise SapiWorkerError('wav_empty_or_truncated')
        except (OSError, EOFError, wave.Error) as exc:
            raise SapiWorkerError('wav_invalid') from exc

    def _request_locked(self, text: str, output: Path, trace=None, ssml: Optional[str] = None):
        self._cancel_idle_locked()
        startup_started = time.monotonic()
        was_cold = not self._alive_locked()
        from .tts_telemetry import safe_trace_set
        safe_trace_set(trace, 'cold_warm', 'cold' if was_cold else 'warm')
        try:
            self._start_locked()
        finally:
            if was_cold:
                safe_trace_set(trace, 'startup_ms', (time.monotonic() - startup_started) * 1000)
        request_id = getattr(trace, 'trace_id', None) or uuid.uuid4().hex
        request = {'id': request_id, 'text': text, 'output_path': str(output.resolve())}
        if ssml:
            request['ssml'] = ssml
        process = self._process
        deadline = time.monotonic() + self.request_timeout
        write_result = queue.Queue(maxsize=1)

        def write_request():
            try:
                process.stdin.write(json.dumps(request, ensure_ascii=False) + '\n')
                process.stdin.flush()
                write_result.put(None)
            except Exception as exc:
                write_result.put(exc)

        threading.Thread(target=write_request, name='echo-sapi-writer', daemon=True).start()
        try:
            write_started = time.monotonic()
            write_error = write_result.get(timeout=self.request_timeout)
        except queue.Empty as exc:
            safe_trace_set(trace, 'write_wait_ms', (time.monotonic() - write_started) * 1000)
            # Terminate the owned child before closing a pipe that may be held by
            # a blocked WriteFile call in the writer thread.
            self._stop_locked(force=True)
            raise SapiWorkerError('worker_write_timeout') from exc
        safe_trace_set(trace, 'write_wait_ms', (time.monotonic() - write_started) * 1000)
        if write_error is not None:
            self._stop_locked(force=True)
            raise SapiWorkerError('worker_write_failed') from write_error
        synth_started = time.monotonic()
        try:
            result = self._read_response_locked(max(0.0, deadline - time.monotonic()))
        finally:
            safe_trace_set(trace, 'synth_wait_ms', (time.monotonic() - synth_started) * 1000)
        if result.get('type') != 'result' or result.get('id') != request_id:
            self._stop_locked()
            raise SapiWorkerError('worker_response_mismatch')
        if result.get('ok') is not True:
            self._last_used = self._clock()
            self._schedule_idle_locked()
            raise SapiWorkerError(str(result.get('error') or 'synthesis_failed'))
        if result.get('voice') != self.VOICE or result.get('culture') != self.CULTURE:
            self._stop_locked()
            raise SapiWorkerError('worker_voice_mismatch')
        if ssml and result.get('ssml') is not True:
            logger.warning('Echo SAPI worker: the voice refused the markup, the cue was spoken plain')   # E76: a silent loss of the intonation
            if '<voice ' in ssml:
                self.lang_fallbacks += 1
                safe_trace_set(trace, 'lang_fallback', self.lang_fallbacks)
        self._last_used = self._clock()
        self._primed = True  # the voice has now spoken once: nothing left to absorb
        self._schedule_idle_locked()

    def warm(self):
        """Start the worker and prime it now (blocking), so the first cue finds it hot."""
        self._closed = False
        self._touch_supervisor()
        with self._lock:
            self._cancel_idle_locked()
            self._ensure_ready_locked()
            self._last_used = self._clock()
            self._schedule_idle_locked()

    def release(self):
        if self._resident:
            # A speech lease going away does not free the resident worker; this also keeps the
            # call from waiting on the worker lock while a cue is being synthesized.
            return
        with self._lock:
            if self._process is not None:
                self._last_used = self._clock()
                self._schedule_idle_locked()

    def synthesize(self, text: str, output_path: str, end: Optional[str] = None, lang: bool = False) -> str:
        """``lang``: English runs go to the English voice (U19-S5). ``end``: a key of END_STYLES (E76) when this is the last portion of an answer; anything else, or a text with nothing to mark,
        is spoken exactly as before. The markup is built here, in Python, where it is testable; a failure of it only means plain speech."""
        if not isinstance(text, str) or not text.strip() or len(text) > self.MAX_TEXT:
            raise SapiWorkerError('bad_text')
        ssml = None
        if lang:                                           # U19-S5: language wins over the end intonation
            try:
                ssml = lang_ssml(text)
            except Exception:
                ssml = None
        style = END_STYLES.get(end) if isinstance(end, str) else None
        if style and ssml is None:
            try:
                ssml = end_ssml(text, **style)
            except Exception:  # an optimisation must never fail a live call
                ssml = None
        self._closed = False
        self._touch_supervisor()
        target = Path(output_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.echo-sapi-', suffix='.wav', dir=str(target.parent))
        os.close(fd)
        os.unlink(temporary)
        temporary_path = Path(temporary)
        from .tts_telemetry import current_trace, TtsLatencyTrace
        own_trace = current_trace() is None and self._telemetry is not None
        trace = TtsLatencyTrace(self._telemetry) if own_trace else current_trace()
        started = time.monotonic()
        lock_started = started
        try:
            with self._lock:
                lock_acquired = time.monotonic()
                from .tts_telemetry import safe_trace_set, safe_trace_finish
                safe_trace_set(trace, 'lock_wait_ms', (lock_acquired - lock_started) * 1000)
                self._request_locked(text, temporary_path, trace, ssml)
                validate_started = time.monotonic()
                try:
                    self._validate_wav(temporary_path)
                finally:
                    safe_trace_set(trace, 'validate_ms', (time.monotonic() - validate_started) * 1000)
                os.replace(str(temporary_path), str(target))
                # A cue that came out is proof of life that the worker's own priming is not: earlier
                # restarts are forgiven (a restart that dies again at once is not).
                self._failures = 0
                self._next_attempt_at = 0.0
            if own_trace:
                safe_trace_finish(trace, 'success')
            return str(target)
        except SapiWorkerError as exc:
            if exc.args and exc.args[0].startswith(('worker_protocol', 'worker_response', 'worker_voice', 'wav_')):
                with self._lock:
                    self._stop_locked()
            if own_trace:
                safe_trace_finish(trace, 'error', exc.args[0] if exc.args else None)
            raise
        except OSError as exc:
            with self._lock:
                self._stop_locked()
            if own_trace:
                safe_trace_finish(trace, 'error', 'output_file_failed')
            raise SapiWorkerError('output_file_failed') from exc
        finally:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    def close(self):
        """Stop the worker now and end supervision. A later cue/warm/keep_resident starts it afresh."""
        with self._supervisor_lock:
            self._closed = True
            supervisor = self._supervisor
        self._wake.set()
        with self._lock:
            self._stop_locked()
        if supervisor is not None and supervisor is not threading.current_thread():
            supervisor.join(timeout=2)


if not hasattr(builtins, '_echo_sapi_profile_workers'):
    builtins._echo_sapi_profile_workers = ({}, threading.Lock())
_PROFILE_WORKERS, _PROFILE_WORKERS_LOCK = builtins._echo_sapi_profile_workers


def profile_sapi_worker(profile_home: str | Path) -> SapiWorkerManager:
    """Get the single worker owner for one resolved Hermes profile home.

    The profile's worker is resident: it lives as long as the server and nothing starts until the
    first cue, warm() or keep_resident() touches it (looking it up has no side effects).
    """
    key = os.path.normcase(str(Path(profile_home).expanduser().resolve()))
    with _PROFILE_WORKERS_LOCK:
        manager = _PROFILE_WORKERS.get(key)
        if manager is None:
            from .tts_telemetry import TtsLatencyCollector
            telemetry = TtsLatencyCollector(Path(key) / 'echo-sync' / 'tts-latency.jsonl')
            manager = SapiWorkerManager(key, telemetry=telemetry, resident=True)
            _PROFILE_WORKERS[key] = manager
        return manager


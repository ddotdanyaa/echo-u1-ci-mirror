"""CL1: through controlled_host.serve - the owner's lesson is read when a call OPENS and goes into the cloud session of that call.

The real serve(), the real loader and assembler, a fake phone, a fake helper pipe and a recording stand-in for
create_gpt_live_session (the only place the cloud sees the instructions). No restart between calls: the files are the state.
"""
import asyncio
import logging
import threading
import time
from pathlib import Path

import helpers_s6_fault as F
from echo_sync import controlled_host, warm
from echo_sync.content_policy import ANSWER_POLICY, POLICY_VERSION, CallContext
from echo_sync.materials import import_materials
from helpers_spoken_diagnostics import run_host


def record_sessions(host):
    """Replace the host's create_gpt_live_session by one that keeps the keywords of every call."""
    sent = []

    def create(sdp, **kwargs):
        sent.append(kwargs)
        return {'auth': 'subscription', 'transport': {'sdp': 'answer-sdp'}}
    host.api.create_gpt_live_session = create
    return sent


def lesson(home, *, subject=None, context=None):
    folder = Path(home) / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    if subject is not None:
        (folder / 'echo_settings.json').write_text('{"portion_mode": "words", "subject": "%s"}' % subject, encoding='utf-8')
    if context is not None:
        (folder / 'context.md').write_text(context, encoding='utf-8')


def test_the_session_of_a_call_gets_the_policy_the_subject_and_the_material(tmp_path, monkeypatch):
    async def body(host):
        sent = record_sessions(host)
        lesson(host.home, subject='Налоговое право', context='Налог на прибыль организаций платят юридические лица.')
        await host.handshake()
        assert len(sent) == 1 and sent[0]['billing'] == 'subscription'
        text = sent[0]['_content_instructions']
        assert text.startswith(ANSWER_POLICY)
        assert 'Предмет занятия: Налоговое право\n' in text
        assert 'Налог на прибыль организаций платят юридические лица.' in text
        assert text.index('Предмет занятия') > len(ANSWER_POLICY)
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_a_profile_with_no_lesson_gets_exactly_the_policy(tmp_path, monkeypatch):
    async def body(host):
        sent = record_sessions(host)
        await host.handshake()
        assert [call['_content_instructions'] for call in sent] == [ANSWER_POLICY]
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_the_next_call_uses_the_changed_files_with_no_restart_in_between(tmp_path, monkeypatch):
    """Break: a lesson read once at server start - the owner loads a new lecture and the old one keeps answering until a restart."""
    async def main():
        F.patch_clock(monkeypatch)
        seen = []
        for subject, text in (('Физика', 'Закон Ома связывает ток и напряжение.'), ('Химия', 'Сублимация - переход из твёрдого в газ.')):
            async with F.HostRig(tmp_path, monkeypatch) as host:
                sent = record_sessions(host)
                lesson(host.home, subject=subject, context=text)
                await host.handshake()
                seen.append(sent[0]['_content_instructions'])
        first, second = seen
        assert 'Предмет занятия: Физика' in first and 'Закон Ома' in first and 'Химия' not in first
        assert 'Предмет занятия: Химия' in second and 'Сублимация' in second
        assert 'Физика' not in second and 'Закон Ома' not in second
    F.run(main)


def test_every_call_logs_the_subject_the_version_and_the_sizes_but_never_the_material(tmp_path, monkeypatch):
    async def body(host):
        record_sessions(host)
        result = import_materials([_source(tmp_path, 'СЕКРЕТНАЯ ФРАЗА: ставка налога на прибыль.')], host.home)
        lesson(host.home, subject='Налоговое право')
        await host.handshake()
        text = host.logger.text(logging.INFO)
        line = next(l for l in text.splitlines() if l.startswith('Controlled call context'))
        assert POLICY_VERSION in line and "subject='Налоговое право'" in line
        assert 'sha256:' + result['manifest']['context_hash'][:12] in line
        assert 'material_chars=' in line and 'excerpt_chars=' in line and 'instructions_chars=' in line
        assert 'СЕКРЕТНАЯ' not in text and 'ставка налога' not in text
    run_host(tmp_path, monkeypatch, body, handshake=False)


def _source(tmp_path, text):
    path = Path(tmp_path) / 'источник.txt'
    path.write_text(text, encoding='utf-8')
    return path


def test_a_tampered_or_broken_lesson_never_fails_the_call(tmp_path, monkeypatch):
    """Break: a file the owner can fix in a minute turns into «Связь прервалась» on a live call."""
    async def body(host):
        sent = record_sessions(host)
        import_materials([_source(tmp_path, 'Настоящий текст.')], host.home)
        path = host.home / 'materials' / 'context.md'
        path.write_bytes(path.read_bytes().replace('Настоящий'.encode(), 'Подменённый'.encode()))
        (host.home / 'materials' / 'echo_settings.json').write_text('{not json', encoding='utf-8')
        await host.handshake()
        assert [call['_content_instructions'] for call in sent] == [ANSWER_POLICY]
        assert not host.errors()
        assert 'note=integrity' in host.logger.text(logging.INFO)
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_even_a_bug_in_the_loader_degrades_to_the_bare_policy_and_is_logged_by_type_only(tmp_path, monkeypatch):
    async def body(host):
        sent = record_sessions(host)

        def broken(home):
            raise RuntimeError('SECRET detail of the failure')
        monkeypatch.setattr(warm.material_cache, 'loader', broken)
        await host.handshake()
        assert [call['_content_instructions'] for call in sent] == [ANSWER_POLICY]
        warnings = host.logger.text(logging.WARNING)
        assert 'Controlled call context unavailable' in warnings and 'type=RuntimeError' in warnings
        assert 'SECRET' not in host.logger.text(logging.INFO)
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_the_files_are_read_off_the_event_loop(tmp_path, monkeypatch):
    """Break: a slow disk (an antivirus scan of a 180 kB file) stalling every timer of the call, the repeat timer included."""
    async def body(host):
        record_sessions(host)
        threads = []
        real = warm.material_cache.loader

        def spy(home):
            threads.append(threading.current_thread())
            return real(home)
        monkeypatch.setattr(warm.material_cache, 'loader', spy)
        loop_thread = threading.current_thread()
        await host.handshake()
        assert threads and all(t is not loop_thread for t in threads)
    run_host(tmp_path, monkeypatch, body, handshake=False)


def test_a_read_of_the_lesson_that_never_returns_still_opens_the_call_with_the_bare_policy(tmp_path, monkeypatch):
    """Break (review P3-1): a HANG in the read (a locked file, a dead network drive), unlike an exception, was not degraded to the
    bare policy: it ate the 18 s cap of both attempts of the open and the call failed. The lesson is an addition to a call.

    This one runs on a REAL event loop: the virtual clock of the other tests stands still while a thread job is in flight, so
    it could never show a timeout. The stub is freed at the end (a thread cannot be killed; it only stops being waited for)."""
    release, entered = threading.Event(), threading.Event()

    def hangs(home):
        entered.set()
        release.wait(30)                              # stands for a read that never returns (freed by the test at the end)
        return CallContext(subject='must never reach the call')
    monkeypatch.setattr(warm.material_cache, 'loader', hangs)

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            sent = record_sessions(host)
            started = time.monotonic()
            try:
                await host.handshake()
                spent = time.monotonic() - started
                assert entered.is_set(), 'the stub was never reached: the test does not test the read'
                assert [call['_content_instructions'] for call in sent] == [ANSWER_POLICY]
                warnings = host.logger.text(logging.WARNING)
                assert 'Controlled call context unavailable' in warnings and 'type=TimeoutError' in warnings
                assert spent < 12, f'the open waited {spent:.1f} s for a read that never returned'
                assert not host.errors()
            finally:
                release.set()
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(main())


def test_a_retried_open_carries_what_the_files_hold_at_that_moment(tmp_path, monkeypatch):
    """The first try of an open can fail; the retry is a new cloud session and carries what the files hold at that moment: the cache of the material is keyed by their size and times, so unchanged files are not read twice and a rewritten one is read again."""
    async def body(host):
        sent = record_sessions(host)
        lesson(host.home, subject='Физика')
        reads = []
        real = warm.material_cache.loader

        def spy(home):
            reads.append(1)
            return real(home)
        monkeypatch.setattr(warm.material_cache, 'loader', spy)
        host.start_fault = _Once('the helper process could not be started')
        await host.handshake()
        assert len(reads) == 1 and len(sent) == 1, (len(reads), len(sent))      # the retry of unchanged files is the cache's hit
        assert 'Предмет занятия: Физика' in sent[0]['_content_instructions']
    run_host(tmp_path, monkeypatch, body, handshake=False)


class _Once(RuntimeError):
    """FakeBridge.start raises ``owner.start_fault`` while it is truthy: this one is truthy the first time only."""

    def __init__(self, *args):
        super().__init__(*args)
        self.armed = True

    def __bool__(self):
        armed, self.armed = self.armed, False
        return armed

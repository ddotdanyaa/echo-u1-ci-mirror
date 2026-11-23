"""Owned worker execution. A Windows job is assigned before the first instruction."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

JOB_LIMIT_FLAGS = 0x2000 | 0x100        # KILL_ON_JOB_CLOSE | PROCESS_MEMORY
JOB_PROCESS_MEMORY_BYTES = 1536 * 1024 * 1024   # a leaking node must not choke the laptop


def kilo_argv(*, entry: str | None = None, node: str | None = None) -> list[str]:
    entry = entry or os.environ.get('FACTORY_KILO_ENTRY')
    if entry:
        path = Path(entry).resolve(strict=True)
        if path.suffix.lower() in ('.cmd', '.bat'):
            raise ValueError('JavaScript entrypoint required')
        binary = node or shutil.which('node')
        if not binary:
            raise FileNotFoundError('node unavailable')
        return [binary, str(path)]
    binary = shutil.which('kilo')
    if binary and Path(binary).suffix.lower() in ('.cmd', '.bat'):
        # npm places the shim alongside node_modules. Read the installed bin map.
        import json
        package = Path(binary).parent / 'node_modules/@kilocode/cli/package.json'
        manifest = json.loads(package.read_text(encoding='utf-8'))
        relative = manifest['bin']
        relative = relative['kilo'] if isinstance(relative, dict) else relative
        target = (package.parent / relative).resolve(strict=True)
        if not target.is_relative_to(package.parent.resolve()):
            raise ValueError('entrypoint escapes installed package')
        return kilo_argv(entry=str(target), node=node)
    if not binary:
        raise FileNotFoundError('kilo unavailable')
    return [binary]


class Owned:
    """One child in its own job (Windows) or process group (POSIX): started suspended and assigned before its first
    instruction; closing the job kills every descendant. ``proc`` is the Popen."""

    def __init__(self, proc, job=None, kernel=None, args=None):
        self.proc, self.job, self._kernel, self.args = proc, job, kernel, args
        self.pid = proc.pid

    def poll(self):
        return self.proc.poll()

    def wait(self, timeout=None):
        return self.proc.wait(timeout=timeout)

    def communicate(self, timeout=None, input=None):
        if input is None:
            return self.proc.communicate(timeout=timeout)
        return self.proc.communicate(input=input, timeout=timeout)

    def peak_bytes(self) -> int | None:
        """The job's peak memory (Windows JobObjectExtendedLimitInformation.job_peak), None when unknown."""
        if self.job is None:
            return None
        import ctypes
        ext = _extended_type()
        info = ext()
        got = ctypes.c_uint32()
        ok = self._kernel.QueryInformationJobObject(self.job, 9, ctypes.byref(info), ctypes.sizeof(info),
                                                    ctypes.byref(got))
        return int(info.job_peak) if ok else None

    def kill(self):
        """The whole tree dies: the job is closed (Windows) / the group is killed (POSIX)."""
        self.close()
        if self.proc.poll() is None:
            self.proc.kill()

    def close(self):
        if os.name != 'nt':
            import signal
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                pass
        elif self.job is not None:
            job, self.job = self.job, None
            self._kernel.CloseHandle(job)       # kills descendants even when the parent exited first
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _extended_type():
    import ctypes
    from ctypes import wintypes as W

    class Basic(ctypes.Structure):
        _fields_ = [('per_process_time', ctypes.c_int64), ('per_job_time', ctypes.c_int64),
                    ('flags', W.DWORD), ('minimum', ctypes.c_size_t),
                    ('maximum', ctypes.c_size_t), ('active', W.DWORD),
                    ('affinity', ctypes.c_size_t), ('priority', W.DWORD),
                    ('scheduling', W.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ('read_ops', 'write_ops', 'other_ops', 'read_bytes',
                     'write_bytes', 'other_bytes')]

    class Extended(ctypes.Structure):
        _fields_ = [('basic', Basic), ('io', IO), ('process_limit', ctypes.c_size_t),
                    ('job_limit', ctypes.c_size_t), ('process_peak', ctypes.c_size_t),
                    ('job_peak', ctypes.c_size_t)]
    return Extended


def start_owned(args, *, cwd, env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, input=None) -> Owned:
    """Start ``args`` owned (see Owned). stdout/stderr: PIPE (default) or open files (a worker the caller does not read
    while it runs)."""
    if os.name != 'nt':
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL, stdout=stdout,
                                stderr=stderr, start_new_session=True)
        return Owned(proc, args=args)
    import ctypes
    from ctypes import wintypes as W
    Extended = _extended_type()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]
    kernel.CreateJobObjectW.restype = W.HANDLE
    kernel.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
    kernel.QueryInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD,
                                                 ctypes.POINTER(W.DWORD)]
    kernel.AssignProcessToJobObject.argtypes = [W.HANDLE, W.HANDLE]
    kernel.CloseHandle.argtypes = [W.HANDLE]
    native = ctypes.WinDLL('ntdll')
    native.NtResumeProcess.argtypes = [W.HANDLE]
    native.NtResumeProcess.restype = ctypes.c_long
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    proc = None
    try:
        limits = Extended()
        limits.basic.flags = JOB_LIMIT_FLAGS
        limits.process_limit = JOB_PROCESS_MEMORY_BYTES
        if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        proc = subprocess.Popen(args, cwd=cwd, env=env, shell=False, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                                stdout=stdout, stderr=stderr,
                                creationflags=0x4 | 0x08000000)  # suspended, hidden
        if not kernel.AssignProcessToJobObject(job, W.HANDLE(int(proc._handle))):
            raise ctypes.WinError(ctypes.get_last_error())
        if native.NtResumeProcess(W.HANDLE(int(proc._handle))) != 0:
            raise OSError('could not resume owned worker')
    except BaseException:
        kernel.CloseHandle(job)
        if proc is not None:
            if proc.poll() is None:
                proc.kill()  # also covers failed assignment of a suspended process
            proc.wait()
        raise
    return Owned(proc, job, kernel, args)


def run_owned(args, *, cwd, env, timeout, input=None):
    owned = start_owned(args, cwd=cwd, env=env, **({'input': input} if input is not None else {}))
    try:
        stdout, stderr = owned.communicate(timeout=timeout, **({'input': input} if input is not None else {}))
        return subprocess.CompletedProcess(args, owned.proc.returncode, stdout, stderr)
    finally:
        owned.close()
        if owned.proc.poll() is None:
            owned.proc.kill()
        owned.proc.communicate()


def claude_argv(*, entry: str | None = None, node: str | None = None) -> list[str]:
    """Resolve a native CLI or npm shim without executing a command shell."""
    binary = entry or os.environ.get('FACTORY_CLAUDE_BIN') or shutil.which('claude')
    if not binary:
        binary = str(Path.home() / '.local' / 'bin' / 'claude.exe')
    path = Path(binary).resolve(strict=True)
    if path.suffix.lower() in ('.cmd', '.bat'):
        import json
        package = path.parent / 'node_modules/@anthropic-ai/claude-code/package.json'
        manifest = json.loads(package.read_text(encoding='utf-8'))
        relative = manifest['bin']
        relative = relative['claude'] if isinstance(relative, dict) else relative
        target = (package.parent / relative).resolve(strict=True)
        if not target.is_relative_to(package.parent.resolve()):
            raise ValueError('entrypoint escapes installed package')
        binary = node or shutil.which('node')
        if not binary:
            raise FileNotFoundError('node unavailable')
        return [binary, str(target)]
    return [str(path)]

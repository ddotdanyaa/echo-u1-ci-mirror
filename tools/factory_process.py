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


def run_owned(args, *, cwd, env, timeout):
    if os.name != 'nt':
        # A process group owns descendants on POSIX too.
        import signal
        proc = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, start_new_session=True)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
            return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
        finally:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
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

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, W.LPCWSTR]
    kernel.CreateJobObjectW.restype = W.HANDLE
    kernel.SetInformationJobObject.argtypes = [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD]
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
        proc = subprocess.Popen(args, cwd=cwd, env=env, shell=False, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                creationflags=0x4 | 0x08000000)  # suspended, hidden
        if not kernel.AssignProcessToJobObject(job, W.HANDLE(int(proc._handle))):
            raise ctypes.WinError(ctypes.get_last_error())
        if native.NtResumeProcess(W.HANDLE(int(proc._handle))) != 0:
            raise OSError('could not resume owned worker')
        stdout, stderr = proc.communicate(timeout=timeout)
        return subprocess.CompletedProcess(args, proc.returncode, stdout, stderr)
    finally:
        kernel.CloseHandle(job)  # kills descendants even when parent exited first
        if proc is not None:
            if proc.poll() is None:
                proc.kill()  # also covers failed assignment of a suspended process
            proc.communicate()

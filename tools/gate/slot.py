"""N183: one heavy test run at a time on a machine. flock on a lock file (released by the kernel if the owner dies) plus an owner note for the message."""
import json
import os
import time
from pathlib import Path

try:
    import fcntl
except ImportError:                                   # Windows: msvcrt byte lock
    fcntl = None
    import msvcrt


class SlotBusy(RuntimeError):
    pass


class HeavySlot:
    def __init__(self, path, owner='', wait=0.0):
        self.path, self.owner, self.wait, self.fd = Path(path), owner, wait, None

    def _try(self):
        if fcntl:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)

    def holder(self):
        try:
            return json.loads(self.path.read_text(encoding='utf-8') or '{}')
        except (OSError, ValueError):
            return {}

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o644)
        end = time.monotonic() + self.wait
        while True:
            try:
                self._try()
                break
            except OSError:
                if time.monotonic() >= end:
                    h = self.holder()
                    os.close(self.fd)
                    self.fd = None
                    raise SlotBusy(f"heavy slot {self.path} is held by {h.get('owner') or '?'} pid {h.get('pid', '?')} since {h.get('at', '?')}")
                time.sleep(0.05)
        os.ftruncate(self.fd, 0)
        os.write(self.fd, json.dumps({'pid': os.getpid(), 'owner': self.owner, 'at': time.time()}).encode())
        return self

    def release(self):
        if self.fd is not None:
            try:
                os.ftruncate(self.fd, 0)
                if fcntl:
                    fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                os.close(self.fd)
                self.fd = None

    __enter__ = acquire

    def __exit__(self, *exc):
        self.release()

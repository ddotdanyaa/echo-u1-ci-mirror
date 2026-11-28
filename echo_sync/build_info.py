"""W03, T01, N186: what build and what code this process runs. Its own module (W13 item 10): the deploy copies every module of the
package into ``echo_controlled`` but ``__init__.py`` (it writes a stub there), so what the host imports must not live in ``__init__.py``."""
import hashlib
import json
import marshal
import pathlib
import subprocess
import sys

_PACKAGE = __name__.rpartition('.')[0] or __name__     # ``echo_sync``, or ``echo_controlled`` where the deploy put it


def build_id(root=None):
    """T01: what build the loaded package is: the ``BUILD`` file the deploy writes beside it, else the git commit of its checkout (12 hex), else 'unknown'. Never raises."""
    root = pathlib.Path(root) if root is not None else pathlib.Path(__file__).resolve().parent
    try:
        text = (root / 'BUILD').read_text(encoding='utf-8').strip().lower()
        if text:
            return text
    except OSError:
        pass
    try:
        if root.is_dir():
            done = subprocess.run(['git', '-C', str(root), 'rev-parse', '--short=12', 'HEAD'], capture_output=True, text=True, timeout=2, check=True)
            return done.stdout.strip() or 'unknown'
    except Exception:     # noqa: BLE001 - no git, no checkout, a timeout: the build is unknown
        pass
    return 'unknown'


def _build_id_at(folder):
    """N186 (w9-gate): ``build_id`` of a folder: the BUILD file wins (its first word), else the git commit, else 'unknown'."""
    found = build_id(folder)
    return found.split()[0] if found else 'unknown'


def _code_digest(module):
    """W03: the code the process runs for ``module``: every function of it and of its classes, by its code object (``marshal``), in name order."""
    digest = hashlib.sha256()
    for name, value in sorted(vars(module).items()):
        for owner, item in [(name, value)] + ([(f'{name}.{key}', member) for key, member in sorted(vars(value).items())] if isinstance(value, type) and value.__module__ == module.__name__ else []):
            code = getattr(getattr(item, '__func__', item), '__code__', None)
            if code is not None:
                digest.update(owner.encode() + b'\0' + marshal.dumps(code))
    return digest.hexdigest()[:12]


def fingerprint(settings=None):
    """W03: what this process has loaded, from the process: ``build`` (``build_id``), ``modules`` (each loaded ``echo_sync`` module, ``_code_digest``), ``prompt`` (the BRAIN of the text channel),
    ``flags`` (the resolved settings given, sorted), and ``digest`` over all of them. Numbers only: no word of a call. Never raises for one module that cannot be read: it is named 'unreadable'."""
    modules = {}
    for name, module in sorted(sys.modules.items()):
        if module is not None and (name == _PACKAGE or name.startswith(_PACKAGE + '.')):
            try:
                modules[name] = _code_digest(module)
            except Exception:     # noqa: BLE001 - one module is not the whole answer
                modules[name] = 'unreadable'
    try:
        from .fast_text import BRAIN
        prompt = hashlib.sha256(str(BRAIN).encode()).hexdigest()[:12]
    except Exception:     # noqa: BLE001
        prompt = 'unreadable'
    flags = hashlib.sha256(json.dumps(settings, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12] if settings is not None else ''
    out = {'build': build_id(), 'modules': modules, 'prompt': prompt, 'flags': flags}
    out['digest'] = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()[:12]
    return out

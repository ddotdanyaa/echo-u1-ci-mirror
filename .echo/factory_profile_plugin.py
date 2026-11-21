
import json, os, sys, threading
import pytest

_root = os.path.realpath(os.environ["FACTORY_PROFILE_ROOT"])
_root_n = os.path.normcase(_root) + os.sep
_prefixes = tuple(p for p in os.environ.get("FACTORY_PROFILE_PREFIXES", "").split("|") if p)
_out = os.environ["FACTORY_PROFILE_OUT"]
_cur = set()
_tests = {}
_res = {}
_tool = None
_fallback = False
_cache = {}


def _rel(filename):
    r = _cache.get(filename)
    if r is None:
        r = ""
        try:
            full = os.path.realpath(filename)
        except (OSError, ValueError):
            full = ""
        if full and os.path.normcase(full).startswith(_root_n):
            rel = full[len(_root) + 1:].replace(os.sep, "/")
            if (rel.startswith(_prefixes) and not rel.startswith("tests/")
                    and rel.rsplit("/", 1)[-1] != "conftest.py"):
                r = rel
        _cache[filename] = r
    return r


def _record(code):
    rel = _rel(code.co_filename)
    if rel and "<" not in code.co_qualname:
        _cur.add((rel, code.co_qualname, code.co_firstlineno))


def _cb(code, offset):
    _record(code)
    return sys.monitoring.DISABLE


def _prof(frame, event, arg):
    if event == "call":
        _record(frame.f_code)


def pytest_configure(config):
    global _tool, _fallback
    mon = None if os.environ.get("FACTORY_PROFILE_FALLBACK") else getattr(sys, "monitoring", None)
    if mon is not None:
        for tid in (3, 4, 1, 2):
            try:
                mon.use_tool_id(tid, "factory_profile")
            except ValueError:
                continue
            mon.register_callback(tid, mon.events.PY_START, _cb)
            mon.set_events(tid, mon.events.PY_START)
            _tool = tid
            return
    _fallback = True
    sys.setprofile(_prof)
    threading.setprofile(_prof)


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_protocol(item, nextitem):
    global _cur
    _cur = set()
    if _tool is not None:
        sys.monitoring.restart_events()
    yield
    _tests[item.nodeid] = sorted(_cur)


def pytest_runtest_logreport(report):
    st = _res.setdefault(report.nodeid, {"call": None, "error": False, "skipped": False, "msg": ""})
    if report.failed:
        crash = getattr(report.longrepr, "reprcrash", None)
        st["msg"] = st["msg"] or str(getattr(crash, "message", "") or "")[:300]
    if report.when == "call":
        st["call"] = report.outcome
    elif report.failed:
        st["error"] = True
    elif report.skipped:
        st["skipped"] = True


def pytest_sessionfinish(session):
    if _tool is not None:
        sys.monitoring.set_events(_tool, 0)
    else:
        sys.setprofile(None)
    tests = {}
    for nodeid, st in _res.items():
        outcome = "error" if st["error"] else (st["call"] or ("skipped" if st["skipped"] else "error"))
        tests[nodeid] = {"outcome": outcome, "calls": [list(c) for c in _tests.get(nodeid, [])],
                          "msg": st["msg"]}
    with open(_out, "w", encoding="utf-8") as f:
        json.dump({"fallback": _fallback, "tests": tests}, f)

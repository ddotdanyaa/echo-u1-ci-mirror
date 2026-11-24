"""W-hyp: many independent hypotheses -> one batch verifier (<id>: k independent fast models -> a deterministic checker).

A row that already has a red test on the current base gets, WITHOUT the slicer's contract, one small card per function the
test ran (<= HYPO_FUNCS, ranked: failure stack -> functions of the guilty diff -> near the assert in the trace -> the rest).
Free fast models answer each card twice (REPLACE FUNCTION / CANNOT); an instant checker (AST, undefined names, "the edit changes the
function", fingerprint dedup) drops the dead ones; <= BATCH_MAX candidates go to ONE cloud run that applies them one by one and
runs the named red ids.  A green candidate becomes an ordinary card WITH code (parts[].code, the W-dry mechanism: no model
call) and test.use = the red id: the usual gates, reviews and merge stay.  All red: one repair round for the 3 best, then the
slicer gets the evidence.  Everything outside (channels, cloud, clock) is injected through ``Ctx``; no second merge path.
"""
import ast
import collections
import difflib
import json
import re
import threading
import time
from pathlib import Path

from tools import factory_cards as K
from tools import factory_ensemble as ENS

HYPO_FUNCS = 8                  # functions per row
CARD_TOKENS = 1000              # target size of one card (input tokens)
TEST_LINES = 40                 # the test body shown, lines
TEMPS = (0.2, 0.8)              # two independent answers per hypothesis
REPAIR_TEMPS = (0.5, 1.0)
REPAIR_TOP = 3
BATCH_MAX = 24
ROW_COOLDOWN_S = 12 * 3600      # the same base+test is not searched again sooner
TPM = 16000                     # input tokens a minute per channel
DEFAULT_CHANNELS = ("default",)  # a bare pump (no loop): one anonymous channel; the loop names the real ones (channels.json ids)
FAILS_MAX = 12                  # network refusals of one hypothesis before it is dropped
WAIT_MAX_S = 5.0                # a worker waits at most this long for a closed channel
SHUT_MAX_S = 1.0                # a channel that said 'no_channel' takes no booking from its other workers for at most this long
SAMPLES_MAX = 20                # kept first answers of each bad / invalid kind (hypo_samples.json)
RETRY_REFUSED_S = 30.0             # a refused hypothesis waits this long for the SAME channel (others take it at once)
PER_CHANNEL = 4                 # concurrent requests of the pump on one channel
CLOUD_TRIES = 3
FAIL_TEXT = 400
ASK_TERM_S = 120.0
RECENT_RE = re.compile(r"^\s*(\S+\.py):(\d+): in (\w+)", re.M)
TB_RE = re.compile(r'File "([^"]+\.py)", line (\d+), in (\w+)')


def est_tokens(text: str) -> int:
    return len(text) // 3 + 1


class CloudFail(RuntimeError):
    """The cloud did not answer (down, busy, unreadable): the batch is repeated, nothing is penalised."""


# ------------------------------------------------------------------------------------------------ 1. hypotheses
def _product(path: str) -> bool:
    p = path.replace("\\", "/")
    return p.endswith(".py") and not p.startswith(("tests/", "test/")) and "/tests/" not in p and "/test_" not in p \
        and not p.rsplit("/", 1)[-1].startswith("test_")


def stack_from_failure(text: str) -> list:
    """[(file, name)] of the frames of a failure text, the deepest frame first (pytest short and plain tracebacks)."""
    frames = [(m.group(1).replace("\\", "/"), m.group(3)) for m in RECENT_RE.finditer(text or "")]
    frames += [(m.group(1).replace("\\", "/"), m.group(3)) for m in TB_RE.finditer(text or "")]
    out = []
    for f in reversed(frames):
        if f not in out:
            out.append(f)
    return out


def _resolve(root, file: str, name: str):
    """The qualified symbol of the product file whose last part is ``name`` (None when the file or name is not there)."""
    path = Path(root) / file
    try:
        found = K._symbols(ast.parse(path.read_text(encoding="utf-8-sig")))
    except (OSError, SyntaxError, ValueError, UnicodeError):
        return None
    for q, node in found.items():
        if q.rpartition(".")[2] == name and K._is_function(node):
            return q
    return None


def rank_functions(root, *, stack=(), diff=(), trace=(), ranked=(), k=HYPO_FUNCS) -> list:
    """[{'file','symbol','why'}] up to ``k``: functions of the failure stack, then of the guilty commit's diff, then those
    nearest (latest) before the assert in the trace, then the rest (repomap rank). Product files only, real functions only."""
    out, seen = [], set()

    def add(file, name, why):
        file = str(file).replace("\\", "/")
        if len(out) >= k or not _product(file):
            return
        sym = _resolve(root, file, str(name).rpartition(".")[2])
        if sym and (file, sym) not in seen:
            seen.add((file, sym))
            out.append({"file": file, "symbol": sym, "why": why})
    for f, n in stack:
        add(f, n, "stack")
    for f, n in diff:
        add(f, n, "diff")
    for item in reversed(list(trace)):      # the trace is in execution order: the last call is the nearest to the assert
        add(item[0], item[1], "trace")
    for f, n in ranked:
        add(f, n, "rank")
    return out


def test_functions(root, test_id: str) -> list:
    """[(file, name)] of the product functions the test file imports (``from m import f``) or calls (``m.f(...)``): the last
    resort when neither the failure, the diff, the trace nor the repomap named a function."""
    file = str(test_id).partition("::")[0]
    try:
        tree = ast.parse((Path(root) / file).read_text(encoding="utf-8-sig"))
    except (OSError, SyntaxError, ValueError, UnicodeError):
        return []
    modules, wanted = {}, []        # alias -> product file; (file, name) in order of appearance

    def product_file(dotted):
        rel = str(dotted).replace(".", "/")
        for cand in (rel + ".py", rel + "/__init__.py"):
            if (Path(root) / cand).is_file() and _product(cand):
                return cand
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            target = product_file(node.module)
            for a in node.names:
                sub = product_file(node.module + "." + a.name)
                if sub:
                    modules[a.asname or a.name] = sub
                elif target and a.name != "*":
                    wanted.append((target, a.name))
        elif isinstance(node, ast.Import):
            for a in node.names:
                target = product_file(a.name)
                if target:
                    modules[a.asname or a.name.split(".")[0]] = target
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in modules:
            wanted.append((modules[node.func.value.id], node.func.attr))
    out = []
    for item in wanted:
        if item not in out:
            out.append(item)
    return out


def diff_funcs_of(diff_text: str) -> list:
    """[(file, name)] of the functions a diff touches: the function of a hunk header and the ``def`` lines it adds or removes."""
    out, file = [], ""
    for line in str(diff_text or "").splitlines():
        if line.startswith("diff --git "):
            file = line.split(" b/")[-1].strip()
            continue
        if not file:
            continue
        found = None
        if line.startswith("@@"):
            found = re.search(r"@@.*?@@\s*(?:async\s+)?def\s+(\w+)", line)
        elif line[:1] in "+-" and not line.startswith(("+++", "---")):
            found = re.match(r"[+-]\s*(?:async\s+)?def\s+(\w+)", line)
        if found and (file, found.group(1)) not in out:
            out.append((file, found.group(1)))
    return out


def _signature(node) -> str:
    try:
        return "def %s(%s)" % (node.name, ast.unparse(node.args))
    except Exception:       # noqa: BLE001  an aid
        return "def %s(...)" % node.name


def _test_body(root, test_id: str) -> str:
    file, _, rest = str(test_id).partition("::")
    name = rest.split("::")[-1].split("[")[0]
    try:
        text = (Path(root) / file).read_text(encoding="utf-8-sig")
        found = K._symbols(ast.parse(text))
    except (OSError, SyntaxError, ValueError, UnicodeError):
        return ""
    for q, node in found.items():
        if q.rpartition(".")[2] == name and K._is_function(node):
            lines = text.splitlines()[K._node_start(node) - 1:node.end_lineno]
            return "\n".join(lines[:TEST_LINES])
    return ""


def assert_text(failure: str, cap: int = 500) -> str:
    """The lines of the failure that say what was asserted (E-lines), else its tail."""
    lines = [l for l in (failure or "").splitlines() if l.lstrip().startswith("E ")]
    text = "\n".join(lines) if lines else (failure or "")
    return text[-cap:] if len(text) > cap else text


def build_card(root, fn: dict, failure: str, test_id: str, *, extra: str = ""):
    """``(text, tokens)`` of the card of one function, or None when the function does not fit CARD_TOKENS even with the
    test and the signatures cut to the bone. Answer format: REPLACE FUNCTION + the whole new function, or CANNOT."""
    file, sym = fn["file"], fn["symbol"]
    try:
        source = (Path(root) / file).read_text(encoding="utf-8-sig")
        header, body = K.part_region(source, [sym])
        tree = ast.parse(source)
        node = K._symbols(tree)[sym]
    except (OSError, SyntaxError, ValueError, UnicodeError, KeyError):
        return None
    calls = []
    defs = {q.rpartition(".")[2]: n for q, n in K._symbols(tree).items() if K._is_function(n)}
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            target = sub.func.id if isinstance(sub.func, ast.Name) else getattr(sub.func, "attr", "")
            if target in defs and defs[target] is not node and target not in [c[0] for c in calls]:
                calls.append((target, _signature(defs[target])))
    test = _test_body(root, test_id)
    fail = assert_text(failure)
    sigs = "\n".join(s for _, s in calls[:6])
    head = ('Fix ONE function so that the red test passes. Answer EXACTLY "REPLACE FUNCTION" on the first line, then the WHOLE '
            'new text of %s in one python block (same name, every line), or "CANNOT: <reason>" if this function is not the '
            'cause.\n' % sym.rpartition(".")[2])

    def make(f, t, s):
        return (head + "RED TEST: %s\nASSERT / FAILURE:\n%s\nTEST:\n%s\nFUNCTION %s (%s):\n%s\nCALLS:\n%s\n%s"
                % (test_id, f, t, sym, file + " " + header, body, s, extra))
    for f_cap, t_cap, s_cap in ((500, 1100, 400), (300, 600, 200), (200, 300, 0)):
        text = make(fail[-f_cap:], test[:t_cap], sigs[:s_cap])
        if est_tokens(text) <= CARD_TOKENS or extra:
            return text, est_tokens(text)
    return None


# ------------------------------------------------------------------------------------------- answer -> candidate
def parse_answer(answer: str):
    """('cannot', reason) | ('code', text) | ('bad', why) for the answer of one call."""
    text = (answer or "").strip()
    if not text:
        return "bad", "empty answer"
    if re.match(r"(?is)\W*CANNOT\b", text):
        return "cannot", text[:200]
    m = re.search(r"REPLACE FUNCTION", text)
    if not m:
        return "bad", "no REPLACE FUNCTION"
    rest = text[m.end():]
    fence = re.search(r"```(?:python|py)?\s*\n(.*?)```", rest, re.S)
    code = fence.group(1) if fence else rest
    return ("code", code.strip("\n")) if code.strip() else ("bad", "no code")


def _undefined(text: str) -> set:
    """Names read somewhere in the module that nothing in it (or the builtins) defines; empty after a star import."""
    import builtins
    tree = ast.parse(text)
    defined, used = set(dir(builtins)) | {"__file__", "__name__", "__doc__"}, set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            (used if isinstance(n.ctx, ast.Load) else defined).add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(n.name)
        elif isinstance(n, ast.arg):
            defined.add(n.arg)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            if any(a.name == "*" for a in n.names):
                return set()
            defined.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            defined.add(n.name)
        elif isinstance(n, (ast.Global, ast.Nonlocal)):
            defined.update(n.names)
    return used - defined


def apply_function(source: str, symbol: str, new_code: str) -> str:
    """The file text with the named function replaced by ``new_code`` (re-indented to the old place). ValueError on a miss."""
    import textwrap
    text = source.replace("\r\n", "\n")
    node = K._symbols(ast.parse(text)).get(symbol)
    if node is None or not K._is_function(node):
        raise ValueError("missing function: " + symbol)
    lines = text.split("\n")
    start, end = K._node_start(node), node.end_lineno
    indent = re.match(r"\s*", lines[start - 1]).group(0)
    body = textwrap.indent(textwrap.dedent(new_code.strip("\n")), indent)
    return "\n".join(lines[:start - 1] + body.split("\n") + lines[end:])


def check_candidate(root, fn: dict, answer: str):
    """The instant checker. ``(cand, why)``: cand = {'file','symbol','code','text','fp'} when valid, else None and the reason."""
    kind, payload = parse_answer(answer)
    if kind != "code":
        return None, kind + ": " + payload[:80]
    file, sym = fn["file"], fn["symbol"]
    try:
        old = (Path(root) / file).read_text(encoding="utf-8-sig").replace("\r\n", "\n")
        pairs = K.split_part_code(payload, [sym])
        new = apply_function(old, sym, pairs[0][1])
        compile(new, file, "exec")
    except (OSError, ValueError, SyntaxError, UnicodeError) as exc:
        return None, "invalid: " + str(exc)[:100]
    if new == old or K.region_sha(new, [sym]) == K.region_sha(old, [sym]):
        return None, "no effect: the function is unchanged"
    why = ""
    fresh = _undefined(new) - _undefined(old)       # undefined-name check without ruff: the names the edit brought and nothing defines
    if fresh:
        why = "undefined names: " + ", ".join(sorted(fresh)[:6])
    else:
        try:
            from tools import agent_factory_runner as R
            why = R.part_undefined(file, old, new)
        except ImportError:
            why = ""
    if why:
        return None, "undefined: " + str(why)[:100]
    return {"file": file, "symbol": sym, "code": pairs[0][1], "text": new, "fp": ENS.fingerprint(new, file)}, ""


def diff_size(root, cand: dict) -> int:
    try:
        old = (Path(root) / cand["file"]).read_text(encoding="utf-8-sig").replace("\r\n", "\n").splitlines()
    except OSError:
        return 10 ** 9
    return sum(1 for l in difflib.unified_diff(old, cand["text"].splitlines(), lineterm="", n=0)
               if l[:1] in "+-" and l[:3] not in ("+++", "---"))


# ------------------------------------------------------------------------------------------------------ 2. pump
OUTCOMES = ("cannot", "bad", "invalid", "no_effect", "undefined", "dup")


def outcome_of(why: str) -> str:
    """The outcome name of a check_candidate reason ('bad: ...' -> 'bad', 'no effect: ...' -> 'no_effect')."""
    return re.sub(r"\W+", "_", str(why).split(":")[0].strip().lower()).strip("_")


class Stats:
    """stats.json['hypo']: counters of the search (thread safe) and the Gemma request times of the last 10 minutes."""
    NAMES = ("rows", "hypotheses", "answers", "valid", "batches", "candidates", "green_rows", "calls", "tokens")

    def __init__(self):
        self.lock = threading.Lock()
        self.c = collections.Counter()
        self.times = collections.deque()
        self.refused = collections.Counter()        # status of a refused request -> n
        self.outcomes = collections.Counter()       # cannot / bad / invalid / no_effect / undefined / dup -> n
        self.chan = {}                              # channel id -> {'sent': n, 'ok': n}

    def add(self, name, n=1):
        with self.lock:
            self.c[name] += n

    def request(self, now, tokens, chan=None):
        with self.lock:
            self.c["calls"] += 1
            self.c["tokens"] += int(tokens)
            self.times.append(now)
            if chan is not None:
                self.chan.setdefault(str(chan), dict(sent=0, ok=0))["sent"] += 1

    def refuse(self, status):
        with self.lock:
            self.refused[str(status)] += 1

    def outcome(self, name):
        with self.lock:
            self.outcomes[str(name)] += 1

    def answered(self, chan):
        with self.lock:
            self.chan.setdefault(str(chan), dict(sent=0, ok=0))["ok"] += 1

    def snapshot(self, now) -> dict:
        with self.lock:
            while self.times and now - self.times[0] > 600:
                self.times.popleft()
            c = self.c
            out = {n: int(c[n]) for n in self.NAMES if n != "candidates"}
            out["candidates_per_batch"] = round(c["candidates"] / c["batches"], 2) if c["batches"] else 0.0
            out["calls_per_green"] = round(c["calls"] / c["green_rows"], 1) if c["green_rows"] else None
            out["gemma_rpm"] = round(len(self.times) / 10.0, 2)
            out["tokens_per_call"] = round(c["tokens"] / c["calls"], 1) if c["calls"] else 0
            out["refused"] = dict(self.refused)
            out["outcomes"] = {n: int(self.outcomes.get(n, 0)) for n in OUTCOMES}
            out["channels"] = {k: dict(v) for k, v in self.chan.items()}
            return out


STATS = Stats()      # the process-wide counters of the loop (stats.json['hypo'])


class Minute:
    """The input tokens booked per channel in the last 60 s. A refused request (503) is booked too and NEVER returned."""

    def __init__(self, limit=TPM, clock=time.monotonic, limits=None, rpms=None):
        self.limit, self.clock = limit, clock
        self.limits = dict(limits or {})        # channel -> its tpm (channels.json); absent: ``limit``
        self.rpms = dict(rpms or {})            # channel -> its rpm (channels.json); absent: no request limit
        self.rows = collections.defaultdict(collections.deque)
        self.lock = threading.Lock()

    def used(self, chan) -> int:
        now = self.clock()
        q = self.rows[chan]
        while q and now - q[0][0] >= 60:
            q.popleft()
        return sum(t for _, t in q)

    def book(self, chan, tokens) -> bool:
        with self.lock:
            if self.used(chan) + tokens > self.limits.get(chan, self.limit):
                return False
            if self.rpms.get(chan) and len(self.rows[chan]) >= self.rpms[chan]:
                return False
            self.rows[chan].append((self.clock(), tokens))
            return True

    def refund(self, chan, tokens) -> None:
        """The booking of a request that never went out (no channel answered): the tokens come back."""
        with self.lock:
            q = self.rows[chan]
            for i in range(len(q) - 1, -1, -1):
                if q[i][1] == tokens:
                    del q[i]
                    return

    def charge(self, chan, tokens) -> None:
        """A request that already goes (the slicer's live one) takes its tokens first, whatever the minute holds: the pump gets the rest."""
        with self.lock:
            self.used(chan)
            self.rows[chan].append((self.clock(), int(tokens)))


class Item:
    __slots__ = ("prio", "key", "text", "tokens", "temp", "tag", "avoid", "avoid_until", "fails", "group")

    def __init__(self, prio, key, text, tokens, temp, tag):
        self.prio, self.key, self.text, self.tokens, self.temp, self.tag = prio, key, text, tokens, temp, tag
        self.avoid, self.avoid_until, self.fails = "", 0.0, 0
        self.group = None


class Group:
    """The items of one search: their own answer callback and the count of items still open."""

    def __init__(self, on_answer):
        self.on_answer, self.pending, self.cancelled = on_answer, 0, False


def row_class(row: str) -> int:
    """Queue order of rows: ECHO rows first (0), then rel-<sha> (1), then the base debt (2)."""
    r = str(row)
    if r.startswith("rel-base-"):       # agent_factory.is_base_debt: the old baseline debt
        return 2
    return 1 if r.startswith("rel-") else 0


class Pump:
    """Background workers (threads of the loop, one per channel) that keep asking while hypotheses wait. ``ask(chan, text,
    temp)`` -> ``(status, answer, tokens)``; status 'ok' | 'http_503' | 'http_429' | 'no_channel' | other. A live request of the
    slicer takes its input tokens from the SAME minute first (``Minute.charge``), the pump takes the rest: up to PER_CHANNEL
    requests of the pump at once per channel, only the minute (tpm, rpm of the channel) limits them. A refusal sends the same
    item to ANOTHER channel at once."""

    def __init__(self, ask, on_answer, *, channels=DEFAULT_CHANNELS, clock=time.monotonic, sleep=time.sleep,
                 minute=None, stats=None):
        self.ask, self.on_answer, self.channels = ask, on_answer, tuple(channels)
        self.clock, self.sleep = clock, sleep
        self.minute = minute or Minute(clock=clock)
        self.stats = stats or Stats()
        self.q: list = []
        self.inflight = 0
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.refused = collections.Counter()
        self.threads = {}           # channel -> its live worker (one pump serves every search of the loop at once)
        self.until = 0.0
        self.shut = {}              # channel -> the time before which it books and asks nothing (it answered 'no_channel')

    def submit(self, items, on_answer=None) -> Group:
        """Queue the items of one search (its own ``on_answer``; default the pump's). One queue for all searches: the lowest
        ``prio`` goes first whichever search it belongs to."""
        grp = Group(on_answer or self.on_answer)
        with self.lock:
            for item in items:
                item.group = grp
                grp.pending += 1
            self.q.extend(items)
        return grp

    def _done(self, item) -> None:
        with self.lock:
            self.inflight -= 1
            if item.group is not None:
                item.group.pending -= 1

    def _take(self, chan):
        now = self.clock()
        with self.lock:
            ready = [i for i in self.q if not (i.avoid == chan and now < i.avoid_until and len(self.channels) > 1)]
            if not ready:
                return None
            item = min(ready, key=lambda i: i.prio)
            self.q.remove(item)
            self.inflight += 1
            return item

    def _back(self, item):
        with self.lock:
            self.q.append(item)
            self.inflight -= 1

    def _worker(self, chan):
        try:
            self._work(chan)
        finally:
            with self.lock:
                self._forget(chan)

    def _forget(self, chan):
        """Drop the current thread from the channel's list (under self.lock)."""
        mine = [t for t in self.threads.get(chan, ()) if t is not threading.current_thread()]
        if mine:
            self.threads[chan] = mine
        else:
            self.threads.pop(chan, None)

    def _call(self, chan, item):
        """One ask; an exception of the model call is a refusal 'other', never the end of the channel's thread."""
        try:
            got = self.ask(chan, item.text, item.temp)
            wait = float(got[3]) if len(got) > 3 and got[3] else 0.0       # the 4th: the wait a closed channel names
            return got[0], got[1], got[2], wait
        except Exception:       # noqa: BLE001
            return "other", "", 0, 0.0

    def _work(self, chan):
        while not self.stop.is_set() and self.clock() < self.until:
            with self.lock:
                if not self.q and not self.inflight:
                    self._forget(chan)              # decided under the lock: a submit after this starts a new thread
                    return
            item = self._take(chan)
            if item is None:
                self.sleep(0.02)
                continue
            if item.group is not None and item.group.cancelled:
                self._done(item)
                continue
            if self.clock() < self.shut.get(chan, 0.0):     # the channel just said 'no channel': no booking, no ask until it may open
                self._back(item)
                self.sleep(0.05)
                continue
            if not self.minute.book(chan, item.tokens):
                self._back(item)
                self.sleep(0.2)
                continue
            status, answer, _tokens, wait = self._call(chan, item)
            if status == "no_channel":
                # no request went out: the booking comes back, no call, no fail; the worker waits what the channel names;
                # the channel's other workers book nothing while it is shut (the window stays free for real sends)
                self.minute.refund(chan, item.tokens)
                if wait > 0:
                    self.shut[chan] = self.clock() + min(SHUT_MAX_S, wait)
                self.refused["no_channel"] += 1
                self.stats.refuse("no_channel")
                self._back(item)
                self.sleep(min(WAIT_MAX_S, wait) if wait > 0 else 0.2)
                continue
            self.stats.request(self.clock(), item.tokens, chan)
            if status == "ok":
                self.stats.add("answers")
                self.stats.answered(chan)
                try:
                    if item.group is None or not item.group.cancelled:
                        (item.group.on_answer if item.group is not None else self.on_answer)(item, answer)
                except Exception:       # noqa: BLE001  the check of one answer failed: that hypothesis is refused ('other'), the thread goes on
                    self.refused["other"] += 1
                finally:
                    self._done(item)
                continue
            self.refused[status] += 1             # the tokens of the refusal stay booked
            self.stats.refuse(status)
            item.fails += 1
            item.avoid, item.avoid_until = chan, self.clock() + RETRY_REFUSED_S
            if item.fails >= FAILS_MAX:
                self._done(item)
            else:
                self._back(item)
            if len(self.channels) < 2:      # with another channel the item goes there at once, no pause
                self.sleep(0.05)

    def _spawn(self):
        with self.lock:
            for chan in self.channels:
                mine = self.threads.setdefault(chan, [])
                while len(mine) < PER_CHANNEL:
                    t = threading.Thread(target=self._worker, args=(chan,), daemon=True)
                    mine.append(t)
                    t.start()

    def run(self, timeout_s=600.0, group=None) -> bool:
        """Work until the queue (``group``: this search's items) is empty or the time is up. True when everything was answered.
        On a time-out the rest of the group is dropped from the queue; the other searches go on."""
        deadline = self.clock() + timeout_s
        self.until = max(self.until, deadline)
        while True:
            self._spawn()               # a worker that has just gone idle or timed out is replaced
            with self.lock:
                done = (group.pending <= 0) if group is not None else (not self.q and not self.inflight)
            if done:
                return True
            if self.clock() >= deadline or self.stop.is_set():
                break
            self.sleep(0.01)
        if group is not None:
            with self.lock:
                group.cancelled = True
                mine = [i for i in self.q if i.group is group]
                self.q = [i for i in self.q if i.group is not group]
                group.pending -= len(mine)
        return False


# ----------------------------------------------------------------------------------------- 3-5. batch and search
def batch_files(cands) -> dict:
    """The candidates file of the cloud run: n -> {file: new text}."""
    return {str(c["n"]): {c["file"]: c["text"]} for c in cands}


def chunks(items, size=BATCH_MAX):
    for i in range(0, len(items), size):
        yield items[i:i + size]


class Ctx:
    """What the search needs from the loop; every field may be replaced by a fake."""

    def __init__(self, **kw):
        self.root = None
        self.ask = None             # (chan, text, temp) -> (status, answer, tokens)
        self.cloud = None           # (root, ids, {n: {file: text}}) -> {n: {passed, failed, text}}; raises CloudFail
        self.clock, self.sleep = time.monotonic, time.sleep
        self.failure_text = lambda ids: ""      # the failure of the red test on the base
        self.failure_of = lambda test_id: ""    # W-part 4: the kept failure text of ONE red id (the groups' signatures)
        self.skip_groups = ()                   # W-part 5: signatures of the groups searched less than ROW_COOLDOWN_S ago
        self.trace = lambda ids: ()             # ((file, name, line), ...) the functions the test ran
        self.diff_funcs = lambda ids: []        # functions of the guilty commit's diff
        self.ranked = lambda ids: []            # repomap order of the rest
        self.stats = STATS
        self.sample = lambda why, answer: None      # the first bad / invalid answer of each kind (the loop redacts and files it)
        self.minute = None
        self.pump = None            # the loop's shared Pump (None: the search makes its own)
        self.event = lambda name, **f: None
        self.timeout_s = 600.0
        self.__dict__.update(kw)


def pick_red(guard=None, rel=None, base=None) -> list:
    """The ready red test ids of a row: the guard's, else rel-<sha>'s, else the base's (in this priority)."""
    for ids in (guard, rel, base):
        if ids:
            return [str(i) for i in ids]
    return []


def cooled(table: dict, base_sha: str, test: str, now: float) -> bool:
    """True when this base+test was searched less than ROW_COOLDOWN_S ago (no new search)."""
    t = (table or {}).get("%s|%s" % (base_sha, test))
    return isinstance(t, (int, float)) and 0 <= now - t < ROW_COOLDOWN_S


def mark_searched(table: dict, base_sha: str, test: str, now: float) -> None:
    table["%s|%s" % (base_sha, test)] = now
    for k in [k for k, t in table.items() if not isinstance(t, (int, float)) or now - t > 2 * ROW_COOLDOWN_S]:
        table.pop(k, None)


def _run_pump(env, row, items, collect):
    pump = getattr(env, "pump", None)       # the loop's ONE pump: every search of the loop queues into it (ECHO < rel < base)
    if pump is None:
        pump = Pump(env.ask, collect, clock=env.clock, sleep=env.sleep, minute=env.minute, stats=env.stats,
                    channels=getattr(env, "channels", None) or DEFAULT_CHANNELS)
    group = pump.submit(items, collect)
    return pump.run(env.timeout_s, group)


def _note_outcome(env, why, answer):
    """The count of a refused answer by kind; a bad / invalid one is offered as a sample (the loop keeps the first of each kind)."""
    name = outcome_of(why)
    env.stats.outcome(name)
    if name in ("bad", "invalid"):
        try:
            env.sample(str(why), answer)
        except Exception:       # noqa: BLE001  an aid
            pass


CONTROL = "ctl"         # W-part 3: the zero candidate of every batch = the tree of the base, unchanged
FILE_RUN = "@"          # an id line '@<file>': the cloud runs the whole file (its green tests are the 'no new red' proof)
SIG_CAP = 100


def failure_sig(text: str):
    """W-part 4: the signature of a failure = exception type | top product frame (file::function) | the assert text without
    numbers. None when there is no failure text."""
    text = str(text or "")
    if not text.strip():
        return None
    elines = [l.strip()[1:].strip() for l in text.splitlines() if l.lstrip().startswith("E ")]
    head = elines[0] if elines else text.strip().splitlines()[-1]
    kind = re.match(r"([A-Za-z_][\w.]*(?:Error|Exception|Exit|Warning))\b", head)
    kind = kind.group(1) if kind else ("AssertionError" if head.startswith("assert") else "")
    frame = next(("%s::%s" % f for f in stack_from_failure(text) if _product(f[0])), "")
    said = re.sub(r"\s+", " ", re.sub(r"0x[0-9a-fA-F]+|\d+(?:\.\d+)?", "#", " ".join(elines) or head)).strip()
    return "%s|%s|%s" % (kind, frame, said[:SIG_CAP])


def group_ids(ids, failure_of) -> list:
    """W-part 4: ``[(signature, [ids])]``, the biggest group first (a tie: the one met first). An id with no failure text takes the
    group of the ids with no text (its signature is its first id)."""
    order, by_sig, textless = [], {}, []
    for i in ids:
        try:
            sig = failure_sig(failure_of(i))
        except Exception:       # noqa: BLE001  an aid
            sig = None
        if sig is None:
            textless.append(i)
            continue
        if sig not in by_sig:
            order.append(sig)
            by_sig[sig] = []
        by_sig[sig].append(i)
    groups = [(s, by_sig[s]) for s in order]
    if textless:
        groups.append((textless[0], textless))
    return sorted(groups, key=lambda g: -len(g[1]))


def judge(res, ctl_pass, ids):
    """W-part 3/4: ``(greens, new_red)`` of one verdict against the control: the ids of the group that passed and did not pass at
    the control; the ids that passed at the control and failed with the candidate."""
    if not isinstance(res, dict):
        return [], []
    passed, failed = set(res.get("passed") or ()), set(res.get("failed") or ())
    return [i for i in ids if i in passed and i not in ctl_pass], sorted(i for i in ctl_pass if i not in passed)


def _control_files(root, cands) -> dict:
    """The zero candidate: a file of the first candidate rewritten with its OWN text (bytes of the base), so the tree stays
    unchanged; {} when the file does not read."""
    try:
        rel = cands[0]["file"]
        return {rel: (Path(root) / rel).read_bytes().decode("utf-8")}
    except (OSError, ValueError, KeyError, IndexError):
        return {}


def _cloud_ids(ids) -> list:
    return list(ids) + [FILE_RUN + f for f in sorted({str(i).split("::", 1)[0] for i in ids})]


def _batch(env, ids, cands):
    """One cloud verdict per candidate and the control (key CONTROL); a failed cloud is repeated (no penalty). Raises CloudFail
    after CLOUD_TRIES."""
    last = None
    for attempt in range(CLOUD_TRIES):
        try:
            files = batch_files(cands)
            files[CONTROL] = _control_files(env.root, cands)
            got = env.cloud(env.root, _cloud_ids(ids), files)
            if isinstance(got, dict) and not isinstance(got.get(CONTROL), dict):
                last = CloudFail("no control verdict")      # W-part fix3: without the control nothing may be credited
            elif isinstance(got, dict):
                env.stats.add("batches")
                env.stats.add("candidates", len(cands))
                return got
            last = CloudFail("unreadable verdict")
        except CloudFail as exc:
            last = exc
        env.sleep(min(30.0, 5.0 * (attempt + 1)))
    raise last or CloudFail("no verdict")


def _is_green(res, ids) -> bool:
    return isinstance(res, dict) and not res.get("failed") and set(ids) <= set(res.get("passed") or ())


def _ctl_pass(verdicts) -> set:
    return set((verdicts.get(CONTROL) or {}).get("passed") or ()) if isinstance(verdicts.get(CONTROL), dict) else set()


def _score(cands, verdicts, ids, row_ids) -> list:
    """The candidates that make >= 1 id of the group green against the control with no id of the file that was green at the
    control going red; each gets ``greens`` and ``left`` (the row's ids still red). Biggest gain first."""
    ctl = _ctl_pass(verdicts)
    good = []
    for c in cands:
        greens, new_red = judge(verdicts.get(str(c["n"])), ctl, ids)
        c["new_red"] = new_red
        if greens and not new_red:
            c["greens"] = greens
            c["left"] = [i for i in row_ids if i not in greens]
            good.append(c)
    return good


def search(row, ids, env, base_failure: str = ""):
    """The whole search of one row. Returns {'green': [cand, ...] (most ids made green first, then the smaller diff), 'tried': [...],
    'evidence': [...], 'status': 'green'|'red'|'none'|'cloud'|'already_green', 'group': signature of the group searched, 'ids': the
    ids of the group}. A row with many red ids is searched by ONE group of one failure signature at a time (the biggest not in
    ``env.skip_groups`` first). Never raises."""
    env.stats.add("rows")
    tried, cands, seen_fp, answers = [], [], set(), {}
    lock = threading.Lock()
    if not ids:
        return dict(green=[], tried=[], evidence=[], status="none", why="no ids")
    row_ids = list(ids)
    failure_of = getattr(env, "failure_of", None) or (lambda i: "")
    groups = group_ids(row_ids, failure_of)
    skip = set(getattr(env, "skip_groups", ()) or ())
    sig, ids = next((g for g in groups if g[0] not in skip), groups[0])
    failure = base_failure or failure_of(ids[0]) or env.failure_text(ids)
    funcs = rank_functions(env.root, stack=stack_from_failure(failure), diff=env.diff_funcs(ids), trace=env.trace(ids),
                           ranked=env.ranked(ids))
    if not funcs:       # no trace and no rank: the product functions the test itself imports or calls
        funcs = rank_functions(env.root, ranked=test_functions(env.root, ids[0]))
    if not funcs:       # the order of the checks: no failure first, then no functions
        return dict(green=[], tried=[], evidence=[], status="none", why="no failure" if not failure else "no functions",
                    group=sig, ids=ids)
    cls = row_class(row)
    items, by_key = [], {}
    for i, fn in enumerate(funcs):
        card = build_card(env.root, fn, failure, ids[0])
        if card is None:
            tried.append(dict(fn, outcome="oversized"))
            continue
        by_key[(fn["file"], fn["symbol"])] = dict(fn, card=card[0])
        env.stats.add("hypotheses")
        for t, temp in enumerate(TEMPS):
            items.append(Item((cls, i, t), (fn["file"], fn["symbol"]), card[0], card[1], temp, "first"))

    def collect(item, answer):
        fn = by_key[item.key]
        cand, why = check_candidate(env.root, fn, answer)
        with lock:
            if cand is None:
                tried.append(dict(fn, outcome=why))
                _note_outcome(env, why, answer)
                return
            env.stats.add("valid")
            if cand["fp"] in seen_fp:
                env.stats.outcome("dup")
                return
            seen_fp.add(cand["fp"])
            cand.update(n=len(cands), temp=item.temp, answer=answer)
            cands.append(cand)
            answers[cand["n"]] = fn
    finished = _run_pump(env, row, items, collect)
    more = dict(group=sig, ids=ids)
    if not cands:
        if not finished:
            return dict(green=[], tried=tried, evidence=[], status="cloud", why="pump timeout", **more)
        return dict(green=[], tried=tried, evidence=_evidence(tried, {}), status="red", **more)
    try:
        verdicts = {}
        for part in chunks(cands):
            verdicts.update(_batch(env, ids, part))
        ctl = _ctl_pass(verdicts)
        if ctl and set(ids) <= ctl:     # W-part 3: the unchanged tree already passes every id: nothing to fix, nothing to credit
            return dict(green=[], tried=tried, evidence=[], status="already_green", why="control is green", **more)
        green = _score(cands, verdicts, ids, row_ids)
        if not green:
            green = _repair(env, row, ids, cands, verdicts, answers, failure, by_key, tried, seen_fp, lock, row_ids)
    except CloudFail as exc:
        return dict(green=[], tried=tried, evidence=[], status="cloud", why=str(exc)[:120], **more)
    if green:
        green.sort(key=lambda c: (-len(c["greens"]), diff_size(env.root, c), c["n"]))
        env.stats.add("green_rows")
        return dict(green=green, tried=tried, evidence=[], status="green", **more)
    for c in cands:
        v = verdicts.get(str(c["n"])) or {}
        why = ("new red: " + ", ".join(c["new_red"][:2]) + " ") if c.get("new_red") else ""
        tried.append(dict(file=c["file"], symbol=c["symbol"], outcome="red: " + why + str(v.get("text") or "")[:120]))
    return dict(green=[], tried=tried, evidence=_evidence(tried, verdicts), status="red", **more)


def _repair(env, row, ids, cands, verdicts, answers, failure, by_key, tried, seen_fp, lock, row_ids=None):
    """One repair circle: the 3 candidates whose failure text changed against the base's get it and 2 more answers each."""
    base = re.sub(r"\s+", " ", assert_text(failure)).strip()
    changed = [c for c in cands if (verdicts.get(str(c["n"])) or {}).get("text")
               and re.sub(r"\s+", " ", assert_text(verdicts[str(c["n"])]["text"])).strip() != base]
    best = changed[:REPAIR_TOP]
    if not best:
        return []
    new, items = [], []
    cls = row_class(row)
    for c in best:
        fn = by_key[(c["file"], c["symbol"])]
        text = (fn["card"] + "\nYOUR PREVIOUS ANSWER (still red):\n" + c["code"] + "\nITS NEW FAILURE:\n"
                + assert_text(verdicts[str(c["n"])]["text"]) + "\nGive a better whole function.\n")
        for t, temp in enumerate(REPAIR_TEMPS):
            items.append(Item((cls, c["n"], t), (c["file"], c["symbol"]), text, est_tokens(text), temp, "repair"))

    def collect(item, answer):
        fn = by_key[item.key]
        cand, why = check_candidate(env.root, fn, answer)
        with lock:
            if cand is None:
                _note_outcome(env, why, answer)
                return
            if cand["fp"] in seen_fp:
                env.stats.outcome("dup")
                return
            seen_fp.add(cand["fp"])
            env.stats.add("valid")
            cand.update(n=len(cands) + len(new), temp=item.temp, answer=answer)
            new.append(cand)
    _run_pump(env, row, items, collect)
    if not new:
        return []
    got = _batch(env, ids, new)
    verdicts.update(got)
    cands.extend(new)
    return _score(new, verdicts, ids, row_ids or ids)


def _evidence(tried, verdicts) -> list:
    """Lines for the slicer: which functions were tried and how each ended."""
    out, seen = [], set()
    for t in tried:
        key = (t.get("file"), t.get("symbol"), str(t.get("outcome"))[:60])
        if key in seen:
            continue
        seen.add(key)
        out.append("TRIED %s::%s -> %s" % (t.get("file"), t.get("symbol"), str(t.get("outcome"))[:140]))
    return out[:12]


def to_contract(row, ids, cand, why="a hypothesis of the batch verifier made the red test green", group=None, rep=None):
    """The contract of a green candidate: a fix with a part that carries the code (applied without a model, W-dry) and
    test.use = the red id; the other red ids go to ``also``."""
    greens = list(cand.get("greens") or ())
    if greens:      # W-part 4: only the ids the candidate made green; the rest of the row's red ids go to ``more``
        test = {"use": greens[0]}
        if len(greens) > 1:
            test["also"] = greens[1:]
    else:
        test = {"use": ids[0]}
        if len(ids) > 1:
            test["also"] = list(ids[1:])
    if group:       # the card shows the representative of the group that was searched
        why = "%s [группа: %s; представитель: %s]" % (why, str(group)[:120], rep or ids[0])
    out = dict(row=row, decision="fix", why=why, test=test,
               parts=[dict(file=cand["file"], symbols=[cand["symbol"]], code=cand["code"],
                           instruction="Replace %s with the verified text from code: the cloud batch made the red test green with it."
                           % cand["symbol"],
                           keep="the signature")])
    left = [i for i in ids if i not in greens] if greens else []
    if left:
        out["more"] = "остались красные: " + ", ".join(left[:6]) + (" (+%d)" % (len(left) - 6) if len(left) > 6 else "")
    return out


# --------------------------------------------------------------------------------------- cloud (real batch run)
def cloud_batch(root, ids, files, *, runner=None, clock=time.monotonic, sleep=time.sleep, tid="hypo"):
    """The real batch: the tree of the base + hypo/cands.json go as ONE cloud run (echo_cloud.publish + wait_junit, one
    shared place of factory_cloud_gate); the run applies every candidate, runs the red ids and returns the files.
    ``{n: {passed, failed, text}}``; CloudFail on any cloud trouble (no dead mark, no penalty)."""
    from tools import echo_cloud as ec
    from tools import factory_cloud_gate as G
    from tools import factory_mirror as fm
    if not G.batch_allowed():
        raise CloudFail("the product route is off")
    if G.dead():
        raise CloudFail("the cloud is marked dead")
    root = Path(root)
    for n, mapping in files.items():       # the mirror scanner first: a candidate with private text never leaves
        for rel, text in mapping.items():
            if ec.scan_bytes(rel, text.encode("utf-8")):
                raise CloudFail("a candidate carries private text")
    work = Path(__import__("tempfile").mkdtemp(prefix="cloud_hypo_"))
    slot = branch = None
    try:
        built = ec.build(root, work / "tree")
        if built["hits"]:
            raise CloudFail("the base carries private text")
        slot = G._take_run_slot(G.SLOT_QUEUE_S, sleep=sleep, clock=clock, weight=1)
        if slot is None:
            raise CloudFail("no place in the cloud")
        label = "h%s-%d" % (__import__("re").sub(r"[^a-z0-9]", "", tid.lower())[:16] or "k", int(time.time() * 1000) % 10 ** 9)

        def renamed(name):
            nonlocal branch
            branch = name
        names = sorted({G._node(t) for t in ids})
        deadline = clock() + ec.QUEUED_MAX_S + G.WAIT_S
        run_id = ec.publish(work / "tree", ec.BRANCH_PREFIX + label, shards=1, runner=runner, clock=clock, sleep=sleep,
                            on_branch=renamed, start_s=float(ec.START_S), tests=names, scan_only=[], hypo=dict(ids=list(ids), files=files))
        G.register_run(run_id, len(slot))
        left = max(1.0, deadline - clock())
        _texts, _ = ec.wait_junit(run_id, timeout_s=left, runner=runner, clock=clock, sleep=sleep,
                                  start_s=min(float(ec.START_S), left), dest=work / "dl", shared=True)
        for path in sorted((work / "dl" / "junit").rglob("hypo-result-*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        raise CloudFail("the run left no hypo result")
    except CloudFail:
        raise
    except Exception as exc:        # noqa: BLE001  down, busy, queued, blocked, unreadable: repeated, never penalised
        raise CloudFail("%s: %s" % (type(exc).__name__, exc)) from exc
    finally:
        if branch:
            try:
                ec.delete_branch(branch, runner)
            except Exception:       # noqa: BLE001
                pass
        fm._rmtree_force(work)
        if slot is not None:
            G._free_run_slot(slot)

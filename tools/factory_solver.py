"""W-solver: ONE free model with READ / GREP / DEF / EDIT / TEST in a loop against the red tests of a row (replaces the
hypotheses search). Bench 25.11: 8 of 19 red tests green on the free Flash-Lite against 3.4 % first hits of the cards.

The model sees the test, its failure and the suspect functions; it reads and greps the snapshot of the base, edits files of the
product in an in-memory overlay and the tests run in the cloud after every edit (``ctx.cloud``: the batch of factory_hypo). The
tools are plain python over the snapshot + the overlay: no shell, tests are never edited. A reply that cannot be read is not a
failure but a hint with the format. The result carries the overlay as SEARCH/REPLACE blocks of any place of a file for the part of the contract (engine
'solver')."""
import ast
import difflib
import json
import os
import re
import time
from pathlib import Path

from tools import factory_hypo as HY

STEPS = 28                      # answered replies of one solve (a refusal of the channel is not a step)
READS_MAX = 4                   # READ / GREP / DEF commands answered in one reply
READ_LINES = 160
OBS_CAP = 7000                  # chars of one observation
CTX_CHARS = 400000              # the whole prompt of the big step; older observations are cut only above this
SMALL_CHARS = 15000             # the compact prompt for the small step (Gemma: 16k tokens a minute)
KEEP = 5                        # the newest steps kept whole in a cut history
TEST_IDS = 5                    # red ids of the group run by an intermediate TEST (the rest at the final check)
FINAL_IDS = 40
CLOUD_TRIES = 3
READ_PREFIXES = ("echo_sync/", "tests/")
EDIT_PREFIXES = ("echo_sync/", "tests/")
TRACE_CAP = 40000               # bytes of the saved full trace of one solve
FAIL_CAP = 2200
STEPS_TFIRST = 40               # test first: the steps of the test and of the fix together

SYSTEM_TFIRST = '''You work on ONE defect of a Python repository (a voice assistant) that has NO red test yet. Step 1: write ONE new test file whose ONE test_ function fails on the product as it is now, with an AssertionError of its own assert (not an import error, not a fixture error, not a skip). Step 2: fix the product in echo_sync/ until that test passes. You work in steps. Every reply: 1-3 short sentences of reasoning, then the command(s): up to 4 READ/GREP/DEF together, or ONE NEWFILE, or ONE EDIT (the tests run by themselves after it):
READ path start end            (lines, at most 160)
GREP regex :: path_prefix      (e.g. GREP def _source\\( :: echo_sync/)
DEF name                       (shows every function/class with that name, with its file and lines)
GIVEN: one sentence            (the state), WHEN: one sentence (the action), THEN: one sentence (the expected result): before NEWFILE
NEWFILE tests/test_factory_<row lowercase>_<word>.py
```python
the whole test file: exactly ONE test_ function, a real assert on a value that comes back from the product code
```
EDIT path
<<<<<<< SEARCH
exact old lines
=======
new lines
>>>>>>> REPLACE
DONE                           (only after the tests passed)
Rules: read the product code first, then write the test from the row, its acceptance and the owner's words: it must pin the behaviour the owner wants, and be red NOW. The machine runs the test on the base: a test that passes, or fails with an error instead of an assertion, is refused with the reason. Once the test is red it is frozen (never edited); then EDIT only files of echo_sync/ (at most 3), small edits, SEARCH text must match exactly once. Never skip, never special-case the test. Write only YOUR next step: never write a RESULT yourself.'''
NEW_TEST_RE = r"tests/test_factory_%s_[a-z0-9_]+\.py"
_NEWFILE = re.compile(r"^[ \t]*NEWFILE[ \t]+[\"'`]?([^\s\"'`]+)[\"'`]?[ \t]*\n(?:```[\w+-]*[ \t]*\n(.*?)\n```|<{5,} NEW[ \t]*\n(.*?)\n>{5,} END)", re.S | re.M)
_BAD_ERROR = re.compile(r"ERROR collecting|ERROR at (?:setup|teardown)|ImportError|ModuleNotFoundError|SyntaxError|NameError|"
                        r"fixture '[^']*' not found|[Ss]kipped|SKIPPED|timeout after \d+ s|INTERNALERROR")
_ASSERT_LINE = re.compile(r"^E\s+(?:assert\b|AssertionError)", re.M)

SYSTEM = '''You fix failing pytest tests in a Python repository (a voice assistant). You work in steps. Every reply: 1-3 short sentences of reasoning, then the command(s): up to 4 READ/GREP/DEF together, or ONE EDIT (the tests run by themselves after it):
READ path start end            (lines, at most 160)
GREP regex :: path_prefix      (e.g. GREP def _source\\( :: echo_sync/)
DEF name                       (shows every function/class with that name, with its file and lines)
EDIT path
<<<<<<< SEARCH
exact old lines
=======
new lines
>>>>>>> REPLACE
STALE: one phrase             (only when the assert is outdated and nothing can be fixed; name file.py::name)
DONE                           (only after the tests passed)
Rules: find the ROOT cause first by reading the test, its helper and the product code it calls. First decide: is the PRODUCT broken, or is the STAND stale (a fixture, a fake, a helper, a setting that no longer exists in tests/)? Fix the product in echo_sync/, or, when the stand is stale, fix the stand and its helpers in tests/ (at most 3 files of echo_sync/ with it). The asserts of the tests are never changed: do not change, remove or weaken any assert, never skip, never special-case the test. If the assert itself is outdated and neither the product nor the stand can be fixed, answer one line 'STALE: <which assert contradicts which code file.py::name>' (the name must exist in the tree). SEARCH text must match exactly once. Small edits. Write only YOUR next step: never write a RESULT yourself, the result comes in the next message.'''

FORMAT_HINT = ("I could not find a command in your reply. Reply with 1-3 sentences and then exactly one of: up to 4 lines "
               "READ path start end / GREP regex :: path_prefix / DEF name, or one block\nEDIT path\n<<<<<<< SEARCH\nold lines\n"
               "=======\nnew lines\n>>>>>>> REPLACE")


class NoChannel(RuntimeError):
    """The ask found no channel within its waits (a closed road, not a step of the model)."""


class Cancelled(Exception):
    """fac-choke: the loop dropped this solve (stale): it ends at once, it never walks a tree that is gone."""


class Result:
    def __init__(self):
        self.green = False
        self.status = "red"             # green | red | cloud | no_channel | already_green | stale
        self.overlay = {}               # file -> new text (LF)
        self.greens = []                # red ids that pass with the overlay
        self.steps = 0
        self.calls = 0                  # asks of the model
        self.tests = 0                  # cloud batches
        self.trace = []                 # [(reply tail, observation head)]
        self.last_fail = ""             # the newest failure text of a TEST
        self.why = ""
        self.model = ""
        self.stale = None               # {"phrase", "ref"} of a proven STALE answer
        self.log = []                   # the full trace: [{"step", "reply", "result"}]
        self.row = ""
        self.tfirst = False             # test first: the row had no red test, the model writes it (res.test) before the fix
        self.test = None                # {"path", "id", "code", "given", "when", "then", "because", "text"} of an accepted red test

    def evidence(self):
        """Lines for the slicer: what the solver edited last and how the test answered."""
        out = []
        if self.test:
            out.append("SOLVER wrote the red test %s (red now because: %s)" % (self.test["id"], self.test["because"]))
        if self.overlay:
            out.append("SOLVER edited %s; the test still failed:" % ", ".join(sorted(self.overlay)))
        if self.last_fail:
            out.append(self.last_fail[-900:])
        if not out and self.why:
            out.append("SOLVER stopped: " + self.why)
        return out


class Ctx:
    """What the solver needs; every field may be replaced by a fake."""

    def __init__(self, **kw):
        self.root = None
        self.ask = None             # (text, small=None) -> answer text; raises NoChannel; sets info['model']
        self.cloud = None           # (root, ids, {n: {file: text}}) -> {n: {passed, failed, text}}; raises HY.CloudFail
        self.sleep = time.sleep
        self.ctx_chars = CTX_CHARS
        self.small_chars = SMALL_CHARS
        self.info = {}
        self.event = lambda name, **f: None
        self.cancel = None          # fac-choke: a threading.Event set by the loop when it drops the solve
        self.__dict__.update(kw)


# ------------------------------------------------------------------------------------------------------ the tools
class Tree:
    """The snapshot of the base + the overlay of the edits, read as one tree."""

    def __init__(self, root, overlay=None):
        self.root = Path(root)
        self.overlay = overlay if overlay is not None else {}
        self._base = {}
        self._files = None
        self.frozen = {}                # test first: the accepted red test (never edited, run with every candidate)
        self.edit_prefixes = EDIT_PREFIXES
        self.cancel = None              # fac-choke: the Event of the solve; a walk over the tree stops when it is set

    def check(self):
        """fac-choke: Cancelled when the solve was dropped; ValueError when the snapshot of the base is gone (a walk over
        tree.files() would otherwise fail on every file)."""
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled("solve dropped")
        if not self.root.is_dir():
            raise ValueError("the snapshot of the base is gone")

    def files(self):
        if self._files is None:
            out = []
            for top in READ_PREFIXES:
                for dirpath, dirs, names in os.walk(self.root / top.rstrip("/")):
                    dirs[:] = [d for d in dirs if d != "__pycache__"]
                    for n in names:
                        if n.endswith(".py"):
                            out.append((Path(dirpath) / n).relative_to(self.root).as_posix())
            self._files = sorted(set(out) | set(self.overlay) | set(self.frozen))
        return self._files

    def base(self, path):
        if path not in self._base:
            self._base[path] = (self.root / path).read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
        return self._base[path]

    def read(self, path, hint=True):
        """The text of a file. ``hint`` = the 'did you mean' of a path the model wrote; the walks over tree.files() pass False:
        difflib over every file of the tree for every missing file is ~50 ms x 1000 files of pure CPU under the GIL (fac-choke)."""
        path = str(path).strip().strip("\"'`").replace("\\", "/")
        if path in self.overlay:
            return self.overlay[path]
        if path in self.frozen:
            return self.frozen[path]
        if ".." in path or not path.startswith(READ_PREFIXES) or not (self.root / path).is_file():
            if not hint:
                raise ValueError("no such file %s" % path)
            near = difflib.get_close_matches(path, self.files(), n=3, cutoff=0.5)
            raise ValueError("no such file %s%s" % (path, ("; did you mean " + ", ".join(near)) if near else ""))
        return self.base(path)


def _numbers(text):
    return [int(x) for x in re.findall(r"\d+", text)]


def do_read(tree, args):
    head = args.strip()
    m = re.match(r"[\"'`]?([^\s\"'`:]+)[\"'`]?(?::|\s)?(.*)$", head)
    if not m:
        return "READ needs a path"
    path, rest = m[1], m[2]
    try:
        s = tree.read(path).split("\n")
    except ValueError:          # a bare or misplaced name: the only file of the tree with it
        same = [p for p in tree.files() if p.rsplit("/", 1)[-1] == path.replace("\\", "/").rsplit("/", 1)[-1]]
        if len(same) != 1:
            raise
        s = tree.read(same[0]).split("\n")
    nums = _numbers(rest)
    i = nums[0] if nums else 1
    j = nums[1] if len(nums) > 1 else i + 120
    j = min(j, i + READ_LINES)
    i = max(1, i)
    return "\n".join("%d: %s" % (n, s[n - 1][:600]) for n in range(i, min(j, len(s)) + 1))[:OBS_CAP] or "(no lines there; the file has %d)" % len(s)


def do_grep(tree, args):
    raw, sep, pre = args.partition("::")
    raw, pre = raw.strip(), pre.strip().strip("\"'` ")
    if not sep:         # `GREP regex path`: a last word that is a path is the prefix
        parts = raw.rsplit(None, 1)
        if len(parts) == 2 and parts[1].strip("\"'`").startswith(READ_PREFIXES):
            raw, pre = parts[0].strip(), parts[1].strip("\"'`")
    raw = raw.strip("\"'`")
    pre = pre.split("*")[0]
    if not pre.startswith(READ_PREFIXES):
        pre = ""
    if not raw:
        return "GREP needs a pattern"
    try:
        rx = re.compile(raw).search
    except re.error:
        rx = lambda line: raw in line      # noqa: <id>
    lit = raw.replace("\\", "")
    words = re.findall(r"\w{4,}", raw)
    word = max(words, key=len) if words else raw
    tree.check()
    for hit, where in ((rx, pre), (lambda l: lit in l, pre), (lambda l: lit in l, ""), (lambda l: word in l, "")):
        out = []
        for p in tree.files():
            if not p.startswith(where):
                continue
            tree.check()
            try:
                body = tree.read(p, hint=False)
            except ValueError:
                continue
            for k, line in enumerate(body.split("\n"), 1):
                if hit(line):
                    out.append("%s:%d: %s" % (p, k, line.strip()[:180]))
            if len(out) > 30:
                break
        if out:
            return "\n".join(out[:30])
    return "no match"


def do_def(tree, args):
    parts = [x.strip().strip("\"'` ") for x in args.split("::")]       # `DEF name :: path`, `DEF path::name` and `DEF Class.name` are one request
    names = [x for x in parts if x and not x.startswith(READ_PREFIXES) and "/" not in x]
    name = (names[0] if names else "").split(".")[-1].split("(")[0].strip()
    name = name.split()[-1] if name else ""
    pre = next((x.split("*")[0] for x in parts if x.startswith(READ_PREFIXES)), "")
    if not name:
        return "DEF needs a name"
    out = []
    tree.check()
    for p in sorted(tree.files(), key=lambda f: not (pre and f.startswith(pre))):
        tree.check()
        try:
            s = tree.read(p, hint=False)
        except ValueError:
            continue
        if name not in s:
            continue
        try:
            t = ast.parse(s)
        except SyntaxError:
            continue
        for n in ast.walk(t):
            if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and n.name == name:
                lines = s.split("\n")[n.lineno - 1:n.end_lineno]
                out.append("%s:%d-%d\n" % (p, n.lineno, n.end_lineno) + "\n".join(x[:500] for x in lines[:60]))
    return "\n".join(out)[:OBS_CAP] or "no def or class of this name; the lines with it:\n" + do_grep(tree, name)


_BLOCK = re.compile(r"<{5,} SEARCH[ \t]*\n(.*?)\n?={5,}[ \t]*\n(.*?)\n?>{5,} REPLACE", re.S)
_HEAD = re.compile(r"^[ \t]*EDIT[ \t]+[\"'`]?([^\s\"'`]+)[\"'`]?[ \t]*$", re.M)
# a command line: where the answer starts after a reasoning block that was never closed (strip_thought)
_ACTION = re.compile(r"^[ \t]*(?:(?:EDIT|READ|GREP|DEF|NEWFILE|TEST|DONE|STALE)\b|GIVEN:|<{5,} SEARCH)", re.M)


def parse_edits(reply):
    """[(path, search, replace)] of every SEARCH/REPLACE block; a block with no EDIT header before it takes the path of the
    block before it. ValueError when a block has no path at all."""
    text = reply.replace("\r\n", "\n")
    heads = [(m.start(), m[1]) for m in _HEAD.finditer(text)]
    out, last = [], None
    for m in _BLOCK.finditer(text):
        before = [p for pos, p in heads if pos < m.start()]
        path = (before[-1] if before else last)
        if path is None:
            raise ValueError("an EDIT block needs the line 'EDIT path' before it")
        heads = [h for h in heads if h[0] >= m.start()]     # a header serves the next block only
        if before:
            last = before[-1]
        out.append((path.replace("\\", "/"), m[1], m[2]))
    return out


def _closest(text, search):
    """The lines of ``text`` that look most like the lines of ``search`` (numbered), for a SEARCH that matched nowhere."""
    lines = text.split("\n")
    want = [l.strip() for l in search.split("\n") if l.strip()]
    if not want or not lines:
        return ""
    stripped = [l.strip() for l in lines]
    cands = set()
    for w in want[:3]:
        for hit in difflib.get_close_matches(w, stripped, n=3, cutoff=0.6):
            cands.update(i for i, l in enumerate(stripped) if l == hit)
    n = max(1, len(search.split("\n")))
    best, at = 0.0, None
    for c in sorted(cands)[:12]:
        for start in range(max(0, c - n + 1), min(len(lines), c + 1)):
            window = "\n".join(lines[start:start + n])
            r = difflib.SequenceMatcher(None, search, window).ratio()
            if r > best:
                best, at = r, start
    if at is None:
        return ""
    return "\n".join("%d: %s" % (k + 1, lines[k][:200]) for k in range(at, min(len(lines), at + n + 1)))


def _apply_one(text, search, replace):
    """(new text, '') or (None, why). One match exactly; a match that differs only in trailing blanks is accepted."""
    n = text.count(search)
    if n == 1:
        return text.replace(search, replace), ""
    if n > 1:
        spots = [str(text[:m.start()].count("\n") + 1) for m in re.finditer(re.escape(search), text)][:6]
        return None, "SEARCH matches %d times (lines %s): add lines around it so that it matches once" % (n, ", ".join(spots))
    lines, want = text.split("\n"), search.split("\n")
    flat = [l.rstrip() for l in lines]
    key = [l.rstrip() for l in want]
    hits = [i for i in range(len(lines) - len(want) + 1) if flat[i:i + len(want)] == key]
    if len(hits) == 1:
        i = hits[0]
        return "\n".join(lines[:i] + replace.split("\n") + lines[i + len(want):]), ""
    near = _closest(text, search)
    return None, "SEARCH matches nowhere. The nearest lines of the file now:\n%s\nCopy the lines exactly." % (near or "(nothing similar)")


def _undefined(text):
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


def do_edit(tree, reply):
    """Apply every block of the reply or none. (observation, applied?)"""
    try:
        blocks = parse_edits(reply)
    except ValueError as exc:
        return str(exc), False
    if not blocks:
        return "EDIT needs the SEARCH/REPLACE block", False
    from tools.agent_factory_runner import _repeat_is_done
    staged, seen = {}, set()
    for path, search, replace in blocks:
        if (path, search, replace) in seen and _repeat_is_done(staged.get(path, ""), search, replace):
            continue        # the same block again (draft and answer, <id>): one normalizer with the light engine
        seen.add((path, search, replace))
        if path in tree.frozen:
            return "refused: %s is the red test, it is frozen: fix the product in echo_sync/" % path, False
        if ".." in path or not path.startswith(tree.edit_prefixes):
            return "refused: only files of %s may be edited: %s" % (" and ".join(tree.edit_prefixes), path), False
        if re.search(r"pytest\.(skip|xfail)|mark\.(skip|xfail)", replace):
            return "refused: skipping is not a fix", False
        try:
            text = staged[path] if path in staged else tree.read(path)
        except ValueError as exc:
            return str(exc), False
        new, why = _apply_one(text, search, replace)
        if new is None:
            return "%s: %s" % (path, why), False
        if new == text:
            return "%s: the edit changes nothing" % path, False
        if path.endswith(".py"):
            try:
                ast.parse(new)
                fresh = _undefined(new) - _undefined(text)
            except SyntaxError as exc:
                return "refused: %s has a syntax error after the edit: %s" % (path, exc), False
            if fresh:
                return "refused: the edit uses names that nothing defines: %s" % ", ".join(sorted(fresh)[:6]), False
        staged[path] = new
    refused = _rig_refusal(tree, staged)
    if refused:
        return refused, False
    tree.overlay.update(staged)
    return "edited " + ", ".join(sorted(staged)), True


def _rig_refusal(tree, staged):
    """A result that touches tests/** is a rig card: the AST lock of the gate (no assert / raises of a test changes, no test goes,
    no new skip), the gate's own forbidden paths and the shape of the touch list (tests/** and at most 3 files of echo_sync/)
    are checked against the base at once. '' or the refusal for the model; nothing of the edit is kept then."""
    files = sorted(set(tree.overlay) | set(staged))
    if not any(f.startswith("tests/") for f in files):
        return ""
    from tools import factory_gate as G
    cand = {f: tree.overlay.get(f, "") for f in files}
    cand.update(staged)
    tests = {f: t for f, t in cand.items() if f.startswith("tests/")}
    problems = list(G.rig_weakens(tree.root, tests)) + list(G.rig_touch_faults(files))
    for f in files:
        if f.startswith("tests/"):
            why = G.is_forbidden(f, "code", named=files, rig=True)
            if why:
                problems.append("%s: %s" % (f, why))
    if problems:
        return "refused (the edit is rolled back): " + "; ".join(problems[:4])
    return ""


# ----------------------------------------------------------------------------------------- what is shipped
SEARCH_MARK, SEP_MARK, REPLACE_MARK = "<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"


def parse_blocks(code):
    """[(search, replace)] of a code made of SEARCH/REPLACE blocks (the reading of the runner's parse_edit_blocks: the marker lines
    are whole lines, the text between them is kept as it is)."""
    lines, out, i = str(code).replace("\r\n", "\n").split("\n"), [], 0
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("<<<<<<<") and "SEARCH" in s:
            j = i + 1
            while j < len(lines) and lines[j].strip() != SEP_MARK:
                j += 1
            k = j + 1
            while k < len(lines) and lines[k].strip() != REPLACE_MARK:
                k += 1
            if k >= len(lines):
                break
            out.append(("\n".join(lines[i + 1:j]), "\n".join(lines[j + 1:k])))
            i = k + 1
            continue
        i += 1
    return out


def _hits(lines, want):
    n = len(want)
    return [i for i in range(len(lines) - n + 1) if lines[i:i + n] == want]


def apply_blocks(old, code):
    """The text after the blocks of ``code`` are applied in order to ``old`` (each SEARCH must stand exactly once, whole lines),
    or None."""
    text = str(old).replace("\r\n", "\n")
    blocks = parse_blocks(code)
    if not blocks:
        return None
    for search, replace in blocks:
        lines = text.split("\n")
        at = _hits(lines, search.split("\n"))
        if len(at) != 1:
            return None
        n = len(search.split("\n"))
        text = "\n".join(lines[:at[0]] + replace.split("\n") + lines[at[0] + n:])
    return text


def block_code(old, new):
    """(code, '') : SEARCH/REPLACE blocks that turn ``old`` into ``new`` exactly (difflib over lines, context grown until each
    SEARCH stands once in ``old``, overlapping blocks merged); ('', why) when that cannot be done. The result is verified by
    applying it (this module's reading and, when the runner imports, the runner's own parse_edit_blocks / apply_edit_blocks)."""
    old, new = str(old).replace("\r\n", "\n"), str(new).replace("\r\n", "\n")
    if old == new:
        return "", "no change"
    if old.endswith("\n") != new.endswith("\n"):
        return "", "the end of the file changed (a final newline)"
    a, b = old.rstrip("\n").split("\n"), new.rstrip("\n").split("\n")
    if old.endswith("\n") and (old.endswith("\n\n") or new.endswith("\n\n")):
        return "", "blank lines at the end of the file changed"
    n = len(a)
    groups = [[i1, i2, j1, j2] for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes() if tag != "equal"]
    for _round in range(60):
        moved = False
        for g in groups:
            while True:
                lo, hi, nlo, nhi = g
                edge_blank = (lo < hi and not a[lo].strip() and lo > 0) or (lo < hi and not a[hi - 1].strip() and hi < n)
                if hi > lo and nhi > nlo and len(_hits(a, a[lo:hi])) == 1 and not edge_blank:     # an empty REPLACE cannot be told from one blank line
                    break
                if lo == 0 and hi == n:
                    return "", "no unique place for a block"
                if lo > 0:
                    g[0] -= 1
                    g[2] -= 1
                if hi < n:
                    g[1] += 1
                    g[3] += 1
                moved = True
        groups.sort()
        merged = []
        for g in groups:
            if merged and g[0] < merged[-1][1]:
                m = merged[-1]
                m[:] = [min(m[0], g[0]), max(m[1], g[1]), min(m[2], g[2]), max(m[3], g[3])]
                moved = True
            else:
                merged.append(list(g))
        groups = merged
        if not moved:
            break
    else:
        return "", "blocks do not settle"
    blocks = ["%s\n%s\n%s\n%s\n%s" % (SEARCH_MARK, "\n".join(a[lo:hi]), SEP_MARK, "\n".join(b[nlo:nhi]), REPLACE_MARK)
              for lo, hi, nlo, nhi in groups]
    code = "\n\n".join(blocks)
    if apply_blocks(old, code) != new:
        return "", "the blocks do not give the new text back"
    try:                    # the runner's own reading and writing of the blocks (a marker-like line inside the text breaks it)
        import tempfile
        from tools import agent_factory_runner as R
        got, outside = R.parse_edit_blocks(code, ("f.py",))
        if outside or getattr(got, "problems", None) or len(got) != len(groups):
            return "", "the runner reads the blocks differently"
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "f.py").write_bytes(old.encode("utf-8"))
            done, failed = R.apply_edit_blocks(Path(tmp), got)
            if failed or Path(tmp, "f.py").read_bytes().decode("utf-8") != new:
                return "", "the runner does not give the new text back"
    except ImportError:
        pass
    return code, ""


def parts_of(root, overlay):
    """([part], '') : one part per changed file, its ``code`` = SEARCH/REPLACE blocks of any place of the file (constants, imports,
    new functions, several functions), ``symbols`` empty (the whole file may change), ``anchor`` = the first line of the first
    block; ([], why) when the blocks cannot be made."""
    parts = []
    for path in sorted(overlay):
        try:
            old = (Path(root) / path).read_bytes().decode("utf-8-sig")
        except (OSError, ValueError) as exc:
            return [], "%s does not read: %s" % (path, str(exc)[:80])
        code, why = block_code(old, overlay[path])
        if why:
            return [], "%s: %s" % (path, why)
        anchor = parse_blocks(code)[0][0].split("\n")[0]
        parts.append(dict(file=path, symbols=[], anchor=anchor, code=code,
                          instruction="Apply the SEARCH/REPLACE blocks of code to %s: the cloud run made the red test green with exactly them." % path))
    return parts, ""


def to_contract(row, ids, res, root, group=None, rep=None, why="the solver made the red test green in the cloud"):
    """The contract of a green result (engine 'solver'): a fix whose parts carry the verified code; ``test.use`` = a green id.
    None when the blocks cannot be made."""
    parts, problem = parts_of(root, res.overlay)
    if problem:
        return None
    greens = list(res.greens) or list(ids[:1])
    test = {"use": greens[0]}
    if len(greens) > 1:
        test["also"] = greens[1:]
    if group:
        why = "%s [группа: %s; представитель: %s]" % (why, str(group)[:120], rep or ids[0])
    out = dict(row=row, decision="fix", why=why, test=test, parts=parts)
    if any(str(p["file"]).startswith("tests/") for p in parts):
        out["rig"] = True       # a result that fixes the stand is a rig card (the gates: AST lock, touch list, the cloud run)
    left = [i for i in ids if i not in greens]
    if left:
        out["more"] = "остались красные: " + ", ".join(left[:6]) + (" (+%d)" % (len(left) - 6) if len(left) > 6 else "")
    return out


# ------------------------------------------------------------------------------------------------------- the loop
def _task(red_ids, failure, test_source, suspects):
    tops = "\n".join(str(s) for s in list(suspects)[:15])
    return ("Failing tests: %s\n\nThe test:\n%s\n\nFailure:\n%s\n\nProduct functions the failing test runs, most suspicious first:\n%s"
            % (", ".join(red_ids[:TEST_IDS]), str(test_source)[:3500], str(failure)[-FAIL_CAP:], tops or "(unknown)"))


def render(task, hist, limit, keep=KEEP, system=None):
    """The prompt: the system rules, the task, the whole history; above ``limit`` characters the observations and replies of the
    steps older than ``keep`` are cut (the newest stay whole), and ``keep`` shrinks until it fits (down to 2)."""
    system = system or SYSTEM

    def build(k):
        parts = [system, "", task]
        for i, (a, o) in enumerate(hist):
            old = len(hist) - i > k
            a = a[:400] if old and len(a) > 400 else a
            o = (o[:300] + " ...[cut]") if old and len(o) > 300 else o
            parts += ["", "YOU:", a, "", "RESULT:", o]
        parts += ["", "YOU:"]
        return "\n".join(parts)
    full = "\n".join([system, "", task] + [x for a, o in hist for x in ("", "YOU:", a, "", "RESULT:", o)] + ["", "YOU:"])
    if len(full) <= limit:
        return full
    k = keep
    text = build(k)
    while len(text) > limit and k > 2:
        k -= 1
        text = build(k)
    if len(text) <= limit:
        return text
    head = system + chr(10) * 2 + task + chr(10)         # the rules and the test always stay; the oldest of the history goes
    return head + text[-max(0, limit - len(head)):] if len(head) < limit - 2000 else text[:limit]


def _run_ids(ids):
    return list(ids[:TEST_IDS])


def _verdict(ctx, ids, files, res):
    """The cloud verdict {n: {passed, failed, text}}; CloudFail after CLOUD_TRIES (a failed cloud is repeated, no penalty)."""
    last = None
    for attempt in range(CLOUD_TRIES):
        res.tests += 1
        try:
            got = ctx.cloud(ctx.root, ids, files)
            if isinstance(got, dict) and isinstance(got.get("1"), dict):
                return got
            last = HY.CloudFail("unreadable verdict")
        except HY.CloudFail as exc:
            last = exc
        ctx.sleep(min(30.0, 5.0 * (attempt + 1)))
    raise last or HY.CloudFail("no verdict")


def _final(ctx, tree, ids, res):
    """The green check: every id of the group passes and nothing that passed on the base fails (the whole files run, the
    unchanged base is the control). ('' = green) or the text for the model."""
    files = sorted({str(i).split("::", 1)[0] for i in ids})
    if res.tfirst:      # the new test file is the only red one: the files of the tests next to the edited product files are the 'no new red' proof
        files += [f for f in neighbors(ctx.root, res.overlay) if f not in files]
    first = sorted(res.overlay)[0]
    got = _verdict(ctx, list(ids[:FINAL_IDS]) + [HY.FILE_RUN + f for f in files],
                   {"1": dict(tree.overlay, **tree.frozen), HY.CONTROL: {first: tree.base(first)}}, res)
    ctl = got.get(HY.CONTROL)
    if not isinstance(ctl, dict):
        raise HY.CloudFail("no control verdict")
    passed = set((got["1"].get("passed") or ()))
    greens, new_red = HY.judge(got["1"], set(ctl.get("passed") or ()), list(ids[:FINAL_IDS]))
    if set(ids[:FINAL_IDS]) <= set(ctl.get("passed") or ()):
        res.status = "already_green"
        return "already_green"
    res.greens = [i for i in ids[:FINAL_IDS] if i in passed]
    if new_red:
        return "The red tests pass, but these tests passed before your edit and fail now: %s\n%s\nFix it without breaking them." % (
            ", ".join(new_red[:6]), str(got["1"].get("text") or "")[-700:])
    if ids[0] not in passed:
        return "FAILED\n" + str(got["1"].get("text") or "")[-FAIL_CAP:]
    return ""


def solve(ctx, row, red_ids, failure, test_source, suspects, *, steps=STEPS, tfirst=None, _res=None):
    """One row: the loop of the model against the red ids. Returns a Result (never raises: a refusal of every road is a status).
    ``tfirst`` = the task text of a row WITHOUT a red test: the model writes the test first (NEWFILE), the ids appear when it is red."""
    res = _res or Result()
    ids = [str(i) for i in red_ids]
    if not ids and tfirst is None:
        res.status, res.why = "red", "no red ids"
        return res
    tree = Tree(ctx.root)
    cancel = tree.cancel = getattr(ctx, "cancel", None)
    res_overlay = tree.overlay
    res.overlay = res_overlay
    system = None
    if tfirst is not None:
        res.tfirst, system = True, SYSTEM_TFIRST
        tree.edit_prefixes = ("echo_sync/",)
        task = tfirst
    else:
        task = _task(ids, failure, test_source, suspects)
    hist = []
    try:
        for n in range(1, steps + 1):
            if cancel is not None and cancel.is_set():
                raise Cancelled("solve dropped")
            res.steps = n
            small = render(task, hist, ctx.small_chars, keep=2, system=system)
            text = render(task, hist, ctx.ctx_chars, system=system)
            try:
                reply = ctx.ask(text, small=small)
            except NoChannel as exc:
                res.status, res.why = "no_channel", str(exc)[:120]
                res.steps = n - 1
                return res
            res.calls += 1
            res.model = str(ctx.info.get("model") or res.model)
            obs = _step(ctx, tree, ids, reply, res)
            if res.green or res.status in ("already_green", "cloud", "stale"):
                res.log.append({"step": n, "reply": reply, "result": obs})
            if res.green:
                res.trace.append((reply[-300:], "PASSED"))
                res.status = "green"
                return res
            if res.status in ("already_green", "cloud", "stale"):
                return res
            if res.tfirst and not ids and n >= max(1, steps // 4):
                obs += "\nYou have read enough: write the failing test now (NEWFILE)."
            elif n == max(1, steps // 3) and not res_overlay:
                obs += "\nYou have read enough: make your best EDIT now (a red test run is cheap and tells more than reading)."
            elif n >= steps // 2 and not res_overlay:
                obs += "\nNo edit yet. Your next reply MUST be an EDIT."
            obs += "\n(%d steps left)" % (steps - n)
            hist.append((reply[-3500:], obs))
            res.trace.append((reply[-300:], obs[:300]))
            res.log.append({"step": n, "reply": reply, "result": obs})
        res.status, res.why = "red", "steps used"
    except HY.CloudFail as exc:
        res.status, res.why = "cloud", str(exc)[:120]
    except Cancelled:           # fac-choke: dropped by the loop; its result is ignored, the thread just ends
        res.status, res.why = "red", "cancelled"
    res.overlay = dict(res_overlay)
    return res


def _step(ctx, tree, ids, reply, res):
    """One reply -> the observation text. Sets res.green, res.status 'cloud' / 'already_green' when it ends the solve."""
    from tools.agent_factory_runner import strip_thought
    text = strip_thought((reply or "").replace("\r\n", "\n"), last=None, first=_ACTION)   # the one reasoning stripper
    if res.tfirst:
        nf = parse_newfile(text)
        if nf is not None:
            return _new_test(ctx, tree, ids, nf, res)
        if not ids and (_BLOCK.search(text) or re.search(r"^[ \t]*(TEST|DONE|STALE)\b", text, flags=re.M)):
            return "no red test yet: first write it with NEWFILE tests/test_factory_<row>_<word>.py and a ```python block (one test_ function that fails now)"
    if _BLOCK.search(text):
        obs, ok = do_edit(tree, text)
        if not ok:
            return obs
        return "%s; %s" % (obs, _test(ctx, tree, ids, res))
    cmds = re.findall(r"^[ \t]*(READ|GREP|DEF)\b[ \t]*(.*)$", text, flags=re.M)
    if cmds:
        out = []
        for verb, args in cmds[:READS_MAX]:
            try:
                got = {"READ": do_read, "GREP": do_grep, "DEF": do_def}[verb](tree, args)
            except ValueError as exc:
                got = str(exc)
            out.append("> %s %s\n%s" % (verb, args.strip(), got))
        return "\n\n".join(out)[:14000]
    stale = re.search(r"^[ \t]*STALE[ \t]*:[ \t]*(.+)$", text, flags=re.M)
    if stale:
        return _stale(tree, stale[1].strip(), res)
    if re.search(r"^[ \t]*DONE\b", text, flags=re.M):
        return "not done: no TEST has passed on your edits yet" if not tree.overlay else "not done: the tests have not passed yet"
    if re.search(r"^[ \t]*TEST\b", text, flags=re.M):
        return _test(ctx, tree, ids, res) if tree.overlay else "no edits yet: make an EDIT first (the tests run after it by themselves)"
    if re.search(r"^[ \t]*EDIT\b", text, flags=re.M):
        return "I found EDIT but no complete block. Use:\nEDIT path\n<<<<<<< SEARCH\nold lines\n=======\nnew lines\n>>>>>>> REPLACE"
    return FORMAT_HINT


def stale_ref(tree, phrase):
    """The 'file.py::name' of the phrase that exists in the tree (the file is there and defines or spells the name), else None."""
    for path, name in re.findall(r"([\w/.\-]+\.py)::([\w.]+)", phrase):
        try:
            text = tree.read(path if "/" in path else "echo_sync/" + path)
        except ValueError:
            try:
                text = tree.read(path)
            except ValueError:
                continue
        last = name.split(".")[-1]
        if re.search(r"(?m)^\s*(?:async\s+)?(?:def|class)\s+%s\b|^\s*%s\s*[:=]" % (re.escape(last), re.escape(last)), text):
            return "%s::%s" % (path, name)
    return None


def _stale(tree, phrase, res):
    ref = stale_ref(tree, phrase)
    if ref is None:
        return ("STALE needs the proof: name the code the assert contradicts as file.py::name, a function, class or constant that "
                "stands in the tree (use GREP/DEF to find it). Or go on with an EDIT.")
    res.stale = {"phrase": phrase[:300], "ref": ref}
    res.status, res.why = "stale", "STALE: " + phrase[:200]
    return "STALE accepted"


def parse_newfile(reply):
    """{path, code, given, when, then} of the NEWFILE block of a reply (a fenced block or NEW/END marks), else None."""
    text = (reply or "").replace("\r\n", "\n")
    m = _NEWFILE.search(text)
    if not m:
        return None
    code = m[2] if m[2] is not None else m[3]
    head = text[:m.start()]
    said = {}
    for key in ("given", "when", "then"):
        found = re.findall(r"^[ \t]*%s:[ \t]*(.+)$" % key.upper(), head, flags=re.M | re.I)
        said[key] = found[-1].strip()[:300] if found else ""
    return dict(path=m[1].replace("\\", "/"), code=code.rstrip("\n") + "\n", **said)


def test_ids_of(path, code):
    """The pytest ids of the test functions of a text: top-level test_*, methods of Test* classes."""
    ids = []
    for node in ast.parse(code).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
            ids.append("%s::%s" % (path, node.name))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            ids += ["%s::%s::%s" % (path, node.name, f.name) for f in node.body
                    if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) and f.name.startswith("test_")]
    return ids


def red_reason(verdict, test_id, path):
    """'' when the verdict shows the test red by an AssertionError of its own test_ function, else why it does not count (the text for
    the model): a pass, a test that did not run (skip, not collected), an error of collection / setup / import, an assert below the test."""
    passed, failed = set(verdict.get("passed") or ()), set(verdict.get("failed") or ())
    text = str(verdict.get("text") or "")
    if test_id in passed:
        return "the test PASSES on the product as it is: it proves nothing. Write a test that fails now, on the behaviour the row says is wrong."
    if test_id not in failed:
        return "the test did not run to a verdict (skipped or not collected): it must run and fail."
    if _BAD_ERROR.search(text):
        return ("the test fails with an ERROR (collection, import, name, fixture or timeout), not with its own assert: the failure must be an "
                "AssertionError inside the test_ function.\n" + text[-900:])
    hit = _ASSERT_LINE.search(text)
    if not hit:
        return "the test fails, but not with an assert (no 'E   assert ...' line): it must fail by an assert of its own.\n" + text[-900:]
    frames = re.findall(r"^(\S+\.py):\d+: in (\w+)", text[:hit.start()], flags=re.M)
    if frames and not (frames[-1][0].replace("\\", "/").endswith(path.rsplit("/", 1)[-1]) and frames[-1][1].startswith("test_")):
        return "the assert that fails is not inside the test_ function of your file (it is %s in %s): assert in the test itself.\n%s" % (
            frames[-1][1], frames[-1][0], text[-700:])
    return ""


def neighbors(root, overlay, limit=3):
    """The test files next to the edited product files (tests/test_<stem>*.py), at most ``limit``."""
    out = []
    for f in sorted(overlay):
        if not str(f).startswith("echo_sync/"):
            continue
        for p in sorted((Path(root) / "tests").glob("test_%s*.py" % Path(f).stem)):
            rel = p.relative_to(root).as_posix()
            if rel not in out:
                out.append(rel)
    return out[:limit]


def _new_test(ctx, tree, ids, nf, res):
    """The first step of a test-first solve: the NEWFILE of the model. Accepted only when the cloud shows it red by its own assert
    on the base; then it is frozen, ``ids`` gets its id and the solve goes on to the fix. The text for the model."""
    from tools import factory_architect as A
    if ids:
        return "the red test is already accepted and frozen (%s): fix the product with EDIT in echo_sync/." % ids[0]
    path, code = nf["path"], nf["code"]
    slug = re.sub(r"[^a-z0-9]+", "_", str(res.row).lower()).strip("_")
    if not re.fullmatch(NEW_TEST_RE % re.escape(slug), path) or (Path(ctx.root) / path).exists():
        return "refused: the path must be a NEW file named tests/test_factory_%s_<word>.py (lowercase letters, digits, _)" % slug
    if re.search(r"pytest\.(skip|xfail)|mark\.(skip|xfail)|importorskip", code):
        return "refused: skipping is not a test"
    faults = A.new_test_code_faults(code, ctx.root)
    if faults:
        return "refused: the test is unusable or weak: " + "; ".join(str(f) for f in faults[:4])
    found = test_ids_of(path, code)
    if len(found) != 1:
        return "refused: the file must hold exactly ONE test_ function (it has %d): one test, one reason to be red." % len(found)
    verdict = _verdict(ctx, found, {"1": {path: code}}, res)["1"]
    why = red_reason(verdict, found[0], path)
    if why:
        res.last_fail = why[-FAIL_CAP:]
        return "the test is refused: " + why
    text = str(verdict.get("text") or "")
    line = _ASSERT_LINE.search(text)
    because = (text[line.start():].split("\n", 1)[0] if line else "assert fails")[:300]
    tree.frozen[path] = code
    ids[:] = found
    res.test = dict(path=path, id=found[0], code=code, given=nf["given"], when=nf["when"], then=nf["then"], because=because, text=text[-FAIL_CAP:])
    res.last_fail = ""
    return "the test is RED by its own assert and now frozen (%s): %s\nNow fix the product in echo_sync/ with EDIT until it passes.\n%s" % (
        found[0], because, text[-900:])


def _test(ctx, tree, ids, res):
    """The cloud run after an edit: the red ids (the first few of the group). res.green only after the final check passes."""
    try:
        got = _verdict(ctx, _run_ids(ids), {"1": dict(tree.overlay, **tree.frozen)}, res)
    except HY.CloudFail as exc:
        res.status, res.why = "cloud", str(exc)[:120]
        return "cloud trouble"
    v = got["1"]
    passed, failed = set(v.get("passed") or ()), set(v.get("failed") or ())
    if not all(i in passed for i in _run_ids(ids)) or failed & set(_run_ids(ids)):
        res.last_fail = str(v.get("text") or "")[-FAIL_CAP:]
        return "FAILED\n" + res.last_fail
    parts, problem = parts_of(ctx.root, tree.overlay)
    if problem:
        return "PASSED, but it cannot be written as blocks: %s. Make the same fix with a smaller change." % problem
    try:
        verdict = _final(ctx, tree, ids, res)
    except HY.CloudFail as exc:
        res.status, res.why = "cloud", str(exc)[:120]
        return "cloud trouble"
    if res.status == "already_green":
        return "already_green"
    if verdict:
        res.last_fail = verdict[-FAIL_CAP:]
        return verdict
    res.green = True
    return "PASSED"


def _task_tfirst(row, text, acceptance, quotes, hints, suspects):
    tops = "\n".join(str(s) for s in list(suspects)[:15])
    return ("Row %s (it has NO red test yet; write one, then fix):\n%s\n\nAcceptance:\n%s\n\nWords of the owner:\n%s\n\nHints (code of the likely places):\n%s\n\n"
            "Product functions that may be involved, most likely first:\n%s"
            % (row, str(text)[:2500], str(acceptance)[:2500], str(quotes)[:2500], str(hints)[:5000], tops or "(unknown)"))


def solve_row(ctx, row, text, acceptance, suspects, quotes="", hints="", *, steps=STEPS_TFIRST):
    """Test first: a row without a red test. The model writes ONE new test (NEWFILE) that the cloud shows red by its own assert,
    the test is frozen, then the usual loop edits echo_sync/ until it is green and no neighbour test goes red. Result.test is set
    once the test is accepted (green or not); Result.green only when the fix passed too."""
    res = Result()
    res.row = row
    res.tfirst = True
    out = solve(ctx, row, [], "", "", suspects, steps=steps, tfirst=_task_tfirst(row, text, acceptance, quotes, hints, suspects),
                _res=res)
    return out


def to_contract_tfirst(row, res, root, why="the solver wrote a red test first and made it green in the cloud", with_fix=True):
    """The contract of a test-first result (engine 'solver'): decision fix, test.new {path, given, when, then, red_now_because, code} and,
    when the fix is green, parts = the SEARCH/REPLACE blocks (a test task, then a code task). A red but good test without a fix:
    ``test_only`` (parts empty: the test task only). None when there is no accepted test."""
    t = res.test
    if not t:
        return None
    new = dict(path=t["path"], given=t["given"] or "the state the backlog row describes", when=t["when"] or "the behaviour of the row is exercised",
               then=t["then"] or "the result the row's acceptance asks for", red_now_because=t["because"] or "the assert fails on the base",
               code=t["code"])
    contract = dict(row=row, decision="fix", why=why, test={"new": new})
    parts, problem = parts_of(root, res.overlay) if res.green and res.overlay and with_fix else ([], "no green fix")
    if parts and not problem:
        contract["parts"] = parts
    else:
        contract.update(parts=[], test_only=True, why="the solver wrote a red test (the fix is left to the next solve): " + t["id"])
    return contract


def trace_text(res, row, ids, redact=lambda t: t, cap=TRACE_CAP):
    """The full trace of one solve as JSON text of at most ``cap`` bytes: every reply and result (redacted); too long: the oldest
    entries are cut to 400 characters first, then dropped."""
    entries = [{"step": e["step"], "reply": redact(str(e["reply"])), "result": redact(str(e["result"]))} for e in res.log]
    head = dict(row=row, status=res.status, model=res.model, steps=res.steps, calls=res.calls, tests=res.tests, why=res.why,
                ids=list(ids)[:10], stale=res.stale, edited=sorted(res.overlay))
    while True:
        text = json.dumps(dict(head, entries=entries), ensure_ascii=False)
        if len(text.encode("utf-8")) <= cap or not entries:
            return text
        for e in entries:
            if not e["result"].endswith("...[cut]") and (len(e["reply"]) > 400 or len(e["result"]) > 400):
                e["reply"], e["result"] = e["reply"][:400] + " ...[cut]", e["result"][:400] + " ...[cut]"
                break
        else:
            entries.pop(0)


# -------------------------------------------------------------------------------------------------------- stats
class Stats:
    """stats.json['solver']: counters of the loop's solves (the loop thread writes, any thread may read)."""

    def __init__(self):
        self.n = dict(rows=0, green=0, red=0, cloud=0, no_channel=0, already_green=0, steps=0, calls=0, tests=0)

    def add(self, res):
        self.n["rows"] += 1
        self.n[res.status if res.status in self.n else "red"] += 1
        self.n["steps"] += res.steps
        self.n["calls"] += res.calls
        self.n["tests"] += res.tests

    def snapshot(self):
        return dict(self.n)


STATS = Stats()

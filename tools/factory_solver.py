"""W-solver: ONE free model with READ / GREP / DEF / EDIT / TEST in a loop against the red tests of a row (replaces the
hypotheses search). Bench 25.11: 8 of 19 red tests green on the free Flash-Lite against 3.4 % first hits of the cards.

The model sees the test, its failure and the suspect functions; it reads and greps the snapshot of the base, edits files of the
product in an in-memory overlay and the tests run in the cloud after every edit (``ctx.cloud``: the batch of factory_hypo). The
tools are plain python over the snapshot + the overlay: no shell, tests are never edited. A reply that cannot be read is not a
failure but a hint with the format. The result carries the overlay and parts of whole functions for the contract (engine
'solver'); a green overlay that cannot be shipped as whole functions is sent back to the model as an observation."""
import ast
import difflib
import os
import re
import time
from pathlib import Path

from tools import factory_cards as K
from tools import factory_hypo as HY

STEPS = 16                      # answered replies of one solve (a refusal of the channel is not a step)
READS_MAX = 4                   # READ / GREP / DEF commands answered in one reply
READ_LINES = 160
OBS_CAP = 7000                  # chars of one observation
CTX_CHARS = 400000              # the whole prompt of the big step; older observations are cut only above this
SMALL_CHARS = 30000             # the compact prompt for the small step (Gemma: 16k tokens a minute)
KEEP = 5                        # the newest steps kept whole in a cut history
TEST_IDS = 5                    # red ids of the group run by an intermediate TEST (the rest at the final check)
FINAL_IDS = 40
CLOUD_TRIES = 3
READ_PREFIXES = ("echo_sync/", "tests/")
EDIT_PREFIXES = ("echo_sync/",)
FAIL_CAP = 2200

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
DONE                           (only after the tests passed)
Rules: find the ROOT cause first by reading the test, its helper and the product code it calls. Fix the product (echo_sync/); tests are never edited. Never change, remove or weaken any assert, never skip, never special-case the test. SEARCH text must match exactly once. Small edits. Write only YOUR next step: never write a RESULT yourself, the result comes in the next message. The result is shipped as whole new versions of the functions you changed: change bodies of existing functions (a new module-level definition, constant or import is not shipped; a local import inside the function is fine).'''

FORMAT_HINT = ("I could not find a command in your reply. Reply with 1-3 sentences and then exactly one of: up to 4 lines "
               "READ path start end / GREP regex :: path_prefix / DEF name, or one block\nEDIT path\n<<<<<<< SEARCH\nold lines\n"
               "=======\nnew lines\n>>>>>>> REPLACE")


class NoChannel(RuntimeError):
    """The ask found no channel within its waits (a closed road, not a step of the model)."""


class Result:
    def __init__(self):
        self.green = False
        self.status = "red"             # green | red | cloud | no_channel | already_green
        self.overlay = {}               # file -> new text (LF)
        self.greens = []                # red ids that pass with the overlay
        self.steps = 0
        self.calls = 0                  # asks of the model
        self.tests = 0                  # cloud batches
        self.trace = []                 # [(reply tail, observation head)]
        self.last_fail = ""             # the newest failure text of a TEST
        self.why = ""
        self.model = ""

    def evidence(self):
        """Lines for the slicer: what the solver edited last and how the test answered."""
        out = []
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
        self.__dict__.update(kw)


# ------------------------------------------------------------------------------------------------------ the tools
class Tree:
    """The snapshot of the base + the overlay of the edits, read as one tree."""

    def __init__(self, root, overlay=None):
        self.root = Path(root)
        self.overlay = overlay if overlay is not None else {}
        self._base = {}
        self._files = None

    def files(self):
        if self._files is None:
            out = []
            for top in READ_PREFIXES:
                for dirpath, dirs, names in os.walk(self.root / top.rstrip("/")):
                    dirs[:] = [d for d in dirs if d != "__pycache__"]
                    for n in names:
                        if n.endswith(".py"):
                            out.append((Path(dirpath) / n).relative_to(self.root).as_posix())
            self._files = sorted(set(out) | set(self.overlay))
        return self._files

    def base(self, path):
        if path not in self._base:
            self._base[path] = (self.root / path).read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
        return self._base[path]

    def read(self, path):
        path = str(path).strip().strip("\"'`").replace("\\", "/")
        if path in self.overlay:
            return self.overlay[path]
        if ".." in path or not path.startswith(READ_PREFIXES) or not (self.root / path).is_file():
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
    s = tree.read(path).split("\n")
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
    for hit, where in ((rx, pre), (lambda l: lit in l, pre), (lambda l: lit in l, ""), (lambda l: word in l, "")):
        out = []
        for p in tree.files():
            if not p.startswith(where):
                continue
            try:
                body = tree.read(p)
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
    name = args.strip().strip("\"'`").split(".")[-1].split("(")[0].strip()
    if not name:
        return "DEF needs a name"
    out = []
    for p in tree.files():
        try:
            s = tree.read(p)
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
    return "\n".join(out)[:OBS_CAP] or "not found"


_BLOCK = re.compile(r"<{5,} SEARCH[ \t]*\n(.*?)\n?={5,}[ \t]*\n(.*?)\n?>{5,} REPLACE", re.S)
_HEAD = re.compile(r"^[ \t]*EDIT[ \t]+[\"'`]?([^\s\"'`]+)[\"'`]?[ \t]*$", re.M)


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
    staged = {}
    for path, search, replace in blocks:
        if ".." in path or not path.startswith(EDIT_PREFIXES):
            return "refused: only files of echo_sync/ may be edited (tests never): " + path, False
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
    tree.overlay.update(staged)
    return "edited " + ", ".join(sorted(staged)), True


# ----------------------------------------------------------------------------------------- what can be shipped
def parts_of(root, overlay):
    """([part], '') for an overlay whose every change is a change of existing functions; ([], why) when something else changed.
    A part = one file: ``symbols`` + ``code`` = the whole new text of each changed function."""
    parts = []
    for path in sorted(overlay):
        if not path.endswith(".py"):
            return [], "%s is not a python file" % path
        try:
            old = (Path(root) / path).read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
            new = overlay[path]
            so, sn = K._symbols(ast.parse(old)), K._symbols(ast.parse(new))
        except (OSError, SyntaxError, ValueError) as exc:
            return [], "%s does not read: %s" % (path, str(exc)[:80])
        funcs_o = {k for k, v in so.items() if K._is_function(v)}
        funcs_n = {k for k, v in sn.items() if K._is_function(v)}
        if funcs_o != funcs_n:
            return [], "%s: functions were added or removed (%s)" % (path, ", ".join(sorted(funcs_o ^ funcs_n)[:4]))
        changed = [k for k in funcs_o if K.region_sha(old, [k]) != K.region_sha(new, [k])]
        top = [k for k in changed if not any(k.startswith(o + ".") for o in changed if o != k and o in funcs_o
                                             and K._is_function(so[o]))]
        if not top:
            return [], "%s: the change is outside of function bodies (a constant, an import or a definition line)" % path
        texts = {}
        for k in top:
            node = sn[k]
            texts[k] = "\n".join(new.split("\n")[K._node_start(node) - 1:node.end_lineno])
        rebuilt = old
        try:
            for k in sorted(top, key=lambda k: -K._node_start(sn[k])):       # from the bottom: the lines above do not move
                rebuilt = HY.apply_function(rebuilt, k, texts[k])
        except ValueError as exc:
            return [], "%s: %s" % (path, exc)
        if rebuilt != new:
            return [], "%s: the change reaches outside of the function bodies (a constant, an import or a decorator)" % path
        code = "\n\n".join(texts[k] for k in sorted(top, key=lambda k: K._node_start(sn[k])))
        try:
            K.split_part_code(code, sorted(top))
        except ValueError as exc:
            return [], "%s: %s" % (path, str(exc)[:100])
        parts.append(dict(file=path, symbols=sorted(top), code=code,
                          instruction="Replace %s with the verified text from code: the cloud run made the red test green with it."
                          % ", ".join(sorted(top)), keep="the signature"))
    return parts, ""


def to_contract(row, ids, res, root, group=None, rep=None, why="the solver made the red test green in the cloud"):
    """The contract of a green result (engine 'solver'): a fix whose parts carry the verified code; ``test.use`` = a green id.
    None when the overlay cannot be shipped as whole functions."""
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
    left = [i for i in ids if i not in greens]
    if left:
        out["more"] = "остались красные: " + ", ".join(left[:6]) + (" (+%d)" % (len(left) - 6) if len(left) > 6 else "")
    return out


# ------------------------------------------------------------------------------------------------------- the loop
def _task(red_ids, failure, test_source, suspects):
    tops = "\n".join(str(s) for s in list(suspects)[:15])
    return ("Failing tests: %s\n\nThe test:\n%s\n\nFailure:\n%s\n\nProduct functions the failing test runs, most suspicious first:\n%s"
            % (", ".join(red_ids[:TEST_IDS]), str(test_source)[:3500], str(failure)[-FAIL_CAP:], tops or "(unknown)"))


def render(task, hist, limit, keep=KEEP):
    """The prompt: the system rules, the task, the whole history; above ``limit`` characters the observations and replies of the
    steps older than ``keep`` are cut (the newest stay whole), and ``keep`` shrinks until it fits (down to 2)."""
    def build(k):
        parts = [SYSTEM, "", task]
        for i, (a, o) in enumerate(hist):
            old = len(hist) - i > k
            a = a[:400] if old and len(a) > 400 else a
            o = (o[:300] + " ...[cut]") if old and len(o) > 300 else o
            parts += ["", "YOU:", a, "", "RESULT:", o]
        parts += ["", "YOU:"]
        return "\n".join(parts)
    full = "\n".join([SYSTEM, "", task] + [x for a, o in hist for x in ("", "YOU:", a, "", "RESULT:", o)] + ["", "YOU:"])
    if len(full) <= limit:
        return full
    k = keep
    text = build(k)
    while len(text) > limit and k > 2:
        k -= 1
        text = build(k)
    return text[-limit:] if len(text) > limit else text


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
    first = sorted(res.overlay)[0]
    got = _verdict(ctx, list(ids[:FINAL_IDS]) + [HY.FILE_RUN + f for f in files],
                   {"1": dict(res.overlay), HY.CONTROL: {first: tree.base(first)}}, res)
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


def solve(ctx, row, red_ids, failure, test_source, suspects, *, steps=STEPS):
    """One row: the loop of the model against the red ids. Returns a Result (never raises: a refusal of every road is a status)."""
    res = Result()
    ids = [str(i) for i in red_ids]
    if not ids:
        res.status, res.why = "red", "no red ids"
        return res
    tree = Tree(ctx.root)
    res_overlay = tree.overlay
    res.overlay = res_overlay
    task = _task(ids, failure, test_source, suspects)
    hist = []
    try:
        for n in range(1, steps + 1):
            res.steps = n
            small = render(task, hist, ctx.small_chars, keep=2)
            text = render(task, hist, ctx.ctx_chars)
            try:
                reply = ctx.ask(text, small=small)
            except NoChannel as exc:
                res.status, res.why = "no_channel", str(exc)[:120]
                res.steps = n - 1
                return res
            res.calls += 1
            res.model = str(ctx.info.get("model") or res.model)
            obs = _step(ctx, tree, ids, reply, res)
            if res.green:
                res.trace.append((reply[-300:], "PASSED"))
                res.status = "green"
                return res
            if res.status in ("already_green", "cloud"):
                return res
            if n == max(1, steps // 3) and not res_overlay:
                obs += "\nYou have read enough: make your best EDIT now (a red test run is cheap and tells more than reading)."
            elif n >= steps // 2 and not res_overlay:
                obs += "\nNo edit yet. Your next reply MUST be an EDIT."
            obs += "\n(%d steps left)" % (steps - n)
            hist.append((reply[-3500:], obs))
            res.trace.append((reply[-300:], obs[:300]))
        res.status, res.why = "red", "steps used"
    except HY.CloudFail as exc:
        res.status, res.why = "cloud", str(exc)[:120]
    res.overlay = dict(res_overlay)
    return res


def _step(ctx, tree, ids, reply, res):
    """One reply -> the observation text. Sets res.green, res.status 'cloud' / 'already_green' when it ends the solve."""
    text = (reply or "").replace("\r\n", "\n")
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
    if re.search(r"^[ \t]*DONE\b", text, flags=re.M):
        return "not done: no TEST has passed on your edits yet" if not tree.overlay else "not done: the tests have not passed yet"
    if re.search(r"^[ \t]*TEST\b", text, flags=re.M):
        return _test(ctx, tree, ids, res) if tree.overlay else "no edits yet: make an EDIT first (the tests run after it by themselves)"
    if re.search(r"^[ \t]*EDIT\b", text, flags=re.M):
        return "I found EDIT but no complete block. Use:\nEDIT path\n<<<<<<< SEARCH\nold lines\n=======\nnew lines\n>>>>>>> REPLACE"
    return FORMAT_HINT


def _test(ctx, tree, ids, res):
    """The cloud run after an edit: the red ids (the first few of the group). res.green only after the final check passes."""
    try:
        got = _verdict(ctx, _run_ids(ids), {"1": dict(tree.overlay)}, res)
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
        return "PASSED, but it cannot be shipped: %s. Make the same fix using only changes inside the bodies of existing functions." % problem
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

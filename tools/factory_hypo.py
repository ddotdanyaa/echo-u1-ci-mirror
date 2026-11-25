"""The cloud side of the solver (factory_solver): the batch of candidate files run in the cloud (``cloud_batch``), the ranking
of the suspect functions, the failure signatures and their groups, the cooldown of a searched group. The generation of
hypotheses (cards, the pump of free models, the repair circle) was replaced by the solver loop (W-solver 25.11): 155 searches
gave 1 green. Everything outside (channels, cloud, clock) is injected by the loop."""
import ast
import json
import re
import time
from pathlib import Path

from tools import factory_cards as K

HYPO_FUNCS = 8                  # functions per row
TEST_LINES = 40                 # the test body shown, lines
ROW_COOLDOWN_S = 12 * 3600      # the same base+test is not searched again sooner
RECENT_RE = re.compile(r"^\s*(\S+\.py):(\d+): in (\w+)", re.M)
TB_RE = re.compile(r'File "([^"]+\.py)", line (\d+), in (\w+)')
CONTROL = "ctl"         # W-part 3: the zero candidate of every batch = the tree of the base, unchanged
FILE_RUN = "@"          # an id line '@<file>': the cloud runs the whole file (its green tests are the 'no new red' proof)
SIG_CAP = 100


class CloudFail(RuntimeError):
    """The cloud did not answer (down, busy, unreadable): the batch is repeated, nothing is penalised."""


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
    # W-hypo3 2: the functions whose lines stand both in the failure trace and in the diff of the last merge come first
    in_diff = {(str(f).replace("\\", "/"), str(n).rpartition(".")[2]) for f, n in diff}
    for f, n in list(stack) + [(t[0], t[1]) for t in reversed(list(trace))]:
        if (str(f).replace("\\", "/"), str(n).rpartition(".")[2]) in in_diff:
            add(f, n, "stack+diff")
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


def row_class(row: str) -> int:
    """Queue order of rows: ECHO rows first (0), then rel-<sha> (1), then the base debt (2)."""
    r = str(row)
    if r.startswith("rel-base-"):       # agent_factory.is_base_debt: the old baseline debt
        return 2
    return 1 if r.startswith("rel-") else 0


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

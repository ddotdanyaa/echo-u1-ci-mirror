"""Repo map ranking for the localizer (H-repomap): which functions does a (Russian) backlog row mean?

After Aider's repo map (aider/repomap.py, Apache-2.0, (c) Aider-AI): a def/ref graph of the repository ranked with
PageRank personalised by what the request mentions; edge weights follow Aider (x10 for a mentioned identifier,
x10 for a long snake/camel name, x0.1 for _private names, x0.1 for a name defined in more than 5 files, sqrt of the
reference count).  Differences, on purpose: tags come from the stdlib ``ast`` (the product is Python-only, so nothing
to install: no tree-sitter, no grep-ast, no networkx; 0 RUB), and the personalisation is lexical: the Russian row is
matched DIRECTLY against each definition's name, docstring and comments (Russian stemmer + <id> of the triage,
``agent_factory_import._words`` / ``_bm25``), so no translation step is needed.  No model call here.
"""
from __future__ import annotations

import ast
import io
import math
import re
import tokenize
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_DIRS = ("echo_sync", "tools")
MENTION_BOOST = 8.0
EN_WEIGHT = 0.6
GLOSSARY_ON = True
_ROW_IDENT = re.compile(r"`([A-Za-z_][\w.]*)(?:\(\))?`|(?<![\w.])([A-Za-z_][A-Za-z0-9_]*_[A-Za-z0-9_]+)(?![\w])")
_FILE_REF = re.compile(r"([A-Za-z_][\w/]*?)\.py")
_CACHE: dict = {}


def _aif():
    from tools import agent_factory_import as I
    return I


# Small deterministic RU->EN term map for the ECHO domain (the code has English identifiers and almost no Russian text:
# ~1000 Russian stems in 4000 definitions, too few to mine a map from co-occurrence, measured).  Russian word -> the
# identifier words it usually becomes.  Used only as a down-weighted query expansion beside the direct Russian match.
_GLOSSARY = """
вопрос: question ask query; ответ: answer reply response; подсказка: cue hint prompt; звонок: call; речь: speech voice;
голос: voice speech; озвучка: speech tts voice say; звук: audio sound; микрофон: mic mike audio; тишина: silence quiet;
пауза: pause gap; слово: word token; фраза: phrase sentence utterance; реплика: utterance turn; порция: portion chunk;
память: memory recall; поиск: search lookup; перебивание: barge interrupt; задержка: latency delay lag; ударение: stress accent;
дата: date; число: number numeral digit cardinal ordinal; ошибка: error fail; журнал: journal log trace; настройка: settings config;
правило: rule; хозяин: owner; ворота: gate; хвост: tail; повтор: repeat again; уточнение: clarify clarification;
адресат: addressee address; текст: text; материал: material; таблица: table; сцена: scene; реестр: registry census;
слушание: listen hear ear; эхо: echo; динамик: speaker; наушники: headset airpods; маршрут: route; сеть: network net;
туннель: tunnel; сервер: server; запись: record recording; транскрипт: transcript; распознавание: recognizer asr stt;
перевод: translate translation; язык: language lang; тема: topic; лекция: lecture; презентация: slide presentation;
математика: math; расчёт: calc compute; поручение: order; закрытие: close; тест: test; замер: measure meter;
первая: first; быстрый: fast quick instant; классификатор: classifier; намерение: intent; команда: command;
подтверждение: confirm confirmation; отказ: refuse refusal deny; приватность: privacy; пароль: secret password;
ритм: pace tempo; темп: pace tempo; скорость: speed rate; дубль: duplicate dup; сбой: failure crash; восстановление: recover resume;
шум: noise; громкость: volume loudness; запрос: request query; сообщение: message; чат: chat; профиль: profile
"""


def _ru_en() -> dict:
    I = _aif()
    out = {}
    for ent in re.split(r";\s*", _GLOSSARY.strip().replace(chr(10), " ")):
        if ":" in ent:
            ru, en = ent.split(":", 1)
            out[I._stem(ru.strip())] = [I._stem(w) for w in en.split()]
    return out


def expand(words) -> list:
    """English stems that the Russian stems of a row usually become (deterministic glossary lookup)."""
    g = _ru_en()
    return [e for w in set(words) for e in g.get(w, ())]


def _py_files(root: Path, dirs) -> list:
    out = []
    for d in dirs:
        base = root / d
        if base.is_dir():
            for p in sorted(base.rglob("*.py")):
                parts = p.relative_to(root).parts
                if "__pycache__" in parts or "tests" in parts or p.name == "__init__.py":
                    continue
                out.append(p.relative_to(root).as_posix())
    return out


def _parse(root: Path, rel: str):
    """(defs, refs) of one file: defs = [(qualname, line, word-counter of name+docstring+comments)]."""
    p = root / rel
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        if key in _CACHE:
            return _CACHE[key]
        src = p.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except (OSError, SyntaxError, ValueError):
        return [], Counter()
    I = _aif()
    spans, defs = [], []

    def walk(node, prefix):
        for ch in ast.iter_child_nodes(node):
            if isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                q = prefix + ch.name
                doc = (ast.get_docstring(ch) or "")[:600]
                bag = Counter(I._words(ch.name + " " + doc))
                defs.append([q, ch.lineno, bag])
                spans.append((ch.lineno, getattr(ch, "end_lineno", ch.lineno), len(defs) - 1))
                walk(ch, q + ".")
            else:
                walk(ch, prefix)
    walk(tree, "")
    try:   # comments belong to the innermost definition that holds the line
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                ln = tok.start[0]
                inner = [s for s in spans if s[0] <= ln <= s[1]]
                if inner:
                    best = min(inner, key=lambda s: s[1] - s[0])
                    defs[best[2]][2].update(I._words(tok.string[:200]))
    except (tokenize.TokenError, IndentationError):
        pass
    refs: Counter = Counter()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            refs[n.id] += 1
        elif isinstance(n, ast.Attribute):
            refs[n.attr] += 1
        elif isinstance(n, ast.ImportFrom):
            for a in n.names:
                refs[a.name] += 1
    res = ([tuple(d) for d in defs], refs)
    _CACHE[key] = res
    return res


def mentioned(text: str) -> tuple:
    """(identifiers, file stems) the row names explicitly (backticks, snake_case words, ``name.py``)."""
    ids = {a or b for a, b in _ROW_IDENT.findall(text or "")}
    ids |= {i.split(".")[-1] for i in list(ids)}
    stems = {Path(m).name for m in _FILE_REF.findall(text or "")}
    return ids, stems


def rank(root, row_text: str, k: int = 10, dirs=DEFAULT_DIRS, shortlist=()) -> list:
    """[(file, qualname, score)] best first: the functions/classes the row most likely means.  [] when nothing in the
    row meets anything in the code (noise, empty)."""
    root = Path(root)
    I = _aif()
    q = set(I._words(row_text))
    ids, stems = mentioned(row_text)
    if not q and not ids:
        return []
    files = _py_files(root, dirs)
    parsed = {rel: _parse(root, rel) for rel in files}
    flat = [(rel, qn, ln, bag) for rel, (defs, _) in parsed.items() for qn, ln, bag in defs]
    if not flat:
        return []
    en_q = set(expand(q)) - q if GLOSSARY_ON else set()
    field = I._bm25_field({i: b for i, (_, _, _, b) in enumerate(flat)})
    short = {s.replace("\\", "/") for s in (shortlist or ())}
    lex = []
    for i, (rel, qn, _, bag) in enumerate(flat):
        s = I._bm25(q, bag, field["len"][i], field["df"], field["n"], field["avg"])
        if en_q:
            s += EN_WEIGHT * I._bm25(en_q, bag, field["len"][i], field["df"], field["n"], field["avg"])
        last = qn.split(".")[-1]
        if last in ids or qn in ids:
            s += MENTION_BOOST
        if s > 0 and (Path(rel).stem in stems or rel in short):
            s *= 1.5
        lex.append(s)
    top = max(lex)
    if top <= 0:
        return []
    lexn = [s / top for s in lex]
    # file graph (Aider): referencer -> definer, per identifier
    definers = defaultdict(set)
    for rel, qn, _, _ in flat:
        definers[qn.split(".")[-1]].add(rel)
    mention_names = ids
    edges = defaultdict(float)      # (src, dst) -> weight
    ident_edges = defaultdict(list)  # dst -> [(src, ident, w)]
    for src_f, (_, refs) in parsed.items():
        for ident, cnt in refs.items():
            ds = definers.get(ident)
            if not ds:
                continue
            mul = 1.0
            if ident in mention_names:
                mul *= 10
            if len(ident) >= 8 and ("_" in ident or any(c.isupper() for c in ident[1:])):
                mul *= 10
            if ident.startswith("_"):
                mul *= 0.1
            if len(ds) > 5:
                mul *= 0.1
            w = mul * math.sqrt(cnt)
            for dst in ds:
                if dst != src_f:
                    edges[(src_f, dst)] += w
                    ident_edges[dst].append((src_f, ident, w))
    pers = defaultdict(float)
    for (rel, _, _, _), s in zip(flat, lexn):
        pers[rel] += s
    tot = sum(pers.values()) or 1.0
    pers = {f: v / tot for f, v in pers.items()}
    nodes = list(files)
    out_w = defaultdict(float)
    for (a, _), w in edges.items():
        out_w[a] += w
    pr = {f: 1.0 / len(nodes) for f in nodes}
    for _ in range(40):          # personalised PageRank, damping 0.85; dangling mass goes back to the seeds
        nxt = {f: 0.15 * pers.get(f, 0.0) for f in nodes}
        dangling = sum(pr[f] for f in nodes if out_w[f] == 0)
        for (a, b), w in edges.items():
            nxt[b] += 0.85 * pr[a] * w / out_w[a]
        for f in nodes:
            nxt[f] += 0.85 * dangling * pers.get(f, 0.0)
        pr = nxt
    prmax = max(pr.values()) or 1.0
    # rank flowing into one definition: the referencers' rank over their out-weight, per identifier (Aider)
    flow = defaultdict(float)
    for dst, lst in ident_edges.items():
        for src_f, ident, w in lst:
            flow[(dst, ident)] += pr[src_f] * w / out_w[src_f]
    fmax = max(flow.values(), default=0.0) or 1.0
    scored = []
    for (rel, qn, _, _), l in zip(flat, lexn):
        last = qn.split(".")[-1]
        score = l * (1 + pr[rel] / prmax) + 0.5 * flow.get((rel, last), 0.0) / fmax * (1 if l > 0 else 0.2)
        if score > 0:
            scored.append((rel, qn, round(score, 4)))
    scored.sort(key=lambda t: (-t[2], t[0], t[1]))
    return scored[:k]


def hints(ranked) -> str:
    """English hint block for the localizer prompts: the ranked functions grouped by file (empty when none)."""
    by: dict = {}
    for rel, qn, _ in ranked or ():
        by.setdefault(rel, []).append(qn)
    if not by:
        return ""
    lines = ["Static repo-map ranking of likely locations (a hint from names, docstrings and call graph; may be wrong):"]
    lines += ["- %s: %s" % (rel, ", ".join(names)) for rel, names in by.items()]
    return "\n".join(lines)

"""V7-AUDIT: the owner census. How many places of the code MAKE each decision, family by family, on any tree or git ref.

    python -m tools.owner_census                                 the working tree against tools/owner_census_sites.ndjson
    python -m tools.owner_census --ref origin/claude/x           any git ref: the files are read by ``git cat-file``, nothing is checked out
    python -m tools.owner_census --ref X --base c1d2434          plus what the branch did: the places gone / moved / changed and the surface delta
    python -m tools.owner_census --list [--family kind]          every place with its status and its line
    python -m tools.owner_census --json                          the same as one JSON object
    python -m tools.owner_census --ref X --base Y --verdict      one line for a branch: clean / review / layer and why, mechanically, from the surface delta and the owners of each family
    python -m tools.owner_census --check                         exit 1 when a place of the list is not ``present`` (the list rotted)

The list: one JSON object a line, a place that makes a decision: family, owner (the judge the place belongs to), role, file, func (``Class.method``, a
function, a class, or ``<module>``), anchor (the deciding line, verbatim), decides. An OWNER is a judge of its own: a function or a group of functions with
one entry that gives or changes a verdict of the family by its own rules, and the verdict acts with no other judge of the family approving it. The rules a
judge calls from its one entry are places of that one owner (a judge of 21 rules is one owner with 21 places); two entries that can each give or change the
verdict on their own are two owners. ``tools/owner_census_owners.json`` names the owners (title, what it decides, what to do with it).
A place is found by its function first (the AST: a shifted line is nothing) and by its anchor inside the function:
    present  the function and the line are there
    changed  the function is there and the line was rewritten (a constant: the name is there with another value): still a place, to be read again
    moved    the same function stands in another file or class (a split of a file is not a removal)
    gone     neither: the place was removed (a place a branch brought, ``since``, is gone wherever its line is not)
Owners of a family = the judges whose verdict acts, with a place still standing: owner (the main one), dup (decides the same on another road), override
(changes a verdict already given), gateway (a newer layer in front of an older road that is still there). Counted apart: shadow (computes and does not act),
dead (a judge no road reaches), flag (a switch of behaviour: a key of the settings, a literal of a constructor), unsorted (a place the sweep found that no
judge was named for yet). One engine = one owner a family.
The surface is what is counted with no list at all: modules, functions (with a hash of the normalised code), decision-shaped names, the keys of
``settings.DEFAULTS``, the names read from the environment, the constants of time. The delta of two surfaces names what a branch brought: a new layer shows
as new modules and new decision-shaped functions, a new mode as a new flag, a new inline decision hides in ``changed_funcs`` only.
Nothing is imported or run.
"""
import argparse
import ast
import hashlib
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITES_PATH = ROOT / 'tools' / 'owner_census_sites.ndjson'
OWNERS_PATH = ROOT / 'tools' / 'owner_census_owners.json'
BASE = 'c1d2434dde4791edfe02f0409a6f7d6e0a8f9118'      # claude/laptop-v7-main on 13.11.2026: the code the list was written from
FAMILIES = (('kind', 'вид реплики'), ('question', 'вопрос'), ('answer', 'ответ'), ('portion', 'порция'), ('timers', 'таймеры'), ('speech', 'речь'),
            ('memory', 'память'), ('modes', 'режимы'), ('route', 'дорога к модели'))
DECIDING = ('owner', 'dup', 'override', 'gateway')
OTHER = ('shadow', 'dead', 'flag', 'unsorted')
PACKAGE = 'echo_sync'
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef)
_TIME = re.compile(r'(_S|_MS|_TTL)$|SECONDS|TIMEOUT|_WAIT$')      # the rule of ``timer_policy._NAME``
_ENV = re.compile(r'''(?:environ\.get\(|getenv\(|environ\[)\s*['"]([A-Za-z0-9_]+)['"]''')
_ASSIGN = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\s*(?::[^=]+)?=(?!=)')
_DECIDER = re.compile(r'^(?:is|has|should|can|must|may|needs?|wants?|allow|accept|reject|admit|decide|pick|choose|select|resolve|detect|match|looks|same|open|drop|abandon|arm|expire)(?:_|$)'
                      r'|question|answer|verdict|decid|judge|classif|route|gate|veto|guard|portion|cursor|repeat|timer|timeout|deadline|due|speak|say|cancel|interrupt|memory|recall|remember|forget'
                      r'|mode|shadow|provider|fallback|reserve|breaker|retry|lookup|search')


def _scope_files(paths):
    return sorted(path for path in paths if path.endswith('.py') and (path.startswith(PACKAGE + '/') or '/' not in path))


class Tree:
    """The python files of one state of the code (the package and the root scripts): path -> text. ``from_dir`` reads a folder, ``from_ref`` a git ref with no checkout."""

    def __init__(self, texts, name=''):
        self.texts, self.name, self._index = dict(texts), name, {}

    @classmethod
    def from_dir(cls, root):
        root = Path(root)
        paths = _scope_files([path.relative_to(root).as_posix() for path in list(root.glob(PACKAGE + '/**/*.py')) + list(root.glob('*.py'))])
        return cls({path: (root / path).read_text(encoding='utf-8', errors='replace') for path in paths}, str(root))

    @classmethod
    def from_ref(cls, ref, repo=ROOT):
        def run(*args, data=None):
            return subprocess.run(['git', '-C', str(repo), *args], input=data, capture_output=True, check=True).stdout
        paths = _scope_files(run('ls-tree', '-r', '--name-only', '-z', ref).decode('utf-8').split('\0'))
        blob, texts, at = run('cat-file', '--batch', data=''.join(f'{ref}:{path}\n' for path in paths).encode('utf-8')), {}, 0
        for path in paths:
            end = blob.index(b'\n', at)
            size = int(blob[at:end].split()[2])
            texts[path] = blob[end + 1:end + 1 + size].decode('utf-8', errors='replace')
            at = end + 2 + size
        return cls(texts, ref)

    def index(self, path):
        if path not in self._index:
            self._index[path] = _index(self.texts[path]) if path in self.texts else None
        return self._index[path]

    def indexes(self):
        return [(path, self.index(path)) for path in sorted(self.texts)]


def _strip(node):
    """Drops the docstring of every body: a doc change is no change of code."""
    for child in ast.walk(node):
        body = getattr(child, 'body', None)
        if isinstance(child, (*_DEFS, ast.ClassDef, ast.Module)) and body and isinstance(body[0], ast.Expr) \
                and isinstance(getattr(body[0], 'value', None), ast.Constant) and isinstance(body[0].value.value, str):
            child.body = body[1:] or [ast.Pass()]
    return node


def _hash(nodes):
    return hashlib.sha1('\n'.join(ast.dump(node, annotate_fields=False) for node in nodes).encode('utf-8')).hexdigest()[:12]


def _index(text):
    """One file: scopes (qualified name -> first line, last line, 'def' or 'class'), consts (``NAME`` / ``Class.NAME`` of module and class level -> line),
    hashes (qualified name -> hash of the normalised code; ``<module>`` and ``Class.<body>`` are the statements outside every function), the lines without spaces compared."""
    lines = text.split('\n')
    found = {'scopes': {}, 'consts': {}, 'hashes': {}, 'norm': [' '.join(line.split()) for line in lines], 'text': text}
    try:
        tree = _strip(ast.parse(text))
    except SyntaxError:
        return found

    def walk(body, prefix, inside):
        loose = []
        for node in body:
            if isinstance(node, (*_DEFS, ast.ClassDef)):
                name = prefix + node.name
                if name not in found['scopes']:
                    found['scopes'][name] = (min([node.lineno] + [mark.lineno for mark in node.decorator_list]), node.end_lineno, 'class' if isinstance(node, ast.ClassDef) else 'def')
                    if isinstance(node, _DEFS):
                        found['hashes'][name] = _hash([node])
                rest = walk(node.body, name + '.', inside or isinstance(node, _DEFS))
                if isinstance(node, ast.ClassDef) and not inside:
                    found['hashes'].setdefault(name + '.<body>', _hash(rest))
                continue
            loose.append(node)
            if not inside and isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                    for leaf in ast.walk(target):
                        if isinstance(leaf, ast.Name):
                            found['consts'].setdefault(prefix + leaf.id, node.lineno)
            for part in [getattr(node, field, None) for field in ('body', 'orelse', 'finalbody')] + [handler.body for handler in getattr(node, 'handlers', [])]:
                if isinstance(part, list) and part and isinstance(part[0], ast.stmt):
                    walk(part, prefix, inside)
        return loose

    found['hashes']['<module>'] = _hash(walk(tree.body, '', False))
    return found


def load_sites(path=SITES_PATH):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').split('\n') if line.strip() and not line.startswith('#')]


def _find(index, anchor, first, last):
    """The first line of [first, last] that holds the anchor; runs of spaces are not compared."""
    want = ' '.join(anchor.split())
    if want:
        for number in range(first, min(last, len(index['norm'])) + 1):
            if want in index['norm'][number - 1]:
                return number
    return 0


def _place(site, tree):
    """(status, where, line) of one place in one tree."""
    path, func, anchor = site['file'], site['func'], site['anchor']
    index, bare = tree.index(path), func.rsplit('.', 1)[-1]
    named = _ASSIGN.match(anchor.strip())
    const = ((func + '.') if func != '<module>' else '') + named.group(1) if named else None
    if func == '<module>':
        line = index and _find(index, anchor, 1, len(index['norm']))
        if line:
            return 'present', path, line
        if index and const in index['consts']:
            return 'changed', path, index['consts'][const]
        for other, found in tree.indexes():
            if other != path and const and const in found['consts']:
                return 'moved', other, found['consts'][const]
        return 'gone', '', 0
    if index and func in index['scopes']:
        first, last, _ = index['scopes'][func]
        line = _find(index, anchor, first, last)
        return ('present', path, line) if line else ('changed', path, index['consts'].get(const, first))
    held, lone = None, []
    for other, found in tree.indexes():
        for name, (first, last, sort) in found['scopes'].items():
            if name == func or name.rsplit('.', 1)[-1] == bare and not bare.startswith('__'):      # the name of a dunder says nothing of who it is
                line = _find(found, anchor, first, last)
                if name == func and (other != path or line) or line:
                    held = held or (other, line or first)
                elif not bare.startswith('__'):
                    lone.append((other, first))
    if held:
        return 'moved', held[0], held[1]
    if len(lone) == 1 and '.' in func:                  # the only function of this name in the whole tree, under another class
        return 'moved', lone[0][0], lone[0][1]
    return 'gone', '', 0


def resolve(sites, tree):
    """Every place of the list with its status in this tree: ``status``, ``where`` (the file it stands in now), ``line``."""
    rows = []
    for site in sites:
        status, where, line = _place(site, tree)
        if site.get('since') and (status == 'changed' or status == 'moved' and site['func'] not in (tree.index(where) or {'scopes': ()})['scopes']):
            status, where, line = 'gone', '', 0             # a place a branch brought: where its line is not under its own name, the place is not (the function may be older)
        rows.append({**site, 'status': status, 'where': where, 'line': line})
    return rows


def census(rows):
    """family -> the count. ``owners`` = the judges with a live place whose verdict acts (DECIDING), ``places`` = their live places, ``files`` = the files they
    stand in; a role = the judges of that role (``flag``: the live flags); ``gone`` / ``changed`` / ``moved`` = places, ``gone_owners`` = judges with no place left."""
    table = {}
    for key, title in FAMILIES:
        mine = [row for row in rows if row['family'] == key]
        live = [row for row in mine if row['status'] != 'gone']
        acting = [row for row in live if row['role'] in DECIDING]
        judges = lambda found, *roles: {row.get('owner', row['func']) for row in found if row['role'] in roles}      # noqa: E731
        table[key] = {'title': title, 'owners': len(judges(acting, *DECIDING)), 'places': len(acting), 'files': len({row['where'] for row in acting}),
                      **{role: len(judges(live, role)) for role in DECIDING + ('shadow', 'dead')}, 'flag': sum(row['role'] == 'flag' for row in live), 'unsorted': sum(row['role'] == 'unsorted' for row in live), 'listed': len(mine),
                      **{status: sum(row['status'] == status and not (status == 'gone' and row.get('since')) for row in mine) for status in ('gone', 'changed', 'moved')},
                      'gone_owners': len(judges(mine, *DECIDING, 'shadow', 'dead') - judges(live, *DECIDING, 'shadow', 'dead'))}
    return table


def owners(rows, names=None):
    """Every judge of the list with what is left of it: family, owner, role, places (live), gone, changed, moved, files, and its title when ``names`` has it."""
    found = {}
    for row in rows:
        if row['role'] in ('flag', 'unsorted'):
            continue
        mine = found.setdefault((row['family'], row.get('owner', row['func'])), {'family': row['family'], 'owner': row.get('owner', row['func']), 'role': row['role'],
                                                                             'places': 0, 'gone': 0, 'changed': 0, 'moved': 0, 'files': set()})
        if row['status'] == 'gone':
            mine['gone'] += 1
        else:
            mine['places'] += 1
            mine['files'].add(row['where'])
            mine[row['status']] = mine.get(row['status'], 0) + 1 if row['status'] in ('changed', 'moved') else mine.get(row['status'], 0)
    order = {key: at for at, (key, _) in enumerate(FAMILIES)}
    out = []
    for (family, owner), mine in sorted(found.items(), key=lambda item: (order.get(item[0][0], 99), (DECIDING + OTHER).index(item[1]['role']) if item[1]['role'] in DECIDING + OTHER else 99, item[0][1])):
        mine['files'] = sorted(mine['files'])
        mine.pop('present', None)
        mine['title'] = ((names or {}).get(family) or {}).get(owner, {}).get('title', '')
        out.append(mine)
    return out


def surface(tree):
    """What is counted with no list: modules, funcs (``path:qualified`` -> hash), deciders (the decision-shaped names), flags, env, timers."""
    found = {'modules': sorted(tree.texts), 'funcs': {}, 'deciders': [], 'flags': [], 'env': [], 'timers': []}
    for path, index in tree.indexes():
        for name, digest in index['hashes'].items():
            found['funcs'][path + ':' + name] = digest
            if name in index['scopes'] and _DECIDER.search(name.rsplit('.', 1)[-1].lstrip('_')):
                found['deciders'].append(path + ':' + name)
        found['timers'] += [path + ':' + name for name in index['consts'] if _TIME.search(name.rsplit('.', 1)[-1])]
        found['env'] += _ENV.findall(index['text'])
        if path == PACKAGE + '/settings.py':
            try:
                for node in ast.parse(index['text']).body:
                    if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict) and any(isinstance(target, ast.Name) and target.id == 'DEFAULTS' for target in node.targets):
                        found['flags'] += [key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)]
            except SyntaxError:
                pass
    for key in ('deciders', 'flags', 'env', 'timers'):
        found[key] = sorted(set(found[key]))
    return found


def _split(name):
    path, qualified = name.split(':', 1)
    return path, qualified


def surface_delta(base, head):
    """What the head has that the base has not, and back. A function or a constant of time that only changed its file is a move; ``changed_funcs`` are the
    functions (and the module / class bodies) whose normalised code differs, a moved one included."""
    delta = {f'{side}_{key}': sorted(set(new[key]) - set(old[key])) for key in ('modules', 'flags', 'env') for side, old, new in (('new', base, head), ('gone', head, base))}
    new, gone = sorted(set(head['funcs']) - set(base['funcs'])), sorted(set(base['funcs']) - set(head['funcs']))
    moved, changed = [], [name for name in sorted(set(base['funcs']) & set(head['funcs'])) if base['funcs'][name] != head['funcs'][name]]
    for full in (True, False):                          # the same qualified name first, then the same bare name under another class
        def key(name):
            return _split(name)[1] if full else _split(name)[1].rsplit('.', 1)[-1]
        came, went = defaultdict(list), defaultdict(list)
        for name in new:
            came[key(name)].append(name)
        for name in gone:
            went[key(name)].append(name)
        for name, old in went.items():
            if len(old) == 1 and len(came.get(name, ())) == 1 and not name.startswith(('<', '__')) and not name.endswith('>'):
                before, after = old[0], came[name][0]
                moved.append(f'{_split(before)[1]}: {_split(before)[0]} -> {_split(after)[0]}' + ('' if _split(before)[1] == _split(after)[1] else ':' + _split(after)[1]))
                new.remove(after)
                gone.remove(before)
                if base['funcs'][before] != head['funcs'][after]:
                    changed.append(after)
    delta.update(new_classes=[name[:-len('.<body>')] for name in new if name.endswith('.<body>')], gone_classes=[name[:-len('.<body>')] for name in gone if name.endswith('.<body>')])
    new, gone = [name for name in new if not name.endswith('>')], [name for name in gone if not name.endswith('>')]      # the body of a new module is named by new_modules
    decision = set(base['deciders']) | set(head['deciders'])
    delta.update(moved_funcs=sorted(moved), new_funcs=new, gone_funcs=gone, changed_funcs=sorted(changed),
                 new_deciders=[name for name in new if name in decision], gone_deciders=[name for name in gone if name in decision])
    came, went = sorted(set(head['timers']) - set(base['timers'])), sorted(set(base['timers']) - set(head['timers']))
    names = {_split(name)[1] for name in came} & {_split(name)[1] for name in went}
    delta.update(new_timers=[name for name in came if _split(name)[1] not in names], gone_timers=[name for name in went if _split(name)[1] not in names],
                 moved_timers=sorted(name for name in came if _split(name)[1] in names))
    return delta


def report(sites, tree, base=None, names=None):
    """The whole answer for one tree (against a base tree when given) as a dict."""
    rows, shape = resolve(sites, tree), surface(tree)
    out = {'ref': tree.name, 'families': census(rows), 'owners': 0, 'judges': owners(rows, names), 'rows': rows, 'surface': {key: len(value) for key, value in shape.items()}}
    out['owners'] = sum(row['owners'] for row in out['families'].values())
    was = {}
    if base is not None:
        old = resolve(sites, base)
        was = {(row['family'], row['file'], row['func'], row['anchor']): row['status'] for row in old}
        out.update(base=base.name, base_families=census(old), base_judges=owners(old, names), surface_delta=surface_delta(surface(base), shape))
        out['base_owners'] = sum(row['owners'] for row in out['base_families'].values())
        out['came'] = [row for row in rows if row['status'] != 'gone' and was[(row['family'], row['file'], row['func'], row['anchor'])] == 'gone']
    for status in ('gone', 'changed', 'moved'):
        out[status] = [row for row in rows if row['status'] == status and was.get((row['family'], row['file'], row['func'], row['anchor']), 'gone' if row.get('since') else 'present') != status]
    return out


def verdict(out):
    """The mechanical verdict of a branch from its report against a base (``report(..., base=...)``): ``{'verdict', 'reasons'}``. No one reads the branch to give it.
    ``layer`` (reject: a new path beside the owner): the owners of a family rose, or a new key of the settings or a new name of the environment came (a new mode): a path that is chosen, not a rule that is added.
    ``review`` (the owner reads these lines): a new module, a new decision-shaped function, or more places in a family with no new owner.
    ``clean``: no owner more, no mode more, no module or decider more. A branch that only removes is clean."""
    delta, now, was = out.get('surface_delta'), out['families'], out.get('base_families')
    if delta is None or was is None:
        raise ValueError('a verdict needs a base: report(sites, tree, base)')
    layer, review = [], []
    for key, _ in FAMILIES:
        if now[key]['owners'] > was[key]['owners']:
            layer.append(f"owners of {key}: {was[key]['owners']} -> {now[key]['owners']}")
        elif now[key]['places'] > was[key]['places']:
            review.append(f"places of {key}: {was[key]['places']} -> {now[key]['places']}")
    layer += [f'new key of the settings: {name}' for name in delta['new_flags']] + [f'new name of the environment: {name}' for name in delta['new_env']]
    review += [f'new module: {name}' for name in delta['new_modules']] + [f'new decision-shaped function: {name}' for name in delta['new_deciders']]
    return {'verdict': 'layer' if layer else 'review' if review else 'clean', 'reasons': layer + review}


def _spot(row):
    return f"{row['family']} | {row.get('owner', '')} | {row['role']} | {row['where'] or row['file']}:{row['line'] or '-'} | {row['func']} | {row['decides']}"


def render(out, listing=False, family=None, judges=False):
    """The report as markdown: the table of the families, the judges that went, then the places that went, changed, moved and came."""
    old = out.get('base_families')
    text = [f"Перепись хозяев: {out['ref'] or 'рабочее дерево'}" + (f" против {out['base']}" if old else ''), '',
            '| семейство | хозяев' + (' | было | разница' if old else '') + ' | должно быть | мест | файлов | главный | дубли | перебивки | шлюзы | тени | мёртвые | флаги | не разнесено | ушло мест | изменено | переехало |',
            '|---|---:' + ('|---:|---:' if old else '') + '|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for key, _ in FAMILIES:
        row = out['families'][key]
        before = f" | {old[key]['owners']} | {row['owners'] - old[key]['owners']:+d}" if old else ''
        text.append(f"| {row['title']} | {row['owners']}{before} | 1 | {row['places']} | {row['files']} | " + ' | '.join(str(row[name]) for name in DECIDING + OTHER + ('gone', 'changed', 'moved')) + ' |')
    text += ['', f"Всего хозяев: {out['owners']}" + (f" (было {out['base_owners']}, разница {out['owners'] - out['base_owners']:+d})" if old else '') + '. Единый движок: 9 (по одному на семейство).']
    if old:
        was = {(judge['family'], judge['owner']): judge for judge in out['base_judges']}
        left = [judge for judge in out['judges'] if not judge['places'] and was.get((judge['family'], judge['owner']), {}).get('places')]
        thin = [judge for judge in out['judges'] if judge['places'] and judge['places'] < was.get((judge['family'], judge['owner']), {}).get('places', 0)]
        new = [judge for judge in out['judges'] if judge['places'] and not was.get((judge['family'], judge['owner']), {}).get('places')]
        for title, found in (('Хозяева, которых не стало', left), ('Хозяева, у которых стало меньше мест', thin), ('Хозяева из списка, которых не было в базе', new)):
            if found:
                text += ['', f'{title}: {len(found)}'] + [f"- {judge['family']} | {judge['owner']} | {judge['role']} | мест {judge['places']} (было {was.get((judge['family'], judge['owner']), {}).get('places', 0)}) | {judge['title']}" for judge in found]
    for status, title in (('gone', 'Ушли'), ('changed', 'Изменены (перечитать)'), ('moved', 'Переехали'), ('came', 'Появились (места из списка, которых не было в базе)')):
        if out.get(status):
            text += ['', f'{title}: {len(out[status])}'] + ['- ' + _spot(row) for row in out[status]]
    shape, delta = out['surface'], out.get('surface_delta')
    text += ['', 'Поверхность: ' + ', '.join(f'{title} {shape[key]}' for key, title in (('modules', 'модулей'), ('funcs', 'функций и тел'), ('deciders', 'решателей по имени'), ('flags', 'ключей настроек'),
                                                                                    ('env', 'имён окружения'), ('timers', 'констант времени')))]
    for key, title in (('new_modules', 'Новые модули'), ('gone_modules', 'Удалённые модули'), ('new_deciders', 'Новые решатели по имени'), ('gone_deciders', 'Удалённые решатели по имени'),
                       ('new_flags', 'Новые ключи настроек'), ('gone_flags', 'Удалённые ключи настроек'), ('new_env', 'Новые имена окружения'), ('gone_env', 'Удалённые имена окружения'),
                       ('new_timers', 'Новые константы времени'), ('gone_timers', 'Удалённые константы времени'), ('moved_timers', 'Переехавшие константы времени'),
                       ('new_classes', 'Новые классы'), ('gone_classes', 'Удалённые классы'),
                       ('moved_funcs', 'Переехавшие функции'), ('changed_funcs', 'Функции с изменённым кодом'), ('new_funcs', 'Новые функции'), ('gone_funcs', 'Удалённые функции')):
        if delta and delta[key]:
            text += ['', f'{title}: {len(delta[key])}'] + ['- ' + name for name in delta[key]]
    if judges:
        text += ['', 'Хозяева:', '', '| семейство | хозяин | роль | мест | ушло | файлы | что это |', '|---|---|---|---:|---:|---|---|']
        text += [f"| {judge['family']} | {judge['owner']} | {judge['role']} | {judge['places']} | {judge['gone']} | {', '.join(name.rsplit('/', 1)[-1] for name in judge['files'])} | {judge['title']} |"
                 for judge in out['judges'] if family in (None, judge['family'])]
    if listing:
        text += ['', 'Места:'] + [f"- {row['status']} | " + _spot(row) for row in out['rows'] if family in (None, row['family'])]
    return '\n'.join(text) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--repo', default=str(ROOT))
    parser.add_argument('--sites', default=None)
    parser.add_argument('--owners', default=None, help='the names of the owners (JSON); tools/owner_census_owners.json when not given')
    parser.add_argument('--ref', default=None, help='a git ref; the working tree of --repo when not given')
    parser.add_argument('--base', default=None, help='a git ref to compare with')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--list', action='store_true', help='every place with its status')
    parser.add_argument('--judges', action='store_true', help='every owner with what is left of it')
    parser.add_argument('--family', default=None, choices=[key for key, _ in FAMILIES])
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--verdict', action='store_true', help='with --base: one line, clean / review / layer, and why (exit 1 on layer)')
    args = parser.parse_args(argv)
    sites = load_sites(args.sites or SITES_PATH)
    tree = Tree.from_ref(args.ref, repo=args.repo) if args.ref else Tree.from_dir(args.repo)
    names = Path(args.owners) if args.owners else OWNERS_PATH
    out = report(sites, tree, Tree.from_ref(args.base, repo=args.repo) if args.base else None, json.loads(names.read_text(encoding='utf-8')) if names.exists() else None)
    if args.verdict:
        found = verdict(out)
        sys.stdout.write('%s: %s\n' % (found['verdict'], '; '.join(found['reasons']) or 'nothing added'))
        return 1 if found['verdict'] == 'layer' else 0
    sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=1) + '\n' if args.json else render(out, args.list, args.family, args.judges))
    return 1 if args.check and any(row['status'] != 'present' for row in out['rows']) else 0


if __name__ == '__main__':
    sys.exit(main())

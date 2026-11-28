"""U169: cleaning of worktrees and branches only after a check, no model. python -m tools.worktree_clean --repo R --base B [--apply]
For every branch that has a worktree (the main worktree and the base branch itself are not listed) one line, sorted by branch name:
  <branch>: слита | не слита в <base>; чистая | грязная; результат сохранён | не сохранён; <path> [; удалена | остаётся (why)]
merged = the branch tip is an ancestor of base (its commits live in base); dirty = `git status --porcelain` is not empty (untracked files count) or
cannot be read; locked and detached worktrees are never touched. Without --apply nothing changes. With --apply a branch that is merged AND clean is
removed (`git worktree remove`, no --force, then `git branch -D` because merged was proved against base, not against HEAD); an unmerged branch and a
dirty tree stay. Exit code 0; 1 if git refused to remove a branch it was asked to remove; 2 if the repository or base cannot be read."""
import argparse
import subprocess
import sys


def git(repo, *args):
    done = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    return done.returncode, done.stdout, done.stderr.strip()


def worktrees(repo):
    """Linked worktrees as dicts path/branch/locked (the first entry of `git worktree list` is the main one: skipped)."""
    code, out, err = git(repo, 'worktree', 'list', '--porcelain', '-z')
    if code:
        raise SystemExit('git worktree list failed: ' + err[-300:])
    blocks, current = [], {}
    for field in out.split('\0'):
        if not field:
            if current:
                blocks.append(current)
            current = {}
            continue
        key, _, value = field.partition(' ')
        current[key] = value
    if current:
        blocks.append(current)
    rows = []
    for block in blocks[1:]:
        branch = block.get('branch', '')
        rows.append({'path': block.get('worktree', ''), 'branch': branch[len('refs/heads/'):] if branch.startswith('refs/heads/') else '', 'locked': 'locked' in block})
    return rows


def inspect(repo, base, row):
    code, _, _ = git(repo, 'merge-base', '--is-ancestor', 'refs/heads/' + row['branch'], base)
    merged = code == 0
    code, out, _ = git(row['path'], 'status', '--porcelain')
    dirty = code != 0 or bool(out.strip())
    return merged, dirty


def main(argv=None):
    parser = argparse.ArgumentParser(prog='tools.worktree_clean', description=__doc__.splitlines()[0])
    parser.add_argument('--repo', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    if git(args.repo, 'rev-parse', '--verify', '--quiet', args.base + '^{commit}')[0]:
        print('base %r not found in %s' % (args.base, args.repo), file=sys.stderr)
        return 2
    rows = [row for row in worktrees(args.repo) if row['branch'] and row['branch'] != args.base]
    failed = False
    for row in sorted(rows, key=lambda r: r['branch']):
        merged, dirty = inspect(args.repo, args.base, row)
        line = '%s: %s, %s, %s; %s' % (row['branch'], ('слита в ' + args.base) if merged else ('не слита в ' + args.base),
                                       'грязная' if dirty else 'чистая', 'результат сохранён' if merged else 'результат не сохранён', row['path'])
        if args.apply:
            if not (merged and not dirty):
                line += '; остаётся (%s)' % ('не слита' if not merged else 'грязное дерево')
            elif row['locked']:
                line += '; остаётся (заблокирована)'
            else:
                code, _, err = git(args.repo, 'worktree', 'remove', row['path'])
                if not code:
                    code, _, err = git(args.repo, 'branch', '-D', row['branch'])
                failed = failed or bool(code)
                line += '; ' + ('не удалена: ' + err[-200:] if code else 'удалена')
        print(line)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

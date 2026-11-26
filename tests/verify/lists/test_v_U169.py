"""V U169 (BACKLOG: «Чистка worktree и веток только после проверки: слита ли в base, грязное ли дерево, сохранён ли результат»): the cleaning script ``tools/worktree_clean.py`` (run as ``python -m tools.worktree_clean
--repo R --base B [--apply]``) prints, per branch with a worktree, whether it is merged («слита» / «не слита») and whether its tree is dirty («грязная» / «чистая»), and with ``--apply`` removes only the branches that are
merged AND clean; an unmerged branch and a dirty tree stay. Checked on a temporary repository with the real git; no part of the script is mocked."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def git(cwd, *args):
    return subprocess.run(['git', '-c', 'user.email=t@t', '-c', 'user.name=t', *args], cwd=cwd, check=True, capture_output=True, text=True).stdout


def make_repo(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-b', 'main')
    (repo / 'a.txt').write_text('a')
    git(repo, 'add', '.')
    git(repo, 'commit', '-m', 'base')
    trees = {}
    for name in ('merged-clean', 'merged-dirty', 'unmerged-clean'):
        tree = tmp_path / name
        git(repo, 'worktree', 'add', '-b', name, str(tree))
        trees[name] = tree
    (trees['unmerged-clean'] / 'b.txt').write_text('b')
    git(trees['unmerged-clean'], 'add', '.')
    git(trees['unmerged-clean'], 'commit', '-m', 'work not in main')
    (trees['merged-dirty'] / 'a.txt').write_text('edited, not committed')
    return repo, trees


def run(repo, *extra):
    return subprocess.run([sys.executable, '-m', 'tools.worktree_clean', '--repo', str(repo), '--base', 'main', *extra], cwd=ROOT, capture_output=True, text=True)


def test_the_script_prints_merged_and_dirty_for_every_branch(tmp_path):
    repo, trees = make_repo(tmp_path)
    done = run(repo)
    assert done.returncode == 0, done.stderr[-400:]
    lines = {name: next((line for line in done.stdout.splitlines() if name in line), '') for name in trees}
    assert 'слита' in lines['merged-clean'] and 'не слита' not in lines['merged-clean'] and 'чистая' in lines['merged-clean'], lines
    assert 'слита' in lines['merged-dirty'] and 'грязная' in lines['merged-dirty'], lines
    assert 'не слита' in lines['unmerged-clean'], lines


def test_apply_removes_only_the_merged_and_clean_branch(tmp_path):
    repo, trees = make_repo(tmp_path)
    done = run(repo, '--apply')
    assert done.returncode == 0, done.stderr[-400:]
    assert not trees['merged-clean'].exists()
    assert trees['merged-dirty'].exists() and (trees['merged-dirty'] / 'a.txt').read_text() == 'edited, not committed'
    assert trees['unmerged-clean'].exists()
    branches = git(repo, 'branch', '--format=%(refname:short)').split()
    assert 'merged-clean' not in branches and 'merged-dirty' in branches and 'unmerged-clean' in branches, branches

"""V7-AUDIT: ``tools/owner_census`` counts the places of the code that MAKE a decision, family by family, on any tree or git ref.

The toy package proves the mechanics (present / changed / moved / gone, the count, the surface delta, a git ref read without a checkout);
the last tests hold the real list ``tools/owner_census_sites.ndjson`` to the code it was written from (``BASE``)."""
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import owner_census as C      # noqa: E402

JUDGE = textwrap.dedent('''
    SILENCE_SECONDS = 4
    MODE = 'shadow'

    def is_question(text):
        if text.endswith('?'):
            return True
        return text.startswith('как')

    class Controller:
        HOLD_MS = 300

        def _accept(self, text):
            verdict = is_question(text)
            if verdict and len(text) < 3:
                verdict = False
            return verdict

        def _shadow(self, text):
            return 'q' if '?' in text else 's'
''')
SETTINGS = textwrap.dedent('''
    import os
    DEFAULTS = {'ear_job': 'off', 'memory': 'shadow'}

    def resolve(raw):
        if os.environ.get('ECHO_GAME') == '1':
            raw['game'] = 'on'
        return raw
''')
SITES = [
    {'family': 'kind', 'owner': 'classifier', 'role': 'owner', 'file': 'echo_sync/judge.py', 'func': 'is_question', 'anchor': "if text.endswith('?'):", 'decides': 'вопрос или рассказ'},
    {'family': 'kind', 'owner': 'cm-accept', 'role': 'override', 'file': 'echo_sync/judge.py', 'func': 'Controller._accept', 'anchor': 'if verdict and len(text) < 3:', 'decides': 'короткое не вопрос'},
    {'family': 'kind', 'owner': 'cm-shadow', 'role': 'shadow', 'file': 'echo_sync/judge.py', 'func': 'Controller._shadow', 'anchor': "return 'q' if '?' in text else 's'", 'decides': 'тень'},
    {'family': 'timers', 'owner': 'silence', 'role': 'owner', 'file': 'echo_sync/judge.py', 'func': '<module>', 'anchor': 'SILENCE_SECONDS = 4', 'decides': 'сколько тишины'},
    {'family': 'timers', 'owner': 'hold', 'role': 'dup', 'file': 'echo_sync/judge.py', 'func': 'Controller', 'anchor': 'HOLD_MS = 300', 'decides': 'удержание'},
    {'family': 'modes', 'owner': 'settings', 'role': 'flag', 'file': 'echo_sync/settings.py', 'func': 'resolve', 'anchor': "if os.environ.get('ECHO_GAME') == '1':", 'decides': 'игра'},
]


def package(tmp_path, judge=JUDGE, settings=SETTINGS, extra=None):
    folder = tmp_path / 'echo_sync'
    folder.mkdir(parents=True, exist_ok=True)
    for name, text in {'judge.py': judge, 'settings.py': settings, **(extra or {})}.items():
        if text is None:
            (folder / name).unlink(missing_ok=True)
        else:
            (folder / name).write_text(text, encoding='utf-8')
    return C.Tree.from_dir(tmp_path)


def by_func(rows):
    return {row['func']: row for row in rows}


def test_every_site_of_the_toy_is_found_with_its_line(tmp_path):
    rows = by_func(C.resolve(SITES, package(tmp_path)))
    assert {row['status'] for row in rows.values()} == {'present'}
    lines = JUDGE.split('\n')
    assert lines[rows['is_question']['line'] - 1].strip() == "if text.endswith('?'):"
    assert lines[rows['<module>']['line'] - 1] == 'SILENCE_SECONDS = 4'
    assert lines[rows['Controller']['line'] - 1].strip() == 'HOLD_MS = 300'


def test_a_shifted_line_is_still_present_and_a_rewritten_one_is_changed(tmp_path):
    shifted = '# a new comment\n\n' + JUDGE.replace('if verdict and len(text) < 3:', 'if verdict and len(text) < 5:').replace('SILENCE_SECONDS = 4', 'SILENCE_SECONDS = 6')
    rows = by_func(C.resolve(SITES, package(tmp_path, judge=shifted)))
    assert rows['is_question']['status'] == 'present' and shifted.split('\n')[rows['is_question']['line'] - 1].strip() == "if text.endswith('?'):"
    assert rows['Controller._accept']['status'] == 'changed'      # the function is there, its deciding line was rewritten: still a place, to be read again
    assert rows['<module>']['status'] == 'changed'                # the constant is there with another value
    assert rows['Controller._shadow']['status'] == 'present'


def test_a_moved_function_is_moved_and_a_deleted_one_is_gone(tmp_path):
    cut = JUDGE[:JUDGE.index('    def _shadow')]
    moved = 'class Controller:\n    def _shadow(self, text):\n        return \'q\' if \'?\' in text else \'s\'\n'
    rows = by_func(C.resolve(SITES, package(tmp_path, judge=cut, extra={'cm_ear.py': moved})))
    assert rows['Controller._shadow']['status'] == 'moved' and rows['Controller._shadow']['where'] == 'echo_sync/cm_ear.py'
    rows = by_func(C.resolve(SITES, package(tmp_path, judge=cut, extra={'cm_ear.py': None})))
    assert rows['Controller._shadow']['status'] == 'gone'
    gone = by_func(C.resolve(SITES, package(tmp_path, judge='X = 1\n')))
    assert {gone[name]['status'] for name in ('is_question', 'Controller._accept', '<module>', 'Controller')} == {'gone'}


def test_a_deleted_dunder_is_gone_and_not_moved_to_another_class_of_the_same_dunder(tmp_path):
    old = JUDGE + "\n\nclass WithReserve:\n    def __call__(self, question):\n        return question or None\n"
    new = JUDGE + "\n\nclass Roads:\n    def __call__(self, question):\n        return question or None\n\n    def one(self, question):\n        return question\n"
    site = {'family': 'route', 'owner': 'reserve', 'role': 'shadow', 'file': 'echo_sync/judge.py', 'func': 'WithReserve.__call__', 'anchor': 'def __call__(self, question):', 'decides': 'кого спрашивать'}
    before, after = package(tmp_path / 'a', judge=old), package(tmp_path / 'b', judge=new)
    assert C.resolve([site], before)[0]['status'] == 'present'
    assert C.resolve([site], after)[0]['status'] == 'gone'       # ``Roads.__call__`` is another judge: the name of a dunder says nothing
    delta = C.surface_delta(C.surface(before), C.surface(after))
    assert delta['new_classes'] == ['echo_sync/judge.py:Roads'] and delta['gone_classes'] == ['echo_sync/judge.py:WithReserve']
    assert 'echo_sync/judge.py:Roads.one' in delta['new_funcs'] and 'echo_sync/judge.py:WithReserve.__call__' in delta['gone_funcs'] and delta['moved_funcs'] == []


def test_a_place_a_branch_brought_into_an_old_function_is_not_there_before_the_branch(tmp_path):
    grown = JUDGE.replace("    return text.startswith('как')\n", "    if text.startswith('а если'):\n        return False\n    return text.startswith('как')\n")
    site = {'family': 'kind', 'owner': 'v7-rule', 'role': 'shadow', 'file': 'echo_sync/judge.py', 'func': 'is_question', 'anchor': "if text.startswith('а если'):", 'decides': 'новое правило ветки', 'since': 'claude/x'}
    before, after = package(tmp_path / 'a'), package(tmp_path / 'b', judge=grown)
    assert C.resolve([site], after)[0]['status'] == 'present'
    assert C.resolve([site], before)[0]['status'] == 'gone'        # the function is old, the line is of the branch: in the base the place is not there
    assert C.census(C.resolve(SITES + [site], before))['kind']['shadow'] == 1 and C.census(C.resolve(SITES + [site], after))['kind']['shadow'] == 2
    assert C.census(C.resolve(SITES + [site], before))['kind']['gone'] == 0        # not there yet is not gone
    assert C.report(SITES + [site], before)['gone'] == [] and C.report(SITES + [site], after, before)['came'][0]['owner'] == 'v7-rule'


def test_a_place_a_branch_brought_is_not_found_in_an_older_function_of_the_same_short_name(tmp_path):
    old = JUDGE + "\n\ndef _rest(now):\n    until = now + 30\n    return until\n"
    new = JUDGE + "\n\nclass Roads:\n    def _rest(self, now):\n        until = now + 30\n        return until\n"
    site = {'family': 'timers', 'owner': 'roads', 'role': 'shadow', 'file': 'echo_sync/judge.py', 'func': 'Roads._rest', 'anchor': 'until = now + 30', 'decides': 'отдых дороги', 'since': 'claude/x'}
    assert C.resolve([site], package(tmp_path / 'a', judge=old))[0]['status'] == 'gone'       # the line is old, the judge is not there yet
    assert C.resolve([site], package(tmp_path / 'b', judge=new))[0]['status'] == 'present'
    split = package(tmp_path / 'c', extra={'cm_roads.py': "class Roads:\n    def _rest(self, now):\n        until = now + 30\n        return until\n"})
    found = C.resolve([site], split)[0]
    assert found['status'] == 'moved' and found['where'] == 'echo_sync/cm_roads.py'             # the same judge in another file is a move


def test_the_count_an_owner_is_a_judge_and_its_rules_are_its_places(tmp_path):
    rule = {'family': 'kind', 'owner': 'classifier', 'role': 'owner', 'file': 'echo_sync/judge.py', 'func': 'starts_like_question', 'anchor': "return text.startswith('как')", 'decides': 'второе правило того же судьи'}
    grown = JUDGE + "\ndef starts_like_question(text):\n    return text.startswith('как')\n"
    table = C.census(C.resolve(SITES + [rule], package(tmp_path, judge=grown)))
    assert set(table) == {key for key, _ in C.FAMILIES}
    assert table['kind']['owners'] == 2 and table['kind']['places'] == 3 and table['kind']['files'] == 1      # two judges whose verdict acts: the classifier (two rules) and the override
    assert table['kind']['owner'] == 1 and table['kind']['override'] == 1 and table['kind']['shadow'] == 1 and table['kind']['dup'] == 0
    assert table['timers']['owners'] == 2 and table['timers']['dup'] == 1
    assert table['modes']['owners'] == 0 and table['modes']['flag'] == 1
    assert table['answer']['owners'] == 0 and table['answer']['places'] == 0
    table = C.census(C.resolve(SITES + [rule], package(tmp_path, judge=grown.replace("    return text.startswith('как')\n", '    return False\n'))))
    assert table['kind']['owners'] == 2 and table['kind']['places'] == 3 and table['kind']['changed'] == 1 and table['kind']['gone'] == 0      # rewritten in place: still places, to be read again
    table = C.census(C.resolve(SITES + [rule], package(tmp_path)))
    assert table['kind']['owners'] == 2 and table['kind']['places'] == 2 and table['kind']['gone'] == 1 and table['kind']['gone_owners'] == 0      # a rule went, the judge stands
    cut = JUDGE[:JUDGE.index('class Controller')]
    table = C.census(C.resolve(SITES + [rule], package(tmp_path, judge=cut)))
    assert table['kind']['owners'] == 1 and table['kind']['shadow'] == 0 and table['kind']['gone'] == 3 and table['kind']['gone_owners'] == 2      # the override and the shadow went whole
    assert table['timers']['owners'] == 1 and table['timers']['gone'] == 1


def test_the_surface_delta_names_what_a_branch_brought(tmp_path):
    base = C.surface(package(tmp_path / 'a'))
    grown = JUDGE + "\nNEW_WAIT_S = 2\n\ndef should_answer_now(text):\n    return bool(text)\n\ndef helper(x):\n    return x\n"
    head = C.surface(package(tmp_path / 'b', judge=grown, settings=SETTINGS.replace("'memory': 'shadow'", "'memory': 'shadow', 'v7_gate': 'off'").replace('ECHO_GAME', 'ECHO_V7'),
                             extra={'v7_layer.py': 'def route_question(q):\n    return q\n'}))
    delta = C.surface_delta(base, head)
    assert delta['new_modules'] == ['echo_sync/v7_layer.py'] and delta['gone_modules'] == []
    assert delta['new_flags'] == ['v7_gate'] and delta['new_env'] == ['ECHO_V7'] and delta['gone_env'] == ['ECHO_GAME']
    assert delta['new_timers'] == ['echo_sync/judge.py:NEW_WAIT_S']
    assert delta['new_deciders'] == ['echo_sync/judge.py:should_answer_now', 'echo_sync/v7_layer.py:route_question']    # ``helper`` is not decision-shaped
    assert 'echo_sync/judge.py:helper' in delta['new_funcs']
    assert delta['changed_funcs'] == ['echo_sync/judge.py:<module>', 'echo_sync/settings.py:<module>', 'echo_sync/settings.py:resolve']      # an old function with new code is where a new inline decision can hide
    same = C.surface_delta(base, base)
    assert not any(same.values())


def test_a_function_that_only_changed_its_file_is_a_move_not_a_new_decider(tmp_path):
    base = C.surface(package(tmp_path / 'a'))
    cut = JUDGE.replace("def is_question(text):\n    if text.endswith('?'):\n        return True\n    return text.startswith('как')\n", '')
    assert 'def is_question' not in cut
    head = C.surface(package(tmp_path / 'b', judge=cut, extra={'cm_judge.py': "def is_question(text):\n    return text.endswith('?')\n"}))
    delta = C.surface_delta(base, head)
    assert delta['moved_funcs'] == ['is_question: echo_sync/judge.py -> echo_sync/cm_judge.py']
    assert delta['new_deciders'] == [] and delta['gone_deciders'] == []
    assert delta['changed_funcs'] == ['echo_sync/cm_judge.py:is_question']      # moved AND rewritten: not a pure move


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def test_any_git_ref_is_read_without_a_checkout(tmp_path):
    package(tmp_path)
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'add', '-A')
    git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'one')
    first = git(tmp_path, 'rev-parse', 'HEAD')
    package(tmp_path, judge='X = 1\n')
    git(tmp_path, 'add', '-A')
    git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'two')
    old = C.census(C.resolve(SITES, C.Tree.from_ref(first, repo=tmp_path)))
    new = C.census(C.resolve(SITES, C.Tree.from_ref('HEAD', repo=tmp_path)))
    assert old['kind']['owners'] == 2 and new['kind']['owners'] == 0 and new['kind']['gone'] == 3
    assert (tmp_path / 'echo_sync' / 'judge.py').read_text(encoding='utf-8') == 'X = 1\n'      # the working tree was not touched
    sites = tmp_path / 'sites.jsonl'
    sites.write_text('\n'.join(json.dumps(site, ensure_ascii=False) for site in SITES) + '\n', encoding='utf-8')
    assert C.load_sites(sites) == SITES
    assert C.main(['--repo', str(tmp_path), '--sites', str(sites), '--ref', 'HEAD', '--base', first, '--json']) == 0


def test_the_report_of_a_branch_says_what_went_and_what_came(tmp_path, capsys):
    package(tmp_path)
    git(tmp_path, 'init', '-q')
    git(tmp_path, 'add', '-A')
    git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'one')
    first = git(tmp_path, 'rev-parse', 'HEAD')
    package(tmp_path, judge=JUDGE[:JUDGE.index('    def _shadow')] + '\ndef judge_again(text):\n    return not text\n')
    git(tmp_path, 'add', '-A')
    git(tmp_path, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'two')
    sites = tmp_path / 'sites.jsonl'
    sites.write_text('\n'.join(json.dumps(site, ensure_ascii=False) for site in SITES) + '\n', encoding='utf-8')
    assert C.main(['--repo', str(tmp_path), '--sites', str(sites), '--ref', 'HEAD', '--base', first, '--json']) == 0
    report = json.loads(capsys.readouterr().out)
    assert report['families']['kind']['owners'] == 2 and report['base_families']['kind']['shadow'] == 1 and report['families']['kind']['shadow'] == 0
    assert [row['func'] for row in report['gone']] == ['Controller._shadow']
    assert report['surface_delta']['new_deciders'] == ['echo_sync/judge.py:judge_again']
    assert C.main(['--repo', str(tmp_path), '--sites', str(sites), '--ref', 'HEAD', '--base', first]) == 0
    text = capsys.readouterr().out
    assert 'вид реплики' in text and 'judge_again' in text and 'Controller._shadow' in text


# --- the real list against the code it was written from ---

def real_tree():
    try:
        git(ROOT, 'cat-file', '-e', C.BASE + '^{commit}')
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip('the base commit is not in this clone')
    return C.Tree.from_ref(C.BASE, repo=ROOT)


def test_the_real_list_is_well_formed():
    sites = C.load_sites(C.SITES_PATH)
    assert len(sites) > 100
    families, roles = {key for key, _ in C.FAMILIES}, set(C.DECIDING) | set(C.OTHER)
    bad = [site for site in sites if site.get('family') not in families or site.get('role') not in roles or not site.get('file') or not site.get('func') or not site.get('anchor') or not site.get('decides')]
    assert bad == []
    keys = [(site['family'], site['file'], site['func'], site['anchor']) for site in sites]
    assert len(keys) == len(set(keys))                                # one place is written once per family
    assert all(site.get('owner') for site in sites)                    # every place belongs to a judge
    for family in families:                                            # one judge has one role, and a family has at most one main owner
        roles = {}
        for site in sites:
            if site['family'] == family and site['role'] != 'flag':
                roles.setdefault(site['owner'], set()).add(site['role'])
        assert [owner for owner, held in roles.items() if len(held) > 1] == []
        mains = {site['owner'] for site in sites if site['family'] == family and site['role'] == 'owner' and not site.get('since')}
        assert len(mains) <= 1                                         # in the base; a place a branch brought (``since``) is the state of that branch
    assert {site['family'] for site in sites} == families              # all nine families are counted


def test_every_place_of_the_real_list_stands_in_the_base_code():
    rows = C.resolve([site for site in C.load_sites(C.SITES_PATH) if not site.get('since')], real_tree())
    lost = [(row['file'], row['func'], row['anchor'], row['status']) for row in rows if row['status'] != 'present']
    assert lost == []                                                 # a place of the baseline that is not found at the base is a place that was never there


# --- P13: the census as a lock: a family may not grow, and the target is one owner a family ---

CAPS = json.loads((ROOT / 'tools' / 'owner_census_caps.json').read_text(encoding='utf-8'))


def now_counts():
    """The owners of every family in the working tree, by the real list (the tree is what the test runs on)."""
    out = C.report(C.load_sites(C.SITES_PATH), C.Tree.from_dir(ROOT))
    return {key: out['families'][key]['owners'] for key, _ in C.FAMILIES}


@pytest.mark.parametrize('family', [key for key, _ in C.FAMILIES])
def test_a_family_has_no_more_owners_than_its_ceiling(family):
    """The ratchet: ``tools/owner_census_caps.json`` holds the number of every family; a new owner of a family (a second path beside the first) fails here, and the number goes down only in the commit
    that deletes the owner. A family with no ceiling is a family the census does not hold."""
    assert family in CAPS['families'], family + ' has no ceiling'
    assert now_counts()[family] <= CAPS['families'][family], '%s: %d owners, the ceiling is %d (a new path beside the owner: merge it into the owner)' % (family, now_counts()[family], CAPS['families'][family])


def test_the_ceilings_are_the_nine_families_and_never_below_the_tree():
    assert set(CAPS['families']) == {key for key, _ in C.FAMILIES}
    counts = now_counts()
    assert all(counts[key] <= CAPS['families'][key] for key in counts)
    assert all(isinstance(value, int) and value >= 1 for value in CAPS['families'].values())
    assert CAPS['target'] == {'total': 15, 'per_family': 2, 'wanted': 9}


def test_the_target_is_one_owner_a_family_at_most_fifteen_in_all_and_no_family_above_two():
    """ARCH_ONE §1: «у каждого семейства решений ровно один хозяин». This is the target of the merge: it is red while a family has a second judge and names each family above the line; the ceilings above are
    what keeps it from growing meanwhile. Lower the ceiling of a family in ``owner_census_caps.json`` in the commit that deletes the owner."""
    counts = now_counts()
    target = CAPS['target']
    over = {key: count for key, count in counts.items() if count > target['per_family']}
    assert sum(counts.values()) <= target['total'] and over == {}, 'owners: %d (target %d, wanted %d: one a family); above %d: %s' % (sum(counts.values()), target['total'], target['wanted'], target['per_family'], over)


def _verdict_trees(tmp_path, head_settings=None, head_extra=None, head_judge=None):
    base = package(tmp_path / 'base')
    head = package(tmp_path / 'head', judge=head_judge or JUDGE, settings=head_settings or SETTINGS, extra=head_extra)
    return C.report(SITES, head, base)


def test_the_verdict_of_a_branch_that_only_removes_is_clean(tmp_path):
    out = _verdict_trees(tmp_path, head_judge=JUDGE.replace("    def _shadow(self, text):\n        return 'q' if '?' in text else 's'\n", ''))
    found = C.verdict(out)
    assert found['verdict'] == 'clean' and found['reasons'] == []


def test_a_new_key_of_the_settings_or_a_new_name_of_the_environment_is_a_layer(tmp_path):
    key = C.verdict(_verdict_trees(tmp_path / 'a', head_settings=SETTINGS.replace("'memory': 'shadow'", "'memory': 'shadow', 'ear_wide': 'on'")))
    env = C.verdict(_verdict_trees(tmp_path / 'b', head_settings=SETTINGS.replace("ECHO_GAME", "ECHO_NEW_MODE")))
    assert key['verdict'] == 'layer' and any('ear_wide' in reason for reason in key['reasons']), key
    assert env['verdict'] == 'layer' and any('ECHO_NEW_MODE' in reason for reason in env['reasons']), env


def test_a_new_module_with_a_decider_is_for_the_owner_to_read_not_a_layer(tmp_path):
    out = _verdict_trees(tmp_path, head_extra={'extra.py': 'def is_polite(text):\n    return text.startswith("пожалуйста")\n'})
    found = C.verdict(out)
    assert found['verdict'] == 'review' and any('echo_sync/extra.py' in reason for reason in found['reasons']), found


def test_more_owners_in_a_family_is_a_layer(tmp_path):
    sites = SITES + [{'family': 'kind', 'owner': 'cm-second', 'role': 'dup', 'file': 'echo_sync/judge.py', 'func': 'is_question', 'anchor': "return text.startswith('как')", 'decides': 'второй путь'}]
    base = package(tmp_path / 'base')
    head = package(tmp_path / 'head')
    out = C.report(sites, head, base)
    out['base_families'] = C.census(C.resolve(SITES, base))      # the base had the list without the second path: the branch brought it
    found = C.verdict(out)
    assert found['verdict'] == 'layer' and any('owners of kind' in reason for reason in found['reasons']), found


def test_the_verdict_needs_a_base(tmp_path):
    with pytest.raises(ValueError):
        C.verdict(C.report(SITES, package(tmp_path)))


def test_the_verdict_runs_from_the_command_line_on_two_refs(tmp_path, capsys):
    repo = tmp_path / 'repo'
    (repo / 'echo_sync').mkdir(parents=True)
    (repo / 'echo_sync' / 'judge.py').write_text(JUDGE, encoding='utf-8')
    (repo / 'echo_sync' / 'settings.py').write_text(SETTINGS, encoding='utf-8')
    git(repo, 'init', '-q')
    git(repo, 'add', '-A')
    git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qm', 'base')
    base = git(repo, 'rev-parse', 'HEAD')
    git(repo, 'checkout', '-qb', 'mode')
    (repo / 'echo_sync' / 'settings.py').write_text(SETTINGS.replace("'memory': 'shadow'", "'memory': 'shadow', 'ear_wide': 'on'"), encoding='utf-8')
    git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qam', 'a mode')
    sites = tmp_path / 'sites.ndjson'
    sites.write_text('\n'.join(json.dumps(site, ensure_ascii=False) for site in SITES), encoding='utf-8')
    code = C.main(['--repo', str(repo), '--sites', str(sites), '--ref', 'mode', '--base', base, '--verdict'])
    assert code == 1 and capsys.readouterr().out.startswith('layer: ')

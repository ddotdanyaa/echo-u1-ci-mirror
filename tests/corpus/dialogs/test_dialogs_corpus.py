"""U137 / E21 / E21.1 / U08: the dialog corpus loads, is frozen, covers >= 4 areas of 5 with a reference in each, and goes through the matrix's judge and denominator."""
import copy
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import dialogs_corpus as dc                  # noqa: E402
from tools.replay import matrix              # noqa: E402


def test_the_corpus_loads_and_covers_the_areas():
    dialogs = dc.load()
    cov = dc.coverage(dialogs)
    assert cov['areas_present'] >= dc.MIN_AREAS and set(cov['lengths']) == {'short', 'long'}
    for area, row in cov['areas'].items():
        assert row['dialogs'] and row['judged'], area          # E21.1: none of the five is empty
    assert dc.status(dialogs)['e21_1_ok']


def test_the_state_against_u137_is_stated_not_hidden():
    st = dc.status(dc.load())
    assert st['u137_ok'] is False and st['external_sources'] == 0       # authored only: the rule is not met and says so; import external dialogs to flip it


def test_every_dialog_has_a_source_with_a_licence():
    for dialog in dc.load():
        assert dialog['source']['license'] in dc.ALLOWED_LICENSES
    bad = copy.deepcopy(dc.load('dev')[0])
    bad['source']['license'] = 'all-rights-reserved'
    with pytest.raises(dc.CorpusError):
        dc.check(bad)


def test_the_holdout_is_frozen(tmp_path):
    folder = tmp_path / 'c'
    shutil.copytree(dc.HERE, folder, ignore=shutil.ignore_patterns('__pycache__', '*.py', '*.md'))
    assert dc.load('holdout', folder)
    one = next((folder / 'holdout').glob('*.json'))
    data = json.loads(one.read_text(encoding='utf-8'))
    data['turns'][0]['expected'] = 'moved to fit the answer'
    one.write_bytes((json.dumps(data, ensure_ascii=False, indent=1) + '\n').encode('utf-8'))
    with pytest.raises(dc.CorpusError):
        dc.load('holdout', folder)
    one.unlink()
    with pytest.raises(dc.CorpusError):
        dc.load('holdout', folder)                # a removed file is a changed holdout too


def test_dev_and_holdout_do_not_share_questions():
    ask = lambda split: {t['user'].strip().lower() for d in dc.load(split) for t in d['turns']}
    assert not ask('dev') & ask('holdout')


def test_tangled_scenes_keep_requirements_and_mark_the_unclear():
    tangled = [d for d in dc.load('dev') if d['kind'] == 'tangled']
    assert len(tangled) >= 3 and all(d['requirements'] for d in tangled)
    assert any(d.get('unclear') for d in tangled)             # U08: the unclear is marked, not guessed


def test_the_matrix_takes_the_corpus_into_its_denominator_without_losing_a_question():
    dialogs = dc.load('dev')
    calls = matrix.dialog_calls('dev')
    asked = sum(len(d['turns']) for d in dialogs if d['kind'] == 'qa' and any(t['kind'] == 'question' for t in d['turns']))
    out = matrix.run(calls)
    assert out['rows'] and out['passport']['status'].startswith('PARTIAL')       # no controller runner here: not matrix evidence
    assert out['rows'][0]['asked'] == sum(1 for c in calls.values() for r in c['cloud'] if r[1] == 'user') and out['rows'][0]['asked'] >= asked


def test_the_matrix_judge_uses_the_reference_of_a_turn():
    ask = matrix.dialog_calls('dev')['everyday-units']['asks'][0]
    assert matrix.judge(ask, 'В килограмме тысяча граммов', 1.0) == 'correct'
    assert matrix.judge(ask, 'Не знаю, спросите потом', 1.0) == 'wrong'
    assert matrix.judge(ask, None, None) == 'missed'


def test_the_holdout_is_not_given_to_the_matrix_unfrozen():
    assert matrix.dialog_calls('holdout')                      # verified against the manifest on the way
    with pytest.raises(dc.CorpusError):
        matrix.dialog_calls('nothing')

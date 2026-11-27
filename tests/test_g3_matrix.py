"""G3: the decision matrix of the turn arbiter (tests/helpers_g3_matrix.py): STATE x UTTERANCE x CLOUD through the real controller, on a fake clock.

The expected action is the table of the brief, Part 2. A cell whose outcome the available signals cannot decide carries its tag in ``expected``
(``undecidable``): it may cost a whisper, never the position. Everything else must be clean, per family, on the dev scenes and on the holdout scene.

Every test runs the cells of one family (scene set x family: 240 dev or 60 holdout cells), cached per process. Was: the first test of a worker ran
the whole matrix (5400 cells, dev and holdout) and passed the 300 s limit of one test in CI (suite 1279842 part 3, suite 446237b part 0);
the cells are independent (each its own engine, in-memory db and call), so a family alone gives the same rows."""
import pytest

import helpers_g3_matrix as matrix

RESULTS = {}
WHICH = ('dev', 'holdout')


def results(which, family):
    if (which, family) not in RESULTS:
        RESULTS[which, family] = matrix.run(which, families=(family,))
    return RESULTS[which, family]


@pytest.mark.parametrize('which', WHICH)
@pytest.mark.parametrize('family', matrix.FAMILIES)
def test_print_the_metrics(capsys, which, family):
    with capsys.disabled():
        print(f'\n--- {which} / {family} ---\n' + matrix.table(results(which, family)))


def unclean(which, family):
    found = {}
    for cell, _, want, defects in results(which, family):
        left = matrix.blocking(defects, want)
        if left:
            found['/'.join((cell.state, cell.cloud, cell.scene.name))] = left
    return found


# w3-integ: named defects, strict: each must still show (else it was fixed: drop it here). cut/chitchat/liquid: the cloud's «Отлично, спасибо за вопрос!» is glued to the answer cut on «не»
# («Показатель ниже единицы не Отлично, спасибо за вопрос!»); the scene's old first portion «… от 1,5» kept the next cue inside the first sentence and hid it (cloud_context/reports/w3-integ.md).
KNOWN = {('dev', 'paraphrase'): {'cut/chitchat/liquid': {'false_int': 1}}}


@pytest.mark.parametrize('family', matrix.FAMILIES)
def test_dev(family):
    found, known = unclean('dev', family), KNOWN.get(('dev', family), {})
    assert {cell: dict(found.get(cell) or {}) for cell in known} == known, 'a named defect is gone or changed: update KNOWN'
    assert not {cell: left for cell, left in found.items() if cell not in known}


@pytest.mark.parametrize('family', matrix.FAMILIES)
def test_holdout(family):
    assert not unclean('holdout', family)


# The bound of the named lookups was 59 on the whole dev matrix and 0 on the holdout. Each family now holds its own share, the measured count
# (the sum is pinned below to stay within 59): a family not named here may run none.
LOOKUPS = {('dev', 'clear'): 25, ('dev', 'chatter'): 34}       # measured on 1279842: 25 + 34 = 59, the old bound exactly
LOOKUP_FAMILIES = ('clear', 'chatter', 'by_question', 'by_statement', 'followup')


def test_the_shares_of_the_named_lookups_keep_the_old_bound():
    assert sum(n for (which, _), n in LOOKUPS.items() if which == 'dev') <= 59
    assert not [key for key, n in LOOKUPS.items() if key[0] == 'holdout' and n]
    assert {family for _, family in LOOKUPS} <= set(LOOKUP_FAMILIES)


@pytest.mark.parametrize('which', WHICH)
@pytest.mark.parametrize('family', matrix.FAMILIES)
def test_the_named_lookups_do_not_grow(which, family):
    """A question-looking line runs its public lookup before the cloud's evidence (S6 pins the lookup at the final): nothing more than that lookup, ever."""
    found = [cell for cell, _, _, defects in results(which, family) if 'lookup_first' in defects]
    assert len(found) <= LOOKUPS.get((which, family), 0), (which, family, len(found))


@pytest.mark.parametrize('which', WHICH)
@pytest.mark.parametrize('family', matrix.FAMILIES)
def test_no_position_is_ever_lost_and_nothing_is_confirmed_twice(which, family):
    assert not [cell for cell, _, _, defects in results(which, family) if defects.keys() & {'lost_pos', 'false_ack', 'double_adv', 'missed_ack', 'missed_q'}]


@pytest.mark.parametrize('scene', matrix.SCENES, ids=lambda scene: scene.name)
def test_the_wordings_are_what_they_claim(scene):
    """The scene's texts: a repeat is said of the portion that really waits, in the states with a plan."""
    assert len(scene.para) == len(scene.wrong) == len(scene.words) == 2
    assert scene.a.startswith(scene.cut)


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

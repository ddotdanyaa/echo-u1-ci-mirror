"""c22-speed: the waits on the way to the first cue that protect nothing, each behind a flag that is off by default. The job on the ear's text (``ear_job``):
``turn_mark`` - a number closed by «?»/«!» at the end of the cloud's open turn is the cloud's (G32 already does it for ``two_witnesses``, ``_turn_reads`` waited
for the final); ``cloud_form`` - the ear hears no «?», so «Нужно не X, а Y эту жидкость …» is a statement to it (gate_text ``statement``): the cloud's open turn,
which has the form, is the witness of it. Numbers, «не» and the roles around them are read as before (``wide_refusal``).

Times are the stand's (``speed.PHONE``: final 3.3 s, the model's first text 1.9 s, the phone's numbers of BACKLOG E93), not a laptop's nor a phone's.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from echo_sync.settings import resolve                                          # noqa: E402
from tools.replay import first_clock as F                                       # noqa: E402
from tools.replay import speed as G                                             # noqa: E402
from tools.replay import stand as A                                             # noqa: E402

EAR_JOB = {**F.candidate(), 'ear_job': 'on'}
ON = {'fast_text': 'on', 'local_ear': 'act', 'ear_release': 'on', 'prepare_wide': 'on', 'two_witnesses': 'on', 'ear_job': 'on'}


@pytest.mark.parametrize('key', ['turn_mark', 'cloud_form'])
def test_off_by_default_and_needs_ear_job(key):
    assert resolve({})[key] == 'off'
    assert resolve({**ON, key: 'on'})[key] == 'on'
    assert resolve({**ON, 'ear_job': 'off', key: 'on'})[key] == 'off'


# --- turn_mark --------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('seed', [1, 7, 9])      # seed 4: the ear lost «сколько», the job on its words has no answer, the final decides (a wait that protects)
def test_a_closed_number_opens_the_ear_job_before_the_final(seed):
    base = G.scene(seed, family='mult', profile=EAR_JOB, **G.PHONE)
    cut = G.scene(seed, family='mult', profile={**EAR_JOB, 'turn_mark': 'on'}, **G.PHONE)
    assert base['right'] and cut['right'] and not cut['violations']
    assert base['cue'] > base['final'], base                     # the wait: «… на 8?» may not grow, it waited for the final
    assert cut['cue'] < cut['final'] - 0.5, cut


def test_another_number_of_the_ear_still_waits_for_the_final():
    """The ear heard «девять», the cloud «8?»: no cue on the ear, the final decides and the cue is right."""
    nine = lambda heard: re.sub(r'\S+$', 'сто', heard)
    row = G.scene(1, family='mult', profile={**EAR_JOB, 'turn_mark': 'on'}, ear=nine, **G.PHONE)
    assert row['cue'] is None or (row['cue'] >= row['final'] and row['right']), row


# --- cloud_form -------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('seed', [0, 3, 5])
def test_the_cloud_s_question_mark_is_the_form_the_ear_did_not_hear(seed):
    base = G.scene(seed, family='verb', profile=EAR_JOB, **G.PHONE)
    cut = G.scene(seed, family='verb', profile={**EAR_JOB, 'cloud_form': 'on'}, **G.PHONE)
    assert base['right'] and cut['right'] and not cut['violations']
    assert base['cue'] > base['final'], base
    assert cut['cue'] < cut['final'] - 0.5, cut


def test_a_statement_of_the_cloud_opens_nothing():
    """The same words said as a statement («…давлении.»): the cloud's turn has no form either, nothing opens before the final."""
    said = lambda q: A.Q(q.family, q.params, q.text.rstrip('?') + '.')
    row = G.scene(0, family='verb', profile={**EAR_JOB, 'cloud_form': 'on'}, question=said, **G.PHONE)
    assert row['cue'] is None or row['cue'] >= row['final'], row


def test_the_ear_s_negation_the_other_way_round_waits_for_the_final():
    """The ear heard «не уменьшать, а увеличивать» where the cloud has «не увеличивать, а уменьшать»: the roles of «не» disagree, nothing opens on the ear."""
    def swap(heard):
        m = re.match(r'нужно не (\S+) а (\S+)(.*)', heard)
        return f'нужно не {m.group(2)} а {m.group(1)}{m.group(3)}' if m else heard
    row = G.scene(0, family='verb', profile={**EAR_JOB, 'cloud_form': 'on'}, ear=swap, **G.PHONE)
    assert row['cue'] is None or row['cue'] >= row['final'], row
    assert row['cue'] is None or row['right'], row


# --- ear_lookup: a question of the search route opens on the two witnesses too, so the job with the source starts when the early search is done, not at the final

def test_ear_lookup_off_by_default_and_needs_ear_job():
    assert resolve({})['ear_lookup'] == 'off'
    assert resolve({**ON, 'ear_lookup': 'on'})['ear_lookup'] == 'on'
    assert resolve({**ON, 'ear_job': 'off', 'ear_lookup': 'on'})['ear_lookup'] == 'off'


@pytest.mark.parametrize('seed', [0, 2, 4])      # seed 6: the ear lost «кодекса», the cloud's turn reads otherwise, the final decides (a wait that protects)
def test_the_search_question_opens_on_two_witnesses_and_the_source_job_starts_at_once(seed):
    base = G.scene(seed, family='article', profile=EAR_JOB, early=True, **G.PHONE)
    cut = G.scene(seed, family='article', profile={**EAR_JOB, 'ear_lookup': 'on'}, early=True, **G.PHONE)
    assert base['right'] and cut['right'] and not cut['violations'] and cut['lookups'] == 1, cut
    assert base['job'] >= base['final'] - 0.05, base             # the wait: the source was there at 2.3 s, the job began at the final
    assert cut['job'] < cut['final'] - 0.5 and cut['cue'] < base['cue'] - 0.7, (base, cut)


def test_the_ear_s_other_article_opens_no_search_before_the_final():
    """The ear heard «статья 33», the cloud «статья 21»: no take on the ear; the final decides and the cue names the cloud's article."""
    other = lambda heard: re.sub(r'(стать\S*) (\S+(?: \S+)?) (налогов)', r'\1 тридцать три \3', heard)
    row = G.scene(0, family='article', profile={**EAR_JOB, 'ear_lookup': 'on'}, ear=other, early=True, **G.PHONE)
    assert row['cue'] is None or (row['right'] and row['job'] >= row['final'] - 0.05), row


def test_a_personal_question_still_never_reaches_the_search():
    row = G.scene(0, family='money', profile={**EAR_JOB, 'ear_lookup': 'on', 'fast_private': 'on'}, early=True, **G.PHONE)
    assert row['lookups'] == 0 and row['right'], row


CANDIDATE_STAND = {'two_witnesses': 'on', 'prepare_wide': 'on', 'ear_release': 'on', 'gate_text': 'on', 'instant': 'on', 'spare_helper': 'on', 'open_overlap': 'on', 'warm_start': 'on',
                   'prefetch': 'on', 'ear_job': 'on'}


def test_cloud_form_opens_nothing_on_chatter_or_on_the_portion_s_words():
    """Fuzz seed 272: ``cloud_form`` waited on «да я готовился …» and on the cue said back; the reverse «не X, а Y» after them went unanswered (A5). Now the run is the one without the flag."""
    plain = A.run(272, profile={**A.profile_of(272), **CANDIDATE_STAND})
    form = A.run(272, profile={**A.profile_of(272), **CANDIDATE_STAND, 'cloud_form': 'on'})
    assert not [v for v in form.violations if v[0] in ('A5', 'A7')], form.violations
    assert [c[:2] for c in form.cues] == [c[:2] for c in plain.cues]

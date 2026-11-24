"""V1a kit: what the verify tests of kind_a share (the family «kind of an utterance: addressee, other people's speech»).

Nothing here decides anything: it drives the REAL ControlledMedia through the REAL NativeMediaSocket of ``tests/helpers_s6_state.World`` (the rig ``call`` of test_h3_tempo: the ear, the job's stream and the cloud's events
are scripted, the controller and the wire are the product's). The clock is the world's: no number here is a measurement of a call, a laptop or a phone.
"""
import re

import helpers_s6_state as S
from echo_sync.textutil import normalize
from test_h3_tempo import TICK
from test_h5_live import LIVE, cloud, fails, plan, said_to_the_room, spoken_failures      # noqa: F401 - re-exported for the tests of this directory

LIVE_RULES = dict(LIVE)                      # the profile of the working call as the other tests of the family build it

# the scene n1_02 step 18 (class 28): the interviewer asks the listener's question to a colleague, the colleague answers «ask Sveta»; the listener himself has said nothing
S18_ASK = 'Слушай, а какой максимум, ну, испытательного срока у главного бухгалтера'
S18_REPLY = 'Да откуда я знаю, у Светы спроси, она недавно людей оформляла'
TERM_QUESTION = 'Какой максимум испытательного срока у главного бухгалтера'
TERM_ANSWER = 'Не больше шести месяцев. Для главного бухгалтера срок испытания такой же, как для руководителя.'
JOB_TERM = 'Максимум шесть месяцев.'


def mark(rig):
    """Where the call stood: the cues that have sounded, the jobs asked, the public lookups made, the plan's revision and cursor."""
    snap = rig.w.snapshot()
    return {'cues': len(rig.cues()), 'runs': len(rig.fake.runs) if rig.fake else 0, 'lookups': len(rig.w.lookup_calls), 'revision': snap['revision'], 'index': snap['index'], 'chunks': snap['chunks']}


def sounded_since(rig, before):
    return [c.text for c in rig.cues()[before['cues']:]]


def pending_jobs(rig, since=0):
    """The numbers of the jobs begun and not over."""
    return [n for n in range(since, len(rig.fake.runs)) if not rig.fake.runs[n].ended.is_set()]


def let_jobs_decline(rig, since=0, rounds=6):
    """The job's answer to talk with no question is «—» (the brain's own rule): every job still open says it and ends. Bounded: a job that begets another is followed ``rounds`` times, never for ever."""
    for _ in range(rounds):
        todo = pending_jobs(rig, since)
        if not todo:
            return
        for n in todo:
            rig.job_says(n, '—')
            rig.job_ends(n)


def job_answers(rig, since, text):
    """Every job begun after ``since`` that is still open answers ``text`` and ends: what a job does with a real question."""
    for n in pending_jobs(rig, since):
        rig.job_says(n, text)
        rig.job_ends(n)


def stranger_pair(rig, first=S18_ASK, reply=S18_REPLY, job_text=JOB_TERM, uid='x'):
    """Two voices that are not the listener's (class 28): the words of a question, 0.9 s of pause, the other's reply. A job begun on the first piece answers it (as it would a question) before the reply is over."""
    since = len(rig.fake.runs)
    said_to_the_room(rig, f'{uid}1', first)
    rig.pump(0.2)
    job_answers(rig, since, job_text)
    rig.pump(0.7)
    said_to_the_room(rig, f'{uid}2', reply)
    rig.pump(0.3)
    let_jobs_decline(rig, since)
    return since


def heard(texts):
    return normalize(' '.join(texts))


def plan_texts(snapshot):
    """The portions of the plan: what a repeat of the waiting portion may sound like."""
    return {normalize(x) for x in snapshot['chunks']}


def only_the_plan_sounds(rig, before):
    """What sounded after ``before`` is the plan's own portions (a timer's repeat of what waits) and nothing else."""
    allowed = plan_texts(before)
    return [t for t in sounded_since(rig, before) if normalize(t) not in allowed]


def log_lines(caplog, word):
    return [r.getMessage() for r in caplog.records if word in r.getMessage()]


def numbers_in(text):
    return re.findall(r'\d+', text)

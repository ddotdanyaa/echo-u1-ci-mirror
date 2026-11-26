"""G34: every real call becomes a test. The journal of a call (``logs/echo_calls/*.jsonl``, ``echo_sync/call_trace.py``) becomes a replay fixture of the form
of ``tests/fixtures/call_1027_replay.json`` - the cloud's turns, the ear's utterances, the jobs' texts, the cues and the decisions, seconds of the call -
and the checks the journal shows by itself:

    loops      a cue said round and round: one text in one question more often than once and the repeats the call allows (``max_auto_repeats``)
    stale      an old answer after a new question: a cue under an older revision than the newest, or a cue of an earlier question said again
               that shares no word with the new one (the same question in other words may get the same answer)
    failures   a spoken diagnostic (``echo_sync.diagnostics.PHRASES``)
    silent     a question with no sound: no cue but a diagnostic, or the controller gave up on it (``answer_timeout``)
    stuck      the owner said the cue back and the same cue came again: the repeat did not move the cursor
    back       the place jumped back: the rest of a portion was said, and then the whole portion again from its head, in one question

A question is a new revision of the controller after a final of the cloud; a correction of the same question (a new revision with no final since) is not.
``tests/test_harvest.py`` replays the fixtures through the controller on the injected clock, with no network and no model, and runs the same checks on what
the replay said. The tool works on the laptop: the fixtures hold the call's text and go to ``tests/fixtures/harvest/`` (ignored by git); what leaves the
laptop is the counters, numbers only.

U06 (``events``, ``passport``): the unique events of a journal, one row each, by label - ``loop_run`` and ``over_cap`` (against the ``cap=`` the decision logged; a journal
without it gets the header's ``max_auto_repeats``, ``cap_source=reconstructed``; ``over_user_cap`` is a column to read, not a defect), ``refusal`` (per job: wrong,
unanswered, abstain, unclear, service), ``false_cue``, ``missed_question``, ``no_text_speech`` and ``wrong_repeat``. Numbers and labels; the text stays in the fixture.

Run: python -m tools.harvest [journal.jsonl | folder ...] [--out folder] [--force] [--manifest]       (no argument: the default echo_calls folder)
"""
import hashlib
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

from echo_sync.classifier import QUESTION_WORDS
from echo_sync.diagnostics import PHRASES

FAILURES = frozenset(PHRASES.values())
OUT_DEFAULT = Path(__file__).resolve().parents[2] / 'tests' / 'fixtures' / 'harvest'
CLOUD = {'user_start': 'ustart', 'user_final': 'user', 'assistant_start': 'astart', 'assistant_final': 'cloud'}
QUIET = frozenset(('silent',))      # the decisions that say nothing: each other decision with a revision is the revision the next cue belongs to
GAVE_UP = frozenset(('answer_timeout', 'cloud_declined'))
AUTO_REPEATS = 1             # a cue and as many repeats of it on its own as the call allows (``max_auto_repeats`` of its header, the default's 1); one more is a loop
REPEAT_SHARE = 0.6           # the owner said the cue back: this share of its words, two at least (one for a cue of one word)
_WORD = re.compile(r'[^\W\d_]+')
_TOKEN = re.compile(r'(\w{1,32})=(\S*)')
JOB_WINDOW_S = 8.0           # a replayed job takes the text of the call's job that ended this soon after it was asked
# U05.2: the calls studied for the fixes (dev, not blind) and the other real calls over a minute (holdout); the rest of the corpus is neither
DEV = frozenset(('20261103-095456-abcc139fe874', '20261103-201019-72c65a267b59', '20261104-203437-a0065d9756d8', '20261106-074253-65f46fe91e81',
                 '20261106-074904-a1fbfe4ba92e', '20261107-202918-5fa76eaa002d', '20261107-211624-de4e4240d8b2', '20261108-120135-6dc9eed08e9b'))
HOLDOUT = frozenset(('20261104-094139-312527f463a8', '20261105-102711-8b495d62bc43', '20261106-090348-594a1af58adc', '20261107-114058-812b0903f0ae',
                     '20261107-123153-4e9697e08277', '20261107-123655-8fa506019cee', '20261107-125656-81f19d2cea23', '20261107-125923-c0ac3df4eb6a',
                     '20261107-144504-fece32f2c959', '20261107-160204-bfad1d2d1f31', '20261107-160609-dfd8725a473b', '20261107-160912-dc818259cafb',
                     '20261107-161507-20321ea72be2', '20261107-211254-441869a7fed7'))
NOT_JOURNALS = frozenset(('counters', 'MANIFEST'))
# U06.2: the numbers of the labels (quantities, not phrases)
RUN_GAP_S = 15.0             # plays of one text are one run while each follows the one before within this long
LATE_ANSWER_S = 15.0         # a question the system took within this long after the last refusal: the refusal was wrong, the answer came late
LOOK_S = 15.0                # a cue wants a final of the ear this close before it; a question wants a cue this close after it
FOLD_S = 6.0                 # finals of the ear with the same or a nested text within this long are one utterance
ASKED_TAIL, ASKED_LOOK, ASKED_SHARE = 8, 12, 0.5      # the ear named the question: its share of the last 8 words of what was asked; the words see one in the last 12
EAR_FRESH_S = 3.5            # the ear's final that named the question stands for it this long before the last refusal of the job (fitted to U06.1 on 074253 and 120135)
CONFIRM_BEFORE_S, CONFIRM_AFTER_S = 6.0, 12.0         # the cloud's final of the same words, around a missed question
NO_TEXT_SPEECH_MS = 800
SERVICE_RULES = frozenset(('released', 'failed'))     # the job was already given out or it failed: not a verdict on the rules
NOT_NEW_CUE = frozenset(('replay', 'ack', 'next', 'resume'))
CUE_BASIS = frozenset(('question', 'ack', 'resume', 'correction', 'replay', 'stop', 'greeting'))
# U06-S6: the numbers of the latency passport
PIECE_GAP_S = 4.0            # a question said in pieces: the next final of the ear within this long after the one before is its next piece, and t0 is the last piece
LATE_S = 15.0                # a useful cue later than this after t0 is flagged late (it stays in the numbers)
ASK_WINDOW_S = 60.0          # a question looks for its cue this long after t0, or up to the next question
WITHIN_S = (3, 5, 8)
P95_MIN_N = 20               # below this n there is no p95
REF_SHARE = 0.6              # a reference belongs to a question when this share of the words of each is in the other
FINDINGS = ('loops', 'stale', 'failures', 'silent', 'stuck', 'back', 'timeouts')


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def read_rows(rows):
    """The records with a time and a kind, in the order of their time (a stable sort: the order of the file within one ms)."""
    good = [row for row in rows if isinstance(row, dict) and _num(row.get('t')) is not None and isinstance(row.get('ev'), str)]
    return sorted(good, key=lambda row: row['t'])


def read(path):
    rows = []
    with open(path, encoding='utf-8', errors='replace') as handle:
        for line in handle:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return read_rows(rows)


def _s(ms):
    return round(ms / 1000, 3)


def fixture(rows, source=None):
    """The replay fixture of a journal; the provider's ids become u1, a1, ... (one turn keeps one id)."""
    cloud, ear, jobs, cues, decisions, ids = [], [], [], [], [], {}
    ear_kind, refused, jobs_meta, mic, judge, keeps = [], [], [], [], [], []
    for row in rows:
        ev, t = row['ev'], row['t']
        if ev in CLOUD:
            prefix = 'u' if ev.startswith('user') else 'a'
            key = ids.setdefault((prefix, row.get('id')), f'{prefix}{sum(1 for p, _ in ids if p == prefix) + 1}')
            cloud.append([_s(t), CLOUD[ev], key, str(row.get('text') or '') if ev.endswith('final') else ''])
        elif ev == 'ear_final':
            lag, speech = _num(row.get('lag_ms')), _num(row.get('speech_ms'))
            if lag is None or speech is None:
                continue
            ear.append([_s(t - lag - speech), _s(t - lag), _s(t), str(row.get('text') or '')])
            ear_kind.append([row.get('kind'), row.get('reason')])
        elif ev == 'fast_job':
            jobs.append([_s(t), row.get('on'), row.get('ttft_ms'), str(row.get('first') or ''), row.get('outcome')])
            jobs_meta.append([_s(t), row.get('job'), row.get('after_ear_ms'), row.get('outcome'), row.get('reason'), row.get('released'), row.get('adopted')])
        elif ev in ('fast_refused', 'fast_refused_sum'):
            refused.append({'t': _s(t), **{key: value for key, value in row.items() if key not in ('t', 'ev')}})
        elif ev in ('judge', 'fast_keep'):      # U15-S8: what the utterance judge and the kept jobs said (scalars only); the acceptance counts them
            (judge if ev == 'judge' else keeps).append({'t': _s(t), **{key: value for key, value in row.items() if key not in ('t', 'ev') and (value is None or isinstance(value, (str, int, float, bool)))}})
        elif ev == 'mic':       # U17-S6: one second of the phone's microphone, numbers only: first and last packet second, packets, bytes
            first, last, n, size = _num(row.get('first_ms')), _num(row.get('last_ms')), _num(row.get('n')), _num(row.get('bytes'))
            if None not in (first, last, n, size):
                mic.append([_s(first), _s(last), int(n), int(size)])
        elif ev == 'cue':
            cues.append([_s(t), str(row.get('text') or ''), None])
        elif ev in ('cue_end', 'cue_cut') and cues and cues[-1][2] is None:
            cues[-1][2] = row.get('status') or 'cut' if ev == 'cue_cut' else row.get('status')
        elif ev == 'decision':
            decisions.append([_s(t), row.get('kind'), row.get('reason'), row.get('revision'), row.get('index')])
    header = next((row for row in rows if row['ev'] == 'call_open'), {})
    profile = {key: header[key] for key in ('max_auto_repeats', 'repeat_seconds') if _num(header.get(key)) is not None}
    made = events(rows)
    got = {'source': source or 'a call journal, harvested by tools.harvest: seconds of the call', 'profile': profile, 'cloud': cloud, 'ear': ear, 'jobs': jobs, 'cues': cues,
            'decisions': decisions, 'checks': checks(rows), 'ear_kind': ear_kind, 'refused': refused, 'jobs_meta': jobs_meta,
            'header': {key: value for key, value in header.items() if key not in ('t', 'ev') and (value is None or isinstance(value, (str, int, float, bool)))},
            'events': made, 'passport': passport(made, rows)}
    if judge:   # a journal without judge / keep rows keeps its old fixture too
        got['judge'] = judge
    if keeps:
        got['keeps'] = keeps
    if mic:     # a journal with no mic rows keeps its old fixture (and the hash of the corpus)
        got['mic'] = mic
    return got


# -- the checks ------------------------------------------------------------------------------------------------------------------------

def words(text):
    return [word for word in _WORD.findall(str(text or '').casefold().replace('ё', 'е')) if len(word) >= 3]


def _alike(a, b):
    """One word, another case of it, or the ear's garble of its ending."""
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n >= max(3, min(len(a), len(b)) - 2)


def said_back(heard, cue):
    """Did the owner say the cue back: REPEAT_SHARE of its words, two at least."""
    want, got = words(cue), words(heard)
    if not want or not got:
        return False
    found = sum(1 for word in want if any(_alike(word, other) for other in got))
    return found >= min(2, len(want)) and found >= REPEAT_SHARE * len(want)


def _about(question, cue):
    """Does the cue share a word with the question: the same question in other words, or the answer it was asked to go on with."""
    return any(_alike(word, other) for word in words(question) for other in words(cue))


def checks(rows):
    """Counters of a journal: what it holds and what is wrong in it, numbers only."""
    got = dict.fromkeys(('finals', 'ear', 'cues', 'jobs', 'decisions', 'questions', 'repeats') + FINDINGS, 0)
    episodes = []                      # each: {'question': the final that opened it, 'texts': {text: plays}, 'sound': bool}
    newest, last_final, final_since, cue_revision, last_cue, repeated = None, None, False, None, None, None
    plays = 1 + AUTO_REPEATS
    for row in rows:
        ev = row['ev']
        if ev == 'call_open' and _num(row.get('max_auto_repeats')) is not None:
            plays = 1 + max(0, int(row['max_auto_repeats']))
        revision = None
        if ev == 'user_final':
            got['finals'] += 1
            last_final, final_since = row.get('text') or '', True
        elif ev == 'ear_final':
            got['ear'] += 1
        elif ev == 'fast_job':
            got['jobs'] += 1
        if ev in ('user_final', 'ear_final') and last_cue is not None and repeated is not last_cue and said_back(row.get('text'), last_cue['text']):
            got['repeats'] += 1
            repeated = last_cue
        elif ev == 'decision':
            got['decisions'] += 1
            kind, revision = row.get('kind'), _num(row.get('revision'))
            if kind == 'silent' and row.get('reason') in GAVE_UP:
                got['timeouts'] += 1
                if final_since:            # the question never got a revision: it is a question with no sound
                    episodes.append({'question': last_final, 'texts': {}, 'sound': False, 'start': revision})
                    final_since = False
            if revision is None:
                continue
            if kind == 'silent' and row.get('reason') == 'fast_text_declined' and episodes and not episodes[-1]['sound']:
                episodes[-1]['declined'] = True
            if kind == 'resume' and len(episodes) > 1 and episodes[-1].get('declined') and not episodes[-1]['sound']:
                episodes.pop()             # c24-a1: the job read the «new question» as none (declined): the plan it retired goes on, the same episode (not P16: a question the job could not answer stays stale)
                newest, final_since = revision, False
            elif kind == 'retire' and row.get('reason') == 'new_question':
                episodes.append({'question': last_final, 'texts': {}, 'sound': False, 'start': revision})
                newest, final_since = revision, False
            elif newest is None or revision > newest:
                if final_since or not episodes:
                    episodes.append({'question': last_final, 'texts': {}, 'sound': False, 'start': revision})
                newest, final_since = revision, False
            if kind not in QUIET:
                cue_revision = revision
        elif ev == 'cue':
            text = str(row.get('text') or '')
            got['cues'] += 1
            if text in FAILURES:
                got['failures'] += 1
                continue
            if not episodes:
                episodes.append({'question': last_final, 'texts': {}, 'sound': False, 'start': revision})
            here = episodes[-1]
            older = cue_revision is not None and here['start'] is not None and cue_revision < here['start']
            earlier = any(text in past['texts'] for past in episodes[:-1]) and not _about(here['question'], text)
            if older or (earlier and text not in here['texts']):
                got['stale'] += 1
            if repeated is not None and repeated['text'] == text and repeated['episode'] is here and last_cue is repeated:
                got['stuck'] += 1
            if text in here.setdefault('cut', set()):
                got['back'] += 1
            mine = words(text)
            here['cut'].update(head for head in here['texts'] if len(mine) < len(words(head)) and words(head)[-len(mine):] == mine)
            here['texts'][text] = here['texts'].get(text, 0) + 1
            if here['texts'][text] == plays + 1:
                got['loops'] += 1
            here['sound'] = True
            last_cue = {'text': text, 'episode': here}
    got['questions'] = len(episodes)
    got['silent'] = sum(1 for episode in episodes if not episode['sound'])
    return got


# -- U06: the events of a journal ------------------------------------------------------------------------------------------------------

def _overlap(heard, asked, tail=None):
    """The share of the words of ``asked`` (its last ``tail``) that ``heard`` has."""
    want, got = (words(asked)[-tail:] if tail else words(asked)), words(heard)
    return sum(1 for word in want if any(_alike(word, other) for other in got)) / len(want) if want else 0.0


def _asking(text):
    """A word of a question or a request in the text (the classifier's own list), or a question mark."""
    text = str(text or '')
    return '?' in text or any(word in QUESTION_WORDS for word in text.casefold().replace('ё', 'е').split()) or any(word in QUESTION_WORDS for word in words(text))


def _caps(rows):
    """``cap_at(t)``: the cap a repeat was held to at ms ``t`` - the last ``cap=`` a decision logged, else the header's ``max_auto_repeats`` (reconstructed)."""
    header = next((row for row in rows if row['ev'] == 'call_open'), {})
    base = int(header['max_auto_repeats']) if _num(header.get('max_auto_repeats')) is not None else AUTO_REPEATS
    logged = [(row['t'], int(row['cap'])) for row in rows if row['ev'] == 'decision' and _num(row.get('cap')) is not None]

    def cap_at(t):
        before = [cap for at, cap in logged if at <= t]
        return (before[-1], 'logged') if before else (base, 'reconstructed')
    return cap_at, base


def _folded(rows):
    """The finals of the ear, a repeated or nested one of the same words within FOLD_S taken for the one before."""
    kept = []
    for row in rows:
        if row['ev'] != 'ear_final':
            continue
        mine = ' '.join(words(row.get('text')))
        if kept and row['t'] - kept[-1]['t'] <= FOLD_S * 1000 and (mine in kept[-1]['norm'] or kept[-1]['norm'] in mine):
            continue
        kept.append({**row, 'norm': mine})
    return kept


def _jobs_refused(rows):
    """Per job: its refusals. t0 of the first note; the sum (``fast_refused_sum``) holds only the refusals BEYOND the noted ones, so its counts are ADDED to the notes' and its ``last_t`` (ms after the JOB started) is put on the call clock by the first note's own ``ms``."""
    jobs = {}
    for row in rows:
        if row['ev'] not in ('fast_refused', 'fast_refused_sum'):
            continue
        one = jobs.setdefault(row.get('job'), {'t0': row['t'], 't1': row['t'], 'asked': '', 'rules': {}, 'sum': False, 'ms0': _num(row.get('ms')) or 0})
        if row['ev'] == 'fast_refused':
            one['t1'], one['asked'] = max(one['t1'], row['t']), str(row.get('asked') or '')
            one['rules'][row.get('rule')] = one['rules'].get(row.get('rule'), 0) + 1
            continue
        counts = row['rules'] if isinstance(row.get('rules'), dict) else {key: value for key, value in row.items() if key not in ('t', 'job', 'last_t', 'last_asked')}
        for key, value in counts.items():
            if _num(value) is not None:
                one['rules'][key] = one['rules'].get(key, 0) + int(value)
        one['sum'] = True
        if _num(row.get('last_t')) is not None:
            one['t1'] = max(one['t1'], one['t0'] + max(0, row['last_t'] - one['ms0']))
        one['asked'] = str(row.get('last_asked') or one['asked'])
    return jobs


def events(rows):
    """The unique events of a journal, in the order of their time: ``{'t': second, 'label': ..., ...}``, labels and numbers only."""
    cap_at, base = _caps(rows)
    out, ears = [], _folded(rows)

    def add(t, label, **fields):
        out.append({'t': _s(t), 'label': label, **fields})
    for row in rows:                    # over_cap: a repeat the cap did not allow; over_user_cap: it is more than the owner's max_auto_repeats too (a column, not a defect)
        if row['ev'] != 'decision':
            continue
        if row.get('kind') == 'replay' and _num(row.get('repeats')) is not None:
            cap, source = cap_at(row['t'])
            if row['repeats'] > cap:
                add(row['t'], 'over_cap', repeats=row['repeats'], cap=cap, cap_source=source, over_user_cap=row['repeats'] > base)
        if row.get('reason') == 'wrong_repeat':
            add(row['t'], 'wrong_repeat')
    run = None                          # loop_run: plays of one text, each within RUN_GAP_S of the one before, more than 1 + cap
    for row in [r for r in rows if r['ev'] == 'cue'] + [None]:
        text = None if row is None else str(row.get('text') or '')
        if run and row is not None and text == run['text'] and row['t'] - run['last'] <= RUN_GAP_S * 1000:
            run['plays'] += 1
            run['last'] = row['t']
            continue
        if run:
            cap, source = cap_at(run['last'])
            if run['plays'] > 1 + cap and run['text'] not in FAILURES:
                add(run['first'], 'loop_run', plays=run['plays'], cap=cap, cap_source=source)
        run = None if row is None else {'text': text, 'plays': 1, 'first': row['t'], 'last': row['t']}
    ran = {row.get('job') for row in rows if row['ev'] == 'fast_job'}
    taken = [row['t'] for row in rows if row['ev'] == 'decision' and row.get('kind') in ('question', 'answer')]
    for number, one in _jobs_refused(rows).items():          # refusal: one event per job
        if all(rule in SERVICE_RULES for rule in one['rules']):
            label = 'service'
        elif number not in ran:
            label = 'unclear'
        else:
            named = any(one['t1'] - EAR_FRESH_S * 1000 <= row['t'] <= one['t1'] and row.get('kind') == 'question' and _overlap(row.get('text'), one['asked'], ASKED_TAIL) >= ASKED_SHARE for row in ears)
            seen = _asking(' '.join(words(one['asked'])[-ASKED_LOOK:]))
            late = any(one['t1'] <= at <= one['t1'] + LATE_ANSWER_S * 1000 for at in taken)
            label = 'abstain' if not named and not seen else 'unclear' if named != seen else 'wrong' if late else 'unanswered'
        add(one['t0'], 'refusal', job=number, verdict=label, rules=one['rules'], raw=sum(one['rules'].values()), t1=_s(one['t1']))
    cues = [row for row in rows if row['ev'] == 'cue' and str(row.get('text') or '') not in FAILURES]
    for n, row in enumerate(cues):      # false_cue: a new cue (not a text said before) with no final of the ear to answer, and (strict) no word of a question in what was said before it
        if str(row.get('text') or '') in {str(c.get('text') or '') for c in cues[:n]}:
            continue
        before = [r for r in rows if r['ev'] == 'decision' and r['t'] <= row['t'] and row['t'] - r['t'] <= 2000]
        if before and before[-1].get('kind') in NOT_NEW_CUE:
            continue
        window = [r for r in rows if r['ev'] in ('ear_final', 'user_final') and row['t'] - LOOK_S * 1000 <= r['t'] <= row['t']]
        if not any(r['ev'] == 'ear_final' and r.get('kind') in CUE_BASIS for r in window):
            add(row['t'], 'false_cue', strict=not any(_asking(r.get('text')) for r in window))
    finals = [r for r in rows if r['ev'] == 'user_final']
    for row in ears:                    # missed_question and no_text_speech
        if row.get('kind') == 'question' and not any(row['t'] < c['t'] <= row['t'] + LOOK_S * 1000 for c in cues):
            sure = any(row['t'] - CONFIRM_BEFORE_S * 1000 <= f['t'] <= row['t'] + CONFIRM_AFTER_S * 1000 and _overlap(f.get('text'), row.get('text')) >= ASKED_SHARE for f in finals)
            add(row['t'], 'missed_question', confirmed=sure)
        if not words(row.get('text')) and (_num(row.get('speech_ms')) or 0) >= NO_TEXT_SPEECH_MS:
            add(row['t'], 'no_text_speech', speech_ms=row['speech_ms'])
    return sorted(out, key=lambda event: event['t'])


def _content(text):
    return [word for word in words(text) if word not in QUESTION_WORDS]


def latency_asks(rows):
    """U06-S6: the questions of a journal, one row each: the ear's final of kind ``question`` and the pieces that go on it (``PIECE_GAP_S``), ``t0`` the second of the LAST
    piece (the last utterance the question needs), its text, ``early`` (useful cues before t0: premature) and ``cues`` (useful cues after t0, the diagnostics left out)."""
    ears, cues = _folded(rows), [row for row in rows if row['ev'] == 'cue']
    useful = [row for row in cues if str(row.get('text') or '') not in FAILURES]
    starts = [n for n, row in enumerate(ears) if row.get('kind') == 'question']
    asks = []
    for k, n in enumerate(starts):
        end = starts[k + 1] if k + 1 < len(starts) else len(ears)
        last, pieces = ears[n], [ears[n]]
        for row in ears[n + 1:end]:
            if words(row.get('text')) and row['t'] - last['t'] <= PIECE_GAP_S * 1000:
                last = row
                pieces.append(row)
        stop = ears[end]['t'] if end < len(ears) else float('inf')
        asks.append({'first': _s(pieces[0]['t']), 't0': _s(last['t']), 'text': ' '.join(str(row.get('text') or '') for row in pieces),
                     'early': [_s(row['t']) for row in useful if pieces[0]['t'] < row['t'] < last['t']],
                     'cues': [(_s(row['t']), str(row.get('text') or '')) for row in useful if last['t'] <= row['t'] <= min(stop, last['t'] + ASK_WINDOW_S * 1000)]})
    return asks


def scene_refs(path):
    """The references from a scenes file (or a U21 gold file of the same form): the scenes that have ``text`` and an ``expected`` answer."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    return [{'id': one.get('id'), 'text': one['text'], 'expected': one['expected']} for one in data.get('scenes', ()) if one.get('text') and one.get('expected')]


def _timed(ask, target):
    """The flag and the latency of a question against the words its useful cue must share (the question's own for the proxy, the reference's for the ref)."""
    if ask['early']:
        return 'premature', None
    if not ask['cues']:
        return 'no_cue', None
    want = _content(target)
    for at, text in ask['cues']:
        if any(_alike(word, other) for word in want for other in _content(text)):
            return ('late' if at - ask['t0'] > LATE_S else 'none'), round(at - ask['t0'], 3)
    return 'unanchored', None


def _latency(timed):
    """``timed``: ``(flag, latency)`` per question. The numbers of the questions that got a latency: n of N, the median, within 3/5/8 s, p95 from ``P95_MIN_N``."""
    got = {'n': 0, 'N': len(timed)}
    if not timed:
        return got
    seen = sorted(latency for _, latency in timed if latency is not None)
    got['n'] = len(seen)
    got['flags'] = {flag: sum(1 for one, _ in timed if one == flag) for flag in ('none', 'premature', 'unanchored', 'late', 'no_cue') if any(one == flag for one, _ in timed)}
    if seen:
        got['median_s'] = round(statistics.median(seen), 3)
        got.update({f'within_{limit}': sum(1 for latency in seen if latency <= limit) for limit in WITHIN_S})
        if len(seen) >= P95_MIN_N:
            got['p95_s'] = seen[math.ceil(0.95 * len(seen)) - 1]
    return got


def passport(made, rows, refs=None, manifest_sha=None):
    """The counters of the events, numbers only, with what they were counted against: the call's minutes, its source and the source of the cap. U06-S6: ``latency_proxy``
    (every question; the cue shares a content word with it) and ``latency_ref`` (only the questions with a reference in ``refs``; the cue shares a word with the expected
    answer) are never merged, each with its own n of N; the header carries the manifest hash and the checker's own."""
    header = next((row for row in rows if row['ev'] == 'call_open'), {})
    caps = {event['cap_source'] for event in made if 'cap_source' in event}
    got = {'minutes': round(max((row['t'] for row in rows), default=0) / 60000, 2), 'source': header.get('source'), 'events_total': len(made),
           'cap_source': 'reconstructed' if 'reconstructed' in caps else 'logged' if caps else None}
    for label in ('loop_run', 'over_cap', 'false_cue', 'missed_question', 'no_text_speech', 'wrong_repeat'):
        got[label] = sum(1 for event in made if event['label'] == label)
    got['loops_run'] = got['loop_run']
    got['over_cap_reconstructed'] = sum(1 for event in made if event['label'] == 'over_cap' and event['cap_source'] == 'reconstructed')
    base = int(header['max_auto_repeats']) if _num(header.get('max_auto_repeats')) is not None else AUTO_REPEATS
    got['over_user_cap'] = sum(1 for row in rows if row['ev'] == 'decision' and row.get('kind') == 'replay' and (_num(row.get('repeats')) or 0) > base)      # a column to read, not a defect
    got['false_cue_strict'] = sum(1 for event in made if event['label'] == 'false_cue' and event['strict'])
    got['missed_question_confirmed'] = sum(1 for event in made if event['label'] == 'missed_question' and event['confirmed'])
    for verdict in ('wrong', 'unanswered', 'abstain', 'unclear', 'service'):
        got['refusal_' + verdict] = sum(1 for event in made if event['label'] == 'refusal' and event['verdict'] == verdict)
    got['refusal_raw'] = sum(event['raw'] for event in made if event['label'] == 'refusal')
    asks = latency_asks(rows)
    got['latency_proxy'] = _latency([_timed(ask, ask['text']) for ask in asks])
    refd = [(ask, next((r for r in refs or () if _overlap(ask['text'], r['text']) >= REF_SHARE and _overlap(r['text'], ask['text']) >= REF_SHARE), None)) for ask in asks]
    got['latency_ref'] = _latency([_timed(ask, ref['expected']) for ask, ref in refd if ref])
    got['manifest_sha256'] = manifest_sha
    got['checker_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return got


def findings(got):
    return {key: got[key] for key in FINDINGS if got.get(key)}


def line(got):
    return ' '.join(f'{key}={value}' for key, value in got.items())


# -- the replay's side -----------------------------------------------------------------------------------------------------------------

def answer_for(fixture, heard, at=None):
    """What a job asked on ``heard`` at second ``at`` of the call answers in a replay: the call's own job that ended next after that moment (within
    JOB_WINDOW_S), else the call's job for the final it heard, else the cloud's answer to that final, else «—»."""
    jobs = [row for row in fixture.get('jobs', ()) if row[3] and row[4] in (None, 'ok')]
    if at is not None:
        near = [row for row in jobs if at - 0.5 <= row[0] <= at + JOB_WINDOW_S]
        if near:
            return min(near, key=lambda row: row[0])[3]
    finals = [row for row in fixture.get('cloud', ()) if row[1] == 'user']
    want = words(heard)
    scored = [(sum(1 for word in want if any(_alike(word, other) for other in words(row[3]))), -n) for n, row in enumerate(finals)]
    best = max(scored, default=(0, None))
    if not best[0]:
        return '—'
    n = -best[1]
    final = finals[n]
    started = max((row[0] for row in fixture['cloud'] if row[1] == 'ustart' and row[2] == final[2]), default=final[0])
    following = finals[n + 1][0] if n + 1 < len(finals) else float('inf')
    for row in jobs:
        if started <= row[0] < following:
            return row[3]
    return next((text for t, kind, _, text in fixture['cloud'] if kind == 'cloud' and final[0] < t < following and text.strip()), '—')


def replay_rows(fixture, cues, decisions):
    """The journal of a replay: the fixture's finals and ear, the cues the replay said ``(second, text, cut)`` and its decision lines ``(second, message)``."""
    rows = [{'t': -1, 'ev': 'call_open', **fixture.get('profile', {})}]
    rows += [{'t': round(at * 1000), 'ev': 'user_final', 'text': text} for at, kind, _, text in fixture['cloud'] if kind == 'user']
    rows += [{'t': round(at * 1000), 'ev': 'ear_final', 'text': text} for _, _, at, text in fixture['ear']]
    for at, message in decisions:
        fields = {}
        for key, value in _TOKEN.findall(message.split('echo-sync decision ', 1)[-1]):
            fields.setdefault(key, int(value) if value.isdigit() else value)
        rows.append({'t': round(at * 1000), 'ev': 'decision', **fields})
    rows += [{'t': round(at * 1000), 'ev': 'cue', 'text': text} for at, text, _ in cues]
    order = {'call_open': 0, 'user_final': 0, 'ear_final': 0, 'decision': 1, 'cue': 2}
    return sorted(rows, key=lambda row: (row['t'], order[row['ev']]))


# -- the corpus manifest ---------------------------------------------------------------------------------------------------------------

def _ids(folder):
    return sorted(path.stem for path in Path(folder).glob('*.json') if path.stem not in NOT_JOURNALS)


DERIVED = ('events', 'passport', 'checks')      # what the checker computes from the journal: not the corpus, so a change of the checker never moves the corpus hash


def _corpus_sha(path):
    """The sha256 of one fixture WITHOUT the keys the checker derives (its own hash lives in the passport and the manifest header, apart from this)."""
    raw = Path(path).read_bytes()
    try:
        body = json.loads(raw.decode('utf-8'))
    except ValueError:
        return hashlib.sha256(raw).hexdigest()
    if isinstance(body, dict):
        body = {key: value for key, value in body.items() if key not in DERIVED}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()


def manifest(folder=OUT_DEFAULT):
    """The corpus every acceptance cites: the journal ids, the sha256 of the set (of each fixture's journal content, without the derived keys, in id order) and the dev/holdout split."""
    ids, whole = _ids(folder), hashlib.sha256()
    for one in ids:
        whole.update(f'{one} {_corpus_sha(Path(folder) / (one + ".json"))}\n'.encode())
    split = {one: 'dev' if one in DEV else 'holdout' if one in HOLDOUT else 'rest' for one in ids}
    return {'count': len(ids), 'ids': ids, 'sha256': whole.hexdigest(), 'checker_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'split': split}


def manifest_subset(folder, keep):
    """A subset of the corpus (e.g. the calls with cue rows) is a filter over the fixtures, not a second list."""
    return [one for one in _ids(folder) if keep(json.loads((Path(folder) / (one + '.json')).read_text(encoding='utf-8')))]


# -- the command -----------------------------------------------------------------------------------------------------------------------

def journals(targets):
    found = []
    for target in map(Path, targets):
        found += sorted(target.glob('*.jsonl')) if target.is_dir() else [target]
    return [path for path in found if path.suffix == '.jsonl' and path.is_file()]


def default_calls():
    """The laptop's echo_calls folder, as ``cloud_context/scripts/latency_chain.py`` has it (``ECHO_CALLS_DIR`` over it)."""
    base = Path(os.environ.get('LOCALAPPDATA', '')) / 'hermes-echo' / 'home' / 'profiles' / 'echo-sync' / 'logs' / 'echo_calls'
    return [os.environ.get('ECHO_CALLS_DIR') or str(base)]


def whatif(rows, missing_ok):
    """U07-S7: the flip table of ``refusal(missing_ok=K)`` over the refusal notes of a journal (they carry ``heard`` and ``asked``): per job and ask, the rule now and with K, and whether it flips to adopted. The job's verdict is U06's (``events``).
    K=0 flips nothing by construction. Reads only; nothing is replayed."""
    from echo_sync.fast_text import refusal      # noqa: PLC0415
    verdict = {event.get('job'): event.get('verdict') for event in events(rows) if event['label'] == 'refusal'}
    table, seen = [], set()
    for row in rows:
        if row['ev'] != 'fast_refused' or not row.get('heard') or not row.get('asked') or (row.get('job'), row['asked']) in seen:
            continue
        seen.add((row.get('job'), row['asked']))
        before, after = refusal(row['heard'], row['asked']), refusal(row['heard'], row['asked'], missing_ok=missing_ok)
        table.append({'job': row.get('job'), 'verdict': verdict.get(row.get('job')), 'rule': row.get('rule'), 'before': before, 'after': after, 'flip': before is not None and after is None, 'asked': row['asked'][-80:]})
    return table


def whatif_lines(table, missing_ok):
    wrong = [row for row in table if row['verdict'] == 'wrong']
    flips = [row for row in table if row['flip']]
    lines = [f"whatif K={missing_ok}: {len(table)} refusals, {len(wrong)} of jobs with a wrong refusal; flips {len(flips)} (wrong {sum(row['verdict'] == 'wrong' for row in flips)}, others {sum(row['verdict'] != 'wrong' for row in flips)})"]
    lines += [f"  job={row['job']} verdict={row['verdict']} {row['before']} -> {row['after']} flip={row['flip']} | {row['asked']}" for row in table if row['verdict'] == 'wrong' or row['flip']]
    return lines


def passport_total(passports):
    """U07-S8: the passports of the calls added up, numbers only: every whole number of a passport, and the n, N and the within_3/5/8 of its two latency columns (``latency_proxy_N``).
    The baseline the next run is read against; the median does not add up and stays in the passport of its call."""
    got = {}
    for one in passports:
        for key, value in one.items():
            if isinstance(value, int) and not isinstance(value, bool):
                got[key] = got.get(key, 0) + value
            elif isinstance(value, dict) and key.startswith('latency_'):
                for part in ('n', 'N', 'within_3', 'within_5', 'within_8'):
                    if isinstance(value.get(part), int):
                        got[f'{key}_{part}'] = got.get(f'{key}_{part}', 0) + value[part]
    return got


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    out, force = OUT_DEFAULT, '--force' in args
    args = [arg for arg in args if arg != '--force']
    if '--whatif' in args:
        at = args.index('--whatif')
        k = int(args[at + 1])
        del args[at:at + 2]
        paths = journals(args or default_calls())
        if not paths:
            print('no call journal found', file=sys.stderr)
            return 1
        for path in paths:
            print(chr(10).join([path.stem[:40], *whatif_lines(whatif(read(path), k), k)]))
        return 0
    if '--out' in args:
        at = args.index('--out')
        out = Path(args[at + 1])
        del args[at:at + 2]
    if '--manifest' in args:
        got = manifest(out)
        (out / 'MANIFEST.json').write_text(json.dumps(got, ensure_ascii=False, indent=1), encoding='utf-8')
        print('\n'.join(got['ids']), f"sha256 {got['sha256']}", sep='\n')
        return 0
    paths = journals(args or default_calls())
    if not paths:
        print('no call journal found', file=sys.stderr)
        return 1
    out.mkdir(parents=True, exist_ok=True)
    rows, passports = [], []
    for path in paths:
        target = out / (path.stem + '.json')
        if target.exists() and not force:
            made = json.loads(target.read_text(encoding='utf-8'))
        else:
            made = fixture(read(path))
            target.write_text(json.dumps(made, ensure_ascii=False, indent=0), encoding='utf-8')
        got = made.get('checks') or {}
        passports.append(made.get('passport') or {})
        rows.append({'call': path.stem[:40], **got})
        print(f'{path.stem[:40]}: {line(got)}')
    total = {key: sum(row.get(key, 0) for row in rows) for key in rows[0] if key != 'call'}
    (out / 'counters.json').write_text(json.dumps({'calls': len(rows), 'total': total, 'events_total': passport_total(passports).get('events_total', 0), 'passport_total': passport_total(passports), 'by_call': rows}, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'{len(rows)} calls: {line(total)} -> {out}')
    return 0

"""The scenes of the ladder and their verdict (see ``tools.ladder``)."""
import glob
import json
import random
import re

from tools.rehearsal import plan as P
from tools.rehearsal import score
from tools.rehearsal import sim
from tools.replay import stand as A
from tools.replay.stand import ANSWER_WAIT_SECONDS, normalize

ROOT = A.ROOT
LEVELS = ('L0', 'L1', 'L2', 'L3', 'L4', 'L5')
CANDIDATE = {'fast_text': 'on', 'local_ear': 'act', 'prompt_tempo': 'ear', 'ear_release': 'on', 'two_witnesses': 'on', 'instant': 'on', 'material_pick': 'on',
             'spare_helper': 'on', 'warm_start': 'on', 'open_overlap': 'on', 'quick_math': 'on'}
# what each level adds: questions, pauses (s), repeats of the owner, stumbles, preambles, conditions, noise, others per minute, model faults, flood, drop, barge
KNOBS = {
    'L0': dict(n=1, alt=0.0, repeat=0.0, stumble=0.0, intro=0.0, cond=0.0, noise='clean', orate=0, model=False, flood=0.0, drop=False, barge=0.0),
    'L1': dict(n=5, alt=0.5, repeat=0.0, stumble=0.0, intro=0.0, cond=0.0, noise='clean', orate=0, model=False, flood=0.0, drop=False, barge=0.0),
    'L2': dict(n=5, alt=0.5, repeat=0.9, stumble=0.35, intro=0.0, cond=0.0, noise='clean', orate=0, model=False, flood=0.0, drop=False, barge=0.0),
    'L3': dict(n=5, alt=0.5, repeat=0.9, stumble=0.35, intro=0.35, cond=0.35, noise='clean', orate=0, model=False, flood=0.0, drop=False, barge=0.0),
    'L4': dict(n=5, alt=0.5, repeat=0.9, stumble=0.35, intro=0.35, cond=0.35, noise='snr10', orate=3, model=True, flood=0.0, drop=False, barge=0.0),
    'L5': dict(n=5, alt=0.5, repeat=0.9, stumble=0.35, intro=0.35, cond=0.35, noise='snr10', orate=3, model=True, flood=0.3, drop=True, barge=0.25),
}
STUMBLES = ('first', 'mid', 'filler', 'restart', 'stretch', 'last')
OTHERS = 'chatter:3,tv:1,aside:2,laugh:1,door:1'
CLEAN_MODEL_S = 3.5                         # the slowest first text of a model with no fault (L0-L3), under fast_text.FIRST_TEXT_S
WAIT = ANSWER_WAIT_SECONDS + 3.5            # how long the owner waits for an answer before the next question (the score's bound)
CONDITIONAL = [(t, a) for t, a in P.BANK['yesno']]


# =====================================================================================================================================
# the bank: the real rows, the questions the ladder asks from them, one index for the whole process
# =====================================================================================================================================

_BANK = {}


def bank():
    """(rows, the index ``instant.Instant`` over them, the askable (question, row) pairs). Askable: a question or an alternative that only its own row has."""
    if not _BANK:
        from echo_sync import instant
        rows = []
        for path in sorted(glob.glob(str(ROOT / 'cloud_context' / 'bank' / 'merged' / '*.json'))):
            rows += json.loads(open(path, encoding='utf-8').read())
        rows = [r for r in (instant.clean_entry(x) for x in rows) if r]
        index = instant.Instant(rows)
        owners = {}
        for n, r in enumerate(rows):
            for text in [r['q']] + list(r['alt']):
                owners.setdefault(normalize(text), set()).add(r['answer'])
        main = [(r['q'], r) for r in rows if len(owners[normalize(r['q'])]) == 1]
        alts = [(t, r) for r in rows for t in r['alt'] if len(owners[normalize(t)]) == 1 and len(t.split()) <= 18]
        _BANK.update(rows=rows, index=index, main=main, alts=alts)
    return _BANK['rows'], _BANK['index'], _BANK['main'], _BANK['alts']


class Mind(sim.Mind):
    """The rehearsal's ideal mind, which also knows a question when its words come trimmed («а», «слушай» cut by the engine, a word lost by the ear): the nearest
    question it learned, by the words they share (a real model understands those; the a1 mind found only the exact text or a learned text inside it)."""

    def read(self, text):
        got = super().read(text)
        if got is not None:
            return got
        import difflib
        said = normalize(text)
        if len(said.split()) < 2:
            return None
        best = max(((difflib.SequenceMatcher(None, said.split(), key.split()).ratio(), meaning) for key, meaning in self.meant.items()
                    if meaning[0] in ('q', 'fix') and key), key=lambda row: row[0], default=(0, None))
        return best[1] if best[0] >= 0.75 else None


# =====================================================================================================================================
# the scene
# =====================================================================================================================================

class Scene(sim.Rehearsal):
    def __init__(self, level, seed, *, flags=None):
        self.level, self.k = level, KNOBS[level]
        k = self.k
        line = f'{level} | min=6 noise={k["noise"]}' + (f' others={OTHERS} orate={k["orate"]}' if k['orate'] else '')
        self._index = bank()[1]
        super().__init__(sim.Spec(f'ladder-{level}', line), seed, flags={**CANDIDATE, **(flags or {})})
        self.rng = random.Random(f'ladder-{level}-{seed}')
        self.out.profile['rehearsal'] = level
        self.mind = Mind()
        self.script = self._questions()
        self.step = 0                         # the next question of the script
        self.asking = None                    # the last question asked (``Said``)
        self.repeated = set()                 # the cues the owner has repeated: (revision, index)
        self.repeats = 0                      # repeats of the current answer
        self.dropped, self.pause_at = False, None
        self.finished = None
        if k['drop']:
            self.later(self.rng.uniform(12.0, 50.0), self.drop, call=None)

    def _attach(self):
        super()._attach()
        index = getattr(self, '_index', None)
        if index is not None and self.settings.get('instant') == 'on':
            index.reset()
            self.w.controller.instant = index

    def _questions(self):
        r, k = self.rng, self.k
        _, _, main, alts = bank()
        out = []
        for n in range(k['n']):
            if r.random() < k['cond']:
                if r.random() < 0.5:
                    text, reply = r.choice(CONDITIONAL)
                    q = P.Fact('yesno', (text,), text, reply)
                else:
                    q = sim.classic(r, r.choice(('money', 'verb')))
            else:
                text, row = r.choice(alts if r.random() < k['alt'] else main)
                q = P.Fact('bank', (text,), text, row['answer'])
            out.append(q)
        return out

    # -- the owner and the friend ---------------------------------------------------------------------------------------------------
    def decide(self):
        r, k, now = self.rng, self.k, self.now()
        if self.finished is not None:
            return
        playing = self.w.open is not None and not self.w.open.diagnostic
        u = self.asking
        if u is not None:
            mine = [c for c in self.w.cues if not c.diagnostic and c.t - self.zero > u.onset]
            if not mine:
                if now - u.offset < WAIT:
                    return self.later(now + 0.3, self.decide, call=None)
            else:
                cue = mine[-1]
                key = (cue.snap.get('revision'), cue.snap.get('index'))
                chunks = cue.snap.get('chunks') or ()
                if k['repeat'] and key not in self.repeated and self.repeats < 4 and r.random() < k['repeat'] ** (1 if self.repeats else 0.2):
                    if playing:
                        return self.later(now + 0.2, self.decide, call=None)
                    self.repeated.add(key)
                    self.repeats += 1
                    text = cue.text
                    if r.random() < k['stumble']:
                        text = self.stuttered(cue.text, r.choice(STUMBLES))
                    self.utter('repeat' if text == cue.text else 'stutter', text, None, 'user', cue, False)
                    return self.later(self.said[-1].offset + r.uniform(0.6, 2.5), self.decide, call=None)
                if k['repeat'] and key in self.repeated and (cue.snap.get('index') or 0) + 1 < len(chunks) and self.repeats < 4 and now - (cue.t - self.zero) < 6.0:
                    return self.later(now + 0.3, self.decide, call=None)                    # the next portion is coming
                if playing and r.random() > k['barge']:
                    return self.later(now + 0.2, self.decide, call=None)
                if not playing:
                    if self.pause_at is None:
                        self.pause_at = now + r.uniform(2.5, 6.0)                # a pause after the answer before the next question
                    if now < self.pause_at:
                        return self.later(self.pause_at, self.decide, call=None)
        if self.step >= len(self.script):
            self.finished = now
            self.length = min(self.length, now + WAIT + 2.0)
            return
        q = self.script[self.step]
        self.step += 1
        text = q.text
        if r.random() < self.k['intro']:
            text = r.choice(P.INTROS) + ' ' + text
        self.current, self.repeats, self.pause_at = q, 0, None
        self.utter('question', text, ('q', q), 'friend', None, playing)
        self.asking = self.said[-1]
        if self.step < len(self.script) and r.random() < k['flood']:
            gap = r.uniform(0.3, 2.0)                                            # the next question at once: this one is no longer owed
        else:
            gap = r.uniform(1.0, 4.0)
        self.later(self.said[-1].offset + gap, self.decide, call=None)

    def heard_by_ear(self, text, kind, exact=False):
        """A number written in groups («2 979 000», «300 000») is said as one number: the rehearsal spelt each group alone («два девятьсот семьдесят девять ноль»),
        a number nobody says (a stand fault: L2 seed 25, the ear's veto of a repeat said right)."""
        text = re.sub(r'\b\d{1,3}(?:[ \u00a0]\d{3})+\b', lambda m: re.sub(r'\s', '', m.group()), text)
        text = re.sub(r'(?<=\d\.)0(\d)\b', r' ноль \1', text)          # «60.02» is «шестьдесят ноль два», not «шестьдесят два» (62): L2 seed 20
        return super().heard_by_ear(text, kind, exact)

    def drop(self):
        """The link drops for 2-5 s and the call comes back (Р073)."""
        self.dropped, self.down = True, True
        self.lines.append((round(self.now(), 2), 'FAULT drop'))
        self.out.reconnects.append(round(self.now(), 2))

        def back():
            self.down = False
            self.reconnect()
        self.later(self.now() + self.rng.uniform(2.0, 5.0), back, call=None)

    def _born(self, job, thread):
        """The model's first text: on the levels without model faults (L0-L3) no slower than ``CLEAN_MODEL_S`` (the log-normal's tail of 9 s is a fault of the model, L4 on)."""
        if self.k['model']:
            return super()._born(job, thread)
        draw = sim.lognormal
        sim.lognormal = lambda r, median, p90: min(draw(r, median, p90), CLEAN_MODEL_S)
        try:
            return super()._born(job, thread)
        finally:
            sim.lognormal = draw

    def play(self):
        old = sim.FAIL_P, sim.TAIL_P
        if not self.k['model']:
            sim.FAIL_P, sim.TAIL_P = 0.0, 0.0
        try:
            return super().play()
        finally:
            sim.FAIL_P, sim.TAIL_P = old


# =====================================================================================================================================
# the verdict
# =====================================================================================================================================

ORDER = ('crash', 'wrong', 'old_answer', 'missed', 'false_cue', 'false_step', 'lost_place', 'two_answers', 'over_speech', 'chatter', 'mixed')
STAND = ('unheard',)


def plan_of(c):
    return ' '.join(c[4])


def verdict(out):
    """The faults of one scene, worst first: [(kind, t, what, cause)]. Empty: the scene passed. ``unheard``: the stand's own (no ear, no cloud had the question)."""
    found = []

    def add(kind, t, what):
        found.append((kind, t, what, score.cause(out, t)))
    if out.crash:
        add('crash', 0.0, out.crash.strip().split('\n')[-1][:200])
    cues = [c for c in out.cues if not c[6]]
    asked = [u for u in out.said if u.kind == 'question' and getattr(u, 'who', '') == 'friend']
    for n, u in enumerate(asked):
        nxt = asked[n + 1].onset if n + 1 < len(asked) else float('inf')
        if nxt - u.offset < WAIT and nxt != float('inf'):
            continue                                                             # the next came at once (L5 flood): this one is not owed
        if any(t > u.onset - 1.0 and t < u.offset + WAIT for t in out.reconnects):
            continue                                                             # the link was down while it was owed (L5 drop): reported by the call, not owed
        q = u.meaning[1]
        mine = [c for c in cues if u.onset < c[0] < nxt + 0.5]
        if u.final_at is None and (u.ear_at is None or not u.ear.strip()):
            if not any(q.fits(plan_of(c)) for c in mine):
                add('unheard', u.offset, f'question {u.n} {u.text!r}: neither the ear nor the cloud had it')
            continue
        if any(q.fits(plan_of(c)) for c in mine):
            continue
        if mine:
            add('wrong', mine[0][0], f'question {u.n} {u.text!r} (ear {u.ear!r}) got {plan_of(mine[0])[:140]!r}, not {q.answer()[:80]!r}')
        else:
            add('missed', u.offset + WAIT, f'question {u.n} {u.text!r} (ear {u.ear!r}, final@{u.final_at}): no cue')
    m, eps = score.board(out)
    for e in eps:
        if e['kind'] in ('false_cue', 'lost_place', 'old_answer'):
            found.append((e['kind'], e['t'], e['what'], e['cause']))
    for t, what in false_steps(out):
        add('false_step', t, what)
    names = {'A1': 'two_answers', 'A6': 'over_speech', 'A8': 'chatter', 'A9': 'mixed', 'A7': 'wrong'}
    for inv, t, msg in out.violations:
        if inv in names:
            add(names[inv], t, msg)
    rank = {k: n for n, k in enumerate(ORDER + STAND)}
    return sorted(found, key=lambda f: (rank.get(f[0], 99), f[1]))


def false_steps(out):
    """Every advance of the cursor needs a repeat-like utterance of the owner since the portion was said: the EARLIEST one not yet used (``score.board`` takes
    the latest of the window, and a state row sampled a tick late puts the next repeat into the window of the step before: L2 seed 1, #13 and #14 each
    moved the cursor once and the second step was counted false)."""
    cues = [c for c in out.cues if not c[6]]
    last, used, found = {}, set(), []
    for t, rev, index, completed, waiting, hearing, call in out.states:
        if rev is None or index is None:
            continue
        before = last.get(rev)
        if before is not None and index == before[1] + 1:
            spoken = [c for c in cues if c[2] == rev and c[3] == before[1] and c[0] <= t]
            since = spoken[0][0] if spoken else before[0]
            own = [u for u in out.said if since - 0.5 < u.onset <= t and u.n not in used and u.kind in score.ADVANCING and getattr(u, 'who', 'user') != 'other']
            if own:
                used.add(own[0].n)
            else:
                others = [u for u in out.said if since - 0.5 < u.onset <= t]
                found.append((t, f'revision {rev}: {before[1]} -> {index} with no repeat of the owner since {since}; said: '
                                 + '; '.join(f'{u.kind}/{getattr(u, "who", "")} {u.text[:40]!r}' for u in others[-3:])))
        last[rev] = (t, index)
    return found


def scene(level, seed, flags=None):
    """One scene: (passed, the faults, the seconds to the first fitting cue of each question)."""
    st = Scene(level, seed, flags=flags)
    out = _play(st)
    faults = verdict(out)
    product = [f for f in faults if f[0] not in STAND]
    return {'level': level, 'seed': seed, 'passed': not product, 'stand': [f for f in faults if f[0] in STAND], 'faults': product, 'out': out}


def _play(st):
    """``sim.play`` for a scene already made: the controller's log lines kept for the first cause."""
    import logging
    lines = []

    class Catch(logging.Handler):
        def emit(self, record):
            lines.append((round(st.now(), 2), record.getMessage()[:200]))
            if len(lines) > 4000:
                del lines[:2000]
    handler, root = Catch(level=logging.INFO), logging.getLogger()
    level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    try:
        try:
            st.play()
        except Exception as error:                     # noqa: BLE001 - a crash of the chain is a finding
            import traceback
            st.out.crash = ''.join(traceback.format_exception(error))[-1500:]
            st.out.violations.append(('A0', round(st.now(), 2), f'{type(error).__name__}: {error}'[:300]))
            st._collect()
    finally:
        st.close()
        root.removeHandler(handler)
        root.setLevel(level)
    out = st.out
    out.violations += A.check(out)
    out.ctl = lines
    out.stand_lines = st.lines
    out.cancelled = {}
    return out


def first_word(text):
    return re.split(r'\W+', text.strip())[0] if text.strip() else ''

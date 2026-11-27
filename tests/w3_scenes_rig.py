"""w3-scenes: the scenes of scenarios_n1.json / scenarios_n2.json through the REAL ControlledMedia, on the stand of tools/replay (branch claude/a1-fuzz).

REAL: ControlledMedia, NativeMediaSocket, the ShadowEar and the FastText channel (as ``tools.replay.stand.Stand`` builds them). SCRIPTED: the speech detector, the ear's worker, the cloud's user
turns (always announced, 0.5-1.5 s late, none lost, no cloud chatter), the text model: ``Mind`` returns the REFERENCE of the step (``gold.answer`` of an ask step; the answer of the ask
before it for a doubt / clarification; ``[стоп]`` / ``[продолжай]`` for a command; ``—`` where the step expects no sound). Nothing here is a measurement of time on a laptop or a phone.

``play(scene)`` -> a list of ``Row`` (one per step): what sounded, where the cursor went, and the verdict of each expectation of the step (``verdict``).
Reference error and product error are kept apart: ``ref`` is a defect of the scene (its own reference does not satisfy its own expectation, or gives the model no text to say),
``product`` is what the controller did against a sound reference, ``unknown`` is what a text stand cannot judge (live judge, sound, overlap).
"""
import json
import logging
import random
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'cloud_context' / 'scripts'
if not (SCRIPTS / 'scenario_common.py').exists():      # RED-C: an import error at collection in a checkout without cloud_context/scripts
    import pytest
    pytest.skip('data outside the repository: cloud_context/scripts/ (not in git; the loud check is tests/test_p14_context_guard.py)', allow_module_level=True)
for _path in (str(SCRIPTS), str(ROOT / 'tests'), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import scenario_common as sc                                                          # noqa: E402
import voice_probe_checks as vc                                                       # noqa: E402
from echo_sync.textutil import normalize                                              # noqa: E402
from tools.replay import stand as T                                                   # noqa: E402

CORPUS = SCRIPTS / 'corpus'
FILES = ('scenarios_n1.json', 'scenarios_n2.json')
PROFILE = {'local_ear': 'act', 'fast_text': 'on'}
CLOUD, JOB = (0.5, 1.5), (0.4, 1.0)
UNCHECKED = ('useful', 'lookup', 'recognized')                    # a live judge / a search / the recognizer: not in a text stand
STOP_WORDS = re.compile(r'(?i)^\W*(стоп|стой|хватит|погоди|подожди)')


def load():
    """[(file, scene)] of both files, in file order."""
    out = []
    for name in FILES:
        for scene in json.loads((CORPUS / name).read_text(encoding='utf-8'))['scenarios']:
            out.append((name, scene))
    return out


class Ref:
    """The meaning the stand hands the ideal mind: ``text`` as said, ``answer()`` what the model replies."""

    def __init__(self, text, answer):
        self.text, self._answer = text, answer

    def answer(self):
        return self._answer


class FuzzyMind(T.Mind):
    """The ideal mind also knows an utterance the product handed it trimmed («Ну и, под конец…» -> «под конец…») or joined to a neighbour."""

    def read(self, text):
        found = super().read(text)
        said = normalize(text)
        if found is None and len(said) >= 12:
            part = [(len(key), meaning) for key, meaning in self.meant.items() if meaning[0] in ('q', 'fix') and said in key]
            found = max(part, key=lambda row: row[0])[1] if part else None
        return found


class Rig(T.Stand):
    """The stand with nobody deciding: the scene says what is spoken and when."""

    def __init__(self, seed=0, *, profile=None, cloud=CLOUD, job=JOB):
        super().__init__(seed, length=1e9, profile=dict(profile or PROFILE), cloud=cloud, job=job, faults=False)
        self.mind = FuzzyMind()

    def decide(self):
        pass

    def heard_by_ear(self, text, kind, exact=False):
        words = re.findall(r'[\w-]+', text.lower().replace('ё', 'е'))
        return ' '.join(T.spell(int(w)) if w.isdigit() else w for w in words)

    def run_to(self, t):
        while self.now() < t:
            while self.agenda and self.agenda[0][0] <= self.now() + 1e-9:
                _, _, call, action = T.heapq.heappop(self.agenda)
                if call is None or call == self.call:
                    action()
            self._packet()
            self.w.advance(T.TICK, step=T.TICK)
            self._sample()

    def run_for(self, seconds):
        self.run_to(self.now() + seconds)

    def run_until(self, done, limit):
        """Run until ``done()`` or ``limit`` seconds; True if done."""
        end = self.now() + limit
        while self.now() < end:
            if done():
                return True
            self.run_for(T.TICK)
        return done()

    def _utter(self, u):
        """Like Stand._utter, with nothing random: the cloud announces every turn, finishes it ``cloud`` s after it ended, says nothing of its own."""
        r = self.rng
        uid = f'u{u.n}'
        box = {}
        self.later(u.onset, lambda: self.steps.append(('onset', box)))
        self.later(u.offset, lambda: self.steps.append(('end', box)))

        def text():
            if box.get('ear') is not None:
                u.ear_at = round(self.now(), 2)
                self.worker.heard(box['ear'], u.ear)
        self.later(u.offset + r.uniform(0.1, 0.5), text)
        words = u.text.split()
        created = u.onset + r.uniform(0.2, 1.0)

        def created_now():
            u.created_at = round(self.now(), 2)
            head = self.ms(u.onset) // 200 * 200
            self._feed({'type': 'turn.created', 'turn': {'id': uid, 'role': 'user', 'transcript': words[0], 'start_ms': head, 'end_ms': head + 200}})
        self.later(created, created_now)
        for n, word in enumerate(words[1:]):
            at = created + (u.offset - created) * (n + 1) / len(words)
            self.later(at, lambda word=word, n=n: self._feed({**T.S.turn_delta(uid, ' ' + word, 0), **self.span(u, n + 1, len(words))}))
        final = max(u.offset + r.uniform(*self.cloud), self.last_final + 0.05)
        self.last_final = final

        def done():
            u.final_at = round(self.now(), 2)
            event = T.S.turn_done(uid, 'user', u.text)
            event['turn'].update(start_ms=self.ms(u.onset) // 200 * 200, end_ms=-(-self.ms(u.offset) // 200) * 200)
            self._feed(event)
        self.later(final, done)

    # -- what the listener does ----------------------------------------------------------------------------------------------------
    def closed_until(self):
        """Conversation second until which the phone's microphone is closed under the last cue: it plays (``voice``: 0.5 s) and the phone keeps the microphone closed 0.35 s after it."""
        last = self.cues(0)
        return (last[-1].t - self.zero + 0.5 + 0.35) if last else 0.0

    def utter(self, text, kind, meaning=None, *, at=None, seconds=None, lossy=False):
        """The listener says ``text`` from ``at`` (default: now, once the last utterance is over). -> the Said.
        ``lossy``: the words begun while the microphone is closed under a cue never reach the ear or the cloud (the detector's onset is the moment it reopens)."""
        if lossy:
            words, onset = text.split(), max(self.now() + 0.1, self.free, at or 0.0)
            length = seconds or max(0.6, len(words) * 0.33)
            closed = self.closed_until()
            gone = sum(1 for k in range(len(words)) if onset + k * length / len(words) < closed)
            if gone:
                text = ' '.join(words[gone:])
                seconds, at = max(0.3, length * (len(words) - gone) / len(words)), max(onset, closed)
                if not text:
                    return None
        ear = self.heard_by_ear(text, kind)
        if meaning:
            for said in {text, ear, meaning[1].text if meaning[0] == 'q' else text}:
                self.mind.learn(said, meaning)
                self.mind.learn(self.heard_by_ear(said, kind, exact=True), meaning)
        onset = max(self.now() + 0.1, self.free, at or 0.0)
        length = seconds or max(0.6, len(text.split()) * 0.33)
        u = T.Said(len(self.said) + 1, kind, text, ear, round(onset, 2), round(onset + length, 2), meaning=meaning, call=self.call)
        self.said.append(u)
        if kind in ('question', 'fix'):
            self.current, self.stopped, self.following = meaning[1], False, True
        elif kind == 'stop':
            self.stopped = True
        elif kind in ('again', 'resume'):
            self.stopped = False
        self.free = u.offset + 0.15
        self._utter(u)
        return u

    def cues(self, since=0.0):
        """The sounded cues (not the diagnostics) begun after ``since`` (conversation seconds)."""
        return [c for c in self.w.cues if not c.diagnostic and c.t - self.zero > since]

    def snapshot(self):
        s = self.w.controller.state() or {}
        return {'revision': s.get('revision'), 'index': s.get('chunk_index'), 'completed': bool(s.get('completed')), 'chunks': list(s.get('chunks') or ()),
                'answer': s.get('answer') or '', 'question': s.get('question'), 'streaming': bool(s.get('streaming')), 'waiting': bool(s.get('stream_waiting_next'))}

    def idle(self):
        return self.w.open is None

    def settle(self, seconds, limit=40.0):
        """Let the current cue end and ``seconds`` of quiet pass."""
        self.run_until(self.idle, limit)
        self.run_for(seconds)

    def close(self):
        super().close()


# =====================================================================================================================================
# a scene, step by step
# =====================================================================================================================================

@dataclass
class Row:
    scene: str
    n: int
    op: str
    label: str
    skipped: str = None
    cues: list = field(default_factory=list)          # (t, text, revision, index) of the cues that sounded in the step
    before: dict = None
    after: dict = None
    failures: list = field(default_factory=list)      # (check, message) the expectation did not hold
    ref: list = field(default_factory=list)           # (check, message) the reference itself breaks (the scene's fault)
    unchecked: list = field(default_factory=list)
    checked: list = field(default_factory=list)       # the checks that held
    spoken: str = ''
    log: list = field(default_factory=list)            # the controller's decision lines during the step
    material: bool = False                             # the answer comes from a prepared material the profile of this stand does not hold
    reference: str = None                              # the text the model was given to say
    cascade: str = None                                # the step before it failed: this one is judged on a state that step spoilt

    @property
    def verdict(self):
        if self.skipped:
            return 'cascade' if self.skipped.startswith('cascade') else 'na' if self.skipped.startswith('n/a') else 'unknown'
        if self.material and self.product:
            return 'unknown'
        if self.cascade and self.product:
            return 'cascade'
        if self.product:
            return 'product'
        if self.failures:
            return 'ref'                                              # every failure is one the reference itself explains
        return 'match'

    @property
    def product(self):
        """The failures the reference does not explain: a check the reference itself breaks is the scene's, not the controller's."""
        blamed = {name for name, _ in self.ref}
        if 'reference_text' in blamed:
            blamed |= {'says', 'says_cue', 'plan_covers'}
        return [f for f in self.failures if f[0] not in blamed]


def hit(pattern, text):
    """The stems of an expectation in a text: «48000» is in «48 000» too (a number grouped by thousands is one number)."""
    text = normalize(text)
    return re.search(pattern, text) is not None or re.search(pattern, re.sub(r'(?<=\d) (?=\d{3}\b)', '', text)) is not None


def case_of(spec):
    found = re.search(r'\[случай: (\w+)\]', spec.get('note', ''))
    return found.group(1) if found else None


def spoken_parts(spec):
    """[(text, pause_before_s)] of an ask / say step."""
    if 'parts' in spec:
        out, pause = [], 0.0
        for part in spec['parts']:
            if 'pause_ms' in part:
                pause = part['pause_ms'] / 1000
            else:
                out.append((part['text'], pause))
                pause = 0.0
        return out
    return [(spec['text'], 0.0)] if 'text' in spec else []


def reference(spec, last_ask):
    """The text the ideal model answers for a step with a sound, and what is wrong with it. -> (kind, answer, fault)
    kind: 'q' (answer), 'stop', 'resume', 'none' (the model says «—»). ``fault``: the reference gives nothing to say / says what the step forbids."""
    expect, text, case = spec['expect'], ' '.join(t for t, _ in spoken_parts(spec)), case_of(spec)
    if expect.get('audio') == 'none':
        return ('stop' if case == 'stop' or (spec['op'] == 'say' and STOP_WORDS.match(text)) else 'none'), None, None
    if 'resumes' in expect:
        return 'resume', None, None
    gold = spec.get('gold', {}).get('answer')
    needs = list(expect.get('says_cue') or []) + list(expect.get('says') or [])
    if spec['op'] == 'ask' and gold:
        return 'q', gold, None
    if spec['op'] == 'repeat_current':
        return 'none', None, None
    # a doubt, an objection, a clarification, «why», an example: the model says again what the plan said (the previous ask's reference), and it has to carry the stems
    if last_ask is not None and all(hit(p, ' '.join(last_ask.split()[:14])) for p in needs):
        return 'q', last_ask, None
    return 'q', last_ask, 'the reference gives the model no text that carries ' + repr(needs) if needs else None


class Capture(logging.Handler):
    """The controller's own log lines of a step (decisions, failures): the evidence of the first cause of a mismatch."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        text = record.getMessage()
        if text.startswith('echo-sync') and (' decision ' in text or ' failure ' in text or ' ear ' in text or 'fast_text' in text):
            self.lines.append(text[len('echo-sync '):][:170])


class Scene:
    """One scene on a fresh Rig."""

    def __init__(self, name, scene, rig=None, *, only=None):
        self.name, self.scene = name, scene
        self.rig = rig or Rig()
        self.rows, self.asks, self.last_ask, self.left, self.previous_failed, self.spoilt = [], {}, None, {}, None, False
        self.newest, self.newest_revision = [], -1
        self.last_plan, self.cursor = None, {}                       # the first portion names a plan; where its cursor stood at the end of the last step that held it
        self.only = only

    # -- driving ---------------------------------------------------------------------------------------------------------------------
    def play(self):
        try:
            for n, spec in enumerate(self.scene['steps'], 1):
                if self.only and n not in self.only:
                    continue
                self.rows.append(self.step(n, spec))
        finally:
            self.rig.close()
        return self.rows

    def step(self, n, spec):
        capture = Capture()
        root = logging.getLogger()
        was = root.level, logging.root.manager.disable
        root.addHandler(capture)
        root.setLevel(logging.INFO)
        logging.disable(logging.NOTSET)
        try:
            row = self.run_step(n, spec)
        finally:
            root.removeHandler(capture)
            root.setLevel(was[0])
            logging.disable(was[1])
        row.log = capture.lines
        if row.product and 'материал' in str(spec.get('gold', {}).get('source', '')) and 'material' in self.scene:
            row.material = True
        return row

    def run_step(self, n, spec):
        rig, op = self.rig, spec['op']
        row = Row(self.scene['id'], n, op, sc.step_label(spec))
        if spec.get('unrunnable_by_text') is True:
            row.skipped = 'the step needs real overlap / loudness (unrunnable_by_text)'
            return row
        if op == 'replay_server_audio':
            row.skipped = "the own voice returning to the microphone: a text stand has no sound; what it takes for speech is the ear's / the cloud's text, which this stand writes itself"
            return row
        row.before = rig.snapshot()
        mark = self.mark = rig.now()
        if op == 'silence':
            rig.run_for(float(spec['seconds']))
            row.cues = self.new(mark, row)
        elif op == 'expect':
            rig.run_for(float(spec.get('settle_s', 5)))
            row.cues = self.new(mark, row)
        elif op in ('ask', 'say'):
            self.speak(n, spec, row, mark)
        elif op == 'repeat_current':
            if not self.repeat(n, spec, row, mark):
                return row
        row.after = rig.snapshot()
        self.check(n, spec, row, mark)
        if row.after['chunks']:
            if row.after['revision'] is not None and row.after['revision'] >= self.newest_revision:
                self.newest, self.newest_revision = list(row.after['chunks']), row.after['revision']
            self.last_plan = row.after['chunks'][0]
            self.cursor[self.last_plan] = row.after['index'] or 0
        if self.previous_failed and (op == 'expect' or op == 'repeat_current' and self.spoilt):
            row.cascade = self.previous_failed
        if op != 'expect':
            self.previous_failed = row.label + f' (step {n})' if row.product else None
            self.spoilt = any(f[0] in ('audio', 'new_responses', 'cue_bound', 'resumes') for f in row.product)             # no plan to repeat, or another one
        return row

    def new(self, mark, row):
        return [(round(c.t - self.rig.zero, 2), c.text, c.snap.get('revision'), c.snap.get('index')) for c in self.rig.cues(mark)]

    def speak(self, n, spec, row, mark):
        rig, expect = self.rig, spec['expect']
        parts = spoken_parts(spec)
        kind, answer, fault = reference(spec, self.last_ask)
        row.reference = answer
        if fault:
            row.ref.append(('reference_text', fault))
        said, onset = [], None
        barge = spec.get('barge_in')
        for k, (text, pause) in enumerate(parts):
            last = k == len(parts) - 1
            at = rig.now() + pause if k else None
            if k == 0 and barge and rig.cues(rig.now() - 30):
                at = max(rig.cues(rig.now() - 30)[-1].t - rig.zero + barge['delay_ms'] / 1000, rig.now())
            if k == 0 and not barge:
                rig.settle(0.3)
            meaning = None
            if last and kind == 'q' and answer:
                meaning = ('q', Ref(text, answer))
            elif last and kind in ('stop', 'resume'):
                meaning = ('cmd', kind)
            said.append(rig.utter(text, 'question' if meaning and meaning[0] == 'q' else kind if kind in ('stop', 'resume') else 'chatter', meaning, at=at))
            if not last:
                rig.run_to(said[-1].offset + 0.01)
        then = spec.get('then')
        if then:                                                      # a repeat and, in the same breath, the next question
            pass
        row.spoken = ' '.join(s.text for s in said)
        end = said[-1].offset
        window = float(spec.get('window_s') or 6)
        if expect.get('audio') == 'none':
            rig.run_to(end + window + 3.0)
        else:
            limit = float(spec.get('max_s') or 25)
            rig.run_until(lambda: bool(rig.cues(end - 0.0)) or bool(rig.cues(mark)) and rig.now() > end + 3, limit + (end - rig.now()))
            rig.settle(4.0)
        row.cues = self.new(mark, row)
        row.after = rig.snapshot()
        self.said_end = end
        if kind == 'q' and spec['op'] == 'ask' and answer:
            self.last_ask = answer
            self.asks[n] = row.after
        if self.asks.get(n) is not None:
            self.left[row.after['revision']] = row.after['index']

    def repeat(self, n, spec, row, mark):
        rig = self.rig
        rig.settle(0.5)
        mark = self.mark = rig.now()
        row.before = rig.snapshot()
        cur = [c for c in rig.cues(0) if c.snap.get('revision') == row.before['revision']]
        current = cur[-1].text if cur else None
        if not current:
            row.skipped = 'cascade: no portion of the present plan has sounded (the step before did not get its answer)'
            return False
        said = sc.repeat_text(current, spec['variant'])
        if said is None:
            row.skipped = 'n/a: the variant does not apply to this portion (no number / adjective / negation / compound number in it)'
            return False
        pieces = list(said) if isinstance(said, tuple) else [said]
        then = spec.get('then')
        if then:
            pieces[-1] = sc.with_tail(pieces[-1], then)
        meaning, kind = None, 'repeat'
        if then:
            _, answer, fault = reference(spec, self.last_ask)
            gold = spec.get('gold', {}).get('answer')
            answer = gold if gold and not gold.startswith(('Повтор', 'Порция')) else None
            if answer:
                meaning, kind = ('q', Ref(then, answer)), 'question'
            else:
                row.ref.append(('reference_text', 'a repeat with a new question in its tail, and the step has no reference answer for the question'))
        said_objs = []
        for k, piece in enumerate(pieces):
            if k:
                rig.run_to(said_objs[-1].offset + (spec.get('pause_ms') or 500) / 1000)
            u = rig.utter(piece, kind, meaning if k == len(pieces) - 1 else None)
            u.cue = (current, row.before['revision'], row.before['index'])
            said_objs.append(u)
        row.spoken = ' | '.join(pieces)
        end = said_objs[-1].offset
        limit = float(spec.get('max_s') or 20)
        if sc.is_advancing(spec['variant']):
            rig.run_until(lambda: any(c.t - rig.zero > end - 0.5 and c.text != current for c in rig.cues(mark)), limit + 3)
        else:
            rig.run_to(end + float(spec.get('window_s') or 6) + 3.0)
        rig.settle(3.0)
        row.cues = self.new(mark, row)
        self.said_end = end
        self.repeat_current = current
        return True

    # -- the expectations ------------------------------------------------------------------------------------------------------------
    def check(self, n, spec, row, mark):
        e, op = spec['expect'], spec['op']
        cues, b, a = row.cues, row.before, row.after
        texts = [c[1] for c in cues]
        ok, bad = row.checked, row.failures

        def verdict(name, held, message):
            ok.append(name) if held else bad.append((name, message))
        for name in UNCHECKED:
            if name in e:
                row.unchecked.append(name)
        plan = ' '.join(a['chunks'])
        if 'audio' in e:
            if e['audio'] == 'none':
                waiting = {normalize(c) for c in b['chunks']}                      # the timer repeats the waiting portion by design (a silence step allows it too)
                other = [t for t in texts if normalize(t) not in waiting]
                verdict('audio', not other, f'sound where none was expected: {other[:3]}')
            else:
                verdict('audio', bool(cues), 'no sound within the window')
        first = texts[0] if texts else ''
        if 'says_cue' in e:
            held = all(hit(p, first) for p in e['says_cue']) if cues else False
            verdict('says_cue', held, f'first sound {first!r} lacks {e["says_cue"]}')
            self.ref_check(spec, row, 'says_cue', e['says_cue'])
        if 'says' in e:
            have = ' '.join(texts + a['chunks'][:2])
            verdict('says', all(hit(p, have) for p in e['says']), f'sound {texts[:3]} lacks {e["says"]}')
            self.ref_check(spec, row, 'says', e['says'])
        cursor_text = normalize(b['chunks'][b['index']]) if b['chunks'] and b['index'] is not None and b['index'] < len(b['chunks']) else None
        for pattern in e.get('says_not') or ():
            bad_texts = [t for t in texts if hit(pattern, t)]
            if bad_texts and cursor_text and all(normalize(t) == cursor_text for t in bad_texts) and op == 'say':
                row.ref.append(('says_not', f'the expectation forbids words ({pattern[:30]}) that are in the portion at the cursor itself, {bad_texts[0]!r}, which a return has to sound'))
            verdict('says_not', not bad_texts, f'sound {bad_texts[:2]} says what is forbidden: {pattern[:40]}')
        if 'new_responses' in e:
            revs = {c[2] for c in cues if c[2] is not None and c[2] != b['revision']}
            verdict('new_responses', len(revs) == e['new_responses'], f'{len(revs)} new answers sounded, expected {e["new_responses"]}: {sorted(revs)}')
        if e.get('no_stale_audio'):
            end = getattr(self, 'said_end', 0.0)
            stale = [c for c in cues if c[2] != a['revision'] and c[0] > end - 0.01 and op != 'silence']
            if op == 'repeat_current':
                stale = [c for c in cues if c[2] is not None and b['revision'] is not None and c[2] < b['revision']]            # a tail question may open a newer plan
            verdict('no_stale_audio', not stale, f'an old answer sounded after the question: {stale[:2]}')
        if 'advance' in e:
            moved = self.advance(b, a)
            verdict('advance', moved == e['advance'], f'the cursor moved {moved}, expected {e["advance"]} (before {b["revision"]}/{b["index"]}, after {a["revision"]}/{a["index"]})')
        if e.get('ack'):
            held, why = self.ack(spec, row)
            verdict('ack', held, why)
        if 'short' in e and cues:
            limit = 9 if e['short'] is True else e['short']
            long = [t for t in texts if len(re.findall(r'\w+(?:-\w+)*', t)) > limit]          # words, not the signs between them
            verdict('short', not long, f'portion over {limit} words: {long[:1]}')
        if e.get('portion_whole') and cues:
            audit = vc.audit_portions(a['chunks'][:max(1, (cues[0][3] or 0) + 1)], complete=not a['streaming'])
            verdict('portion_whole', not audit['defects'] or all(d not in ('dangling_end', 'number_split', 'sentence_crossing') for d in map(str, audit['defects'])), f'first portion not whole: {audit["defects"]}')
        if e.get('cue_bound') and cues:
            c = cues[0]
            verdict('cue_bound', c[2] == a['revision'] and c[1] in a['chunks'], f'first sound {c[1]!r} (revision {c[2]}) is not of the plan of this question (revision {a["revision"]})')
        if e.get('answer_after_last_part') and cues:
            verdict('answer_after_last_part', cues[0][0] >= self.said_end - 0.01, f'the answer began at {cues[0][0]} before the last part ended at {self.said_end}')
        if 'resumes' in e:
            plan_state = self.asks.get(e['resumes'])
            key = plan_state['chunks'][0] if plan_state and plan_state['chunks'] else None
            same = key is not None and bool(a['chunks']) and a['chunks'][0] == key
            present = key is not None and (b['chunks'][:1] == [key] if b['chunks'] else self.last_plan == key)       # after a stop the state holds no chunks: the plan that was last
            idx = self.cursor.get(key)
            want = plan_state['chunks'][idx] if present and idx is not None and idx < len(plan_state['chunks']) else None
            held = bool(cues) and want is not None and normalize(cues[0][1]) == normalize(want) and same
            if plan_state and not present:
                row.ref.append(('resumes', f'the return is to the plan of step {e["resumes"]}, but the present plan is another one (revision {b["revision"]}, {b["chunks"][:1] or self.last_plan}): the stand\'s text model has only «[продолжай]», which goes on with the present plan, and no way to name an older one'))
            if plan_state and not held and cues and key != (self.newest[0] if self.newest else None) and cues[0][1] in self.newest:
                row.ref.append(('resumes', f'the scene wants the plan of step {e["resumes"]}; the product returned to the newest answer ({self.newest[:1]}), the only one «[продолжай]» can name in this stand'))
            verdict('resumes', held, f'resumed {cues[:1]}, the portion at the cursor of the plan of step {e["resumes"]} is {want!r} (cursor {idx}); the plan now is the same: {same}')
            if want is not None and any(hit(p, want) for p in e.get('says_not') or ()):
                row.ref.append(('says_not', f'the expectation forbids words that are in the portion at the cursor itself, {want!r}'))
        if 'plan_covers' in e:
            verdict('plan_covers', all(hit(p, plan + ' ' + a['answer']) for p in e['plan_covers']), f'plan {plan!r} lacks {e["plan_covers"]}')
            self.ref_check(spec, row, 'plan_covers', e['plan_covers'])
        if e.get('portions_well_formed'):
            audit = vc.audit_portions(a['chunks'], complete=not a['streaming'])
            verdict('portions_well_formed', bool(a['chunks']) and audit['well_formed'], f'portions {a["chunks"]}: {audit["defects"]}')
        if e.get('answer_complete'):
            verdict('answer_complete', a['completed'], f'the answer is not closed: cursor {a["index"]} of {len(a["chunks"])}')
        if e.get('alive'):
            verdict('alive', a['revision'] is not None and not self.rig.w.loop_errors and not self.rig.w.violations, f'wire: {self.rig.w.violations[:1]} {self.rig.w.loop_errors[:1]}')
        if e.get('only_current_text'):
            current = a['chunks'][a['index']] if a['chunks'] and a['index'] is not None and a['index'] < len(a['chunks']) else None
            other = [t for t in texts if current is None or normalize(t) != normalize(current)]
            verdict('only_current_text', not other, f'a text that is not the waiting portion {current!r} sounded: {other[:2]}')

    @staticmethod
    def advance(b, a):
        """How many portions the cursor went forward in the plan the step began with (a stop and a return only count the revision up; a plan begun over is not a step)."""
        same = bool(b['chunks']) and a['chunks'][:len(b['chunks'])] == b['chunks']
        if b['revision'] != a['revision'] and not same:
            return 0
        delta = (a['index'] or 0) - (b['index'] or 0)
        if delta == 0 and a['completed'] and not b['completed']:
            delta = 1                                                  # the last portion was taken: the answer is closed, the index stays
        return max(0, delta)

    def ack(self, spec, row):
        """The repeat was taken for a repeat: no new answer, no spoken failure; an advancing one also sounds the next portion."""
        b, a = row.before, row.after
        if a['revision'] != b['revision']:
            return False, f'a new answer (revision {a["revision"]}) took the place of the plan: the repeat was heard as a question'
        if [c for c in self.rig.w.cues if c.diagnostic and c.t - self.rig.zero > self.mark]:
            return False, 'a failure phrase sounded'
        if sc.is_advancing(spec['variant']) and not (a['index'] != b['index'] or a['completed'] and not b['completed']):
            return False, 'a correct repeat, and the cursor did not move'
        return True, ''

    def ref_check(self, spec, row, name, stems):
        """The reference of an ask step must itself satisfy the expectation it is judged by (the scene's fault otherwise)."""
        gold = row.reference or spec.get('gold', {}).get('answer')
        if spec['op'] not in ('ask', 'say') or not gold or row.reference is None and spec['op'] != 'ask':
            return
        if name == 'says_cue':
            first = ' '.join(gold.split()[:5])                                       # first_useful.first_cue: 2-4 words, 5 to keep a term or a number whole; it never waits for more
            if not all(hit(p, first) for p in stems):
                row.ref.append((name, f'the first 5 words of the reference {first!r} (the first cue is 2-4, at most 5 words, first_useful) do not carry {stems}'))
        elif name == 'says':
            head = ' '.join(gold.split()[:14])                                      # the first cue (5 words) and the portion after it (at most 9)
            if not all(hit(p, head) for p in stems):
                row.ref.append((name, f'the first 14 words of the reference {head!r} (a first cue and a portion) do not carry {stems}'))
        elif not all(hit(p, gold) for p in stems):
            row.ref.append((name, f'the reference {gold!r} does not carry {stems}'))


def run_scene(name, scene, **keywords):
    was = logging.root.manager.disable                                              # the quiet is scoped: left on, it silenced the INFO logs the tests after it read
    logging.disable(logging.WARNING)
    try:
        return Scene(name, scene, **keywords).play()
    finally:
        logging.disable(was)

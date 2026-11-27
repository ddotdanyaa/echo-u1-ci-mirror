"""g36: what a call must do when there is no cloud at all (06.11, 12:43 and 12:45: ``handshake operation timed out``, both calls dead in 36 s with
``controlled_upstream_unavailable``, though the bank, the laws and the material answer on the laptop in 0.6 s).

REAL: ControlledMedia, NativeMediaSocket, the ShadowEar in act mode, FastText, the bank (``instant.Instant``), the law base (``reference_kb``). SCRIPTED: the listener (what is
said and when, the ear's text of it), the cloud. Two kinds of «no cloud»:
  refused  the helper cannot be opened (``connect`` raises, as on 06.11); until ``cloud_back`` it keeps raising, after it the open works
  deaf     the helper opens and nothing ever comes back from it (no user turn, no answer): the controller's own abilities without the cloud
In both the text model is unreachable: every fast job fails at once (ConnectionError), as the OpenAI text model does without the network.

THE RULES (``check``; each violation is (rule, t, message)):
  NC1 the call opens: the readiness probe is answered, the phone's socket stays open, no 'session.updated' is withheld
  NC2 a bank question is answered: its first cue begins the bank's answer within the bound of the mode (BOUNDS) after the question
  NC3 a law question is answered the same way, from the law base
  NC4 an unknown question (or one the bank and the law base answer differently: the controller takes neither) gets ONE honest phrase (``honest``) within HONEST_S of its end: not silence, not an invented answer, not two phrases
  NC5 a repeat of the waiting portion moves to the next portion within STEP_S; a stumble (the first words, then silence) is prompted again from where it stopped
  NC6 the cloud's return does not restart the call: same controller and wire, the call never closed, the plan and its cursor kept, the helper opened within BACK_S
  NC7 the outage is told at most once: no more than one channel phrase and one channel error frame in the whole call
Nothing here measures time on a laptop or a phone: the bounds are the stand's.
"""
import asyncio
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT / 'tests'), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import helpers_s6_state as S                                                          # noqa: E402
from echo_sync import instant as I                                                    # noqa: E402
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, EAR_FIRST_BIND_SECONDS  # noqa: E402
from echo_sync.native_media_socket import LOCAL_RETRY_EVERY_S, LOCAL_PHRASES, LOCAL_RETRY_FIRST_S, UPSTREAM_OPEN_TIMEOUT_S, NativeMediaSocket  # noqa: E402
from echo_sync.reserve_text import REFUSE_AFTER_S  # noqa: E402
from echo_sync.fast_text import FIRST_TEXT_S                                          # noqa: E402
from echo_sync.diagnostics import PHRASES                                             # noqa: E402
from echo_sync.reference_kb import lookup as law_lookup                               # noqa: E402
from echo_sync.textutil import normalize                                              # noqa: E402
from tools.replay import stand as A                                                   # noqa: E402

# The bounds, after the end of the question, by mode. REFUSED: the wire KNOWS there is no cloud, so nothing waits for it: the base answers as fast as it does
# on the laptop (0.6 s) plus the ear's lag; an unknown question is told as soon as the text model has failed, a hung one has the owner's whole 8 s (``Record.model``)
# (the text model is another host than the Live channel: it is still tried). DEAF: the cloud looks open, the controller cannot
# tell it from a slow one: the bank waits EAR_FIRST_BIND_SECONDS for the cloud's turn (+1 s), the unknown question ANSWER_WAIT_SECONDS after the ear stood in.
BOUNDS = {'refused': (1.5, FIRST_TEXT_S + 1.0), 'cloud': (3.0, ANSWER_WAIT_SECONDS),
          'deaf': (EAR_FIRST_BIND_SECONDS + 1.0, ANSWER_WAIT_SECONDS)}      # hold8: no honest phrase later than 8 s after the end of the question (the ear's 4 s hold is inside it)
STEP_S = 2.0          # the next portion after a repeat
BACK_S = 60.0         # the helper is open again after the cloud came back
CHANNEL = PHRASES['channel']
STATUS = (LOCAL_PHRASES['local_opened'], LOCAL_PHRASES['local_back'])      # local mode's two status lines (the fall, the return): told once, answer no question
HONEST = re.compile(r'не знаю|нет ответа|ответа пока нет|не наш[её]л|нет связи|без связи|не могу ответить|ответа нет', re.I)

PROFILE = {'local_fallback': 'on', 'local_ear': 'act', 'prompt_tempo': 'ear', 'fast_text': 'on', 'instant': 'on', 'quick_math': 'on'}

# The bank of the scenes: rows of cloud_context/bank/instant_bank_2.json (the owner's bank), and padding so the index has a margin to judge.
BANK = [{'id': f'p{n}', 'q': f'Что такое показатель номер {n}?', 'alt': [], 'answer': f'Показатель {n}.'} for n in range(30)] + [
    {'id': 'b00000', 'q': 'Что такое бухгалтерский учёт?', 'alt': ['Дай определение бухучёта'],
     'answer': 'Формирование документированной систематизированной информации об объектах учёта и составление на её основе бухгалтерской отчётности.'},
    {'id': 'nma', 'q': 'Что такое нематериальные активы?', 'alt': [], 'answer': 'Имущество без физической формы; его стоимость переносят амортизацией.'},
]
LAW = 'Что такое статья 80 НК?'
UNKNOWN = ('Как зовут мою собаку?', 'Какая погода будет завтра в Казани?', 'Что ты думаешь о моём докладе?')


def honest(text):
    """An honest «I do not know» of a few words: no figure in it, no channel phrase (that one is NC7's), one of the known wordings."""
    text = str(text or '')
    return bool(HONEST.search(text)) and text != CHANNEL and not re.search(r'\d', text) and len(text.split()) <= 8


def words(text):
    return normalize(text).split()


def begins(cue, answer):
    """The cue is the first portion of ``answer`` (or the whole of it)."""
    c, a = words(cue), words(answer)
    return bool(c) and a[:len(c)] == c


_INDEX = {}


def index(bank):
    """The bank's index, built once per bank (``instant.from_settings`` keeps one per bank file the same way); a call takes ``for_call()`` of it."""
    key = id(bank)
    if key not in _INDEX:
        _INDEX[key] = (bank, I.Instant(bank, adapters=()))
    return _INDEX[key][1]


class StandWire(NativeMediaSocket):
    """The product's wire, with one change for the stand: the quiet retries of local mode wait on the stand's clock (a sleep of the stand's ``VirtualAsyncio`` would push the whole
    clock forward by the delay at once, and a scene of 60 s would be over in one retry)."""

    async def _local_retries(self):
        wait = LOCAL_RETRY_FIRST_S
        while not self.closed and self.local_mode:
            due = self.clock() + wait
            wait = LOCAL_RETRY_EVERY_S
            while self.clock() < due:
                if self.closed or not self.local_mode:
                    return
                await asyncio.sleep(0)
            try:
                source = await asyncio.wait_for(self.connect(), UPSTREAM_OPEN_TIMEOUT_S)
            except Exception:
                continue
            await self._leave_local(source)
            return


class Refused(S.World):
    """The helper that cannot be opened (06.11): ``connect`` raises until ``cloud_up``; the readiness probe is still sent, and whether it was answered is noted."""
    cloud_up = False
    wire_cls = StandWire
    wire_kw = {'local_fallback': True}      # c22: the product's own local mode (settings ``local_fallback`` = "on"), not the g36 proposal's NullSource

    async def _connect(self):
        self.opens = getattr(self, 'opens', 0) + 1
        if not self.cloud_up:
            raise ConnectionError('handshake operation timed out')
        return self.source

    async def _handshake(self):
        sent = len(self.frames)
        await self.wire.client({'type': 'session.update', 'session': {}})
        await self.wire.client({'type': 'response.create', 'response': {'conversation': 'none', 'input': [{'content': [{'text': 'conduit-ready-g36'}]}]}})
        marker = [f for _, _, f in self.frames[sent:] if f.get('type') == 'conduit.turn']
        if marker:
            await self.wire.client({'type': 'conduit.turn.done', 'turn_id': marker[-1]['turn_id']})
        self.opened = bool(self.wire.ready) and not self.wire.closed
        self.updated = any(f.get('type') == 'session.updated' for _, _, f in self.frames[sent:])


class Deaf(S.World):
    opened = updated = True
    wire_cls = StandWire
    wire_kw = {'local_fallback': True}


@dataclass
class Line:
    """One utterance of the listener: ``kind`` ask (``want``: bank, law, unknown) / repeat / stumble; ``ear``: what the ear wrote."""
    kind: str
    text: str
    ear: str
    onset: float
    offset: float
    want: str = None
    answer: str = None
    portion: str = None          # repeat / stumble: the portion it is of
    said: int = 0                # stumble: how many words of it were said


@dataclass
class Record:
    mode: str
    model: str = 'fail'      # what the text model of the scene does: fails at once, or hangs
    lines: list = field(default_factory=list)
    cues: list = field(default_factory=list)          # (t, text, revision, index, chunks, cleared, diagnostic)
    errors: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    opened: bool = False
    updated: bool = False
    connections: int = 1
    closed: bool = False
    gave_up: list = field(default_factory=list)   # (t, kind): a repeat or stumble with no portion heard to say it of
    back: dict = None             # NC6: what was true when the cloud came back, and after it
    log: list = field(default_factory=list)
    model: str = 'fail'      # the text model of the run: 'hang' has the whole 8 s of the owner (ANSWER_WAIT_SECONDS), a model that fails is told as soon as it has failed


class Scene(A.Stand):
    """The stand with the cloud gone (``mode``), the listener scripted (``say`` / ``ask`` / ``repeat`` / ``stumble``), no random decisions."""

    def __init__(self, mode='refused', *, seed=0, length=60.0, profile=None, bank=BANK, model='fail'):
        assert mode in ('refused', 'deaf', 'cloud')
        assert model in ('fail', 'hang')
        self.mode, self.bank, self.model = mode, bank, model
        original = S.World
        S.World = Refused if mode == 'refused' else Deaf if mode == 'deaf' else S.World
        try:
            super().__init__(seed, length=length, profile=dict(profile or PROFILE), faults=False)
        finally:
            S.World = original
        self.rec = Record(mode, model=model, opened=getattr(self.w, 'opened', True), updated=getattr(self.w, 'updated', True))
        self.cloud_at = None

    def _attach(self):
        super()._attach()
        self.w.controller.instant = index(self.bank).for_call() if self.settings.get('instant') == 'on' else None
        self.w.controller.quick_math = self.settings.get('quick_math') == 'on'

    # the cloud: nothing from it (the reference mode 'cloud': its user turns, as the stand gives them), the text model unreachable
    def _feed(self, event):
        if self.mode == 'cloud' or (self.cloud_at is not None and self.w.wire.source is not None and not getattr(self.w.wire.source, 'absent', False)):
            self.w.feed(event)

    def _born(self, job, thread):
        run = A.Run(job, thread, self.now())
        self.runs[id(job.request)] = run
        self.out.jobs.append({'at': round(self.now(), 2), 'heard': job.request['input'][-1]['content'][0]['text'][-120:]})
        if self.model == 'fail':      # 'hang': the request never comes back (a handshake that times out); only a cancel of the job ends it
            self.later(self.now() + 0.05, lambda: run.box.put(('fail', 'ConnectionError: no network')), call=None)

    def decide(self):
        pass

    def cloud_back(self, at):
        """NC6: from ``at`` the helper can be opened (refused mode); the cursor and the controller of that moment are kept for the check."""
        def up():
            self.cloud_at = round(self.now(), 2)
            self.w.cloud_up = True
            s = self.w.controller.state() or {}
            self.rec.back = {'at': self.cloud_at, 'controller': id(self.w.controller), 'wire': id(self.w.wire), 'revision': s.get('revision'),
                             'index': s.get('chunk_index'), 'connections': self.w.connections, 'opens': getattr(self.w, 'opens', 0)}
        self.later(at, up, call=None)

    # the listener
    def say(self, at, kind, text, ear=None, length=None, **extra):
        line = Line(kind, text, ear if ear is not None else self.heard_by_ear(text, kind, exact=True), at, at + (length or max(0.6, 0.33 * len(text.split()))), **extra)
        self.rec.lines.append(line)
        box = {}
        self.later(line.onset, lambda: self.steps.append(('onset', box)), call=None)
        self.later(line.offset, lambda: self.steps.append(('end', box)), call=None)
        self.later(line.offset + 0.2, lambda: self.worker.heard(box['ear'], line.ear) if box.get('ear') is not None else None, call=None)
        if self.mode != 'deaf':        # 'refused': they reach the controller once the cloud is back (``_feed``)
            uid = f'c{len(self.rec.lines)}'
            def created():
                head = self.ms(line.onset) // 200 * 200
                self._feed({'type': 'turn.created', 'turn': {'id': uid, 'role': 'user', 'transcript': '', 'start_ms': head, 'end_ms': head + 200}})
            def done():
                turn = S.turn_done(uid, 'user', line.text)
                turn['turn'].update(start_ms=self.ms(line.onset) // 200 * 200, end_ms=-(-self.ms(line.offset) // 200) * 200)
                self._feed(turn)
            self.later(line.onset + 0.5, created, call=None)
            self.later(line.offset + 1.0, done, call=None)
        return line

    def ask(self, at, text, want=None):
        hit = index(self.bank).for_call().lookup(text, bank_only=True)
        law = law_lookup(text, [])
        if want is None and hit is not None and law and hit.answer != law and not I.same_fact(hit.answer, law):
            return self.say(at, 'ask', text, want='conflict', answer=(hit.answer, law))      # the base and the bank differ: the controller takes neither (``_reference``)
        want = want or ('bank' if hit is not None else 'law' if law else 'unknown')
        return self.say(at, 'ask', text, want=want, answer=hit.answer if hit is not None else law)

    def _fresh(self):
        """The portion the listener has heard to its end since they last spoke, or None."""
        cue = self.last_cue()
        last = max((l.offset for l in self.rec.lines if l.onset <= self.now()), default=0.0)
        if cue is None or not cue.done or cue.cleared or cue.t - self.zero < last or self.w.open is not None:
            return None
        return cue.text

    def _when_heard(self, at, act, kind, patience=15.0):
        """``act(portion)`` at ``at`` or as soon after it as a portion has been heard to its end (the listener answers what they heard)."""
        def go(until=at + patience):
            portion = self._fresh()
            if portion:
                act(portion)
            elif self.now() < until:
                self.later(self.now() + 0.2, lambda: go(until), call=None)
            else:
                self.rec.gave_up.append((at, kind))
        self.later(at, go, call=None)

    def repeat(self, at):
        """The listener says the portion they have just heard, word for word (as the ear writes it)."""
        self._when_heard(at, lambda portion: self.say(self.now() + 0.3, 'repeat', portion, portion=portion), 'repeat')

    def stumble(self, at, said=2):
        """The first ``said`` words of the portion just heard, then silence."""
        def act(portion):
            if len(portion.split()) > said:
                self.say(self.now() + 0.3, 'stumble', ' '.join(portion.split()[:said]), portion=portion, said=said)
        self._when_heard(at, act, 'stumble')

    def play(self):
        self.later(0.0, lambda: None)
        out = super().play()
        w, rec = self.w, self.rec
        rec.cues = [(round(c.t - self.zero, 2), c.text, c.snap.get('revision'), c.snap.get('index'), tuple(c.snap.get('chunks') or ()), c.cleared, c.diagnostic)
                    for c in w.cues if c.text]
        rec.errors = [f.get('error', {}).get('code') for f in w.errors]
        rec.connections, rec.closed = w.connections, bool(w.wire.closed)
        if rec.back is not None:
            s = w.controller.state() or {}
            rec.back.update(after_controller=id(w.controller), after_wire=id(w.wire), source=w.wire.source is not None, after_revision=s.get('revision'),
                            after_opens=getattr(w, 'opens', 0))
        rec.violations = check(rec) + [('A0', 0.0, v) for v, in ((x[2],) for x in out.violations if x[0] == 'A0')]
        rec.log = w.log[-80:]
        return rec


def check(rec):
    v = []
    if not rec.opened:
        v.append(('NC1', 0.0, 'the call did not open: the readiness probe was not answered with the cloud out'))
    if rec.closed:
        v.append(('NC1', 0.0, 'the phone\'s call was closed'))
    cues = rec.cues
    lines = sorted(rec.lines, key=lambda l: l.onset)
    answer_s, honest_s = BOUNDS[rec.mode]
    if rec.mode == 'refused' and rec.model == 'hang':
        honest_s = ANSWER_WAIT_SECONDS      # hold8: a hung text model is given the owner's whole bound (end of the question to the decision), the roads' refusal comes just before it
    for n, line in enumerate(lines):
        until = lines[n + 1].onset if n + 1 < len(lines) else float('inf')
        after = [c for c in cues if line.offset - 0.3 <= c[0] < until]
        if line.kind == 'ask' and line.want in ('bank', 'law'):
            rule = 'NC2' if line.want == 'bank' else 'NC3'
            first = next((c for c in after if not c[6]), None)
            if first is None:
                v.append((rule, line.offset, f'{line.want} question {line.text!r} was not answered (cues after it: {[c[1] for c in after]})'))
            elif first[0] - line.offset > answer_s:
                v.append((rule, line.offset, f'{line.want} answer to {line.text!r} began {first[0] - line.offset:.1f} s after the question'))
            elif not begins(first[1], line.answer):
                v.append((rule, line.offset, f'{line.text!r}: the cue {first[1]!r} is not the start of {line.answer!r}'))
        elif line.kind == 'ask' and line.want == 'conflict':
            first = next((c for c in after if not c[5] and c[1] != CHANNEL), None)
            if first is None:
                v.append(('NC4', line.offset, f'{line.text!r} (the bank and the law base differ): silence'))
            elif not (honest(first[1]) or any(begins(first[1], a) for a in line.answer)):
                v.append(('NC4', line.offset, f'{line.text!r} (the bank and the law base differ): {first[1]!r} is neither of them nor an honest phrase'))
            elif first[0] - line.offset > honest_s:
                v.append(('NC4', line.offset, f'{line.text!r} (the bank and the law base differ): told {first[0] - line.offset:.1f} s after it'))
        elif line.kind == 'ask':
            spoken = [c for c in after if not c[5]]
            told = [c for c in spoken if honest(c[1])]
            other = [c for c in spoken if not honest(c[1]) and c[1] != CHANNEL and c[1] not in STATUS]
            if other:
                v.append(('NC4', line.offset, f'unknown question {line.text!r} got an answer that cannot be known: {other[0][1]!r}'))
            if not told:
                v.append(('NC4', line.offset, f'unknown question {line.text!r}: silence, no honest phrase (cues: {[c[1] for c in after]})'))
            elif told[0][0] - line.offset > honest_s:
                v.append(('NC4', line.offset, f'unknown question {line.text!r}: the honest phrase came {told[0][0] - line.offset:.1f} s after it'))
            elif len(told) > 1:
                v.append(('NC4', line.offset, f'unknown question {line.text!r}: the honest phrase {len(told)} times'))
        elif line.kind == 'repeat':
            nxt = next((c for c in after if not c[6] and c[1] != line.portion), None)
            plan = next((c[4] for c in reversed(cues) if c[1] == line.portion and c[4]), ())
            want = plan[plan.index(line.portion) + 1] if line.portion in plan and plan.index(line.portion) + 1 < len(plan) else None
            if want is not None and (nxt is None or nxt[1] != want or nxt[0] - line.offset > STEP_S):
                v.append(('NC5', line.offset, f'repeat of {line.portion!r}: next portion {want!r} not in {STEP_S} s (got {nxt and nxt[1]!r} at {nxt and nxt[0]})'))
        elif line.kind == 'stumble':
            rest = line.portion.split()[line.said:]
            nxt = next((c for c in after if not c[6]), None)
            if nxt is None:
                v.append(('NC5', line.offset, f'stumble after {line.text!r}: no prompt at all'))
            elif not (words(nxt[1])[:2] == words(' '.join(rest))[:2] or words(nxt[1])[:2] == words(line.portion)[:2]):
                v.append(('NC5', line.offset, f'stumble after {line.text!r}: prompted with {nxt[1]!r}, not from {" ".join(rest)!r}'))
    v += [('NC5', t, f'{kind}: no portion was ever heard to {kind} it') for t, kind in rec.gave_up]
    if sum(1 for c in cues if c[1] == CHANNEL) > 1:
        v.append(('NC7', 0.0, f'the channel phrase was said {sum(1 for c in cues if c[1] == CHANNEL)} times'))
    if sum(1 for e in rec.errors if e in ('controlled_upstream_unavailable', 'controlled_upstream_closed')) > 1:
        v.append(('NC7', 0.0, f'channel errors: {rec.errors}'))
    b = rec.back
    if b is not None:
        if b['after_controller'] != b['controller'] or b['after_wire'] != b['wire'] or rec.connections != b['connections']:
            v.append(('NC6', b['at'], 'the call was restarted when the cloud came back'))
        if not b['source']:
            v.append(('NC6', b['at'], f'the helper was not opened again within the scene after the cloud came back (opens {b["opens"]} -> {b["after_opens"]})'))
        if b['revision'] is not None and b['after_revision'] is not None and b['after_revision'] < b['revision']:
            v.append(('NC6', b['at'], 'the plan went back'))
    return v


def describe(rec):
    rows = [f'mode={rec.mode} opened={rec.opened} connections={rec.connections} closed={rec.closed} errors={rec.errors}']
    rows += [f'  said {l.onset:6.2f}-{l.offset:6.2f} {l.kind:7} {l.text!r}' + (f' [{l.want}]' if l.want else '') for l in sorted(rec.lines, key=lambda l: l.onset)]
    rows += [f'  cue  {c[0]:6.2f} {c[1]!r}' + (' (diag)' if c[6] else '') + (' (cleared)' if c[5] else '') for c in rec.cues]
    rows += [f'  {r} {t:6.2f} {m}' for r, t, m in rec.violations]
    return '\n'.join(rows)


def run(mode='refused', script=None, **kw):
    scene = Scene(mode, **kw)
    try:
        (script or standard)(scene)
        return scene.play()
    finally:
        scene.close()


def standard(s):
    """The rehearsal of 07.11 in one call: a bank question, a repeat, a stumble, a law question, an unknown one, the cloud back, a bank question after it."""
    s.ask(4.0, 'Что такое бухгалтерский учёт?')        # after the phrase that may tell the outage at the start
    s.repeat(9.0)
    s.stumble(12.0)
    s.ask(20.0, LAW)
    s.ask(28.0, UNKNOWN[0])
    s.cloud_back(32.0)        # the product tries again 10 s after the fall and then every 30 s (LOCAL_RETRY_*): at 40 s
    s.ask(46.0, 'Что такое нематериальные активы?')


def stumbles(s):
    """A stumble alone, with room for its prompt: a bank question, the first two words of its first portion, silence."""
    s.ask(4.0, 'Что такое бухгалтерский учёт?')
    s.stumble(9.0)


if __name__ == '__main__':
    import logging
    logging.disable(logging.WARNING)
    bad = 0
    for mode in ('cloud', 'deaf', 'refused'):
        rec = run(mode, length=60.0)
        bad += bool(rec.violations)
        print(describe(rec))
    sys.exit(1 if bad else 0)


# =====================================================================================================================================
# many seeds: the owner's bank, the law base, unknown questions, the listener's gaps drawn by the seed
# =====================================================================================================================================

LAWS = ('Что такое статья 80 НК?', 'Про что статья 88 НК?', 'Что регулирует статья 143 НК?', 'Что такое статья 146 НК?', 'Что говорит статья 81 ТК?')


def owner_bank(path=ROOT / 'cloud_context' / 'bank' / 'instant_bank_2.json'):
    return I.load_bank(path)


def seeded(seed, bank):
    """One call of the seed: three questions of the bank, one of the law base, one unknown, a repeat after the first answer and a stumble after the second."""
    import random
    r = random.Random(seed)
    asked = r.sample([row for row in bank if len(row['q'].split()) <= 9], 3)
    laws = [q for q in LAWS if law_lookup(q, [])]

    def script(s):
        t = 4.0
        s.ask(t, asked[0]['q'])
        s.repeat(t + 5.0 + r.uniform(0, 1))
        t += 14.0 + r.uniform(0, 2)
        s.ask(t, asked[1]['q'])
        s.stumble(t + 5.0 + r.uniform(0, 1), said=r.choice((1, 2)))
        t += 14.0 + r.uniform(0, 2)
        s.ask(t, r.choice(laws))
        t += 9.0 + r.uniform(0, 2)
        s.ask(t, r.choice(UNKNOWN))
        t += 15.0 + r.uniform(0, 2)
        s.ask(t, asked[2]['q'])
    return script


def sweep(mode, seeds, bank=None):
    """{rule: count of calls that broke it}, and the first violation of each rule (its seed)."""
    import logging
    bank = bank or owner_bank()
    counts, first = {}, {}
    logging.disable(logging.WARNING)
    try:
        for seed in seeds:
            rec = run(mode, seeded(seed, bank), seed=seed, length=90.0, bank=bank)
            for rule in sorted({v[0] for v in rec.violations}):
                counts[rule] = counts.get(rule, 0) + 1
                first.setdefault(rule, (seed, next(v for v in rec.violations if v[0] == rule)))
    finally:
        logging.disable(logging.NOTSET)
    return counts, first

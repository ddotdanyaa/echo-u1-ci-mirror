"""G3 chaos: a chain of questions through the real chain of the stand (``stand.Stand``), and at one step of it one failure thrown in.

The faults (``FAULTS``), each at the step ``at`` (the ``at``-th question, 1-based):
  model_hang     the text model's job for that question never yields a word and never ends
  model_cut      the job yields the first part of the answer and breaks
  ear_down       the ear's worker fails (state ``failed``) from that question on
  ws_drop        the phone's websocket drops while the answer is awaited; the phone reconnects
  helper_dead    the GPT-Live helper dies: its turns of that question are lost, what is sent to it raises for 3 s, then a new one is there
  no_audio       the synthesizer raises for every portion of that answer
  disk_full      the call trace (the journal) and the PCM cache cannot be written from that question on
  search_hang    the public lookup of that question never returns (the question is one that is looked up)
  mid_portion    the phone reconnects while a portion of that answer is being played
  open_down      c22: the cloud is unreachable at the OPEN of the call: the phone reconnects at that question, the helper's connect fails (both tries, so the wire
                 says ``controlled_upstream_unavailable``) until the cloud is back 1-9 s later; the phone retries every 2 s, and the call that opens then goes on
  cloud_flicker  c22: the cloud flickers for 12 s from that question: its events are lost in the down windows, a reconnect in a down window meets one failed try
                 of the open (the wire's retry takes it) or both; the windows are 0.7-2.5 s up and 0.7-2.5 s down

After the fault (the checks ``check_chaos``):
  C1 every later question gets an answer of its own (a cue that fits it) within ANSWER_WAIT_SECONDS + 3.5 s of the moment the system had it
  C2 the call is alive: no crash, no unhandled error in a task of the wire, no error frame but the reported timeout
  C3 the old answer does not come back: no cue of the question of the fault (or older) after the next question was had
  C4 no portion is stuck: at the end nothing is open, the flag of speech is down, the plan is not waiting for a next portion forever
  C5 the log names the cause (``CAUSES``)
plus the stand's own invariants (``stand.check``) over the whole record.

``run(seed, fault, at)`` -> ``Outcome`` with ``.violations``; ``python -m tools.replay.chaos [seeds]`` prints the table fault x passed.
Nothing here is a measurement of time on a laptop or a phone.
"""
import asyncio
import logging
import random
import re
import sys
import tempfile
from pathlib import Path

from tools.replay import stand as ST
from tools.replay.stand import GRID, Q, Stand, check
from echo_sync import pcm_cache
from echo_sync.call_trace import CallTrace
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS
from echo_sync.native_media_socket import LOOKUP_TIMEOUT_S

FAULTS = ('none', 'model_hang', 'model_cut', 'ear_down', 'ws_drop', 'helper_dead', 'no_audio', 'disk_full', 'search_hang', 'mid_portion', 'open_down', 'cloud_flicker')
STEPS = 5                      # questions in a chain
ATS = (1, 2, 3, 4)             # every step that has a next question
CANDIDATE = {'local_ear': 'act', 'prompt_tempo': 'ear', 'fast_text': 'on', 'ear_release': 'on', 'two_witnesses': 'on', 'instant': 'on', 'material_pick': 'on',
             'spare_helper': 'on', 'warm_start': 'on', 'open_overlap': 'on', 'quick_math': 'on'}      # WAVE16: the candidate's flags (the stand wires those it has)
CAUSES = {                     # what the log must say (a regex over the log lines after the fault)
    'none': r'.',
    'model_hang': r'fast_text job=\d+ .*outcome=(timeout|cancelled)',      # cancelled: a newer job (the cloud's final) took over before the bound
    'model_cut': r'fast_text job=\d+ .*outcome=(error|cancelled)',
    'ear_down': r'ear state=failed reason=',
    'ws_drop': r'.',           # the reconnect is the host's own line; the stand does it
    'helper_dead': r'upstream_closed',
    'no_audio': r'synthes',
    'disk_full': r'call_trace|trace|pcm.cache',
    'search_hang': r'lookup',
    'mid_portion': r'.',
    'open_down': r'failure class=channel attempt=|upstream_unavailable',
    'cloud_flicker': r'failure class=channel attempt=|upstream|cloud|provider|final',
}


OWN_ERRORS = {'helper_dead': 'controlled_upstream_closed', 'no_audio': 'controlled_synthesis_failed', 'open_down': 'controlled_upstream_unavailable', 'cloud_flicker': 'controlled_upstream_unavailable'}      # the fault's own report to the phone: its name, not a defect
HARD = ('C1', 'C1f', 'C2', 'C3', 'C4', 'C5', 'A1', 'A2', 'A4', 'A5', 'A7', 'A8')                                      # a failure of a scene (A2e, A6o: reported by the stand, not defects)


class Catch(logging.Handler):
    def __init__(self, stand):
        super().__init__(logging.INFO)
        self.stand, self.lines = stand, []

    def emit(self, record):
        try:
            self.lines.append((round(self.stand.now(), 2), record.getMessage()[:300]))
        except Exception:                                   # noqa: BLE001
            pass


class Chaos(Stand):
    def __init__(self, seed, fault, at, *, steps=STEPS, **keywords):
        self.fault, self.at, self.steps_total = fault, at, steps
        self.asked, self.fired, self.fault_t, self.dead_turns = [], False, None, set()
        self.cloud_up_at, self.windows, self.open_tries = 0.0, [], 0
        self.trace_dir = Path(tempfile.mkdtemp(prefix='g3-chaos-'))
        keywords.setdefault('profile', dict(CANDIDATE))
        super().__init__(seed, faults=False, length=steps * 22.0 + 20.0, **keywords)
        self.rng_fault = random.Random(f'chaos-{seed}-{fault}-{at}')
        self.trace = None
        self._open_trace()
        self.cache = pcm_cache.PcmCache(self.trace_dir / 'pcm')
        self._wrap_wire()

    # -- the boundaries the faults break ------------------------------------------------------------------------------------------
    def _open_trace(self):
        self.trace = CallTrace(self.trace_dir / 'calls', f'g3{self.call}', clock=self.w.clock.now)
        self.trace.open(source='chaos')

    def _wrap_wire(self):
        w, me = self.w, self
        plain = ST.voice

        async def synthesize(text, end=None):
            if me.fault == 'no_audio' and me.fired and me._of_fault(text):
                raise OSError('chaos: the synthesizer failed')
            return await asyncio.to_thread(pcm_cache.cached, me.cache, lambda said: b'\x00\x40' * 12000, text, 'sapi', 24000)

        async def lookup(question):
            if me.fault == 'search_hang' and me.fired and not me.search_hung:
                # Hung: the wire's own bound (asyncio.wait_for, LOOKUP_TIMEOUT_S) runs on the loop's REAL clock, which does not move in the stand
                # (World's time is the FakeClock): it is played here on the stand's clock, the way the wire meets it - TimeoutError when it is due.
                me.search_hung = True
                due = me.now() + LOOKUP_TIMEOUT_S
                while me.now() < due:
                    await asyncio.sleep(0)
                raise asyncio.TimeoutError()
            return list(ST.S.SOURCE_ROWS)
        self.search_hung = False
        w.wire.synthesize = synthesize
        w.wire.lookup = lookup
        if getattr(w.wire, 'early', None) is not None:
            w.wire.early.fetch = lookup
        del plain

    def _of_fault(self, text):
        """Is ``text`` the answer of the question of the fault, while it is the last one asked (the same question may be asked again later: that one is not broken)."""
        q = self.asked[self.at - 1].meaning[1] if len(self.asked) == self.at else None
        return q is not None and q.fits(text)

    def cloud_down(self):
        """Is the cloud unreachable now (open_down: until ``cloud_up_at``; cloud_flicker: inside a down window)?"""
        now = self.now()
        return now < self.cloud_up_at or any(a <= now < b for a, b in self.windows)

    def reconnect(self):
        if self.trace is not None:
            self.trace.close()
        if self.fault in ('open_down', 'cloud_flicker') and self.fired:
            self._reconnect_into_cloud()
            return
        super().reconnect()
        self._open_trace()
        self._wrap_wire()
        self.later(self.now() + 0.5, self.decide)          # the listener goes on in the new call

    def _reconnect_into_cloud(self):
        """The phone's reconnect while the cloud may be down: ``connect`` of the helper fails while ``cloud_down`` (open_down: every try; cloud_flicker: the first try of
        the open only when the window began less than 1 s ago, else both), the wire's own retry and phrase run as in the product; a dead open is retried by the phone every 2 s."""
        w = self.w
        self.out.reconnects.append(round(self.now(), 2))
        self.call += 1
        w.version += 1
        w.note('-- reconnect (c22: the cloud may be down)')
        w.run(w.wire.close())
        w.settle()
        me, tries = self, [0]

        async def connect():
            tries[0] += 1
            if me.cloud_down() and not (me.fault == 'cloud_flicker' and tries[0] > 1 and me.rng_fault.random() < 0.7):
                raise ConnectionError('chaos: the cloud is unreachable')
            return w.source
        w._connect = connect

        async def handshake():
            errors = len(w.errors)
            await w.wire.client({'type': 'session.update', 'session': {}})
            if any(e.get('error', {}).get('code') == 'controlled_upstream_unavailable' for e in w.errors[errors:]):
                return                                          # the open failed (both tries): the wire has said so
            sent = len(w.frames)
            await w.wire.client({'type': 'response.create', 'response': {'conversation': 'none', 'input': [{'content': [{'text': 'conduit-ready-s6'}]}]}})
            marker = [f for _, _, f in w.frames[sent:] if f.get('type') == 'conduit.turn']
            if marker:
                await w.wire.client({'type': 'conduit.turn.done', 'turn_id': marker[-1]['turn_id']})
        w._handshake = handshake
        w.connect_peer()
        w.settle()
        self.audio_zero, self.steps, self.speaking, self.input_clock = self.now(), [], None, []
        self._attach()
        self.open_tries += 1
        if self.trace is not None:
            self.trace.close()
        self._open_trace()
        self._wrap_wire()
        if not w.wire.ready:
            self.later(self.now() + 2.0, self.reconnect, call=None)           # the phone retries the dead open
        else:
            self.later(self.now() + 0.5, self.decide)

    # -- the model --------------------------------------------------------------------------------------------------------------
    def _born(self, job, thread):
        answer = self.mind.answer(job.request)
        target = self.fault in ('model_hang', 'model_cut') and self.fired and not getattr(self, 'model_done', False) and len(self.asked) == self.at \
            and normalize_eq(answer, self.asked[-1].meaning[1].answer())
        if not target:
            return super()._born(job, thread)
        self.model_done = True
        run = ST.Run(job, thread, self.now())
        self.runs[id(job.request)] = run
        self.out.jobs.append({'at': round(self.now(), 2), 'heard': job.request['input'][-1]['content'][0]['text'][-160:], 'answer': answer, 'first': 0.0,
                              'fail': True, 'mixed': False, 'chaos': self.fault})
        if self.fault == 'model_cut':
            words = answer.split(' ')
            self.later(self.now() + 0.6, lambda: run.say(' '.join(words[:max(1, len(words) // 2)]) + ' '), call=None)
            self.later(self.now() + 0.9, lambda: run.end(True), call=None)
        # model_hang: nothing is ever said and the stream never ends (until the job is cancelled)

    # -- the listener: a chain of questions, the next one when the last is answered (or 14 s) -----------------------------------
    def decide(self):
        now = self.now()
        if len(self.asked) >= self.steps_total:
            return
        if self.asked:
            last = self.asked[-1]
            answered = any(c.t - self.zero > last.offset and not c.diagnostic and last.meaning[1].fits(c.text) and (c.done or c.cleared) for c in self.w.cues)
            if (self.w.open is not None or not answered) and now - last.offset < 14.0:
                self.later(now + 0.3, self.decide)
                return
        self.later(max(now + self.rng.uniform(0.8, 2.5), self.free), self._ask)

    def _ask(self):
        n = len(self.asked) + 1
        if n == self.at:
            self._fire()
        before = len(self.said)
        if n == self.at and self.fault == 'search_hang':
            k = self.rng.choice(ST.ARTICLES)
            q = Q('article', (k,), f'Что говорит статья {k} Налогового кодекса?')
            self._speak_q(q)
        else:
            self.speak('question', None)
        self.asked.append(self.said[before])

    def _speak_q(self, q):
        original = ST.ask
        ST.ask = lambda rng, last=None: q
        try:
            self.speak('question', None)
        finally:
            ST.ask = original

    def speak(self, kind, cue, barge=False):
        before = len(self.said)
        super().speak(kind, cue, barge)
        u = self.said[before] if len(self.said) > before else None
        if u is not None and len(self.asked) + 1 == self.at and self.fault == 'helper_dead':
            self._helper_dies(u)

    def _fire(self):
        self.fired, self.fault_t = True, round(self.now(), 2)
        self.out.log.append(f'chaos {self.fault} at question {self.at} t={self.fault_t}')
        r = self.rng_fault
        if self.fault == 'ear_down':
            self.worker.state, self.worker.reason = 'failed', 'chaos_ear_down'
        elif self.fault == 'ws_drop':
            self.later(self.now() + 4.0 + r.uniform(0.0, 1.5), self.reconnect)
        elif self.fault == 'mid_portion':
            self._watch_portion()
        elif self.fault == 'disk_full':
            self._break_disk()
        elif self.fault == 'open_down':
            self.cloud_up_at = self.now() + r.uniform(1.0, 9.0)
            self.later(self.now() + 0.6, self.reconnect, call=None)
        elif self.fault == 'cloud_flicker':
            t, end, up = self.now(), self.now() + 12.0, False          # the open meets a down window
            while t < end:
                n = r.uniform(0.7, 2.5)
                if not up:
                    self.windows.append((t, t + n))
                t, up = t + n, not up
            self.later(self.now() + 0.6, self.reconnect, call=None)

    def _watch_portion(self, tries=0):
        open_ = self.w.open
        if open_ is not None and not open_.diagnostic and open_.text and self._of_fault(open_.text):
            self.reconnect()
            return
        if tries < 200:
            self.later(self.now() + 0.1, lambda: self._watch_portion(tries + 1))

    def _break_disk(self):
        class Full:
            def write(self, *_):
                raise OSError(28, 'No space left on device')
            flush = write

            def close(self):
                pass
        if self.trace is not None and self.trace._file is not None:
            self.trace._file = Full()
        broken = self.trace_dir / 'not-a-dir'
        broken.write_text('x')
        self.cache.dir = broken / 'pcm'

    def _helper_dies(self, u):
        """As controlled_host does when its reader of the helper ends (``helper_lost``): the turns of this utterance never come, the wire says
        ``controlled_upstream_closed`` and its phrase, the socket closes; the phone reconnects 1-3 s later to a new call with a new helper."""
        self.dead_turns.add(f'u{u.n}')
        w = self.w

        def lost():
            w.wire.ready = False
            w.run(w.wire._error('controlled_upstream_closed', 'helper_closed'))
            w.run(w.wire.finish_diagnostic())
            w.settle()
            self.later(self.now() + self.rng_fault.uniform(1.0, 3.0), self.reconnect)
        self.later(u.onset + self.rng_fault.uniform(0.3, 1.5), lost)

    def _feed(self, event):
        turn = event.get('turn') if isinstance(event, dict) else None
        tid = (turn or {}).get('id') or event.get('turn_id') or event.get('id')
        if tid in self.dead_turns:
            return                                          # the helper that had this turn is dead
        if self.fault == 'cloud_flicker' and self.fired and self.cloud_down():
            return                                          # the cloud's events of the down window are lost
        super()._feed(event)

    def close(self):
        try:
            super().close()
        finally:
            if self.trace is not None:
                self.trace.close()


def normalize_eq(a, b):
    from echo_sync.textutil import normalize
    return normalize(a) == normalize(b)


def check_chaos(stand, out, lines):
    v = []
    asked = stand.asked
    if len(asked) < stand.steps_total:
        v.append(('C1', 0.0, f'only {len(asked)} of {stand.steps_total} questions were asked: the chain stalled'))

    def known(u):
        return u.final_at if u.final_at is not None else (u.ear_at if u.ear_at is not None else u.offset)
    cues = [c for c in out.cues if not c[6]]
    for i, u in enumerate(asked):
        if i + 1 <= stand.at:
            continue
        t0 = known(u)
        nxt = asked[i + 1].onset if i + 1 < len(asked) else float('inf')
        bound = min(t0 + ANSWER_WAIT_SECONDS + 3.5, nxt)
        if not any(u.onset <= c[0] <= bound and u.meaning[1].fits(' '.join(c[4])) for c in cues):
            v.append(('C1', bound, f'question {i + 1} {u.text!r} (had at {t0}) after {stand.fault}@{stand.at}: no answer of its own by {bound}'))
    if stand.fault == 'search_hang' and len(asked) >= stand.at:
        u = asked[stand.at - 1]
        t0 = known(u)
        nxt = asked[stand.at].onset if stand.at < len(asked) else out_end_t(stand)
        bound = t0 + LOOKUP_TIMEOUT_S + ANSWER_WAIT_SECONDS + 3.5
        if nxt > bound and not any(t0 - 0.5 <= c[0] <= bound for c in out.cues):
            v.append(('C1f', bound, f'question {stand.at} {u.text!r} of the hung lookup (had at {t0}): no cue and no report by {bound}'))
    if out.crash:
        v.append(('C2', 0.0, 'crash: ' + out.crash.strip().split('\n')[-1][:200]))
    for inv, t, msg in out.violations:
        if inv == 'A0':
            v.append(('C2', t, msg))
    if stand.at < len(asked):
        old = [u.meaning[1] for u in asked[:stand.at]]
        nxt = asked[stand.at]
        t0 = known(nxt)
        for c in cues:
            text = ' '.join(c[4])
            if c[0] > t0 + GRID and any(q.fits(text) for q in old) and not nxt.meaning[1].fits(text) and not any(u.meaning[1].fits(text) for u in asked[stand.at:]):
                v.append(('C3', c[0], f'old answer {c[1]!r} after question {stand.at + 1} was had at {t0}'))
                break
    w = stand.w
    s = w.controller.state() or {}
    if w.open is not None:
        v.append(('C4', out_end_t(stand), f'a portion is still open at the end: {w.open.text!r}'))
    if w.controller.hearing:
        v.append(('C4', out_end_t(stand), 'the flag of speech stands at the end'))
    if s.get('stream_waiting_next') and not s.get('completed'):
        v.append(('C4', out_end_t(stand), f'the plan waits for a next portion at the end: {s.get("chunks")}'))
    pattern = re.compile(CAUSES[stand.fault], re.I)
    after = [line for t, line in lines if stand.fault_t is not None and t >= stand.fault_t - 0.5]
    if not any(pattern.search(line) for line in after):
        v.append(('C5', stand.fault_t or 0.0, f'no log line names the cause of {stand.fault} ({CAUSES[stand.fault]})'))
    return v


def _heard_early(stand, out, v):
    """A5 of the stand counts from the cloud's final; a question the ear opened earlier may be answered (or reported, the fault's own phrase) between the ear's text
    and that final, and the stand's window misses it. Such a cue is the answer of that question (it came after the question was heard and before any other)."""
    if v[0] != 'A5':
        return False
    for u in stand.asked:
        if f"question {u.n} " in v[2] and u.ear_at is not None and u.final_at is not None:
            return any(u.ear_at - 1e-6 <= c[0] < u.final_at - 0.5 and (c[6] or u.meaning[1].fits(' '.join(c[4]))) for c in out.cues)
    return False


def _lookup_bound(stand, v):
    """search_hang: the question of the fault is a looked-up one and its lookup hangs; the wire gives up on it after LOOKUP_TIMEOUT_S and the answer
    from memory follows (``no_source``). Its A5 is judged by that bound (LOOKUP_TIMEOUT_S + ANSWER_WAIT_SECONDS + 3.5), not the stand's 11.5 s of a
    question with no lookup; ``check_chaos`` C1f holds it to that. Every other question keeps the stand's bound."""
    if stand.fault != 'search_hang' or v[0] != 'A5' or len(stand.asked) < stand.at:
        return False
    return f"question {stand.asked[stand.at - 1].n} " in v[2]


def out_end_t(stand):
    return round(stand.now(), 2)


def run(seed, fault, at=2, **keywords):
    chaos = Chaos(seed, fault, at, **keywords)
    catch = Catch(chaos)
    # The product's own logger, not the root: a test before this one may have cut its propagation, raised its level or disabled logging (seen in the full suite).
    log = logging.getLogger('echo-sync')
    saved = (log.level, log.disabled, logging.root.manager.disable)
    log.addHandler(catch)
    log.setLevel(logging.INFO)
    log.disabled = False
    logging.disable(logging.NOTSET)
    try:
        try:
            chaos.play()
            # a quiet tail: whatever is still on its way ends
        except Exception as error:                     # noqa: BLE001 - a crash of the chain is a finding
            import traceback
            chaos.out.crash = ''.join(traceback.format_exception(error))[-1500:]
            chaos.out.violations.append(('A0', round(chaos.now(), 2), f'{type(error).__name__}: {error}'[:300]))
            chaos._collect()
        out = chaos.out
        own = OWN_ERRORS.get(fault)
        out.violations = [v for v in out.violations if not (own and v[0] == 'A0' and v[2] == f'error frame {own}')]
        out.violations += [v for v in check(out) if not (own and v[0] == 'A0' and v[2] == f'error frame {own}') and not _lookup_bound(chaos, v) and not _heard_early(chaos, out, v)]
        out.violations += check_chaos(chaos, out, catch.lines)
        out.chaos_lines = catch.lines
        out.asked = [u.text for u in chaos.asked]
    finally:
        log.removeHandler(catch)
        log.setLevel(saved[0])
        log.disabled = saved[1]
        logging.disable(saved[2])
        chaos.close()
    return out


def first(out, only=HARD):
    found = [v for v in out.violations if v[0] in only]
    return found[0] if found else None


def _one(job):
    seed, fault, at = job
    out = run(seed, fault, at)
    bad = first(out)
    return fault, seed, at, bad, sorted({inv for inv, _, _ in out.violations if inv not in HARD})


def table(seeds=range(20), faults=FAULTS, ats=ATS, workers=None):
    """fault, passed, of N, the first cause (the smallest seed), the stand's reported invariants (not counted). Each scene in its own process."""
    import multiprocessing
    jobs = [(seed, fault, at) for fault in faults for seed in seeds for at in ats]
    with multiprocessing.get_context('fork').Pool(workers or multiprocessing.cpu_count()) as pool:
        done = pool.map(_one, jobs, chunksize=1)
    rows = []
    for fault in faults:
        mine = [d for d in done if d[0] == fault]
        bad = [d for d in mine if d[3] is not None]
        cause = f'seed {bad[0][1]} at {bad[0][2]}: {bad[0][3][0]} {bad[0][3][2][:150]}' if bad else '-'
        reported = {}
        for d in mine:
            for inv in d[4]:
                reported[inv] = reported.get(inv, 0) + 1
        rows.append((fault, len(mine) - len(bad), len(mine), cause, reported))
    return rows


def main(argv):
    seeds = range(int(argv[0])) if argv else range(10)
    faults = tuple(argv[1].split(',')) if len(argv) > 1 else FAULTS
    print(f'{"fault":12} {"passed":>9}  first cause / stand invariants')
    for fault, passed, n, cause, stand_v in table(seeds, faults):
        print(f'{fault:12} {passed:4}/{n:<4}  {cause}  {stand_v or ""}')


if __name__ == '__main__':
    main(sys.argv[1:])

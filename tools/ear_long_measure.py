"""L3 (the night of 12-13 Nov): the local ear on LONG speech, offline - no server, no phone, no cloud, nothing leaves the laptop.

    $py = "$env:LOCALAPPDATA\\hermes-echo\\hermes-agent\\venv\\Scripts\\python.exe"
    & $py -I tools\\ear_long_measure.py build  --out DATA                      # long phrases out of open Russian speech (once)
    & $py -I tools\\ear_long_measure.py run    --repo WORKTREE --data DATA --out RAW.jsonl [--mode ear|stream] [--ear KEY=VALUE ...]
    & $py -I tools\\ear_long_measure.py stress --repo WORKTREE --data DATA --out RAW.jsonl --speed 1 [--ear KEY=VALUE ...]
    & $py -I tools\\ear_long_measure.py score  RAW.jsonl [RAW.jsonl ...] [--against RAW.jsonl]

What is measured. A long remark (20-40 s) is fed to the ear AS A CALL FEEDS IT: 100 ms packets of PCM16 mono 24 kHz into the product's own
``ShadowEar`` (pre-roll, the detector's start and end, the window bound), ``SileroOnset`` (the profile's default detector), ``EarWorker`` (its
own thread and queue) and ``SherpaEngine`` (modified_beam_search, 1 thread, the command hotwords of a call with no waiting portion) taken from
``--repo`` - so the same script measures the code before a change and after it. ``echo_sync/__init__`` is not executed (it pulls the plugin in);
the profile's files are never opened.

* ``build``: the audio is real people reading (Common Voice ru, CC0, the sample track I of this night left in ``prosody_v6\\data\\sample``):
  each clip is cut to its speech, levelled, resampled to 24 kHz, and clips are joined into remarks of 20-40 s with a short gap of room tone.
  Set ``natural``: 600 ms between the clips - the detector cuts at the pauses. Set ``tight``: 120 ms - with the 80 ms kept around every clip
  that is still a pause of ~280 ms and the detector cuts at most of them (the longest stretch it left was 13 s: the window bound was never
  reached). Set ``glued`` (``build --sets glued``): the same clips cut to 20 ms around the speech and joined with no gap - nothing between
  them is a pause for the detector, so a remark is ONE stretch of 20-40 s and the window bound is what cuts it.
  The speakers of one remark differ (the corpus has no speaker ids): this is real speech, but not one person's long remark.
* ``run --mode stream``: the whole file through ONE recognizer stream, no detector, no window: what the recognizer can do on this audio.
* ``run --mode ear``: the ear. The packets are fed in lock-step (the next one when the worker has taken the last), so nothing is dropped
  by the queue bound and the result does not depend on the load of the laptop; the compute time of the detector and of the recognizer is
  counted (wall and CPU of the thread).
* ``--detector hold`` (run, stress): the remark as ONE stretch of speech (``HoldDetector``: the energy rule's start, the end only after 1 s of
  quiet), as the long stretches of the owner's calls are - the window bound is then what cuts the remark, 1-3 times in each.
* ``stress``: the ear with the real thread, the real clock and packets arriving at ``--speed`` times real time (1 = a call; 4 = a recognizer
  four times too slow): what the queue does when the recognizer cannot keep up. ``--slow MS``: every packet costs the recognizer MS more
  (150: it can take about 60 % of the audio).
* ``score``: words lost against the written text (word alignment), words that differ from another run (``--against``: the same audio through
  one stream), empty finals, compute time per second of audio; the load marks of the records too (how much
  audio was not recognized, how far behind the recognizer was, the words written down for the windows with holes).

The process runs at BelowNormal priority. Numbers taken while the laptop is busy are LOADED: the CPU columns are the ones to compare.
"""
import argparse
import array
import ctypes
import json
import math
import os
import random
import re
import statistics
import sys
import threading
import time
import types
import wave
from pathlib import Path

sys.dont_write_bytecode = True

RATE = 24000
PACKET = 4800                       # bytes: 100 ms of PCM16 mono 24 kHz, the phone's packet
BYTES_PER_S = 48000
LEAD_S, TAIL_S = 0.5, 1.5           # room tone before and after a remark (the detector must hear its end)
FLOOR_DB = -62.0
SETS = {'tight': 120, 'natural': 600, 'glued': 0}       # the gap between clips, ms
KEEP = {'tight': 4, 'natural': 4, 'glued': 1}           # 20 ms frames kept around the speech of a clip
BUILT_FIRST = ('tight', 'natural')                      # the sets of the first build (their files are not rebuilt by ``--sets glued``)
WORK = Path(r'C:\УСТРОЙСТВО 1\U1\05_WORK')
SAMPLE = WORK / 'prosody_v6' / 'data' / 'sample'
DEPS = WORK / 'prosody_v6' / 'deps'
BELOW_NORMAL = 0x00004000


def below_normal():
    try:
        kernel = ctypes.windll.kernel32
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        kernel.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        return bool(kernel.SetPriorityClass(kernel.GetCurrentProcess(), BELOW_NORMAL))
    except Exception:                                   # noqa: BLE001 - not Windows: the priority stays
        return False


def machine_load(interval=1.0):
    """The CPU load of the whole laptop over ``interval`` seconds, percent (None when it cannot be read): the passport of a timing."""
    try:
        class FileTime(ctypes.Structure):
            _fields_ = [('low', ctypes.c_uint32), ('high', ctypes.c_uint32)]

        def times():
            idle, kernel, user = FileTime(), FileTime(), FileTime()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            ticks = lambda t: (t.high << 32) | t.low    # noqa: E731
            return ticks(idle), ticks(kernel) + ticks(user)       # the kernel time includes the idle time
        idle0, all0 = times()
        time.sleep(interval)
        idle1, all1 = times()
        return round(100 * (1 - (idle1 - idle0) / max(1, all1 - all0)))
    except Exception:                                   # noqa: BLE001 - not Windows
        return None


# ------------------------------------------------------------------------------------------------------------------------------ build

def build(args):
    sys.path.insert(0, str(args.deps))
    import numpy as np                                  # noqa: PLC0415 - only the build needs it (track I's private folder)
    import soundfile as sf                              # noqa: PLC0415

    def resample(x, r_in, r_out):
        n_out = int(round(len(x) * r_out / r_in))
        spectrum = np.fft.rfft(x)
        m = n_out // 2 + 1
        out = np.zeros(m, dtype=complex)
        k = min(m, len(spectrum))
        out[:k] = spectrum[:k]
        return np.fft.irfft(out, n_out) * (n_out / len(x))

    def clip_audio(item, keep=4):
        x, sr = sf.read(str(args.sample / item['file']), dtype='float64', always_2d=False)
        if x.ndim > 1:
            x = x.mean(axis=1)
        x = x - x.mean()
        peak = np.percentile(np.abs(x), 99.5)
        if peak < 1e-4:
            return None
        x = resample(x / peak * 0.5, sr, RATE)
        frame = RATE // 50                              # 20 ms
        n = len(x) // frame
        if n < 25:
            return None
        level = 10 * np.log10(np.maximum((x[:n * frame].reshape(n, frame) ** 2).mean(axis=1), 1e-12))
        active = np.nonzero(level >= level.max() - 35)[0]
        first, last = max(0, active[0] - keep), min(n, active[-1] + 1 + keep)      # ``keep`` frames (80 ms; glued: 20 ms) kept around the speech
        cut = x[first * frame:last * frame].copy()
        fade = RATE // 100                              # 10 ms in and out: no click at the joins
        ramp = np.linspace(0.0, 1.0, fade)
        cut[:fade] *= ramp
        cut[-fade:] *= ramp[::-1]
        return np.clip(cut * 32768, -32768, 32767).astype(np.int16)

    rng = random.Random(args.seed)
    first = np.random.default_rng(args.seed)            # the room tone of the first build's sets, drawn in their order
    extra = {name: np.random.default_rng(args.seed + 1 + k) for k, name in enumerate(n for n in SETS if n not in BUILT_FIRST)}
    amp = 32768 * 10 ** (FLOOR_DB / 20)
    sets = [name for name in SETS if name in (args.sets or BUILT_FIRST)]
    if set(sets) & set(BUILT_FIRST) and not set(BUILT_FIRST) <= set(sets):
        raise SystemExit('the sets of the first build share one room tone: build them together')

    def tone(seconds, name):
        noise = extra.get(name, first)
        return np.clip(noise.normal(0.0, amp, int(seconds * RATE)), -32768, 32767).astype(np.int16)

    meta = json.loads((args.sample / 'meta.json').read_text(encoding='utf-8'))
    pool = [m for m in meta if 2.0 <= m.get('dur', 0) <= 12.0]
    rng.shuffle(pool)
    args.out.mkdir(parents=True, exist_ok=True)
    kept = []
    if (args.out / 'manifest.json').is_file():          # the sets built before stay in the manifest
        kept = [m for m in json.loads((args.out / 'manifest.json').read_text(encoding='utf-8')) if m['set'] not in sets]
    manifest, at = [], 0
    for number in range(args.count):
        want = rng.uniform(args.min_s, args.max_s)
        chosen, total = [], 0.0
        while total < want and at < len(pool):          # the clips of a remark are chosen by their length in the first build: every set has the same ones
            item = pool[at]
            at += 1
            audio = clip_audio(item)
            if audio is None or len(audio) < RATE:
                continue
            chosen.append((item, audio))
            total += len(audio) / RATE
        if total < args.min_s:
            break
        for name in sets:
            gap_ms = SETS[name]
            clips = chosen if KEEP[name] == 4 else [(item, clip_audio(item, KEEP[name])) for item, _ in chosen]
            parts, marks, cursor = [tone(LEAD_S, name)], [], LEAD_S
            for k, (item, audio) in enumerate(clips):
                if k and gap_ms:
                    parts.append(tone(gap_ms / 1000, name))
                    cursor += gap_ms / 1000
                marks.append({'id': item['id'], 'start_s': round(cursor, 3), 'end_s': round(cursor + len(audio) / RATE, 3), 'text': item['text']})
                parts.append(audio)
                cursor += len(audio) / RATE
            parts.append(tone(TAIL_S, name))
            pcm = np.concatenate(parts)
            file = f'{name}_{number:02d}.wav'
            with wave.open(str(args.out / file), 'wb') as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(RATE)
                handle.writeframes(pcm.tobytes())
            manifest.append({'id': f'{name}_{number:02d}', 'set': name, 'file': file, 'dur_s': round(len(pcm) / RATE, 2),
                             'speech_s': round(cursor - LEAD_S, 2), 'gap_ms': gap_ms, 'text': ' '.join(m['text'] for m in marks), 'clips': marks})
    (args.out / 'manifest.json').write_text(json.dumps(kept + manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    for name in sets:
        rows = [m for m in manifest if m['set'] == name]
        print(f'{name}: {len(rows)} remarks, {sum(m["dur_s"] for m in rows):.0f} s of audio, speech {min(m["speech_s"] for m in rows):.1f}-'
              f'{max(m["speech_s"] for m in rows):.1f} s, words {sum(len(words(m["text"])) for m in rows)}')
    print('source: Common Voice ru (CC0), sample of track I:', args.sample)


# ---------------------------------------------------------------------------------------------------------------------------- product

def load_product(repo):
    """The ear's own modules from ``repo``, without executing echo_sync/__init__ (it imports the plugin and the engine)."""
    package = types.ModuleType('echo_sync')
    package.__path__ = [str(Path(repo) / 'echo_sync')]
    sys.modules['echo_sync'] = package
    from echo_sync import diagnostics, ear_shadow, ear_sherpa, local_ear, vad_silero   # noqa: PLC0415
    return types.SimpleNamespace(diagnostics=diagnostics, ear_shadow=ear_shadow, ear_sherpa=ear_sherpa, local_ear=local_ear, vad_silero=vad_silero)


class TimedEngine:
    """The recognizer with its compute time counted (wall and the CPU of the calling thread); everything else passes through."""

    def __init__(self, engine):
        self.engine = engine
        self.reset()

    def reset(self):
        self.wall = {'accept': 0.0, 'finish': 0.0, 'peek': 0.0}
        self.cpu = {'accept': 0.0, 'finish': 0.0, 'peek': 0.0}
        self.calls = {'start': 0, 'accept': 0, 'finish': 0, 'peek': 0}
        self.active = 0
        self.overlap = 0                 # how many times a call began while another was still running (must stay 0)

    def _timed(self, name, work, *a):
        self.active += 1
        if self.active > 1:
            self.overlap += 1
        w0, c0 = time.perf_counter(), time.thread_time()
        try:
            return work(*a)
        finally:
            self.wall[name] += time.perf_counter() - w0
            self.cpu[name] += time.thread_time() - c0
            self.calls[name] += 1
            self.active -= 1

    def start(self, hotwords=None):
        self.calls['start'] += 1
        return self.engine.start(hotwords)

    def accept(self, stream, pcm):
        return self._timed('accept', self.engine.accept, stream, pcm)

    def finish(self, stream):
        return self._timed('finish', self.engine.finish, stream)

    def peek(self, stream):
        return self._timed('peek', self.engine.peek, stream)

    def __getattr__(self, name):
        return getattr(self.engine, name)


class TimedDetector:
    """The speech detector with its compute time counted; everything else passes through."""

    def __init__(self, detector):
        self.detector, self.wall, self.cpu = detector, 0.0, 0.0

    def feed(self, pcm):
        w0, c0 = time.perf_counter(), time.thread_time()
        try:
            return self.detector.feed(pcm)
        finally:
            self.wall += time.perf_counter() - w0
            self.cpu += time.thread_time() - c0

    def __getattr__(self, name):
        return getattr(self.detector, name)


class HoldDetector:
    """``--detector hold``: a detector that does not see the short pauses - the start is the energy rule's (S0), the end comes only after ``hold_ms``
    with no frame above the floor. On clean read speech Silero ends an utterance at every breath (the longest stretch it left in the three sets was
    17.7 s); in the owner's calls of 11 Nov 17 of 366 utterances ran into the window bound, the longest for over 75 s (noise, a second voice). This
    is that case on the open recordings: the remark is one stretch and the window bound is what cuts it."""

    preroll_packets = 3
    engine = 'hold'

    def __init__(self, meter, hold_ms=1000):
        self.meter, self.hold_ms = meter, hold_ms
        self.speaking, self.silent_ms = False, 0

    @property
    def quiet_ms(self):
        return self.silent_ms if self.speaking else 0

    @property
    def level(self):
        return self.meter.level

    @property
    def floor(self):
        return self.meter.floor

    def feed(self, pcm):
        heard = self.meter.feed(pcm)
        if not self.speaking:
            if heard == 'onset':
                self.speaking, self.silent_ms = True, 0
                return 'onset'
            return None
        if self.meter.voiced:
            self.silent_ms = 0
            return 'speech'
        self.silent_ms += len(pcm) * 1000 // BYTES_PER_S
        if self.silent_ms >= self.hold_ms:
            self.speaking = False
        return None


def make_detector(product, kind):
    if kind == 'hold':
        return HoldDetector(product.local_ear.SpeechOnset())
    return product.vad_silero.SileroOnset()


class AudioClock:
    """The clock of a lock-step run: the time of the audio fed so far."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def read_wav(path):
    with wave.open(str(path), 'rb') as handle:
        if (handle.getframerate(), handle.getnchannels(), handle.getsampwidth()) != (RATE, 1, 2):
            raise ValueError(f'{path}: not PCM16 mono 24 kHz')
        return handle.readframes(handle.getnframes())


def ear_kwargs(pairs):
    out = {}
    for pair in pairs or ():
        key, _, value = pair.partition('=')
        try:
            out[key] = json.loads(value)
        except ValueError:
            out[key] = value
    return out


def make_ear(product, worker, detector, clock, notes, extra):
    def report(ev, **fields):
        notes.append({'ev': ev, **fields})
    return product.ear_shadow.ShadowEar(worker, lambda text: ('silent', 'measure', None, None), detector=detector, report=report, clock=clock,
                                        hotwords=lambda: product.ear_sherpa.hotwords_for(None), **extra)


def settle(ear, worker_idle, timeout=120.0):
    """Lock-step: wait until the worker has taken every packet queued so far."""
    deadline = time.monotonic() + timeout
    while ear.pending > 0 and time.monotonic() < deadline:
        time.sleep(0.0005)
    worker_idle()


def final_fields(note):
    keep = ('uid', 'text', 'kind', 'reason', 'speech_ms', 'lag_ms', 'decode_ms', 'onset_input_ms', 'offset_input_ms', 'part', 'more', 'revised',
            'lost_ms', 'behind_ms', 'cut', 'heard')
    return {key: note[key] for key in keep if key in note}


def run(args):
    below_normal()
    product = load_product(args.repo)
    manifest = [m for m in json.loads((args.data / 'manifest.json').read_text(encoding='utf-8')) if not args.sets or m['set'] in args.sets]
    if args.limit:
        manifest = [m for name in SETS for m in [x for x in manifest if x['set'] == name][:args.limit]]
    if args.max_utterance is not None:
        product.ear_shadow.MAX_UTTERANCE_S = args.max_utterance          # a harness override (the bound off: a huge number)
    engine = TimedEngine(product.ear_sherpa.SherpaEngine())
    extra = ear_kwargs(args.ear)
    load_before = machine_load()
    head = {'ev': 'run', 'mode': args.mode, 'detector': args.detector, 'repo': str(args.repo), 'ear': extra, 'max_utterance': getattr(product.ear_shadow, 'MAX_UTTERANCE_S', None),
            'load_before': load_before, 'started': time.strftime('%Y-%m-%d %H:%M:%S')}
    worker = None
    if args.mode == 'ear':
        worker = product.ear_shadow.EarWorker(lambda: engine)
        if not worker.wait_ready(60):
            raise SystemExit('the recognizer did not load: ' + str(worker.reason))
    with open(args.out, 'w', encoding='utf-8') as out:
        out.write(json.dumps(head, ensure_ascii=False) + '\n')
        for item in manifest:
            pcm = read_wav(args.data / item['file'])
            engine.reset()
            row = {'ev': 'file', 'id': item['id'], 'set': item['set'], 'dur_s': item['dur_s'], 'speech_s': item['speech_s']}
            began = time.perf_counter()
            if args.mode == 'stream':
                stream = engine.start(product.ear_sherpa.hotwords_for(None))
                for at in range(0, len(pcm), PACKET):
                    engine.accept(stream, pcm[at:at + PACKET])
                row['finals'] = [{'uid': 1, 'text': engine.finish(stream)}]
                row['vad'] = {'wall': 0.0, 'cpu': 0.0}
            else:
                clock, notes = AudioClock(), []
                detector = TimedDetector(make_detector(product, args.detector))
                ear = make_ear(product, worker, detector, clock, notes, extra)
                finals = []
                for at in range(0, len(pcm), PACKET):
                    clock.now = (at + PACKET) / BYTES_PER_S
                    ear.feed(pcm[at:at + PACKET], input_ms=round(clock.now * 1000))
                    settle(ear, lambda: None)
                    finals += ear.poll()
                deadline = time.monotonic() + 30
                while (ear.spans or ear.current is not None) and time.monotonic() < deadline:      # the last final is on its way
                    time.sleep(0.002)
                    finals += ear.poll()
                finals += ear.poll()
                ear.close()
                row['finals'] = [final_fields(n) for n in notes if n['ev'] == 'ear_final']
                row['notes'] = [n for n in notes if n['ev'] != 'ear_final' and n['ev'] != 'ear_early']
                row['records'] = len(finals)
                row['vad'] = {'wall': round(detector.wall, 4), 'cpu': round(detector.cpu, 4)}
                row['engine_overlap'] = engine.overlap
            row['wall_s'] = round(time.perf_counter() - began, 3)
            row['rec'] = {'wall': {k: round(v, 4) for k, v in engine.wall.items()}, 'cpu': {k: round(v, 4) for k, v in engine.cpu.items()}, 'calls': dict(engine.calls)}
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
            out.flush()
            print(f'{item["id"]}: {item["dur_s"]:.1f} s audio, {row["wall_s"]:.1f} s wall, finals {len(row["finals"])}, '
                  f'empty {sum(not (f.get("text") or "").strip() for f in row["finals"])}', flush=True)
        out.write(json.dumps({'ev': 'end', 'load_after': machine_load(), 'ended': time.strftime('%Y-%m-%d %H:%M:%S')}) + '\n')


def stress(args):
    """The real thread, the real clock, packets at ``speed`` times real time: nothing waits for the recognizer."""
    below_normal()
    product = load_product(args.repo)
    manifest = [m for m in json.loads((args.data / 'manifest.json').read_text(encoding='utf-8')) if not args.sets or m['set'] in args.sets]
    if args.limit:
        manifest = manifest[:args.limit]
    engine = TimedEngine(product.ear_sherpa.SherpaEngine())
    if args.slow:
        inner = engine.engine.accept

        def slow_accept(stream, pcm):                   # a recognizer made slower: every packet costs ``slow`` ms more
            time.sleep(args.slow / 1000)
            return inner(stream, pcm)
        engine.engine.accept = slow_accept
    extra = ear_kwargs(args.ear)
    worker = product.ear_shadow.EarWorker(lambda: engine)
    if not worker.wait_ready(60):
        raise SystemExit('the recognizer did not load: ' + str(worker.reason))
    with open(args.out, 'w', encoding='utf-8') as out:
        out.write(json.dumps({'ev': 'run', 'mode': 'stress', 'detector': args.detector, 'speed': args.speed, 'slow_ms': args.slow, 'repo': str(args.repo), 'ear': extra,
                              'load_before': machine_load(), 'started': time.strftime('%Y-%m-%d %H:%M:%S')}, ensure_ascii=False) + '\n')
        for item in manifest:
            pcm = read_wav(args.data / item['file'])
            engine.reset()
            notes = []
            detector = TimedDetector(make_detector(product, args.detector))
            ear = make_ear(product, worker, detector, time.monotonic, notes, extra)
            step = 0.1 / args.speed
            began = time.monotonic()
            peak, late, records = 0, 0.0, 0
            for number, at in enumerate(range(0, len(pcm), PACKET)):
                due = began + number * step
                wait = due - time.monotonic()
                if wait > 0:
                    time.sleep(wait)
                else:
                    late = max(late, -wait)
                ear.feed(pcm[at:at + PACKET], input_ms=round((at + PACKET) * 1000 / BYTES_PER_S))
                peak = max(peak, ear.pending)
                records += len(ear.poll())
            deadline = time.monotonic() + 60
            while (ear.spans or ear.pending > 0) and time.monotonic() < deadline:
                time.sleep(0.01)
                records += len(ear.poll())
            records += len(ear.poll())
            ear.close()
            row = {'ev': 'file', 'id': item['id'], 'set': item['set'], 'dur_s': item['dur_s'], 'speech_s': item['speech_s'],
                   'finals': [final_fields(n) for n in notes if n['ev'] == 'ear_final'],
                   'notes': [n for n in notes if n['ev'] not in ('ear_final', 'ear_early')], 'records': records,
                   'peak_pending_ms': round(peak * 1000 / BYTES_PER_S), 'feeder_late_ms': round(late * 1000), 'engine_overlap': engine.overlap,
                   'vad': {'wall': round(detector.wall, 4), 'cpu': round(detector.cpu, 4)},
                   'rec': {'wall': {k: round(v, 4) for k, v in engine.wall.items()}, 'cpu': {k: round(v, 4) for k, v in engine.cpu.items()}, 'calls': dict(engine.calls)}}
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
            out.flush()
            print(f'{item["id"]}: finals {len(row["finals"])}, peak queue {row["peak_pending_ms"]} ms, notes {[n.get("state") or n["ev"] for n in row["notes"]]}', flush=True)
        out.write(json.dumps({'ev': 'end', 'load_after': machine_load(), 'ended': time.strftime('%Y-%m-%d %H:%M:%S')}) + '\n')


# ------------------------------------------------------------------------------------------------------------------------------ score

def words(text):
    return re.sub(r'[^\w]+', ' ', (text or '').casefold().replace('ё', 'е')).split()


def align(ref, hyp):
    """Word alignment (Levenshtein): ``(hits, substitutions, deletions, insertions, ops)``; ``ops`` is a list of (op, ref index, hyp index)."""
    n, m = len(ref), len(hyp)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = i
    for j in range(1, m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        row, above, word = cost[i], cost[i - 1], ref[i - 1]
        for j in range(1, m + 1):
            row[j] = min(above[j - 1] + (word != hyp[j - 1]), above[j] + 1, row[j - 1] + 1)
    ops, i, j = [], n, m
    while i or j:
        if i and j and cost[i][j] == cost[i - 1][j - 1] + (ref[i - 1] != hyp[j - 1]):
            ops.append(('hit' if ref[i - 1] == hyp[j - 1] else 'sub', i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and cost[i][j] == cost[i - 1][j] + 1:
            ops.append(('del', i - 1, None))
            i -= 1
        else:
            ops.append(('ins', None, j - 1))
            j -= 1
    ops.reverse()
    count = {name: sum(1 for op in ops if op[0] == name) for name in ('hit', 'sub', 'del', 'ins')}
    return count['hit'], count['sub'], count['del'], count['ins'], ops


def load_raw(path):
    head, files, end = {}, {}, {}
    with open(path, encoding='utf-8') as handle:
        for line in handle:
            row = json.loads(line)
            if row['ev'] == 'run':
                head = row
            elif row['ev'] == 'file':
                files[row['id']] = row
            elif row['ev'] == 'end':
                end = row
    return head, files, end


def heard_text(row, written=False):
    """The texts of the records in order; ``written``: with the words of the windows that lost audio (``heard``: in the journal, not a text to act on)."""
    said = [(f.get('text') or (f.get('heard') if written else '') or '').strip() for f in sorted(row['finals'], key=lambda f: f['uid'])]
    return ' '.join(text for text in said if text)


def score(args):
    manifest = {m['id']: m for m in json.loads((args.data / 'manifest.json').read_text(encoding='utf-8'))}
    against = load_raw(args.against)[1] if args.against else {}
    for path in args.raw:
        head, files, end = load_raw(path)
        print(f'\n=== {Path(path).name}: mode={head.get("mode")} detector={head.get("detector", "silero")} repo={Path(head.get("repo", "")).name} ear={head.get("ear")} '
              f'max_utterance={head.get("max_utterance")} load {head.get("load_before")}%->{end.get("load_after")}% {head.get("started")}')
        for name in SETS:
            rows = [r for r in files.values() if r['set'] == name]
            if not rows:
                continue
            total = {'ref': 0, 'hit': 0, 'sub': 0, 'del': 0, 'ins': 0, 'finals': 0, 'empty': 0, 'audio': 0.0, 'speech': 0.0}
            versus = {'ref': 0, 'sub': 0, 'del': 0, 'ins': 0, 'files': 0}
            cpu = {'vad': 0.0, 'accept': 0.0, 'finish': 0.0, 'peek': 0.0}
            wall = dict(cpu)
            lost_runs = []
            lengths = []
            overlap = 0
            for row in rows:
                ref = words(manifest[row['id']]['text'])
                hyp = words(heard_text(row))
                hit, sub, dele, ins, ops = align(ref, hyp)
                total['ref'] += len(ref)
                total['hit'] += hit
                total['sub'] += sub
                total['del'] += dele
                total['ins'] += ins
                total['finals'] += len(row['finals'])
                total['empty'] += sum(not (f.get('text') or '').strip() for f in row['finals'])
                total['audio'] += row['dur_s']
                total['speech'] += row['speech_s']
                lengths += [f['speech_ms'] for f in row['finals'] if f.get('speech_ms') is not None]
                overlap += row.get('engine_overlap', 0)
                run_len = longest = 0
                for op in ops:                              # the longest run of reference words in a row with no counterpart
                    run_len = run_len + 1 if op[0] == 'del' else 0
                    longest = max(longest, run_len)
                lost_runs.append(longest)
                for key in ('accept', 'finish', 'peek'):
                    cpu[key] += row['rec']['cpu'].get(key, 0.0)
                    wall[key] += row['rec']['wall'].get(key, 0.0)
                cpu['vad'] += row['vad']['cpu']
                wall['vad'] += row['vad']['wall']
                other = against.get(row['id'])
                if other is not None:
                    base = words(heard_text(other))
                    _, s2, d2, i2, _ = align(base, hyp)
                    versus['ref'] += len(base)
                    versus['sub'] += s2
                    versus['del'] += d2
                    versus['ins'] += i2
                    versus['files'] += 1
            n = max(1, total['ref'])
            errors = total['sub'] + total['del'] + total['ins']
            print(f'  [{name}] remarks {len(rows)}, audio {total["audio"]:.0f} s (speech {total["speech"]:.0f} s), reference words {total["ref"]}')
            print(f'    against the written text: lost (no counterpart) {total["del"]} = {100 * total["del"] / n:.1f} %, other word {total["sub"]} = '
                  f'{100 * total["sub"] / n:.1f} %, extra {total["ins"]} = {100 * total["ins"] / n:.1f} %, all errors {100 * errors / n:.1f} %; '
                  f'longest run of lost words: median {statistics.median(lost_runs)}, max {max(lost_runs)}')
            if versus['files']:
                m = max(1, versus['ref'])
                print(f'    against {Path(args.against).name} ({versus["files"]} files, {versus["ref"]} words): missing {versus["del"]} = {100 * versus["del"] / m:.1f} %, '
                      f'other {versus["sub"]} = {100 * versus["sub"] / m:.1f} %, extra {versus["ins"]} = {100 * versus["ins"] / m:.1f} %, '
                      f'all {100 * (versus["del"] + versus["sub"] + versus["ins"]) / m:.1f} %')
            if total['finals']:
                print(f'    finals {total["finals"]} ({total["finals"] / len(rows):.1f} per remark), empty {total["empty"]} = {100 * total["empty"] / total["finals"]:.1f} %; '
                      f'length of a final, s: median {statistics.median(lengths) / 1000 if lengths else 0:.1f}, max {max(lengths) / 1000 if lengths else 0:.1f}; '
                      f'recognizer calls overlapping: {overlap}')
            a = max(1e-9, total['audio'])
            print(f'    compute per second of audio (CPU of the thread / wall): recognizer {1000 * (cpu["accept"] + cpu["finish"] + cpu["peek"]) / a:.0f} / '
                  f'{1000 * (wall["accept"] + wall["finish"] + wall["peek"]) / a:.0f} ms, detector {1000 * cpu["vad"] / a:.1f} / {1000 * wall["vad"] / a:.1f} ms')
            if any('peak_pending_ms' in r for r in rows):
                peaks = [r['peak_pending_ms'] for r in rows]
                states = {}
                for r in rows:
                    for note in r.get('notes', ()):
                        key = note.get('state') or note['ev']
                        states[key] = states.get(key, 0) + 1
                lags = sorted(f['lag_ms'] for r in rows for f in r['finals'] if f.get('lag_ms') is not None)
                print(f'    queue: peak {max(peaks)} ms (median of remarks {statistics.median(peaks)}), notes {states}, lag of a final ms: median '
                      f'{lags[len(lags) // 2] if lags else None}, max {lags[-1] if lags else None}; records to the transport {sum(r.get("records", 0) for r in rows)}')
            marked = [f for r in rows for f in r['finals'] if 'lost_ms' in f]
            if marked:                                   # what the records say about the load
                holes = [f for f in marked if f['lost_ms']]
                written = sum(align(words(manifest[r['id']]['text']), words(heard_text(r, written=True)))[0] for r in rows)
                print(f'    load marks: records {len(marked)}, with audio not recognized {len(holes)} (ended by an overflow {sum(1 for f in marked if f.get("cut"))}), '
                      f'not recognized {sum(f["lost_ms"] for f in marked) / 1000:.1f} s of {total["speech"]:.0f} s of speech, behind at the end of a window ms: max '
                      f'{max(f["behind_ms"] for f in marked)}; reference words found in the texts {total["hit"]} = {100 * total["hit"] / n:.1f} %, '
                      f'with the words written down for the windows with holes {written} = {100 * written / n:.1f} %')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build')
    b.add_argument('--out', type=Path, required=True)
    b.add_argument('--sample', type=Path, default=SAMPLE)
    b.add_argument('--deps', type=Path, default=DEPS)
    b.add_argument('--count', type=int, default=12)
    b.add_argument('--min-s', type=float, default=20.0)
    b.add_argument('--max-s', type=float, default=40.0)
    b.add_argument('--seed', type=int, default=1113)
    b.add_argument('--sets', nargs='*', help='which sets to build (default: the first build, tight and natural)')
    for name in ('run', 'stress'):
        r = sub.add_parser(name)
        r.add_argument('--repo', type=Path, required=True)
        r.add_argument('--data', type=Path, required=True)
        r.add_argument('--out', type=Path, required=True)
        r.add_argument('--sets', nargs='*')
        r.add_argument('--limit', type=int, default=0)
        r.add_argument('--ear', action='append', help='KEY=VALUE (JSON) passed to ShadowEar')
        r.add_argument('--detector', choices=('silero', 'hold'), default='silero', help='hold: the remark is one stretch (HoldDetector)')
        if name == 'run':
            r.add_argument('--mode', choices=('ear', 'stream'), default='ear')
            r.add_argument('--max-utterance', type=float, default=None)
        else:
            r.add_argument('--speed', type=float, default=1.0)
            r.add_argument('--slow', type=float, default=0.0, help='ms added to every recognizer packet')
    s = sub.add_parser('score')
    s.add_argument('raw', nargs='+')
    s.add_argument('--data', type=Path, required=True)
    s.add_argument('--against')
    args = parser.parse_args(argv)
    {'build': build, 'run': run, 'stress': stress, 'score': score}[args.command](args)


if __name__ == '__main__':
    main()

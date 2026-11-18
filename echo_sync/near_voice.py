
import math
import operator
from array import array
from collections import deque, namedtuple
ONSET_HOLD_MAX_S = 1.0

SAMPLE_RATE = 16000
FRAME = 320
FRAME_S = FRAME / SAMPLE_RATE
FLOOR_DB = -90.0
NOISE_RISE_DB_PER_FRAME = 0.01
SPEECH_OVER_NOISE_DB = 9.0
SPEECH_ABS_DB = -52.0
LEVEL_PERCENTILE = 0.75
MIN_SPEECH_FRAMES = 10
WINDOW_S = 2.0
MIN_PIECE_SPEECH_S = 0.6
MIN_PIECES = 3
MIN_PROFILE_SECONDS = 4.0
MAX_PIECES = 12
BOOT_PIECES = 2
REJECT_BELOW_DB = -10.0
OWN_BAND_DB = 4.0
GAP_DB = 4.0
QUIET_REL_DB = 25.0
TILT_TOLERANCE = 0.6
HISTORY_FRAMES = 400


OTHER_FIRST_HOLD_S = 12.0
UNKNOWN_HOLD_S = 30.0
OTHER_NEXT_HOLD_S = 0.3
UNKNOWN_NEXT_HOLD_S = ONSET_HOLD_MAX_S
OTHER_RUN_CAP_S = 20.0
JUDGE_EVERY_S = 0.25

ECHO_LAG_FRAMES = 25
ECHO_MIN_FRAMES = 25
ECHO_CORR = 0.9

Verdict = namedtuple('Verdict', 'kind conf rel_db tilt_off')
_UNKNOWN = Verdict('unknown', 0.0, None, None)


def mode(settings):
    
    try:
        value = settings.get('near_voice') if settings else None
        return value if value in ('shadow', 'act') else 'off'
    except Exception:
        return 'off'


def frames_of(pcm):
    
    samples = array('h');samples.frombytes(bytes(pcm[:len(pcm) // 2 * 2]))
    if samples.itemsize != 2:raise ValueError('array h is not 16 bit')
    out = []
    for at in range(0, len(samples) - FRAME + 1, FRAME):
        s = samples[at:at + FRAME]
        energy = sum(map(operator.mul, s, s))
        if energy <= 0:
            out.append((FLOOR_DB, 0.0));continue
        diff = sum((a - b) * (a - b) for a, b in zip(s, s[1:]))
        out.append((max(FLOOR_DB, 10.0 * math.log10(energy / FRAME / 32768.0 ** 2)), diff / energy))
    return out


def _percentile(values, share):
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def _median(values):
    ordered = sorted(values);n = len(ordered)
    return ordered[n // 2] if n % 2 else (ordered[n // 2 - 1] + ordered[n // 2]) / 2


def speech_of(frames, noise_db):
    
    limit = max(SPEECH_ABS_DB, (noise_db if noise_db is not None else FLOOR_DB) + SPEECH_OVER_NOISE_DB)
    return [f for f in frames if f[0] > limit]


def level_of(speech):
    
    if len(speech) < MIN_SPEECH_FRAMES:
        return None
    return _percentile([f[0] for f in speech], LEVEL_PERCENTILE), _median([f[1] for f in speech])


def enabled(settings):
    return mode(settings) != 'off'


class NearVoice:
    

    def __init__(self):
        self.reset()

    def reset(self):
        self._pieces = [];self.rejected = 0;self.errors = 0
        self.noise_db = None;self.history = deque(maxlen=HISTORY_FRAMES);self._rest = b'';self.frame_count = 0

    @property
    def pieces(self):
        return len(self._pieces)

    @property
    def seconds(self):
        return sum(n for _, _, n in self._pieces) * FRAME_S

    @property
    def ready(self):
        return self.pieces >= MIN_PIECES and self.seconds >= MIN_PROFILE_SECONDS

    @property
    def own_db(self):
        return _median([a for a, _, _ in self._pieces]) if self._pieces else None

    @property
    def own_tilt(self):
        return _median([b for _, b, _ in self._pieces]) if self._pieces else None

    @property
    def spread_db(self):
        
        if len(self._pieces) < 3:
            return 2.0
        mid = self.own_db
        return min(4.0, max(1.0, 1.4826 * _median([abs(a - mid) for a, _, _ in self._pieces])))

    def feed(self, pcm):
        
        try:
            data = self._rest + bytes(pcm);whole = len(data) // (FRAME * 2) * FRAME * 2
            self._rest = data[whole:]
            for db, tilt in frames_of(data[:whole]):
                if self.noise_db is None or db < self.noise_db:self.noise_db = db
                else:self.noise_db += NOISE_RISE_DB_PER_FRAME
                self.history.append((self.frame_count, db, tilt, db > max(SPEECH_ABS_DB, self.noise_db + SPEECH_OVER_NOISE_DB)))
                self.frame_count += 1
        except Exception:
            self.errors += 1;self._rest = b''

    def _clip(self, pcm):
        frames = frames_of(pcm)
        if not frames:
            return None
        floor = _percentile([f[0] for f in frames], 0.1)
        floor = min(floor, self.noise_db) if self.noise_db is not None else floor
        return level_of(speech_of(frames, floor)), len(speech_of(frames, floor))

    def learn(self, pcm, *, aligned):
        
        if aligned is not True:
            return
        try:
            got = self._clip(pcm)
            if got is None or got[0] is None or got[1] * FRAME_S < MIN_PIECE_SPEECH_S:
                return
            (level, tilt), n = got
            if self.pieces >= BOOT_PIECES and level - self.own_db < REJECT_BELOW_DB:
                self.rejected += 1;return
            self._pieces = (self._pieces + [(level, tilt, n)])[-MAX_PIECES:]
        except Exception:
            self.errors += 1

    def classify(self, level, tilt):
        
        if not self.ready or level is None:
            return _UNKNOWN
        rel = level - self.own_db
        if rel < -QUIET_REL_DB:
            return Verdict('quiet', 1.0, rel, None)
        own_edge = OWN_BAND_DB + 1.5 * self.spread_db;other_edge = own_edge + GAP_DB
        tilt_off = abs(tilt - self.own_tilt) / max(self.own_tilt, 0.05)
        if rel >= -own_edge:
            return Verdict('own', round(min(1.0, 0.5 + 0.5 * (rel + own_edge) / (own_edge + 6.0)), 3), round(rel, 2), round(tilt_off, 3))
        if rel <= -other_edge:
            return Verdict('other', round(min(1.0, 0.5 + 0.5 * (-other_edge - rel) / 10.0), 3), round(rel, 2), round(tilt_off, 3))
        if tilt_off > TILT_TOLERANCE:
            return Verdict('other', 0.4, round(rel, 2), round(tilt_off, 3))
        return Verdict('unknown', 0.0, round(rel, 2), round(tilt_off, 3))

    def judge(self):
        
        try:
            recent = list(self.history)[-int(WINDOW_S / FRAME_S):]
            speech = [(db, tilt) for _, db, tilt, is_speech in recent if is_speech]
            if not self.ready:
                return _UNKNOWN
            got = level_of(speech)
            return Verdict('quiet', 1.0, None, None) if got is None else self.classify(*got)
        except Exception:
            self.errors += 1
            return _UNKNOWN

    def judge_clip(self, pcm):
        
        try:
            got = self._clip(pcm)
            if got is None or got[0] is None:
                return Verdict('quiet', 1.0, None, None) if self.ready else _UNKNOWN
            return self.classify(*got[0])
        except Exception:
            self.errors += 1
            return _UNKNOWN

    def record(self, pcm):
        
        try:
            frames = frames_of(pcm);verdict = self.judge_clip(pcm)
            got = self._clip(pcm);dbs = [f[0] for f in frames] or [FLOOR_DB]
            level = got[0][0] if got and got[0] else None
            rms = 10.0 * math.log10(sum(10.0 ** (d / 10.0) for d in dbs) / len(dbs))
            return {'kind': verdict.kind, 'conf': verdict.conf, 'rel_db': verdict.rel_db, 'tilt_off': verdict.tilt_off, 'level_db': None if level is None else round(level, 1),
                    'own_db': None if self.own_db is None else round(self.own_db, 1), 'ready': self.ready, 'pieces': self.pieces,
                    'noise_db': None if self.noise_db is None else round(self.noise_db, 1), 'peak_db': round(max(dbs), 1), 'crest_db': round(max(dbs) - rms, 1), 'frames': len(frames)}
        except Exception:
            self.errors += 1
            return {'kind': 'unknown', 'conf': 0.0}


def journal_line(rec, uid=None, aligned=None):
    
    keys = ('kind', 'conf', 'rel_db', 'tilt_off', 'level_db', 'own_db', 'noise_db', 'peak_db', 'crest_db', 'frames', 'pieces')
    return 'echo-sync near_voice uid=%s aligned=%s %s' % (uid, aligned, ' '.join('%s=%s' % (k, rec.get(k)) for k in keys))


def agc_signs(records):
    
    own = [r for r in records if r.get('aligned') and r.get('level_db') is not None]
    rest = [r for r in records if not r.get('aligned') and r.get('level_db') is not None]
    noise = [r['noise_db'] for r in records if r.get('noise_db') is not None]
    out = {'own_crest_db': None, 'gap_db': None, 'noise_spread_db': None, 'own_drift_db': None}
    signs = 0
    if own:
        out['own_crest_db'] = round(_median([r['crest_db'] for r in own if r.get('crest_db') is not None] or [0.0]), 1)
        signs += out['own_crest_db'] < 9.0
        if len(own) >= 6:
            third = len(own) // 3
            out['own_drift_db'] = round(_median([r['level_db'] for r in own[-third:]]) - _median([r['level_db'] for r in own[:third]]), 1)
            signs += abs(out['own_drift_db']) > 6.0
    if own and rest:
        out['gap_db'] = round(_median([r['level_db'] for r in own]) - max(r['level_db'] for r in rest), 1)
        signs += out['gap_db'] < 8.0
    if len(noise) >= 4:
        out['noise_spread_db'] = round(_percentile(noise, 0.9) - _percentile(noise, 0.1), 1)
        signs += out['noise_spread_db'] > 12.0
    out['suspect'] = signs >= 2;out['signs'] = int(signs)
    return out


def barge_cuts(kind, echo=False):
    
    return not echo and kind not in ('other', 'quiet')


def envelope(pcm, rate=SAMPLE_RATE):
    
    samples = array('h');samples.frombytes(bytes(pcm[:len(pcm) // 2 * 2]));n = int(rate * FRAME_S);out = []
    for at in range(0, len(samples) - n + 1, n):
        s = samples[at:at + n];energy = sum(map(operator.mul, s, s))
        out.append(FLOOR_DB if energy <= 0 else max(FLOOR_DB, 10.0 * math.log10(energy / n / 32768.0 ** 2)))
    return out


def correlation(a, b):
    n = min(len(a), len(b))
    if n < 2:return 0.0
    a, b = a[:n], b[:n];ma, mb = sum(a) / n, sum(b) / n
    va, vb = sum((x - ma) ** 2 for x in a), sum((y - mb) ** 2 for y in b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb) if va > 1e-9 and vb > 1e-9 else 0.0


class OtherSpeech:
    
    EPS = 1e-6

    def __init__(self):
        self.reset()

    def reset(self):
        self.run_start = None;self.other_since = None

    def run_seconds(self, now):
        return max(0.0, now - self.run_start) if self.run_start is not None else 0.0

    def _note(self, now, speaking, kind):
        if not speaking:
            self.reset();return
        if self.run_start is None:self.run_start = now
        if kind == 'other':
            if self.other_since is None:self.other_since = now
        else:self.other_since = None

    def step(self, now, *, speaking, verdict, first):
        try:
            now = float(now)
            if not math.isfinite(now):return 'go'
            kind = verdict if verdict in ('own', 'other') else 'unknown'
            self._note(now, bool(speaking), kind)
            if not speaking:return 'go'
            if kind == 'own':return 'hold'
            if kind == 'other':limit, since = (OTHER_FIRST_HOLD_S if first else OTHER_NEXT_HOLD_S), self.other_since
            else:limit, since = (UNKNOWN_HOLD_S if first else UNKNOWN_NEXT_HOLD_S), self.run_start
            return 'go' if now - since >= limit - self.EPS else 'hold'
        except Exception:
            return 'go'

    def cut_playing(self, now, *, speaking, verdict):
        
        try:
            now = float(now)
            kind = verdict if verdict in ('own', 'other') else 'unknown'
            self._note(now, bool(speaking), kind)
            return bool(speaking) and (kind != 'other' or self.run_seconds(now) >= OTHER_RUN_CAP_S)
        except Exception:
            return True


ALIGNED_SHARE = 0.6


def aligned(text, portion):
    
    try:
        from .textutil import norm_words, stems
        said, given = set(stems(norm_words(text))), set(stems(norm_words(portion)))
        return len(said) >= 2 and len(said & given) >= ALIGNED_SHARE * len(said)
    except Exception:
        return False


class NearGate:
    

    def __init__(self, near=None, *, speaking, clock, act=True, policy=None, log=None):
        self.near = near or NearVoice();self.speaking, self.clock, self.act = speaking, clock, act
        self.policy = policy or OtherSpeech();self.log = log;self._at = None;self._verdict = _UNKNOWN;self._cue = None

    def cue_began(self, pcm, rate=24000):
        
        try:self._cue = (envelope(pcm, rate), self.near.frame_count)
        except Exception:self._cue = None

    def hears_cue_back(self):
        
        try:
            if self._cue is None:return False
            env, first = self._cue;mic = [(i, db) for i, db, _, _ in self.near.history if i >= first][-int(1.5 / FRAME_S):]
            if len(mic) < ECHO_MIN_FRAMES:return False
            return max(correlation([db for _, db in mic], [env[i - first - lag] if 0 <= i - first - lag < len(env) else FLOOR_DB for i, _ in mic]) for lag in range(ECHO_LAG_FRAMES + 1)) >= ECHO_CORR
        except Exception:
            return False

    def cuts_cue(self):
        
        try:return barge_cuts(self.verdict().kind, self.hears_cue_back())
        except Exception:return True

    def on_audio(self, pcm):
        self.near.feed(pcm)

    def on_utterance(self, pcm, text, portion, uid=None):
        
        rec = None
        aligned_ = aligned(text, portion or '')
        try:
            rec = self.near.record(pcm);rec['aligned'] = aligned_
            if self.log:self.log(journal_line(rec, uid, aligned_))
        except Exception:
            pass
        self.near.learn(pcm, aligned=aligned_)
        return rec

    def verdict(self):
        now = self.clock()
        if self._at is None or now - self._at >= JUDGE_EVERY_S:
            self._at = now;self._verdict = self.near.judge()
        return self._verdict

    def releases(self, cue):
        try:
            if not self.act:return False
            speaking = bool(self.speaking());kind = self.verdict().kind if speaking else 'unknown'
            go = self.policy.step(self.clock(), speaking=speaking, verdict=kind, first=bool(cue and cue.get('first'))) == 'go'
            return speaking and go and kind != 'own'
        except Exception:
            return False

    def other_speaking(self):
        
        try:
            return bool(self.act and self.releases({'first': False}) and self.verdict().kind == 'other')
        except Exception:
            return False

    def cuts_playing(self):
        try:
            speaking = bool(self.speaking())
            if not self.act:return speaking
            return self.policy.cut_playing(self.clock(), speaking=speaking, verdict=self.verdict().kind if speaking else 'unknown')
        except Exception:
            return True

    def is_other_utterance(self, rec):
        
        try:
            return bool(self.act and rec and rec.get('kind') == 'other' and rec.get('conf', 0) >= 0.6)
        except Exception:
            return False

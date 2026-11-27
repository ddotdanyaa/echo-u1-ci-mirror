"""w2-own-voice (E78, RELEASE_FOCUS 5.2): whose voice is the ear hearing, and how long does the gate wait on somebody else's speech. Mono, nobody is invented.
Learning without enrolment: whatever the ear heard that ALIGNED with the prompt (the speaker repeats the portion the prompter gave) is, by definition, the speaker's voice. Those pieces are
embedded by a speaker model (``Embedder``; here a scripted one, on the laptop ``SherpaEmbedder``) and averaged into a profile; later speech is judged against it: 'own', 'other', or 'unknown' (the band between
the thresholds, no profile yet, a piece too short, a model that failed). Nothing here decides alone: 'unknown' is the gate's behaviour of today, bounded.
Thresholds are placeholders until measured on the laptop with the real model (cloud_context/reports/w2-own-voice.md, the plan). Pure Python, no numpy, no network, never raises into the caller."""
import math
from collections import namedtuple
from .timer_policy import ONSET_HOLD_MAX_S

SAMPLE_RATE = 16000
MIN_SEGMENT_SECONDS = 0.8        # a piece shorter than this does not carry a voice
MIN_JUDGE_SECONDS = 0.5          # nor does it judge one
MIN_PROFILE_SECONDS = 6.0        # aligned speech needed before anything is judged
MIN_PIECES = 3
MAX_PIECES = 12                  # the newest pieces: the voice drifts over a long speech
BOOT_PIECES = 2                  # the first pieces are taken as they come, later ones must agree with the profile
REJECT_BELOW = 0.5               # an aligned piece further from the profile than this was said by somebody else (a word of the prompt in the other's mouth)
OWN_ABOVE = 0.6
OTHER_BELOW = 0.4

# The gate's wait on speech of somebody else (``OtherSpeech``). name -> seconds; what each means is in the report. 'first': the first cue of an answer (it answers what was asked, so it waits for the end of it).
OTHER_FIRST_HOLD_S = 12.0        # voice judged 'other': a question of 10-20 s is waited for 12 s, then what is ready is said (the cap of a question, 30 s, stands over it)
UNKNOWN_HOLD_S = 30.0            # voice not known: no shortening of today's hold (the cap of a question, controlled_media.ANSWER_CAP_SECONDS); an owner's long question is not cut into on a guess
OTHER_NEXT_HOLD_S = 0.3          # a next portion or a replay (the speaker stalled): somebody else talking is no reason to wait
UNKNOWN_NEXT_HOLD_S = ONSET_HOLD_MAX_S
OWN_HOLD_S = 8.0                 # reference: 'own' voice keeps the holds of today (controlled_media.HOLD_BOUNDS), this policy does not shorten them
OTHER_RUN_CAP_S = 20.0           # a cue that plays is cut by 'other' speech only after this long a run of it

Verdict = namedtuple('Verdict', 'kind score')
_UNKNOWN = Verdict('unknown', None)


def cosine(a, b):
    try:
        if len(a) != len(b) or not a:
            return 0.0
        na = math.sqrt(sum(x * x for x in a));nb = math.sqrt(sum(y * y for y in b))
        return sum(x * y for x, y in zip(a, b)) / (na * nb) if na > 0 and nb > 0 else 0.0
    except Exception:
        return 0.0


def unit_mean(vectors):
    size = len(vectors[0]);total = [sum(v[i] for v in vectors) for i in range(size)]
    norm = math.sqrt(sum(x * x for x in total)) or 1.0
    return [x / norm for x in total]


class ScriptedEmbedder:
    """Test double: ``fn(tag)`` -> vector or None, ``tag`` the first s16 sample of the PCM."""

    def __init__(self, fn):
        self.fn = fn;self.error = None

    def embed(self, pcm):
        return self.fn(int.from_bytes(pcm[:2], 'little', signed=True))


class SherpaEmbedder:
    """The speaker model of sherpa-onnx (``SpeakerEmbeddingExtractor``), loaded on first use. Not exercised in the cloud (no package, no model): the laptop measures it. A failure is kept in ``error``, the answer is None."""

    def __init__(self, model, threads=1):
        self.model = model;self.threads = threads;self.error = None;self._extractor = None

    def embed(self, pcm):
        try:
            if self._extractor is None:
                import sherpa_onnx
                config = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(self.model), num_threads=self.threads, provider='cpu')
                if not config.validate():raise RuntimeError('speaker model config is not valid')
                self._extractor = sherpa_onnx.SpeakerEmbeddingExtractor(config)
            import numpy
            samples = numpy.frombuffer(pcm[:len(pcm) // 2 * 2], dtype='<i2').astype('float32') / 32768.0
            stream = self._extractor.create_stream();stream.accept_waveform(sample_rate=SAMPLE_RATE, waveform=samples);stream.input_finished()
            return [float(x) for x in self._extractor.compute(stream)] if self._extractor.is_ready(stream) else None
        except Exception as exc:
            self.error = f'{type(exc).__name__}: {exc}'[:200]
            return None


class VoiceProfile:
    """The speaker's voice from the pieces that aligned with the prompt. ``learn`` takes a piece (s16 mono PCM at 16 kHz), ``judge`` says whose a piece is."""

    def __init__(self, embedder, *, own_above=OWN_ABOVE, other_below=OTHER_BELOW):
        self.embedder = embedder;self.own_above = own_above;self.other_below = other_below
        self.errors = 0;self.reset()

    def reset(self):
        self._pieces = [];self.rejected = 0;self.centroid = None

    @property
    def pieces(self):
        return len(self._pieces)

    @property
    def seconds(self):
        return sum(sec for _, sec in self._pieces)

    @property
    def ready(self):
        return self.pieces >= MIN_PIECES and self.seconds >= MIN_PROFILE_SECONDS

    def _embed(self, pcm, least):
        if not pcm or len(pcm) / 2 / SAMPLE_RATE < least:
            return None
        try:
            vector = self.embedder.embed(pcm)
        except Exception:
            self.errors += 1
            return None
        return list(vector) if vector else None

    def learn(self, pcm, *, aligned):
        """Only a piece the caller found aligned with the prompt is taken, and after the first pieces only one that agrees with the profile so far."""
        if aligned is not True:
            return
        vector = self._embed(pcm, MIN_SEGMENT_SECONDS)
        if vector is None:
            return
        if self.pieces >= BOOT_PIECES and cosine(vector, self.centroid) < REJECT_BELOW:
            self.rejected += 1
            return
        self._pieces = (self._pieces + [(vector, len(pcm) / 2 / SAMPLE_RATE)])[-MAX_PIECES:]
        self.centroid = unit_mean([v for v, _ in self._pieces])

    def judge(self, pcm):
        if not self.ready:
            return _UNKNOWN
        vector = self._embed(pcm, MIN_JUDGE_SECONDS)
        if vector is None:
            return _UNKNOWN
        score = cosine(vector, self.centroid)
        return Verdict('own' if score >= self.own_above else 'other' if score <= self.other_below else 'unknown', score)


class OtherSpeech:
    """How long the gate waits on speech it hears while a cue is ready (``step``), and whether speech cuts a cue that plays (``cut_playing``). Pure: the clock is the caller's.
    'own' voice: 'hold', the holds of today stand. 'other': a first cue waits OTHER_FIRST_HOLD_S of an unbroken run of it, a next portion OTHER_NEXT_HOLD_S. 'unknown' or no verdict: UNKNOWN_HOLD_S / UNKNOWN_NEXT_HOLD_S.
    Silence, or the speaker's own voice in between, starts the count anew."""
    EPS = 1e-6

    def __init__(self):
        self.reset()

    def reset(self):
        self.run_start = None;self.other_since = None

    def run_seconds(self, now):
        return max(0.0, now - self.run_start) if self.run_start is not None else 0.0

    def _note(self, now, speaking, kind):
        if not speaking:
            self.reset()
            return
        if self.run_start is None:
            self.run_start = now
        if kind == 'other':
            if self.other_since is None:
                self.other_since = now
        else:
            self.other_since = None

    def step(self, now, *, speaking, verdict, first):
        """``'hold'`` or ``'go'`` for a ready cue now."""
        try:
            now = float(now)
            if not math.isfinite(now):
                return 'go'
            kind = verdict if verdict in ('own', 'other') else 'unknown'
            self._note(now, bool(speaking), kind)
            if not speaking:
                return 'go'
            if kind == 'own':
                return 'hold'
            if kind == 'other':
                limit, since = (OTHER_FIRST_HOLD_S if first else OTHER_NEXT_HOLD_S), self.other_since
            else:
                limit, since = (UNKNOWN_HOLD_S if first else UNKNOWN_NEXT_HOLD_S), self.run_start
            return 'go' if now - since >= limit - self.EPS else 'hold'
        except Exception:
            return 'go'

    def cut_playing(self, now, *, speaking, verdict):
        """Does speech that begins over a playing cue cut it? Not when it is confirmed somebody else's, until OTHER_RUN_CAP_S of it."""
        try:
            now = float(now)
            kind = verdict if verdict in ('own', 'other') else 'unknown'
            self._note(now, bool(speaking), kind)
            if not speaking:
                return False
            return kind != 'other' or self.run_seconds(now) >= OTHER_RUN_CAP_S
        except Exception:
            return True


JUDGE_EVERY_S = 0.5              # one embedding of the speech heard so far per this long: the laptop's N95 budget (report: plan of the measurement)
WINDOW_S = 3.0                   # the newest seconds of the current speech that are judged
ALIGNED_SHARE = 0.6              # of the content stems of an utterance found in the prompt's portion


def aligned(text, portion):
    """Did the utterance repeat the prompt? At least two content stems, ALIGNED_SHARE of them in the portion. By definition that is the speaker's voice."""
    try:
        from .textutil import norm_words, stems
        said, given = set(stems(norm_words(text))), set(stems(norm_words(portion)))
        return len(said) >= 2 and len(said & given) >= ALIGNED_SHARE * len(said)
    except Exception:
        return False


class SpeakerGate:
    """What the transport's gate asks (``releases``): may a ready cue play over the speech the ear hears? Never lengthens a hold of today, only shortens it, and only on a verdict 'other' (or the cap of ``OtherSpeech``).
    The ear tells it the audio (``on_audio``, 16 kHz s16 mono, while it hears speech) and what it recognized (``on_utterance``); ``speaking()`` and ``clock()`` are the ear's and the call's."""

    def __init__(self, profile, *, speaking, clock, policy=None):
        self.profile, self.speaking, self.clock, self.policy = profile, speaking, clock, policy or OtherSpeech()
        self._buf = b'';self._at = None;self._verdict = _UNKNOWN

    def on_audio(self, pcm):
        try:
            if not self.speaking():
                self._buf = b'';self._verdict = _UNKNOWN;self._at = None
                return
            self._buf = (self._buf + bytes(pcm))[-int(WINDOW_S * SAMPLE_RATE) * 2:]
        except Exception:
            self._buf = b''

    def on_utterance(self, pcm, text, portion):
        self.profile.learn(pcm, aligned=aligned(text, portion))

    def verdict(self):
        now = self.clock()
        if self._at is None or now - self._at >= JUDGE_EVERY_S:
            self._at = now;self._verdict = self.profile.judge(self._buf)
        return self._verdict

    def releases(self, cue):
        try:
            speaking = bool(self.speaking());kind = self.verdict().kind if speaking else 'unknown'
            go = self.policy.step(self.clock(), speaking=speaking, verdict=kind, first=bool(cue and cue.get('first'))) == 'go'
            return speaking and go and kind != 'own'
        except Exception:
            return False

    def other_speaking(self):
        """Is the speech the ear hears confirmed to be somebody else's, and has it run OTHER_NEXT_HOLD_S? Then the speaker is silent as far as the prompter's timer is concerned."""
        return self.releases({'first': False}) and self.verdict().kind == 'other'

    def cuts_cue(self):
        """U52: may the speech cut the cue that plays? Only a voice that is not confirmed somebody else's (``near_voice.barge_cuts``, the one rule; no echo witness here: the print judges the voice)."""
        try:
            from .near_voice import barge_cuts
            return barge_cuts(self.verdict().kind)
        except Exception:
            return True

    def cuts_playing(self):
        try:
            speaking = bool(self.speaking())
            return self.policy.cut_playing(self.clock(), speaking=speaking, verdict=self.verdict().kind if speaking else 'unknown')
        except Exception:
            return True

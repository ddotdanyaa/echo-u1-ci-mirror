"""Task R-VAD: Silero VAD as the engine of the transport's own ear (the ready component behind ``local_onset``).

Silero VAD (MIT, a small neural net, int8 ONNX, 208 KiB) is run through sherpa-onnx - already installed for the shadow ear's recognizer
(ear_sherpa.py) - from the model file ``silero_vad.int8.onnx`` that sits next to the recognizer's files. ``SileroOnset`` has the contract
of S0's energy detector (``local_ear.SpeechOnset``): ``feed(pcm)`` per microphone packet (PCM16LE mono 24 kHz, ~100 ms, any size) says
``'onset'`` (speech started in it), ``'speech'`` (it goes on) or ``None``; ``speaking``, ``level``, ``floor``.

* The audio is resampled to 16 kHz (resample.py: a real anti-aliasing polyphase filter, streaming) and cut into the 512-sample windows
  (32 ms) the model takes; the model's own smoothing decides: speech starts after ONSET_MS of it and is over after OFFSET_MS without
  (local_ear's constants, the energy detector's numbers), so a pause of 300 ms or more ends an utterance in both engines.
* Why a neural net: the energy rule needs speech to stand out of a floor; in noise 15 dB under the voice it ended 29 % of the utterances
  late (S1: p95 1.34 s). The model tells speech from noise by what it sounds like. It does not tell WHO speaks (a TV is speech), and
  synthetic tones are not speech to it.
* ``level`` and ``floor`` stay the energy meter's numbers (an S0 ``SpeechOnset`` runs beside it, ~0.1 ms per packet): the log line is
  the same for both engines. The meter also decides when the model's «speech» is MEANT: sherpa-onnx's verdict stays True for 0.3 s after
  the last speech window (and across a gap in the phone's microphone stream, which it is never told about), and every ``'speech'`` event
  re-arms the controller's «the listener is speaking» flag in mode 'on' - so ``'speech'`` is only said in a packet in which some frame
  stood out of the floor (``meter.voiced``), as the energy engine does; ``speaking`` and ``'onset'`` are the model's alone. That meter is
  also the safety net: whatever the model or the resampler does wrong at run time (an
  exception), the ear goes on with the energy detector for the rest of the call - logged once by the error TYPE, never its message.
* sherpa-onnx EXITS THE WHOLE PROCESS (it does not raise) on a window of the wrong size, a configuration that does not validate and - found
  in the review - ANY ONNX graph that is not Silero's ("Unsupported silero vad model", rc -1, inside ``VadModel.create``). Here the window
  is exactly ``window_size()`` floats by construction, the configuration is validated first, and the model file is PINNED before sherpa
  touches it: the size and the SHA-256 of the file S1 downloaded (``verify_model``), else ``ValueError`` and ``make_onset`` falls back to
  the energy rule. A newer Silero is a conscious change of the two constants below, after trying it.
"""
import hashlib
import logging
import sys
from array import array
from pathlib import Path

from .diagnostics import reason_of
from .local_ear import OFFSET_MS, ONSET_MS, SAMPLE_RATE, ZERO_HOLD_MS, SpeechOnset
from .resample import Resampler

logger = logging.getLogger('echo-sync')

MODEL_FILE = 'silero_vad.int8.onnx'
MODEL_SIZE = 212860          # the pin: bytes and SHA-256 of the file S1 downloaded (GitHub release asr-models; S1 report, 3 Nov 2026)
MODEL_SHA256 = 'c36d490aff5ab924ca6c7aeec4d8f6bd3d22db6fa17611b9c5b17eae58ac3a20'
VAD_RATE = 16000             # Silero takes 8 or 16 kHz
WINDOW = 512                 # samples per model call at 16 kHz (32 ms)
THRESHOLD = 0.5              # the model's probability above which a window is speech (its default; 0.4-0.6 measured alike)


_trusted = {}                # (path, size, mtime_ns) of the files whose digest was checked in this process


def _sha256_of(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_model(path):
    """Raise ``ValueError`` unless the file at ``path`` is exactly the pinned Silero model. A file whose path, size and modification time
    were checked before in this process is trusted without reading it again (a call opens every few minutes, the file is 208 KiB)."""
    path = Path(path)
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    if key in _trusted:
        return
    if stat.st_size != MODEL_SIZE:
        raise ValueError('silero vad model size')
    if _sha256_of(path) != MODEL_SHA256:
        raise ValueError('silero vad model digest')
    _trusted[key] = True


def default_model_path():
    """Where the model is looked for: next to the recognizer's files (``ECHO_EAR_MODEL_DIR`` or the ECHO copy's models folder)."""
    from .ear_sherpa import default_model_dir            # noqa: PLC0415 - ear_sherpa pulls the Russian matcher in
    return str(Path(default_model_dir()) / MODEL_FILE)


class SherpaVad:
    """sherpa-onnx's Silero ``VadModel`` with the three calls ``SileroOnset`` uses: ``window_size()``, ``is_speech(window)``, ``reset()``.
    Raises (and never exits) when the package or the model is missing; ``is_speech`` refuses a window of the wrong size."""

    def __init__(self, path=None, *, threshold=THRESHOLD, onset_ms=ONSET_MS, offset_ms=OFFSET_MS):
        path = Path(path or default_model_path())
        if not path.is_file():
            raise FileNotFoundError(MODEL_FILE)
        verify_model(path)                                   # BEFORE sherpa-onnx is touched: any other graph exits the whole process
        import sherpa_onnx                                   # noqa: PLC0415
        from .ear_sherpa import short_path                   # noqa: PLC0415
        config = sherpa_onnx.VadModelConfig()
        config.silero_vad.model = short_path(path)
        config.silero_vad.threshold = threshold
        config.silero_vad.min_speech_duration = onset_ms / 1000
        config.silero_vad.min_silence_duration = offset_ms / 1000
        config.silero_vad.window_size = WINDOW
        config.sample_rate = VAD_RATE
        config.num_threads = 1
        config.provider = 'cpu'
        if not config.validate():                            # create() on a configuration that does not validate exits the process
            raise ValueError('silero vad configuration')
        self.model = sherpa_onnx.VadModel.create(config)
        self.size = self.model.window_size()

    def window_size(self):
        return self.size

    def is_speech(self, window):
        if len(window) != self.size:
            raise ValueError('silero vad window')            # sherpa-onnx would exit the process
        return bool(self.model.is_speech(window))

    def reset(self):
        self.model.reset()


class SileroOnset:
    """The ear's speech detector on Silero VAD. ``model`` (None: the real one, loaded now - raises when it cannot be) needs
    ``window_size()``, ``is_speech(window) -> bool`` and ``reset()``. Packets of any size; an incomplete window waits for the next one."""

    # Packets of audio the shadow ear keeps before a start (ear_shadow.ShadowEar reads it): this engine is sure of a start 0.19 s after the
    # first sound (S1 set: p95 0.29 s, max 0.40 s; the energy rule 0.09 s, max 0.25 s) and the ear's stream begins 4 packets before the
    # verdict's own - 3 packets are exactly enough for the worst case seen, and a clipped «не» at the start is the dangerous kind of miss.
    preroll_packets = 4

    def __init__(self, model=None, *, sample_rate=SAMPLE_RATE):
        self.model = model if model is not None else SherpaVad()
        self.size = self.model.window_size()
        self.resampler = Resampler(sample_rate, VAD_RATE, gain=1 / 32768)
        self.meter = SpeechOnset(sample_rate=sample_rate)    # level, floor - and the energy detector the ear falls back to
        self.rest = b''                                      # half a sample left over from the last packet
        self.pending = []                                    # 16 kHz floats waiting for a whole window
        self.failed = None                                   # why the model was given up (an error type), None while it works
        self._speaking = False
        self.sample_rate = sample_rate
        self.zero_ms = 0                                     # U27: digital zero in a row (a hole someone filled), ms

    @property
    def engine(self):
        return 'energy' if self.failed else 'silero'

    @property
    def speaking(self):
        return self.meter.speaking if self.failed else self._speaking

    @property
    def quiet_ms(self):
        return self.meter.quiet_ms if self._speaking or self.failed else 0     # the energy meter's silence while the model still says speech

    @property
    def level(self):
        return self.meter.level

    @property
    def floor(self):
        return self.meter.floor

    def feed(self, pcm):
        energy = self.meter.feed(pcm)
        if self.failed:
            return energy
        if self._hole(pcm):
            return None                                      # U27: a hole of zeros inside the speech is no silence: the model is not asked, the utterance waits
        try:
            return self._hear(pcm)
        except Exception as error:                           # noqa: BLE001 - the ear never breaks the call: the energy detector takes over
            self.failed = reason_of(error)
            logger.warning('echo-sync local speech onset engine=silero failed reason=%s fallback=energy', self.failed)
            return energy

    def _hole(self, pcm):
        """True while the packet is digital zero inside speech and the hole is not older than ZERO_HOLD_MS (after it the zeros count as silence, as everything else)."""
        pcm = bytes(pcm)
        if not pcm or pcm.count(0) != len(pcm):
            self.zero_ms = 0
            return False
        self.zero_ms += len(pcm) * 500 // self.sample_rate
        return self._speaking and self.zero_ms <= ZERO_HOLD_MS

    def _hear(self, pcm):
        data = self.rest + bytes(pcm)
        whole = len(data) - len(data) % 2
        self.rest = data[whole:]
        if not whole:
            return None
        samples = array('h')
        samples.frombytes(data[:whole])
        if sys.byteorder == 'big':
            samples.byteswap()
        self.pending.extend(self.resampler.feed(samples))
        size, heard = self.size, None
        count = len(self.pending) // size
        for k in range(count):
            speech = self.model.is_speech(self.pending[k * size:(k + 1) * size])
            event = ('speech' if self._speaking else 'onset') if speech else None
            self._speaking = bool(speech)
            if event == 'onset' or (event and heard is None):
                heard = event
        del self.pending[:count * size]
        if heard == 'speech' and not self.meter.voiced:
            return None                                      # the model is in its hangover, or hears room tone after a gap: nothing is going on
        return heard

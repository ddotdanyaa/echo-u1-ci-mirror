"""Task S1: the recognizer behind the shadow ear (ear_shadow.py) - sherpa-onnx 2.0.1 with the Vosk small streaming Russian Zipformer
(int8; csukuangfj/sherpa-onnx-streaming-zipformer-small-ru-vosk-int8-2025-08-16, byte-identical to alphacep/vosk-model-small-streaming-ru,
Apache-2.0), installed in the ECHO copy only: the wheels in its venv, the model in ``%LOCALAPPDATA%\\hermes-echo\\models\\sherpa-small-ru-int8``
(or ``ECHO_EAR_MODEL_DIR``). ``sherpa_onnx`` is imported only when an engine is made, so nothing else needs the package.

The configuration is the winner of the offline bake-off (U1/05_WORK/scripts/local_ear_bakeoff.py, config ``beam_hot_safe``):
modified_beam_search with 4 paths, one thread, and per-utterance hotwords from ``hotwords_for`` - the waiting portion's plain words and
the command words, NEVER a number or «не»/«ни»: with the numbers in the hotwords the bake-off heard «статья четыреста двадцать вторая» as
the expected «… первая» and «не больше четырёх раз» as «… трёх …» (false ACKs). The phone's 24 kHz PCM is fed as is (sherpa resamples to
16 kHz itself); at the end of an utterance 0.5 s of zeros give the encoder its right context. The C++ side opens the BPE vocabulary
through a narrow path and fails on the Cyrillic profile folder, so every path goes through its 8.3 short name (``short_path``)."""
import ctypes
import logging
import os
import re
import sys
from array import array
from pathlib import Path

from .ru_alignment import _canonical
from .settings import environment

logger = logging.getLogger('echo-sync')
MODEL_DIR_ENV = 'ECHO_EAR_MODEL_DIR'
MODEL_FILES = ('encoder.int8.onnx', 'decoder.onnx', 'joiner.int8.onnx', 'tokens.txt', 'unigram_500.vocab')
COMMAND_HOTWORDS = ('повтори', 'еще раз', 'стоп', 'хватит', 'дальше')
SAMPLE_RATE = 24000
TAIL_PAD_S = 0.5
_WORD = re.compile(r'[A-Za-zА-Яа-яЁё]+(?:-[A-Za-zА-Яа-яЁё]+)*|\d+')


def default_model_dir():
    return environment(MODEL_DIR_ENV) or str(Path(environment('LOCALAPPDATA', '')) / 'hermes-echo' / 'models' / 'sherpa-small-ru-int8')


def short_path(path):
    """The 8.3 name of an existing Windows path when it is pure ASCII, else the path as it is."""
    if os.name != 'nt':
        return str(path)
    buffer = ctypes.create_unicode_buffer(32768)
    found = ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, len(buffer))
    return buffer.value if found and buffer.value.isascii() else str(path)


class SherpaEngine:
    """The engine of an ``ear_shadow.EarWorker``: one stream per utterance (``start`` / ``accept`` / ``finish``), used from ONE thread.
    A missing package or model raises here (the worker then reports 'failed')."""

    def __init__(self, model_dir=None, *, decoding='modified_beam_search', threads=1, hotwords_score=1.5):
        import sherpa_onnx                                  # noqa: PLC0415
        folder = short_path(model_dir or default_model_dir())
        path = lambda name: os.path.join(folder, name)     # noqa: E731
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=path('tokens.txt'), encoder=path('encoder.int8.onnx'), decoder=path('decoder.onnx'),
            joiner=path('joiner.int8.onnx'), num_threads=threads, sample_rate=16000, feature_dim=80, decoding_method=decoding,
            max_active_paths=4, modeling_unit='bpe', bpe_vocab=path('unigram_500.vocab'), hotwords_score=hotwords_score)
        self.biased = decoding == 'modified_beam_search'

    def start(self, hotwords=None):
        return self.recognizer.create_stream(hotwords) if hotwords and self.biased else self.recognizer.create_stream()

    def accept(self, stream, pcm):
        samples = array('h')
        samples.frombytes(pcm[:len(pcm) - len(pcm) % 2])
        if sys.byteorder == 'big':
            samples.byteswap()
        stream.accept_waveform(SAMPLE_RATE, [value / 32768.0 for value in samples])
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)

    def peek(self, stream):
        """The text so far, the stream untouched (ear-early): no tail padding, no end of input - the last word may still be unsettled."""
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)
        return self.recognizer.get_result(stream)

    def finish(self, stream):
        stream.accept_waveform(SAMPLE_RATE, [0.0] * int(TAIL_PAD_S * SAMPLE_RATE))
        stream.input_finished()
        while self.recognizer.is_ready(stream):
            self.recognizer.decode_stream(stream)
        return self.recognizer.get_result(stream)


class Bias(str):
    """The hotwords of one utterance (a plain string for every engine) that also says the language of the turn the utterance begins in (U19, ``lang``): what ``LangEngine.start`` reads."""
    lang = 'ru'

    def __new__(cls, text='', lang='ru'):
        self = super().__new__(cls, text or '')
        self.lang = lang
        return self


def english_model_dir():
    """U19-S7: the English streaming model sits beside the Russian one (``sherpa-en-streaming``); no folder, no English ear (the Russian ear stays for every turn)."""
    return Path(default_model_dir()).with_name('sherpa-en-streaming')


class EnglishEngine:
    """The English recognizer: a streaming zipformer transducer of sherpa-onnx (the kroko build or the 20M one; the file names are looked for in the folder), greedy search, no bias. The same contract as ``SherpaEngine``.
    NOT measured on a real model here (U19-S7 needs the model on the laptop): the plumbing is proved with toy engines (tests/test_s5_ear_part.py)."""

    def __init__(self, model_dir=None, *, threads=1):
        import sherpa_onnx                                  # noqa: PLC0415
        folder = Path(model_dir or english_model_dir())
        found = lambda stem: next(iter([*sorted(folder.glob(stem + '*.int8.onnx')), *sorted(folder.glob(stem + '*.onnx'))]), None)    # noqa: E731 - the int8 file first
        encoder, decoder, joiner, tokens = found('encoder'), found('decoder'), found('joiner'), folder / 'tokens.txt'
        if not (encoder and decoder and joiner and tokens.is_file()):
            raise FileNotFoundError('english model')
        encoder, decoder, joiner = (str(short_path(path)) for path in (encoder, decoder, joiner))
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(tokens=str(short_path(tokens)), encoder=encoder, decoder=decoder, joiner=joiner, num_threads=threads,
                                                                       sample_rate=16000, feature_dim=80, decoding_method='greedy_search')

    start = SherpaEngine.start
    accept = SherpaEngine.accept
    peek = SherpaEngine.peek
    finish = SherpaEngine.finish
    biased = False


class LangEngine:
    """U19-S7 (S5 part, no mode key): the recognizer of one utterance follows the language of the turn it begins in. ``start(hotwords)`` reads ``hotwords.lang`` (``Bias``; a plain string is Russian): 'en' and an English
    recognizer that builds -> the English stream, else the Russian one - never a failure of the call (a missing or broken English model is said once, by the error type, and the Russian ear goes on). The English recognizer
    is built by ``english()`` at the first English utterance. A stream is its engine and its stream: ``accept`` / ``peek`` / ``finish`` go where ``start`` went."""

    def __init__(self, russian, english=None):
        self.russian, self.english_factory, self.english_engine, self.english_failed = russian, english, None, english is None

    def english(self):
        if self.english_engine is None and not self.english_failed:
            try:
                self.english_engine = self.english_factory()
            except Exception as error:                      # noqa: BLE001 - no package, no model: the Russian ear stays
                self.english_failed = True
                logger.warning('echo-sync ear english=unavailable reason=%s', type(error).__name__)
        return self.english_engine

    def start(self, hotwords=None):
        engine = self.english() if getattr(hotwords, 'lang', 'ru') == 'en' else None
        engine = engine or self.russian
        return engine, engine.start(None if engine is not self.russian else hotwords)

    def accept(self, stream, pcm):
        stream[0].accept(stream[1], pcm)

    def peek(self, stream):
        return stream[0].peek(stream[1])

    def finish(self, stream):
        return stream[0].finish(stream[1])


def ear_engine():
    """The engine of the process's shared ear worker: Russian always, English where its folder is (``LangEngine``)."""
    return LangEngine(SherpaEngine(), english=EnglishEngine if (english_model_dir() / 'tokens.txt').is_file() else None)


def _protected(word):
    """A number (digits, or a number word in any case: «первая», «ста», «двухстах») or «не»/«ни»: what ru_alignment protects."""
    if word.isdigit() or word in ('не', 'ни'):
        return True
    return any(atom.kind in ('n', 'p') for atom in _canonical(word, (), True))


MATERIAL_TERMS = 30          # C6: at most this many words of the material go into the bias
MATERIAL_CHARS = 1200        # ... and the whole bias string stays under about this long
MATERIAL_MIN_LETTERS = 5


def _plain_words(text):
    """Runs of plain words, cut at every number and «не»/«ни»."""
    runs, run = [], []
    for token in _WORD.findall(text or ''):
        word = token.casefold()
        if _protected(word):
            if run:
                runs.append(run)
            run = []
        else:
            run.append(word.replace('-', ' '))
    if run:
        runs.append(run)
    return runs


def material_terms(material, limit=MATERIAL_TERMS):
    """C6: the plain words of the material (a string or a list of strings) by frequency, forms of one 6-letter stem counted together (the most
    frequent form stands for them), longest first among equals. Never a digit, a number word or «не»/«ни»."""
    if isinstance(material, str):
        material = [material]
    counts = {}
    for text in material or ():
        for run in _plain_words(text):
            for word in run:
                if len(word) >= MATERIAL_MIN_LETTERS and ' ' not in word and word not in COMMAND_HOTWORDS:
                    counts[word] = counts.get(word, 0) + 1
    best = {}
    for word, n in counts.items():
        total, top, top_n = best.get(word[:6], (0, word, 0))
        best[word[:6]] = (total + n, word if n > top_n or (n == top_n and len(word) > len(top)) else top, max(n, top_n))
    ranked = sorted(best.values(), key=lambda v: (-v[0], -len(v[1]), v[1]))
    return [word for _, word, _ in ranked[:limit]]


def hotwords_for(portion, material=None, base=None):
    """The bias for one utterance, '/'-separated: the waiting portion's runs of plain words, then the answer's terms (C6, ``material_terms``), then the
    terms of the BASE (E60: the owner's materials, ``materials/context.md``, a list from ``base_terms``), then the command words. Both kinds of terms
    are cut to fit MATERIAL_CHARS, the answer's first. The portion and the command words always stay; a base term that is already in the bias is not
    repeated."""
    head = list(dict.fromkeys(' '.join(words) for words in _plain_words(portion) if sum(len(w) for w in words) >= 4))
    room = MATERIAL_CHARS - sum(len(p) + 1 for p in head + list(COMMAND_HOTWORDS))
    extra = []
    for term in [*(material_terms(material) if material else ()), *(base or ())]:
        if any(term in p.split() for p in head) or term in extra:
            continue
        if room < len(term) + 1:
            break
        extra.append(term)
        room -= len(term) + 1
    return '/'.join(dict.fromkeys(head + extra + list(COMMAND_HOTWORDS)))


def base_terms(text, limit=MATERIAL_TERMS):
    """E60: the terms of the BASE (the whole text of the owner's materials, one string): ``material_terms`` of it - plain words by frequency, never a number or
    «не»/«ни» - as a list for ``hotwords_for(base=...)``. Pure; the reading of the file and its cache are ``ear_shadow.base_reader``."""
    return material_terms(text, limit=limit) if text else []

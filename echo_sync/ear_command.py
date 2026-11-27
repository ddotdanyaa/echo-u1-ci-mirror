"""w8-donors N74: a stop heard on the ear's text so far (a *peek*, ear_shadow.EarFeed, on ``ear_early_ms`` of silence inside an utterance)
instead of after the end of the utterance (local_ear.OFFSET_MS = 300 ms of silence, then the 0.5 s tail pad is decoded). With
``ear_early_ms`` = 135 a stop stops the cue about 300 - 135 = 165 ms sooner, plus the final decode (calculation, not a measurement).

Why not sherpa-onnx's KeywordSpotter (sherpa_onnx/keyword_spotter.py, 2.0.1): it needs its own KWS transducer, and no Russian one is
published by the project (the ones listed are Chinese and English); the ear's streaming Russian model already has the command words in its
hotwords (ear_sherpa.COMMAND_HOTWORDS), so the peek IS the keyword spotter, at no extra model or CPU.

Only the stop family acts early (user_intents.is_stop: the WHOLE peek is [lead]* CORE [adjunct]*), because a stop that turns out to be the
start of «Подожди, я хотел спросить …» costs nothing the final would not do anyway (the cue stops either way). «дальше» and «повтори» do not:
a peek «дальше» may be the start of «дальше что было», and a wrong NEXT skips a portion. Own voice: when the cue being spoken has the core
word itself («Хватит одной ложки»), the peek may be the phone's echo of it - the full path, with its own guard, decides. Flag
``ear_command_early`` (off); the integration patch is in cloud_context/reports/w8-donors.md."""
from .textutil import norm_words
from .user_intents import STOP_CORES, fold_asr, is_stop


def early_command(text, *, portion=None, fillers=frozenset()):
    """``'stop'`` when the peek ``text`` is a stop or hold command by itself and the cue being spoken (``portion``) does not say the core
    word, else ``None`` (the final decides)."""
    words = norm_words(text)
    if not words or not is_stop(words, fillers):
        return None
    if portion and STOP_CORES.intersection(fold_asr(words)) & STOP_CORES.intersection(fold_asr(norm_words(portion))):
        return None
    return 'stop'

"""M7, slot S1: the probes of the kind/question owners (``ControlledMedia._judge``, ``_open_question``) and every other reader of the pure language functions
(classifier, user_intents, question_part, lang_hint). ``probe(name, text, ctx)`` reports a ``Feature(value, confidence, origin)`` of the situation; it decides nothing:
the owner of the family reads the feature and rules. ``value`` may be ``UNKNOWN`` («no evidence either way»), which is never a verdict and never a veto.
A new feature of the situation is one row of ``PROBES`` here, and no other file: ``{name: fn(text, **ctx)}``; a row returns the value, or a ``Feature`` when it knows its own confidence.
The functions are read from this module's globals at the call, so ``cm_patch.patch_controller`` reaches them."""
from typing import Any, NamedTuple

from .classifier import _known as known_word, _readings as word_readings
from .classifier import analyze, conjunction_that, contrast_not_but, heard_spelling, open_tail, portion_share, question_part, self_corrected, strip_fillers, turn_end, waiting_portion, what_opener
from .lang_hint import TurnLang, counts as lang_counts, cross_equal, ear_foreign, ear_unknown, lang_hint, lang_spans, word_lang
from .question_part import extract as question_extract
from .user_intents import HESITATION_WORDS, fold_asr, going_on, hearing_repair, is_confirmation_tag, is_repeat_request, is_stop, pause_split, return_topic, stop_kind
from .settings import resolve
from .textutil import norm_words

UNKNOWN = 'unknown'


class Feature(NamedTuple):
    value: Any                # what the probe read; ``UNKNOWN`` when the text gives no evidence
    confidence: float         # 0.0 (unknown) .. 1.0 (a structural reading with no doubt)
    origin: str               # the function that read it: ``module.function``

    @property
    def known(self):
        return self.value is not UNKNOWN and self.value != UNKNOWN


def _words(text, ctx):
    words = ctx.get('words')
    return list(words) if words is not None else norm_words(text)


def _fillers(ctx):
    fillers = ctx.get('fillers')
    return frozenset(fillers) if fillers is not None else frozenset(resolve(ctx.get('settings'))['fillers']) | HESITATION_WORDS


def _word(text, ctx):
    return ctx['word'] if 'word' in ctx else text


# -- classifier: pure readings of one utterance (no verdict: ``analyze`` is the reading the kind judge weighs, not the judge) --
def _analyze(text, state=None, settings=None, qa=(), **_):
    return analyze(text, state, list(qa), settings)


def _strip_fillers(text, settings=None, **_):
    return strip_fillers(text, settings)


def _question_part(text, **_):
    return question_part(text)


def _open_tail(text, **_):
    return open_tail(text)


def _turn_end(text, **_):
    return turn_end(text)


def _waiting_portion(text='', state=None, **_):
    return waiting_portion(state)


def _self_corrected(text, **_):
    return self_corrected(text)


def _portion_share(text, state=None, settings=None, loose_numbers=False, **_):
    share = portion_share(text, state, settings, loose_numbers=loose_numbers)
    return UNKNOWN if share is None else share


def _conjunction_that(text, **ctx):
    """``1`` when the text has a «что» (or «вот почему я») that is a conjunction after a governor, not a question word."""
    return 1 if conjunction_that(_words(text, ctx)) else UNKNOWN


def _contrast_not_but(text, **ctx):
    """``1`` for the form «не X, а Y» with enough around it; the ear writes no mark, the judge may read the form as a question."""
    return 1 if contrast_not_but(_words(text, ctx), _fillers(ctx)) else UNKNOWN


def _what_opener(text, **ctx):
    found = what_opener(_words(text, ctx), _fillers(ctx))
    return UNKNOWN if found is None else found


def _heard_spelling(text, **_):
    return heard_spelling(text)


def _known(text, **ctx):
    return known_word(_word(text, ctx))


def _readings(text, **ctx):
    return word_readings(_word(text, ctx))


# -- user_intents: the shape of a short turn, read on the words --
def _fold_asr(text, **ctx):
    return fold_asr(_words(text, ctx))


def _is_stop(text, **ctx):
    return is_stop(_words(text, ctx), _fillers(ctx))


def _stop_kind(text, **ctx):
    found = stop_kind(_words(text, ctx), _fillers(ctx))
    return UNKNOWN if found is None else found


def _pause_split(text, **ctx):
    found = pause_split(_words(text, ctx), _fillers(ctx))
    return UNKNOWN if found is None else found


def _is_repeat_request(text, **ctx):
    return is_repeat_request(_words(text, ctx), _fillers(ctx))


def _hearing_repair(text, **ctx):
    found = hearing_repair(_words(text, ctx), _fillers(ctx))
    return UNKNOWN if found is None else found


def _is_confirmation_tag(text, **ctx):
    return is_confirmation_tag(_words(text, ctx), _fillers(ctx))


def _going_on(text, **ctx):
    return going_on(_words(text, ctx), _fillers(ctx))


def _return_topic(text, **ctx):
    found = return_topic(_words(text, ctx))
    return UNKNOWN if found is None else found


# -- question_part: the part of a turn that asks --
def _question_extract(text, titles=(), **_):
    return question_extract(str(text or ''), titles=titles)


# -- lang_hint: the language of a word, a text, a turn --
def _lang_hint(text, **_):
    return lang_hint(text)


def _word_lang(text, **ctx):
    found = word_lang(_word(text, ctx))
    return UNKNOWN if found is None else found


def _lang_counts(text, **_):
    return lang_counts(text)


def _lang_spans(text, **_):
    return lang_spans(text)


def _turn_lang(text, turn_lang=None, **_):
    """The language of this turn as the call's ``TurnLang`` reads it (a fresh one when the call has none)."""
    return (turn_lang or TurnLang()).observe(text)


def _ear_foreign(text, known=(), **_):
    return ear_foreign(text, known)


def _ear_unknown(text, known=(), **_):
    return ear_unknown(text, known)


def _cross_equal(text, other='', **_):
    return cross_equal(text, other)


PROBES = {
    'analyze': _analyze,
    'strip_fillers': _strip_fillers,
    'question_part': _question_part,
    'open_tail': _open_tail,
    'turn_end': _turn_end,
    'waiting_portion': _waiting_portion,
    'self_corrected': _self_corrected,
    'portion_share': _portion_share,
    'conjunction_that': _conjunction_that,
    'contrast_not_but': _contrast_not_but,
    'what_opener': _what_opener,
    'heard_spelling': _heard_spelling,
    'known_word': _known,
    'readings': _readings,
    'fold_asr': _fold_asr,
    'is_stop': _is_stop,
    'stop_kind': _stop_kind,
    'pause_split': _pause_split,
    'is_repeat_request': _is_repeat_request,
    'hearing_repair': _hearing_repair,
    'is_confirmation_tag': _is_confirmation_tag,
    'going_on': _going_on,
    'return_topic': _return_topic,
    'question_extract': _question_extract,
    'lang_hint': _lang_hint,
    'word_lang': _word_lang,
    'lang_counts': _lang_counts,
    'lang_spans': _lang_spans,
    'turn_lang': _turn_lang,
    'ear_foreign': _ear_foreign,
    'ear_unknown': _ear_unknown,
    'cross_equal': _cross_equal,
}


def probe(name, text='', ctx=None, **more):
    """``Feature`` of ``text`` read by the row ``name``; the context (``state``, ``settings``, ``words``, ``fillers`` …) is a dict, keywords, or both. An unknown name is an error, not a silent miss."""
    found = PROBES[name](text, **{**(ctx or {}), **more})
    if isinstance(found, Feature):
        return found
    origin = getattr(PROBES[name], '__name__', name).lstrip('_')
    unknown = isinstance(found, str) and found == UNKNOWN
    return Feature(found, 0.0 if unknown else 1.0, f'cm_probes.{origin}')

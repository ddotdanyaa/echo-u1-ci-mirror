"""Helpers of tests/test_r21_first_portion.py (R21: the first thing the listener hears is a short, right gist).

Test code only. Nothing here re-implements a decision: the text an answer arrives as is cleaned by the very functions
``ControlledMedia._admit_text`` calls before ``first_cue`` (``strip_process_prefix``, ``drop_process_sentences``, ``definition_body``,
``compact_opening``, ``expand_abbreviations``, in that order, the profile the call runs in), then ``first_useful.first_cue`` chooses,
and the portions after it are the engine's (``EchoEngine._portions_after``). The only thing simulated is the order of arrival: one
word at a time, with the punctuation that is attached to it, the way the cloud and the text channel deliver a stream.
``fast`` is the text channel (``patient``: its next word is a moment away, digits for numbers); otherwise the cloud's.
"""
from __future__ import annotations

import collections
import re

from echo_sync.engine import EchoEngine
from echo_sync.first_useful import compact_opening, first_cue
from echo_sync.abbrev_state import expand_abbreviations
from echo_sync.settings import CALL_SETTINGS, resolve
from echo_sync.textutil import definition_body, drop_process_sentences, strip_process_prefix

WORD = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*")


def words(text):
    return WORD.findall(text)


def normal(text):
    """Lower case, ё as е, one space between words, no mark at the ends: the way two portions are compared."""
    return ' '.join(str(text or '').casefold().replace('ё', 'е').split()).strip(' .,;:!?…—–-')


def arrivals(answer):
    """The prefixes of ``answer`` as a stream delivers it: ``(text, final)`` after each word (its closing punctuation with it)."""
    ends = [m.end() for m in WORD.finditer(answer)]
    for k, end in enumerate(ends, 1):
        final = k == len(ends)
        while not final and end < len(answer) and not answer[end].isspace() and not answer[end].isalnum():
            end += 1
        yield (answer if final else answer[:end]), final


def admitted(raw, question, *, final, fast=False, settings=CALL_SETTINGS):
    """The text ``first_cue`` gets for the stream ``raw``, as ControlledMedia cleans it."""
    text = strip_process_prefix(raw, question, digits=fast)
    text = drop_process_sentences(text, question, final=final, talk=fast)
    text = definition_body(text, question)
    text = compact_opening(text, question, settings)
    return expand_abbreviations(text, resolve(settings)['abbreviations'])


First = collections.namedtuple('First', 'cue arrived total whole lag')


def first_portion(question, answer, *, fast=False, settings=CALL_SETTINGS):
    """``First(cue, arrived, total, whole, lag)``: the first cue of ``answer`` to ``question``; ``arrived``: the words of the answer that
    had arrived when it was released, of ``total``; ``whole``: the cleaned text of the whole answer that the cue is a prefix of; ``lag``:
    the words of the cleaned text known beyond the cue at that moment (what the first portion waited for). ``cue`` is None when no cue was
    ever released (the controller then waits for more text, or its stall rescue speaks)."""
    total = len(words(answer))
    whole = admitted(answer, question, final=True, fast=fast, settings=settings)
    for k, (raw, final) in enumerate(arrivals(answer), 1):
        text = admitted(raw, question, final=final, fast=fast, settings=settings)
        if not text:
            continue
        cue = first_cue(text, question, settings, final=final, last=final, patient=fast)
        if cue:
            known = len(words(text)) - (0 if final or not text[-1:].isalnum() else 1)
            return First(cue, k, total, whole, known - len(words(cue)))
    return First(None, None, total, whole, None)


def after(cue, whole, settings=CALL_SETTINGS):
    """The portions the engine dictates after the first cue ``cue`` of ``whole`` (EchoEngine.publish: ``[first] + _portions_after``)."""
    return EchoEngine._portions_after([cue], whole[len(cue):], resolve(settings))

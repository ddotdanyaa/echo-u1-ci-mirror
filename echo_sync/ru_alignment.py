"""Minimal dependency adapter using the same pymorphy3 morphology as production."""
from __future__ import annotations
import functools
import threading

_LOCK=threading.RLock()
_MORPH=None

@functools.lru_cache(maxsize=8192)
def _lemma(word):
    global _MORPH
    import pymorphy3
    with _LOCK:
        if _MORPH is None:
            _MORPH=pymorphy3.MorphAnalyzer()
        try:
            return _MORPH.parse(word)[0].normal_form.replace('ё','е')
        except Exception:
            return word.replace('ё','е')

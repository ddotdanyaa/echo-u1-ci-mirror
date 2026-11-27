"""Trim the engine's silence around synthesized cue PCM before it is sent to the phone.

The Windows SAPI voice opens every WAV with ~55 ms of exact digital zero and a content-independent
pre-roll click (peaks up to ~75), so its first phoneme starts 105-130 ms into the audio, or ~250 ms
when the cue opens with a plosive closure (measured on the real worker, 2026-11-01). The transport
paces PCM out in real time, so all of that is added to the delay before the listener hears the cue.
The front is cut (``trim_leading_silence``), keeping a short lead-in so the first phoneme is not clipped.

Every cue also ENDS in ~0.78 s of silence (760-814 ms measured). On the open speaker the phone keeps its microphone closed while
a response plays and 0.35 s after it (scripts/DUAL_SYSTEM_DESIGN.md §1.2), so that silence kept the listener deaf for ~1.2 s after
the voice had stopped and a quick repeat lost its first words. ``trim_trailing_silence`` keeps ``TAIL_KEEP_MS`` after the last
audible sample and drops the rest (task S0). The silence timer and the window in which the cue can be heard back count from the
voice, not from the PCM end (controlled_media.ControlledMedia.playback_done), so the trim does not change how long the listener has.

Samples are never modified: a trim returns a suffix (front) or a prefix (tail) of its input, and never a voiced sample less.

``voiced_seconds`` tells where the voice STOPS in a cue: the transport reports it, so that the window in which the cue can be heard
back ends there and not at the PCM end (see controlled_media.CUE_TAIL_SECONDS).
"""
from __future__ import annotations

import sys
from array import array

SAMPLE_RATE = 24000          # Hz, 16-bit mono, as produced by sapi_worker.ps1
LEAD_IN_KEEP_MS = 40         # silence kept in front of the first audible sample
# |sample| above this is sound. 128 is about -48 dBFS: above the engine's own pre-roll (peaks ~75)
# and plosive-closure noise (peaks ~70), below the quietest real phoneme onset measured (~110-150).
AUDIBLE_THRESHOLD = 128
MAX_SCAN_MS = 1500           # look for the first sound only this far in; audio quieter than that is left alone
MAX_TAIL_SCAN_MS = 3000      # look for the last sound only this far from the end (a SAPI cue ends in ~0.8 s of silence)
# Silence kept after the last audible sample. The real voice decays into the engine's own floor (peaks 56-80) within ~40 ms of its
# last audible sample (the six packaged phrases, echo_sync/diag_audio); the diagnostic phrases have been cut to the same 0.12 s.
TAIL_KEEP_MS = 120


def trim_leading_silence(pcm, *, sample_rate: int = SAMPLE_RATE, keep_ms: int = LEAD_IN_KEEP_MS,
                         threshold: int = AUDIBLE_THRESHOLD, max_scan_ms: int = MAX_SCAN_MS) -> bytes:
    """Drop the silence in front of the first audible sample, keeping at most ``keep_ms`` of it.

    Returns the input unchanged when there is nothing worth cutting, when no sound is found within
    ``max_scan_ms`` (never produce empty or surprising audio), or when the input is not whole samples.
    """
    data = bytes(pcm)
    scan = min(len(data) // 2, sample_rate * max_scan_ms // 1000)
    head = array('h')
    head.frombytes(data[:scan * 2])
    if sys.byteorder == 'big':
        head.byteswap()
    first = next((index for index, value in enumerate(head) if value > threshold or value < -threshold), None)
    if first is None:
        return data
    start = first - sample_rate * keep_ms // 1000
    return data[start * 2:] if start > 0 else data


def _last_audible(data: bytes, total: int, *, sample_rate: int, threshold: int, max_tail_ms: int):
    """Index of the last sample louder than ``threshold`` within the last ``max_tail_ms`` of ``total`` samples, or ``None``."""
    scan = min(total, sample_rate * max_tail_ms // 1000)
    tail = array('h')
    tail.frombytes(data[(total - scan) * 2:total * 2])
    if sys.byteorder == 'big':
        tail.byteswap()
    for index in range(scan - 1, -1, -1):
        value = tail[index]
        if value > threshold or value < -threshold:
            return total - scan + index
    return None


def trim_trailing_silence(pcm, *, sample_rate: int = SAMPLE_RATE, keep_ms: int = TAIL_KEEP_MS,
                          threshold: int = AUDIBLE_THRESHOLD, max_tail_ms: int = MAX_TAIL_SCAN_MS) -> bytes:
    """Drop the silence after the last audible sample, keeping at most ``keep_ms`` of it.

    Returns the input unchanged when there is nothing worth cutting, when no sound is found within the last ``max_tail_ms`` (where
    the voice stopped is not known), or when the input is not whole samples. The result is always a prefix of the input.
    """
    data = bytes(pcm)
    if len(data) % 2:
        return data
    total = len(data) // 2
    last = _last_audible(data, total, sample_rate=sample_rate, threshold=threshold, max_tail_ms=max_tail_ms)
    if last is None:
        return data
    end = last + 1 + sample_rate * keep_ms // 1000
    return data[:end * 2] if end < total else data


def trim_silence(pcm, *, threshold: int = AUDIBLE_THRESHOLD) -> bytes:
    """The silence around the voice cut at both ends (the packaged diagnostic phrases): the front keeps ``LEAD_IN_KEEP_MS``, the tail ``TAIL_KEEP_MS``."""
    return trim_leading_silence(trim_trailing_silence(pcm, threshold=threshold), threshold=threshold)


def voiced_seconds(pcm, *, sample_rate: int = SAMPLE_RATE, threshold: int = AUDIBLE_THRESHOLD,
                   max_tail_ms: int = MAX_TAIL_SCAN_MS) -> float:
    """Seconds from the start of ``pcm`` to the end of its last audible sample: where the voice stops.

    ``0.0`` for nothing or for silence. When the last ``max_tail_ms`` hold no sound but the PCM is longer than that, where the voice
    stopped is not known and the whole length is returned (the cautious answer: the cue is taken to play to its end).
    """
    data = bytes(pcm)
    total = len(data) // 2
    if total == 0:
        return 0.0
    last = _last_audible(data, total, sample_rate=sample_rate, threshold=threshold, max_tail_ms=max_tail_ms)
    if last is not None:
        return (last + 1) / sample_rate
    return total / sample_rate if total > sample_rate * max_tail_ms // 1000 else 0.0

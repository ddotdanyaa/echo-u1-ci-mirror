"""w5-near: synthetic near/far speech for the level judge. Voiced signals (harmonic pulse trains with a syllable envelope) plus room noise; the 'phone' may run an AGC. dB are re dBFS of the RMS."""
import math
import random
from array import array

RATE = 16000
NOISE_DB = -58.0
_NOISE = None


def _noise():
    global _NOISE
    if _NOISE is None:
        rnd = random.Random(7);_NOISE = [rnd.gauss(0, 1) for _ in range(RATE)]
    return _NOISE


def _period(f0, harmonics):
    n = RATE // f0
    return [sum(math.sin(2 * math.pi * k * i / n) / k for k in range(1, harmonics + 1)) for i in range(n)]


_VOICES = {'own': _period(125, 12), 'other': _period(200, 6)}


def voice(kind, seconds, db, seed=0):
    """Float samples of RMS ``db`` dBFS: a syllabic envelope of ~4 Hz with gaps, from the voice ``kind``."""
    table = _VOICES[kind];n = int(seconds * RATE);rnd = random.Random(seed * 31 + len(kind))
    phase = rnd.random() * 6.28;rate = 3.5 + rnd.random()
    raw = [table[i % len(table)] * max(0.0, 0.55 + 0.45 * math.sin(2 * math.pi * rate * i / RATE + phase)) ** 1.3 for i in range(n)]
    rms = math.sqrt(sum(x * x for x in raw) / n) or 1.0
    gain = 10 ** (db / 20) * 32768 / rms
    return [x * gain for x in raw]


def room(seconds, seed=0, db=NOISE_DB):
    table = _noise();n = int(seconds * RATE);at = (seed * 977) % RATE
    gain = 10 ** (db / 20) * 32768
    return [table[(at + i) % RATE] * gain for i in range(n)]


def mix(*parts):
    n = max(len(p) for p in parts)
    return [sum(p[i] for p in parts if i < len(p)) for i in range(n)]


def agc(samples, target_db=-20.0, attack_s=0.05, release_s=1.0, max_gain_db=24.0):
    """A toy automatic gain control on 20 ms frames: gain follows the target with a fast attack (down) and a slow release (up)."""
    out = [];gain_db = 0.0;frame = 320
    for at in range(0, len(samples), frame):
        part = samples[at:at + frame];rms = math.sqrt(sum(x * x for x in part) / len(part)) or 1e-3
        level = 20 * math.log10(rms / 32768 + 1e-9);want = max(-6.0, min(max_gain_db, target_db - level))
        tau = attack_s if want < gain_db else release_s
        gain_db += (want - gain_db) * min(1.0, 0.02 / tau);g = 10 ** (gain_db / 20)
        out.extend(x * g for x in part)
    return out


def pcm(samples):
    return array('h', [max(-32768, min(32767, int(round(x)))) for x in samples]).tobytes()


def trained(near, pieces=4, seconds=1.4, own_db=-22.0, noise=True, agc_on=False):
    """Teaches ``near`` the own level with aligned pieces; the floor is learned from a quiet second first."""
    near.feed(pcm(room(1.0, 99)))
    for k in range(pieces):
        s = mix(voice('own', seconds, own_db, k), room(seconds, k)) if noise else voice('own', seconds, own_db, k)
        near.learn(pcm(agc(s) if agc_on else s), aligned=True)
    return near


def scene(kind, other_db, own_db=-22.0, seconds=1.6, seed=0, agc_on=False):
    parts = {'own': [voice('own', seconds, own_db, seed)], 'own_soft': [voice('own', seconds, own_db - 6, seed)], 'other': [voice('other', seconds, own_db + other_db, seed)],
             'both': [voice('own', seconds, own_db, seed), voice('other', seconds, own_db + other_db, seed + 1)], 'noise': []}[kind]
    s = mix(room(seconds, seed + 5), *parts)
    return pcm(agc(s) if agc_on else s)


EXPECT = {'own': 'own', 'own_soft': 'own', 'both': 'own', 'other': 'other', 'noise': 'quiet'}


def rows():
    from echo_sync.near_voice import NearVoice
    out = []
    for agc_on in (False, True):
        near = trained(NearVoice(), agc_on=agc_on)
        for level in range(-3, -21, -1):
            for kind in ('own', 'own_soft', 'both', 'other'):
                for seed in (0, 1):
                    v = near.judge_clip(scene(kind, level, seed=seed, agc_on=agc_on))
                    out.append((agc_on, level, kind, seed, EXPECT[kind], v.kind, v.conf, v.rel_db))
        for seed in range(6):
            v = near.judge_clip(scene('noise', -20, seed=seed, agc_on=agc_on))
            out.append((agc_on, 0, 'noise', seed, 'quiet', v.kind, v.conf, v.rel_db))
    return out


if __name__ == '__main__':
    print('agc,other_db,scene,seed,expected,got,conf,rel_db')
    for r in rows():print(','.join(str(x) for x in r))

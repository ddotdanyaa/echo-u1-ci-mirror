"""c22-voice measurement: peak, RMS, clipped share and processing time per 20 ms frame, before/after, at gain 1/2/3 (and presence), on synthetic voices and
on the WAVs of the repository; and the ear check (does a leak of the boosted cue into the microphone make the energy ear hear speech?).
Run: python tools/voice_boost_measure.py   (cloud numbers: NOT the laptop, NOT the phone, NOT the real ear-piece)."""
import array, glob, math, os, sys, time, wave
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from echo_sync import voice_boost as vb
from echo_sync.local_ear import SpeechOnset

RATE = 24000


def smp(pcm):
    a = array.array('h');a.frombytes(pcm);return a


def stats(pcm):
    s = smp(pcm)
    peak = max(map(abs, s))
    rms = math.sqrt(sum(x * x for x in s) / len(s))
    clip = sum(1 for x in s if abs(x) >= 32767) / len(s)
    db = lambda v: round(20 * math.log10(max(v, 1) / 32768), 1)
    return peak, db(peak), round(rms), db(rms), clip


def gain_report(pcm, gain, presence=0.0):
    """U142: what ``voice_boost`` does to ``pcm`` at ``gain``: the RMS and the peak gain in dB, the peak, the number of clipped samples. The one the test and the owner read."""
    out = b''.join(vb.boost_frames(pcm, gain, presence))
    before, after = smp(pcm), smp(out)
    rms = lambda s: math.sqrt(sum(x * x for x in s) / len(s))
    return {'rms_gain_db': round(20 * math.log10(rms(after) / rms(before)), 2), 'peak_gain_db': round(20 * math.log10(max(map(abs, after)) / max(map(abs, before))), 2),
            'peak': max(map(abs, after)), 'clipped': sum(1 for x in after if abs(x) >= 32767), 'bytes_in': len(pcm), 'bytes_out': len(out)}


def synth(amp, seconds=3.0, f0=140.0):
    out = []
    for n in range(int(seconds * RATE)):
        t = n / RATE;env = max(0.0, math.sin(2 * math.pi * 4 * t)) ** 2
        out.append(max(-32768, min(32767, int(amp * env * sum(math.sin(2 * math.pi * f0 * k * t) / k for k in range(1, 20)) / 2.2))))
    return array.array('h', out).tobytes()


def timed(pcm, gain, presence):
    it = vb.boost_frames(pcm, gain, presence);worst = total = 0.0;n = 0;out = []
    while True:
        t = time.perf_counter()
        try:chunk = next(it)
        except StopIteration:break
        d = time.perf_counter() - t;worst = max(worst, d);total += d;n += 1;out.append(chunk)
    return b''.join(out), worst * 1000, total / n * 1000


def ear_onsets(cue, coupling_db):
    k = 10 ** (coupling_db / 20)
    floor = array.array('h', [int(25 * math.sin(n * 0.37)) for n in range(RATE // 2)]).tobytes()
    leak = array.array('h', [max(-32768, min(32767, int(x * k))) for x in smp(cue)]).tobytes()
    ear = SpeechOnset();ear.feed(floor)
    return sum(1 for i in range(0, len(leak), 960) if ear.feed(leak[i:i + 960]) == 'onset')


def main():
    sources = [('synth quiet (amp 2500)', synth(2500)), ('synth normal (amp 9000)', synth(9000)), ('synth loud (amp 30000)', synth(30000))]
    for p in sorted(glob.glob(os.path.join(os.path.dirname(__file__), '..', 'echo_sync', 'diag_audio', '*.wav'))):
        w = wave.open(p);sources.append(('wav ' + os.path.basename(p), w.readframes(w.getnframes())))
    print('%-28s %-11s %7s %7s %8s %8s %8s %9s %9s' % ('source', 'gain/pres', 'peak', 'dBFS', 'rms', 'dBFS', 'clip%', 'max ms/fr', 'avg ms/fr'))
    for name, pcm in sources:
        for gain, pres in ((1.0, 0), (2.0, 0), (vb.OWNER_GAIN, 0), (3.0, 0), (2.0, 4.0), (3.0, 4.0)):
            out, worst, avg = (pcm, 0.0, 0.0) if gain == 1.0 and not pres else timed(pcm, gain, pres)
            pk, pkdb, r, rdb, clip = stats(out)
            print('%-28s %-11s %7d %7.1f %8d %8.1f %8.4f %9.3f %9.3f' % (name, '%g/%g' % (gain, pres), pk, pkdb, r, rdb, clip * 100, worst, avg))
    print('\nprepare (portion RMS pass) for a 5 s portion:')
    pcm = synth(9000, 5.0);t = time.perf_counter();vb.portion_norm(smp(pcm));print('  %.3f ms' % ((time.perf_counter() - t) * 1000))
    print('\near check: onsets the energy ear counts when the cue leaks into the microphone at the given coupling (cue = answer.wav)')
    w = wave.open(os.path.join(os.path.dirname(__file__), '..', 'echo_sync', 'diag_audio', 'answer.wav'));cue = w.readframes(w.getnframes())
    print('%-10s %-8s %-8s %-8s' % ('coupling', 'gain 1', 'gain 2', 'gain 3'))
    for c in (-50, -40, -30, -20, -10):
        print('%-10s %-8d %-8d %-8d' % ('%d dB' % c, ear_onsets(cue, c), ear_onsets(b''.join(vb.boost_frames(cue, 2.0)), c), ear_onsets(b''.join(vb.boost_frames(cue, 3.0)), c)))


if __name__ == '__main__':
    main()

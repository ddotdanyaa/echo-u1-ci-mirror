"""N153 (the criterion «разборчивость»): an intelligibility proxy for a voiced WAV in the band of an ear-piece, to put two voices side by side (SAPI Irina and any other) on the same phrase.
Prints rms_dbfs, peak_dbfs, band_share (energy of 300-3400 Hz over the whole) and cons_share (2000-3400 Hz over 300-3400 Hz: where the fricatives and the consonants live). A proxy, not a listening test:
measure on the laptop and write the rows with a measurement passport (ANALYSIS_20261105/07_METRICS_PROVENANCE.md section 6).
Run: python tools/voice_clarity.py a.wav [b.wav ...]"""
import sys
import wave

import numpy as np

BAND = (300.0, 3400.0)
CONSONANTS = (2000.0, 3400.0)


def clarity(pcm, rate=24000):
    """``pcm``: 16-bit mono little-endian bytes. The four numbers of the module docstring."""
    x = np.frombuffer(bytes(pcm[:len(pcm) // 2 * 2]), dtype='<i2').astype(np.float64)
    if not len(x):
        return {'rms_dbfs': float('-inf'), 'peak_dbfs': float('-inf'), 'band_share': 0.0, 'cons_share': 0.0}
    spectrum = np.abs(np.fft.rfft(x)) ** 2
    freq = np.fft.rfftfreq(len(x), 1.0 / rate)

    def energy(low, high):
        return float(spectrum[(freq >= low) & (freq <= high)].sum())
    total, band, cons = float(spectrum.sum()), energy(*BAND), energy(*CONSONANTS)
    db = lambda value: round(20 * float(np.log10(max(value, 1e-9) / 32768.0)), 1)
    return {'rms_dbfs': db(float(np.sqrt(np.mean(x * x)))), 'peak_dbfs': db(float(np.max(np.abs(x)))),
            'band_share': round(band / total, 3) if total else 0.0, 'cons_share': round(cons / band, 3) if band else 0.0}


def main(paths):
    for path in paths:
        with wave.open(path, 'rb') as audio:
            row = clarity(audio.readframes(audio.getnframes()), audio.getframerate())
        print(path, ' '.join('%s=%s' % item for item in row.items()))


if __name__ == '__main__':
    main(sys.argv[1:])

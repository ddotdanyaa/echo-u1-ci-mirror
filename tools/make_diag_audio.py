#!/usr/bin/env python3
"""Render the spoken-diagnostic phrases with the local SAPI and write them next to the package (echo_sync/diag_audio).

These WAVs are the fallback that keeps a diagnostic playable when the pre-render at the start of a call fails (SAPI
broken). They are made with the production worker script (echo_sync/sapi_worker.ps1: Microsoft Irina Desktop, 24 kHz mono
PCM16, rate 0), so they sound like the cues. Silence around the speech is trimmed exactly like the pre-render does it.

    python tools/make_diag_audio.py            # rewrites echo_sync/diag_audio/*.wav and manifest.json

Offline, local Windows TTS only. Run it again after the wording in echo_sync/diagnostics.py changes: a test compares the
text recorded in the manifest with the phrases in the code.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
import wave
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from echo_sync import diagnostics, pcm_trim  # noqa: E402

WORKER = ROOT / 'echo_sync' / 'sapi_worker.ps1'


def render_all():
    """{key: raw PCM} for every phrase, from one worker process (the same protocol SapiWorkerManager speaks)."""
    process = subprocess.Popen(
        ['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-File', str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding='utf-8', bufsize=1)
    rendered = {}
    try:
        ready = json.loads(process.stdout.readline())
        if ready.get('type') != 'ready' or ready.get('voice') != 'Microsoft Irina Desktop' or ready.get('culture') != 'ru-RU':
            raise SystemExit(f'unexpected SAPI worker: {ready}')
        with tempfile.TemporaryDirectory(prefix='diag-audio-') as scratch:
            for index, (key, text) in enumerate(diagnostics.PHRASES.items()):
                target = Path(scratch) / (key + '.wav')
                process.stdin.write(json.dumps({'id': f'p{index}', 'text': text, 'output_path': str(target)},
                                               ensure_ascii=False) + '\n')
                process.stdin.flush()
                result = json.loads(process.stdout.readline())
                if result.get('ok') is not True:
                    raise SystemExit(f'SAPI could not render {key}: {result.get("error")}')
                rendered[key] = diagnostics.load_wav_pcm(target)
    finally:
        process.stdin.close()
        process.wait(timeout=10)
    return rendered


def write_wav(path, pcm):
    with wave.open(str(path), 'wb') as target:
        target.setframerate(diagnostics.SAMPLE_RATE)
        target.setnchannels(1)
        target.setsampwidth(2)
        target.writeframes(pcm)


def main():
    directory = diagnostics.ASSET_DIR
    directory.mkdir(exist_ok=True)
    phrases = {}
    for key, raw in render_all().items():
        pcm = pcm_trim.trim_silence(raw, threshold=diagnostics.TRIM_THRESHOLD)
        path = directory / (key + '.wav')
        write_wav(path, pcm)
        phrases[key] = {'text': diagnostics.PHRASES[key], 'seconds': round(len(pcm) / diagnostics.BYTES_PER_SECOND, 2),
                        'raw_seconds': round(len(raw) / diagnostics.BYTES_PER_SECOND, 2),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        print(f'{key:16s} {phrases[key]["seconds"]:5.2f} s (raw {phrases[key]["raw_seconds"]:5.2f} s)  {diagnostics.PHRASES[key]}')
    manifest = {
        'voice': 'Microsoft Irina Desktop',
        'format': {'sample_rate': diagnostics.SAMPLE_RATE, 'channels': 1, 'sample_width': 2},
        'generated_by': 'tools/make_diag_audio.py through echo_sync/sapi_worker.ps1 (SAPI rate 0)',
        'generated_on': date.today().isoformat(),
        'trim': {'threshold': diagnostics.TRIM_THRESHOLD, 'head_pad_s': pcm_trim.LEAD_IN_KEEP_MS / 1000,
                 'tail_pad_s': pcm_trim.TAIL_KEEP_MS / 1000},
        'target_seconds': diagnostics.TARGET_SECONDS,
        'phrases': phrases,
    }
    (directory / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()

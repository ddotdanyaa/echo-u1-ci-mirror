"""Реестр 1.06 «Запись звука звонка» (call_audio.py, controlled_host.py): состояние по реестру — РАБОТАЕТ НА СЕРВЕРЕ.
Стенд: helpers_s6_fault.HostRig — настоящий controlled_host.serve() на виртуальном времени, поддельные телефон и облако.
Настройки (живые значения сервера) пишутся настоящим файлом <home>/materials/echo_settings.json из LIVE.
Снаружи видно: файлы <home>/logs/echo_pcm/<звонок>/mic.wav, cue.wav, timeline.jsonl; строка call_close журнала звонка (pcm_rec);
кадры телефону с записью и без неё одни и те же."""
import base64
import wave
from pathlib import Path

import helpers_s6_fault as F
from test_ux_call_trace_host import dictation, normal_end, read_trace, settings_file, what_the_phone_saw

LIVE = {'pcm_record': 'on', 'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200}
PACKETS = [bytes([i + 1]) * 4 + bytes(range(250, 256)) * 100 for i in range(5)]      # пять известных непустых пакетов, каждый свой


def pcm_root(home):
    return Path(home) / 'logs' / 'echo_pcm'


def run_call(tmp_path, monkeypatch, settings, prepare=None):
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            settings_file(host.home, **settings)
            if prepare:
                prepare(host)
            await host.handshake()
            for p in PACKETS:
                host.ws.push({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(p).decode()})
            await dictation(host)
            await host.advance(20)
        return host
    return F.run(main)


def only_call_dir(home):
    dirs = [p for p in pcm_root(home).iterdir() if p.is_dir()]
    assert len(dirs) == 1, dirs
    return dirs[0]


def pcm_of(path):
    with wave.open(str(path), 'rb') as w:      # заголовок после закрытия звонка исправлен: wave читает файл как есть
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 24000)
        return w.readframes(w.getnframes())


def close_record(host):
    return [r for r in read_trace(host.home) if r.get('ev') == 'call_close'][0]


def test_live_call_leaves_mic_and_cue_wavs_and_a_timeline(tmp_path, monkeypatch):
    host = run_call(tmp_path, monkeypatch, LIVE)
    folder = only_call_dir(host.home)
    mic = pcm_of(folder / 'mic.wav')
    assert all(mic.count(p) == 1 for p in PACKETS), 'каждый пакет микрофона лёг в запись целиком'
    assert [mic.find(p) for p in PACKETS] == sorted(mic.find(p) for p in PACKETS)
    cues = [base64.b64decode(f.data['delta']) for f in host.audio()]
    assert cues, 'сценарий озвучивает подсказки'
    cue = pcm_of(folder / 'cue.wav')
    assert all(c in cue for c in cues)
    lines = (folder / 'timeline.jsonl').read_text(encoding='utf-8')
    assert '"ev": "open"' in lines and '"cap_mb": 1200' in lines, 'потолок одного звонка из живых настроек'


def test_close_record_carries_the_recording_state(tmp_path, monkeypatch):
    host = run_call(tmp_path, monkeypatch, LIVE)
    rec = close_record(host)['pcm_rec']
    assert rec['state'] == 'on' and rec['bytes'] >= sum(map(len, PACKETS)) and rec['dropped'] == 0


def test_the_phone_sees_the_same_with_recording_on_and_off(tmp_path, monkeypatch):
    on = run_call(tmp_path / 'on', monkeypatch, LIVE)
    off = run_call(tmp_path / 'off', monkeypatch, {})
    assert what_the_phone_saw(on) == what_the_phone_saw(off) and len(what_the_phone_saw(on)) > 10
    assert normal_end(on.outcome) and normal_end(off.outcome)
    assert pcm_root(on.home).exists() and not pcm_root(off.home).exists()


def test_live_keep_limit_does_not_prune_old_calls(tmp_path, monkeypatch):
    def prepare(host):
        for name in ('old1', 'old2', 'old3'):
            (pcm_root(host.home) / name).mkdir(parents=True)
            (pcm_root(host.home) / name / 'mic.wav').write_bytes(b'x')
    host = run_call(tmp_path, monkeypatch, LIVE, prepare)
    assert len(list(pcm_root(host.home).iterdir())) == 4, 'живые 200 звонков / 8192 МБ: старые три и новый целы'

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

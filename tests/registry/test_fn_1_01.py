"""Реестр 1.01 «Слушать всегда, и во время подсказки». Состояние по реестру: СЛОМАНО (телефон не шлёт микрофон во время подсказки).

Стенд: настоящий controlled_host.serve() через HostRig (поддельный телефон, помощник, SAPI, виртуальное время). Настройки LIVE — живые
значения сервера (facts_journal=on, call_trace=on; mic_gap_ms=1500, mic_ring_s=60 — умолчания, действуют на сервере) пишутся настоящим
файлом materials/echo_settings.json. Снаружи наблюдаем: что ушло помощнику наверх (кадры 'P'), журнал звонка logs/echo_calls/*.jsonl
(duplex, ready_verdict, mic_gap, mic_facts) и строка «Controlled call closed» агентского лога.
Доказана серверная часть: всё, что телефон прислал, доходит наверх и считается, а молчание микрофона на время подсказки записывается
честно (дыра, вердикт «half»). Заставить телефон слать звук сервер не может: это проверяется только на телефоне (см. registry_proof/1.01.json)."""
import asyncio
import base64
import json
from pathlib import Path

import helpers_s6_fault as F

LIVE = {'preset': 'meaning', 'ack_match': 'stem', 'on_mismatch': 'replay_if_attempt', 'local_ear': 'off',
        'instant': 'on', 'two_witnesses': 'on', 'input_state': 'on', 'lang_turn': 'shadow', 'facts_journal': 'on', 'call_trace': 'on',
        'mic_gap_ms': 1500, 'mic_ring_s': 60, 'repeat_seconds': 2.0, 'max_auto_repeats': 3, 'record_mode': 'earned', 'open_overlap': 'on',
        'stop_in_flight': 'on', 'pcm_record': 'off'}
APPEND = {'type': 'input_audio_buffer.append', 'audio': base64.b64encode(bytes(4800)).decode()}      # 100 мс микрофона
ECHO_TAIL = 0.35


def cue_in_flight(host):
    for frame in reversed(host.ws.frames):
        if frame.type in {'response.created', 'response.done', 'output_audio_buffer.clear'}:
            return frame.type == 'response.created'
    return False


async def phone_mic(host, seconds, sent, *, half_duplex):
    """Микрофон телефона: пакет раз в 100 мс; «половинный» телефон молчит на время подсказки и 0,35 с после неё."""
    end, quiet = host.now() + seconds, 0.0
    while host.now() < end:
        if cue_in_flight(host):
            quiet = host.now() + ECHO_TAIL
        if not (half_duplex and (cue_in_flight(host) or host.now() < quiet)):
            host.ws.push(APPEND)
            sent.append(1)
        await host.advance(0.1)


def a_call(tmp_path, monkeypatch, *, half_duplex, seconds=14):
    async def main():
        F.patch_clock(monkeypatch)
        sent = []
        async with F.HostRig(tmp_path, monkeypatch, synth=[('long', 2.5)]) as host:
            folder = host.home / 'materials'
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'echo_settings.json').write_text(json.dumps(LIVE), encoding='utf-8')
            await host.handshake()
            phone = asyncio.create_task(phone_mic(host, seconds, sent, half_duplex=half_duplex))
            await host.ask(F.DIRECT_QUESTION, tid='u1')
            await host.answer(F.DIRECT_ANSWER, tid='a1')
            await phone
        up = sum(1 for kind, _ in host.bridges[-1].sent if kind == 'P')
        return host, len(sent), up
    return F.run(main)


def journal(host):
    files = sorted((f for f in Path(host.home, 'logs', 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def test_a_phone_that_keeps_sending_is_heard_during_the_cues(tmp_path, monkeypatch):
    host, sent, up = a_call(tmp_path, monkeypatch, half_duplex=False)
    rows = journal(host)
    duplex = next(r for r in rows if r['ev'] == 'duplex')
    verdict = next(r for r in rows if r['ev'] == 'ready_verdict')
    assert sent > 120 and up == sent                                   # каждый пакет телефона дошёл до помощника, в том числе во время подсказки
    assert duplex['cues'] >= 1 and duplex['cue_span_s'] > 2.0 and duplex['cue_coverage'] > 0.9 and duplex['verdict'] == 'full' and duplex['mic_missing_cue_s'] < 1.0
    assert verdict['mic_kept'] is True and verdict['reason'] == 'packets_kept_arriving'
    assert not [r for r in rows if r['ev'] == 'mic_gap']               # ни одной дыры: микрофон слышен весь звонок
    assert next(r for r in rows if r['ev'] == 'mic_facts')['appends'] == sent


def test_a_phone_that_goes_quiet_during_the_cue_leaves_an_honest_gap_in_the_journal(tmp_path, monkeypatch):
    host, sent, up = a_call(tmp_path, monkeypatch, half_duplex=True)
    rows = journal(host)
    cues = [r for r in rows if r['ev'] == 'cue_end' and 'first_ms' in r]
    gaps = [r for r in rows if r['ev'] == 'mic_gap']
    duplex = next(r for r in rows if r['ev'] == 'duplex')
    verdict = next(r for r in rows if r['ev'] == 'ready_verdict')
    assert up == sent and cues                                         # сервер передал всё, что получил; подсказки были
    assert gaps and all(g['cause'] == 'unknown' for g in gaps)         # причину сервер не знает и не выдумывает
    backs = [r for r in rows if r['ev'] == 'mic_back']
    assert any(g['start_ms'] <= c['first_ms'] and b['at_ms'] >= c['last_ms'] for c in cues for g in gaps for b in backs)   # дыра от подсказки до возвращения микрофона
    assert duplex['verdict'] == 'half' and duplex['cue_coverage'] < 0.05 and duplex['mic_missing_cue_s'] > 2.0
    assert verdict['mic_kept'] is False and verdict['reason'].startswith('no_packets_while_the_cue_played')
    assert next(r for r in rows if r['ev'] == 'mic_facts')['gaps'] == len(gaps)


def test_the_gap_tolerance_of_the_setting_decides_what_is_a_gap(tmp_path, monkeypatch):
    """mic_gap_ms: пока подсказка короче допуска, молчание телефона не дыра. Допуск 60000 мс — дыр нет, но вердикт «half» остаётся."""
    monkeypatch.setitem(LIVE, 'mic_gap_ms', 60000)
    host, sent, up = a_call(tmp_path, monkeypatch, half_duplex=True)
    rows = journal(host)
    assert not [r for r in rows if r['ev'] == 'mic_gap'] and next(r for r in rows if r['ev'] == 'duplex')['verdict'] == 'half'

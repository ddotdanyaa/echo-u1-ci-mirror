"""Реестр 1.07 «Ранний буфер, кольцо, сетевая рябь» (native_media_socket.py: g9-boot, pre-ready buffer): состояние: ВКЛЮЧЕНО (U76: keep_pre_ready убран, буфер всегда).
Стенд: helpers_s6_fault.HostRig — настоящий controlled_host.serve() на виртуальном времени, поддельные телефон и помощник-труба.
Настройки: ключа у функции нет (код её не включает нигде), LIVE — живые значения серверных ключей, влияющих на путь микрофона.
Снаружи видно: пакеты микрофона ('P'), ушедшие помощнику (host.bridge.sent), и кадры телефону. Целевое поведение: слова, сказанные пока
канал не готов (до conduit.turn.done), после готовности уходят помощнику по порядку, не больше последних 6 с. Кольца и сетевой ряби в коде нет."""
import base64

import helpers_s6_fault as F
from test_ux_call_trace_host import settings_file

LIVE = {'local_ear': 'act', 'instant': 'on', 'fast_text': 'on', 'facts_journal': 'on'}
PRE = [bytes([i + 1]) * 960 for i in range(5)]      # пять известных пакетов по 20 мс, сказанных до готовности канала
AFTER = bytes([200]) * 960                          # пакет после готовности


def mic_sent(host):
    return [p for k, p in host.bridge.sent if k == 'P']


def append(pcm):
    return {'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pcm).decode()}


def call(tmp_path, monkeypatch, before):
    """Подключение: session.update -> (телефон говорит ``before``) -> маркер готовности -> один пакет после готовности."""
    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            settings_file(host.home, **LIVE)
            host.ws.push({'type': 'session.update', 'session': {}})
            assert await host.until(lambda: any(f.type == 'session.updated' for f in host.ws.frames), 120)
            for pcm in before:
                host.ws.push(append(pcm))
            await host.advance(0.5)
            host.ws.push({'type': 'response.create', 'response': {'conversation': 'none', 'input': [{'content': [{'text': 'conduit-ready-s6'}]}]}})
            assert await host.until(lambda: any(f.type == 'conduit.turn' for f in host.ws.frames), 5)
            marker = next(f for f in host.ws.frames if f.type == 'conduit.turn')
            host.ws.push({'type': 'conduit.turn.done', 'turn_id': marker.data['turn_id']})
            assert await host.until(lambda: any(f.type == 'response.done' for f in host.ws.frames), 5)
            host.ws.push(append(AFTER))
            await host.advance(1)
            assert host.outcome is None and not host.errors()
        return host
    return F.run(main)


def test_audio_after_ready_reaches_the_helper(tmp_path, monkeypatch):      # контроль стенда: измеряемый путь работает
    host = call(tmp_path, monkeypatch, [])
    assert mic_sent(host) == [AFTER]


def test_words_spoken_before_the_channel_is_ready_are_heard_in_order_after_it(tmp_path, monkeypatch):
    host = call(tmp_path, monkeypatch, PRE)
    assert mic_sent(host)[-1] == AFTER, 'контроль: пакет после готовности дошёл'
    assert mic_sent(host) == PRE + [AFTER], 'первые слова не потеряны, ушли по порядку до новых'


def test_the_kept_start_is_bounded_to_the_newest_six_seconds(tmp_path, monkeypatch):
    many = [bytes([i % 250 + 1]) * 960 for i in range(400)]      # 8 с по 20 мс
    host = call(tmp_path, monkeypatch, many)
    sent = mic_sent(host)
    assert len(sent) > 1 and sent[-1] == AFTER and sent[-2] == many[-1], 'новейшее слово сохранено'
    assert 0 < sum(map(len, sent[:-1])) <= 6 * 48000, 'сохранено не больше 6 с, старейшее отброшено'

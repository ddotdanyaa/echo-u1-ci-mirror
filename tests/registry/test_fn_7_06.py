"""Реестр 7.06 «Быстрый старт звонка»: три ключа профиля warm_start / spare_helper / open_overlap (на сервере владельца все три on).

Ключи ставятся файлом materials/echo_settings.json профиля, как на сервере. Прогрев запускает настоящий вход плагина echo_sync.register(ctx)
с подставным ctx Hermes; звонок ведёт настоящий controlled_host.serve на подставных телефоне, звуковом помощнике и SAPI (HostRig, виртуальное время).
Смотрим только наружу: сколько раз файл материала читался с диска (на старте сервера и на звонке), какой помощник получил команды открытия
и в каком порядке относительно чтения материала, были ли голос и ухо подняты до звонка. Подмены на границе: диск (Path.read_text для
context.md), голос SAPI и распознаватель уха (их запускают внешние процессы), hermes_constants и ctx Hermes.
"""
import json
import pathlib
import sys
import threading
import time
import types
from pathlib import Path

import helpers_s6_fault as F
from echo_sync import controlled_host, warm

ON = {'warm_start': 'on', 'spare_helper': 'on', 'open_overlap': 'on'}
OFF = {'warm_start': 'off', 'spare_helper': 'off', 'open_overlap': 'off'}
LESSON = 'Закон Ома связывает ток, напряжение и сопротивление цепи.'


def prepare(tmp_path, monkeypatch, flags, **more):
    """Профиль с ключами и материалом; события чтения файла материала и команд помощнику идут в один список в порядке времени."""
    folder = Path(tmp_path) / 'home' / 'materials'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'echo_settings.json').write_text(json.dumps(dict(flags, subject='Физика', **more)), encoding='utf-8')
    (folder / 'context.md').write_text(LESSON, encoding='utf-8')
    events, real_read, real_send = [], pathlib.Path.read_text, F.FakeBridge.send

    def read_text(self, *args, **kwargs):
        if self.name != 'context.md':
            return real_read(self, *args, **kwargs)
        events.append('read_start')
        time.sleep(0.05)                                  # диск медленный: чтение материала видно во времени
        try:
            return real_read(self, *args, **kwargs)
        finally:
            events.append('read_end')

    async def send(self, kind, payload=b''):
        events.append('send_' + kind)                     # C: просьба о предложении соединения, самая первая команда открытия
        return await real_send(self, kind, payload)

    monkeypatch.setattr(pathlib.Path, 'read_text', read_text)
    monkeypatch.setattr(F.FakeBridge, 'send', send)
    F.patch_clock(monkeypatch)
    return events


async def one_call(tmp_path, monkeypatch):
    """Один звонок до готовности; возвращает стенд (после выхода из него звонок закрыт)."""
    async with F.HostRig(tmp_path, monkeypatch) as host:
        monkeypatch.setattr(controlled_host, 'ThreadedHelperBridge', lambda *a, **k: F.FakeBridge(host, *a, **k))   # запасной помощник
        await host.handshake()
    await host.advance(1)                                 # запасной помощник стартует сразу после закрытия звонка
    return host


class Ear:
    """Распознаватель уха (sherpa-onnx в отдельной загрузке): считаем, сколько раз его просили подняться."""
    waits = 0

    def wait_ready(self, seconds):
        self.waits += 1
        return True


def start_server(tmp_path, monkeypatch):
    """Старт сервера Hermes: настоящий echo_sync.register(ctx); ждём, пока доработает поток прогрева. Возвращает голос и ухо (подставные)."""
    voice, ear = F.FakeWorker(F.Plan('ok')), Ear()
    monkeypatch.setitem(sys.modules, 'hermes_constants', types.SimpleNamespace(get_hermes_home=lambda: Path(tmp_path) / 'home'))
    monkeypatch.setattr('echo_sync.sapi_worker.profile_sapi_worker', lambda home: voice)
    monkeypatch.setattr('echo_sync.ear_shadow.shared_worker', lambda: ear)
    noop = lambda *a, **k: None
    import echo_sync
    echo_sync.register(types.SimpleNamespace(get_config=lambda key, default=None: default, register_hook=noop, register_middleware=noop,
                                             register_cli_command=noop))
    for thread in threading.enumerate():
        if thread.name == 'echo-warm':
            thread.join(60)
    warm.guard.stop()
    return voice, ear


def test_warm_start_loads_the_material_before_the_first_call(tmp_path, monkeypatch):
    events = prepare(tmp_path, monkeypatch, ON)
    start_server(tmp_path, monkeypatch)
    assert events.count('read_end') == 1, 'при старте сервера материал прочитан один раз'
    events.clear()
    F.run(lambda: one_call(tmp_path, monkeypatch))
    assert 'send_C' in events, 'звонок открыт: помощник получил команду открытия'
    assert 'read_start' not in events, 'материал не читался с диска на звонке: он уже загружен при старте'


def test_warm_start_raises_the_voice_and_the_ear_before_the_first_call(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch, ON, local_ear='act')       # ухо поднимается, только если распознавание включено (живое значение 1.02: act)
    voice, ear = start_server(tmp_path, monkeypatch)
    assert voice.pins >= 1, 'голос SAPI закреплён резидентным до звонка'
    assert ear.waits >= 1, 'ухо запрошено и дождались готовности до звонка'


def test_without_warm_start_nothing_is_loaded_at_start_and_the_call_reads_the_material(tmp_path, monkeypatch):
    events = prepare(tmp_path, monkeypatch, dict(ON, warm_start='off'), local_ear='act')
    voice, ear = start_server(tmp_path, monkeypatch)
    assert events == [] and voice.pins == 0 and ear.waits == 0, 'без ключа старт сервера ничего не грузит'
    F.run(lambda: one_call(tmp_path, monkeypatch))
    assert 'send_C' in events and events.count('read_end') == 1, 'звонок читает материал сам'


def test_spare_helper_is_waiting_and_the_next_call_takes_it(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch, dict(ON, warm_start='off'))
    async def main():
        first = await one_call(tmp_path, monkeypatch)
        assert len(first.bridges) == 2, 'после звонка наготове стоит ещё один помощник'
        spare = first.bridges[1]
        assert spare.sent == [] and spare.closed is False
        second = await one_call(tmp_path, monkeypatch)
        return spare, second
    spare, second = F.run(main)
    assert [kind for kind, _ in spare.sent][:2] == ['C', 'A'], 'второй звонок открыт запасным помощником'
    assert all(not b.sent for b in second.bridges), 'новый помощник для второго звонка не запускался'


def test_without_spare_helper_each_call_starts_its_own(tmp_path, monkeypatch):
    prepare(tmp_path, monkeypatch, dict(ON, warm_start='off', spare_helper='off'))
    first = F.run(lambda: one_call(tmp_path, monkeypatch))
    assert len(first.bridges) == 1


def test_open_overlap_starts_the_helper_while_the_material_is_read(tmp_path, monkeypatch):
    events = prepare(tmp_path, monkeypatch, dict(ON, warm_start='off', spare_helper='off'))
    F.run(lambda: one_call(tmp_path, monkeypatch))
    assert 'read_end' in events and 'send_C' in events
    assert events.index('send_C') < events.index('read_end'), 'помощник начал открытие, пока материал ещё читался'


def test_without_open_overlap_the_helper_waits_for_the_material(tmp_path, monkeypatch):
    events = prepare(tmp_path, monkeypatch, dict(OFF))
    F.run(lambda: one_call(tmp_path, monkeypatch))
    assert events.index('read_end') < events.index('send_C')

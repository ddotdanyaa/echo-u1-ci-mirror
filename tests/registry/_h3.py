"""Стенд реестра, глава 3: ОДИН звонок через настоящий ``controlled_host.serve`` (HostRig из helpers_s6_fault); тест смотрит только наружу.
НАСТОЯЩЕЕ: serve, контроллер, провод, движок, fast_text с потоками заданий, журнал звонка (<home>/logs/echo_calls/*.jsonl), файл настроек, прочитанный до рукопожатия.
СЦЕНАРНОЕ, только на границе: телефон и его микрофон, события облака, синтез SAPI, поиск, часы (виртуальное время), текстовая модель (``Model``: отвечает по одному запросу).
ПРОФИЛЬ: SERVER это живой профиль сервера (приложение А реестра, файл настроек от 13.11 06:33: 43 ключа, которыми он отличается от умолчаний движка) без шести ключей, названных ниже.
Под ним движок сам даёт repeat_seconds=2.0 и выключает ear_job/cloud_form/ear_lookup (как в реестре); пути ноутбука (instant_bank_file, pcm_cache_dir) и тексты subject/style не входят намеренно.
ECHO_REGISTRY_SET="ключ=значение,ключ2=значение2" (значение: JSON, иначе строка) применяется ПОСЛЕДНИМ, поверх SERVER и ``own``: проверка на пустышку (fast_text=off: тест обязан покраснеть)
и проба «а если включить» одной командой, без правки файлов; пустая переменная ничего не меняет. Тест: import pytest, стандартная библиотека и этот помощник; судит по
``host.spoken()``, ``journal``/``decisions``/``cues`` и ``Model.requests``.
ГРАНИЦЫ ПО ЗАПРОСУ (приватные имена движка живут только здесь; переименуют, и звонок с этой границей падает AttributeError, остальные звонки их не трогают):
``play(ear=[...])`` локальное ухо + ``host.voice(...)``; ``roads={...}`` файл ключей запасных дорог и чистое состояние дорог; ``hears``/``hears_more``/``final`` открытый ход облака рядом с ``say``."""
import itertools
import asyncio, base64, json, logging, os, threading, time
from collections import namedtuple
from pathlib import Path

import helpers_s6_fault as F
from echo_sync import fast_text as FT
from echo_sync import codex_road as CR

SERVER = {
    'preset': 'meaning', 'local_ear': 'act', 'fast_text': 'on', 'ear_job': 'on', 'cloud_form': 'on', 'ear_lookup': 'on',
    'material_pick': 'on', 'instant': 'on', 
    'stop_in_flight': 'on', 'bank_rejoin': 'on', 'pcm_cache_mb': 800, 'facts_journal': 'on', 'v5_answer_gate': 'shadow',
    'adopt_missing_words': 1, 'voice_gain': 4.0, 'voice_presence': 3.0, 'open_overlap': 'on', 'max_auto_repeats': 3, 
    'conversation_ledger': 'memory', 'recall_words': 'on', 
    # ОПУЩЕНО 6 из 43 (с ними те же решения и подсказки, проверено): pcm_record, pcm_record_calls, pcm_record_mb, pcm_record_call_mb: пишут звук звонка на диск (cue.wav, mic.wav) и чистят
    # старые записи; spare_helper: запасной звуковой помощник, его задача к концу звонка не завершена («Task was destroyed but it is pending»); warm_start: первый звонок берёт материал и
    # VAD из кэшей всего процесса (с потоком дозаправки), они живут дольше звонка и теста: общее состояние между тестами.
}
Asked = namedtuple('Asked', 'request question')      # что движок послал модели: сырой запрос и текст вопроса в нём
NOISE = base64.b64encode(bytes([20, 0, 236, 255]) * 1200).decode()      # 0.1 с PCM 24 кГц: шум ±20 из 32768 (цифровой нуль движок читает как выключенный микрофон)
LOUD = base64.b64encode(bytes([64, 31, 192, 224]) * 600).decode()        # 0.1 с громкого звука (±8000 из 32768): речь по энергии


def profile(**own):
    """{**SERVER, **own}, последним ECHO_REGISTRY_SET ("ключ=значение,...": значение как JSON, иначе строка)."""
    out = {**SERVER, **own}
    for key, _, value in (item.partition('=') for item in os.environ.get('ECHO_REGISTRY_SET', '').split(',') if '=' in item):
        try: out[key.strip()] = json.loads(value)
        except ValueError: out[key.strip()] = value.strip()
    return out


def asked(request):
    """Вопрос задания: последняя реплика запроса без «Сейчас прозвучало:» (ответ в игре) и без «Распознано:» (слова уха после « / » отброшены)."""
    text = request['input'][-1]['content'][0]['text'].rsplit('Сейчас прозвучало: ', 1)[-1]
    return text[len('Распознано: '):].split(' / ')[0] if text.startswith('Распознано: ') else text


class Model:
    """Текстовая модель на границе (``CR.codex_stream``). ``answers``: {подстрока вопроса: ответ} или функция (вопрос, запрос) -> текст или None; неизвестный вопрос получает '—'
    (так модель движка говорит «нет ответа»), исключение функции это отказ модели. ``requests``: всё, что движок реально отправил, Asked(request, question), по порядку."""

    def __init__(self, answers=None):
        self.answers, self.requests = answers or {}, []

    def __call__(self, credentials):                  # codex_stream(credentials) -> stream(request, cancelled)
        return self.stream

    def stream(self, request, cancelled):
        question = asked(request)
        self.requests.append(Asked(request, question))      # list.append: потокобезопасно
        text = self.answers(question, request) if callable(self.answers) else next((a for k, a in self.answers.items() if k.casefold() in question.casefold()), None)
        yield '—' if text is None else text

    def questions(self):
        return [item.question for item in self.requests]


class Ear:
    """Распознаватель на границе (то, что ShadowEar ждёт от EarWorker): на конец каждой речи отдаёт следующий текст списка; текст это str или (итог, ранний текст на паузе внутри речи).
    Всё сразу, в потоке звонка. Приватные ShadowEar._consumed/_heard/_early: только ими приёмник уха получает ответ воркера, публичного входа нет."""
    state, reason, can_carry = 'ready', None, False

    def __init__(self, texts): self.texts = list(texts)

    def submit(self, sink, uid, op, payload=None):
        final, early = (self.texts[0] if self.texts else ''), None
        if isinstance(final, tuple): final, early = final
        if op == 'audio': sink._consumed(len(payload))
        elif op == 'end': self.texts[:1] = []; sink._heard(uid, final, 1)
        elif op == 'peek': sink._early(uid, payload, early, 1)      # payload это номер пробы; early None: проба ничего не принесла


async def settle(host, within=5.0):
    """Ждёт в НАСТОЯЩЕМ времени, при стоящих виртуальных часах, пока не кончатся потоки заданий модели. ``say``, ``cloud_answer`` и ``host.advance`` зовут его сами (стенд делает
    ``host.advance`` шагами по 0.1 с); звать вручную нужно только после ``host.cloud(...)`` или ``host.ws.push(...)``, перед тем как время двинется."""
    end = time.monotonic() + within
    for _ in range(3):                                # тик, которому пора, может запустить задание: пусть сначала отработает
        await asyncio.sleep(0)
    while any(t.name == 'echo-fast-text' and t.is_alive() for t in threading.enumerate()):
        if time.monotonic() > end:
            raise AssertionError('a model job thread did not end in %s s of real time' % within)
        await asyncio.sleep(0)
        time.sleep(0.001)
    for _ in range(3):                                # что проснулось от конца задания
        await asyncio.sleep(0)


_CALLS = itertools.count()      # calls of this process: the first numbers its turns h1, h2..., the next h1001...


def play(tmp_path, monkeypatch, body, *, model=None, files=None, ear=None, roads=None, **own):
    """Один звонок: файлы ``files`` ({путь внутри home: str или bytes}) и настройки profile(**own) до рукопожатия, рукопожатие, ``await body(host)``; возвращает его результат.
    ``model``: Model или её ``answers``; None: модель, что на всё отвечает '—'. Микрофон телефона (``host.mic``, закрыть: ``host.mic.cancel()``) шлёт пакет комнатного шума каждые 0.1 с:
    без пакетов input_state держит повтор подсказки; ``host.voice('quiet' | 'loud' | 'talk')``: комнатный шум / непрерывная речь / речь с паузами по 0.1 с каждые 0.6 с (короче порога конца речи).
    Уровень INFO логгера 'echo-sync' (без него решений нет в журнале) после звонка возвращается.
    ``ear``: список текстов уха (str или (итог, ранний текст)), по одному на конец каждой речи; [] ухо есть, текстов нет. Облака у уха нет: распознаватель ставится на границе (``ear_shadow.shared_worker``),
    речь для него это громкий звук (``host.voice``); ранний текст (проба на паузе внутри речи) приходит при ear_early_ms>0 и речи с паузами ('talk'). ``roads``: {имя ключа: выдуманное значение} файла ключей запасных дорог; звонок начинается как новый процесс сервера (``reserve_text``: _REST, _BUDGET,
    _PRIMARY пусты, потому что они живут весь процесс, а часы у них настоящие), после звонка прежнее состояние возвращается. Без ``roads`` ключей нет (ни сети, ни второй модели), состояние дорог общее."""
    model = model if isinstance(model, Model) else Model(model)
    monkeypatch.setattr(CR, 'codex_stream', model)
    keys = Path(tmp_path) / ('no-reserve-keys.env' if roads is None else 'reserve-keys.env')      # без roads файла нет: запасная дорога не находит ключей
    if roads is not None: keys.write_text(''.join('%s=%s\n' % item for item in roads.items()), encoding='utf-8')
    monkeypatch.setenv('ECHO_RESERVE_ENV', str(keys))
    if ear is not None:
        from echo_sync import ear_shadow                # только здесь: звонок без уха не зависит от его имён
        ear_shadow.ShadowEar._consumed, ear_shadow.ShadowEar._heard, ear_shadow.ShadowEar._early      # переименовали: AttributeError здесь, не тихая тишина уха
        monkeypatch.setattr(ear_shadow, 'shared_worker', lambda: Ear(ear))      # ear_shadow.shared_worker: единственная точка, где движок берёт распознаватель
    if roads is not None:
        from echo_sync import reserve_text as RT        # RT._REST/_BUDGET/_PRIMARY: отказ, остаток минуты и покой первой модели на весь процесс; RT._LOCK их замок
        boxes = (RT._REST, RT._BUDGET, RT._PRIMARY); kept = [dict(box) for box in boxes]

        def reset(states):
            with RT._LOCK:
                for box, state in zip(boxes, states): box.clear(); box.update(state)
        reset([{}, {}, {'until': 0.0}])      # как после старта процесса

    async def mic(host):
        ticks = 0
        while True:
            ticks += 1
            host.ws.push({'type': 'input_audio_buffer.append', 'audio': LOUD if host.sound == 'loud' or (host.sound == 'talk' and ticks % 6) else NOISE})
            await asyncio.sleep(0.1)

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            real = host.advance

            async def advance(seconds):               # шагами по 0.1 с (тик движка), после каждого settle: время не прыгает через работающее задание
                left = float(seconds)
                while left > 1e-9:
                    await real(min(0.1, left))
                    await settle(host)
                    left = round(left - 0.1, 6)

            def voice(mode):
                assert mode in ('quiet', 'loud', 'talk'), mode
                host.sound = mode
            host.model, host.turns, host.advance, host.voice, host.sound, host.deltas = model, 1000 * next(_CALLS), advance, voice, 'quiet', {}      # turn ids are new across calls too, as the cloud's: U91 takes a repeated id for the same final
            host.mic = asyncio.create_task(mic(host))
            for name, content in {**(files or {}), 'materials/echo_settings.json': json.dumps(profile(**own))}.items():      # настройки последними: файл их не перекроет
                (host.home / name).parent.mkdir(parents=True, exist_ok=True)
                (host.home / name).write_bytes(content if isinstance(content, bytes) else content.encode('utf-8'))
            await host.handshake()
            try:
                return await body(host)
            finally:
                host.mic.cancel()
    log = logging.getLogger('echo-sync')
    was = log.level
    log.setLevel(logging.INFO)
    try: return F.run(main)
    finally:
        log.setLevel(was)
        if roads is not None: reset(kept)


async def say(host, text):
    """Реплика человека, как её отдаёт облако (turn.created, затем turn.done; id каждый раз новый), и 0.3 с звонка."""
    host.turns += 1
    tid = 'h%d' % host.turns
    host.cloud(F.created(tid, 'user', text.split(' ', 1)[0]))
    host.cloud(F.done(tid, 'user', text))
    await host.advance(0.3)


async def hears(host, text):
    """Реплика человека НАЧАЛАСЬ и не кончена: turn.created с первым словом, остальные слова одной дельтой, финала нет; возвращает id хода. Время не двигает (``say`` двигает на 0.3 с): дальше ``host.advance``."""
    host.turns += 1
    tid = 'h%d' % host.turns
    first, _, rest = text.partition(' ')
    host.cloud(F.created(tid, 'user', first)); host.deltas[tid] = 0
    await (hears_more(host, tid, rest) if rest else settle(host))
    return tid


async def hears_more(host, tid, text):
    """Ещё слова открытого хода ``tid`` (дельта; пробел перед ними ставит помощник)."""
    host.deltas[tid] += 1
    host.cloud(F.delta(tid, ' ' + text, host.deltas[tid]))
    await settle(host)


async def final(host, tid, text):
    """Финал открытого хода ``tid`` (turn.done с полным текстом реплики человека). Время не двигает."""
    host.cloud(F.done(tid, 'user', text))
    await settle(host)


async def cloud_answer(host, text):
    """Ответ облака голосом (assistant turn) и 0.3 с звонка."""
    host.turns += 1
    await host.answer(text, tid='c%d' % host.turns)


def journal(host):
    """Записи (dict) единственного журнала звонка; файл v5_tap рядом с ним (<звонок>.v5tap.jsonl) не журнал."""
    files = [f for f in sorted((Path(host.home) / 'logs' / 'echo_calls').glob('*.jsonl')) if '.v5tap' not in f.name]
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def decisions(rows):
    return [(row['kind'], row.get('reason')) for row in rows if row['ev'] == 'decision']


def cues(rows):
    return [row['text'] for row in rows if row['ev'] == 'cue']

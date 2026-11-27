"""Реестр 2.11 «Кто говорит: чужие голоса, адресат, своё эхо». Реестр: ВЫКЛЮЧЕНО - own_voice_guard=shadow (near_voice=off, gate_text=off, speaker_voice=off).
LIVE - весь файл настроек сервера (65 ключей) + own_voice_guard=shadow (умолч.). Отклонения: HostRig - fast_text=off (без поддельной модели он ходит в сеть); Call - topic_recap/v6_memory=off
(умолч.; Call включает их сам); Rig - LIVE через ECHO_REPLAY_PROFILE, near_voice меняется только там, где сказано. Везде настоящий контроллер. HostRig (controlled_host.serve, журнал звонка) - эхо
подсказки; Call (поддельная модель отвечает по смыслу вопроса) - gate_text; Rig (настоящие NativeMediaSocket и ShadowEar, синтетический звук 24 кГц своего и чужого голоса через провод) - near_voice.
Снаружи: озвученное, запросы модели, журнал, решения в логе. Не покрыто: speaker_voice (мёртвый ключ), speech_start, звук телефона."""
import base64
import functools
import json
import logging
import pytest
import helpers_night_memory as N
import helpers_s6_fault as F
import helpers_s6_state as S
from test_h3_tempo import TICK, call  # noqa: F401 - call: фикстура Rig
from test_w9_ear_voice import hush, say
LIVE = {
    'preset': 'meaning', 'portion_sense': 'off', 'abbreviations': {}, 'ack_match': 'stem', 'on_mismatch': 'replay_if_attempt', 'local_ear': 'act', 'ear_early_ms': 0, 'ear_vocab': 'off', 'fast_text': 'on',
    'text_transport': 'http', 'prompt_tempo': 'ear', 'ear_release': 'on', 'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on', 
    'material_pick': 'on', 'warm_start': 'on', 'quick_math': 'on', 'instant': 'on', 'repeat_rule': 'on', 'dictation': 'off', 'dictation_cycle': 'on', 'stumble_place': 'on', 'resume_word': 'on', 'instant_rank': 'on',
    'instant_rank2': 'on', 'two_witnesses': 'on', 'fast_private': 'off', 'stop_in_flight': 'on', 'gate_text': 'off', 
    'bank_rejoin': 'on', 'brain_short': 'off', 'ear_command_early': 'off', 'pcm_cache_mb': 800, 'pcm_record': 'on', 'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 'facts_journal': 'on',
    'v5_answer_gate': 'shadow', 'adopt_missing_words': 1, 'spare_helper': 'on', 'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0, 'open_overlap': 'on', 
    'inline_repeat': False, 'max_auto_repeats': 3, 'record_mode': 'earned', 'local_onset': 'on', 'local_fallback': 'on', 'conversation_ledger': 'memory', 'recall_words': 'on', 'input_state': 'on',
    'lang_turn': 'shadow'}
ANSWER = 'Небо голубое из-за рассеяния света, пока он идёт через воздух вокруг земли.'      # две порции; эхо = первая
CHAT = ['а мы вчера с Ирой ходили на рынок там помидоры подешевели', 'потом созвонимся мне надо бежать на остановку', 'у меня дочка в субботу играет в школьном спектакле']
LAKE = 'Первая порция про озеро байкал. Вторая порция про глубину озера. Третья порция про воду в нём. Четвёртая порция про рыбу омуль. Пятая порция про берега озера.'
xfail = lambda reason: pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.11: ' + reason)      # noqa: E731
say, hush = functools.lru_cache(None)(say), functools.lru_cache(None)(hush)      # синтез звука дорог: один раз на сочетание
OWN, FOREIGN = ('own', -22), ('other', -36)      # голос и громкость в дБ: свой и чужой тихий

@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')

# ---- свой голос подсказки (own_voice_guard) на настоящем хосте ----
def decisions(rows):
    return [(r['kind'], r['reason']) for r in rows if r['ev'] == 'decision']

def echo(tmp_path, monkeypatch, delay):
    """Вопрос, ответ из двух порций, первая подсказка (3 с звука); через delay после начала облако закрывает реплику с её текстом. -> (озвучено, журнал звонка)."""
    async def body(host):
        (host.home / 'materials').mkdir(parents=True)
        (host.home / 'materials' / 'echo_settings.json').write_text(json.dumps({**LIVE, 'fast_text': 'off'}), encoding='utf-8')
        await host.handshake()
        await host.ask('Почему небо голубое?', tid='u1')
        await host.answer(ANSWER, tid='a1')
        await host.advance(0.5 + delay)
        first = host.spoken()[0]
        host.cloud(F.created('e1', 'user', first.split()[0]))
        host.cloud(F.done('e1', 'user', first))
        await host.advance(0.5)
        [path] = [p for p in (host.home / 'logs' / 'echo_calls').glob('*.jsonl') if not p.name.endswith('.v5tap.jsonl')]
        return host.spoken(), [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch, synth=[('long', 3.0)]) as host:
            return await body(host)
    return F.run(main)

def test_shadow_journals_the_echo_as_own_voice_but_accepts_it(tmp_path, monkeypatch):
    """Тень: эхо опознано (decision ack/own_voice_suspect, evidence=announcement), но засчитано: ушла вторая порция. Живой файл дошёл до хоста (шапка журнала)."""
    spoken, rows = echo(tmp_path, monkeypatch, 1.0)
    [suspect] = [r for r in rows if r['ev'] == 'decision' and r['reason'] == 'own_voice_suspect']
    assert suspect['kind'] == 'ack' and suspect['evidence'] == 'announcement' and len(spoken) == 2 and spoken[1] != spoken[0], decisions(rows)
    assert ('ack', 'ack_ru_canonical') in decisions(rows) and (rows[0]['record_mode'], rows[0]['max_auto_repeats'], rows[0]['dictation_cycle']) == ('earned', 3, 'on')

def test_control_a_real_repeat_after_the_cue_is_accepted_without_suspicion(tmp_path, monkeypatch):
    """Контроль: тот же сценарий, но реплика позже конца подсказки (3 с): засчитана, подозрения нет, вторая порция звучит."""
    spoken, rows = echo(tmp_path, monkeypatch, 2.9)
    assert len(spoken) == 2 and ('ack', 'ack_ru_canonical') in decisions(rows) and 'own_voice_suspect' not in [r for _, r in decisions(rows)]

# ---- болтовня по тексту (gate_text) на Call ----
@pytest.mark.parametrize('quiet', [0, pytest.param(len(CHAT), marks=xfail('выключено - gate_text=off (включение ухудшает звонки по U42: ответ 16/молчание 47/таймаут 6 при базе 14/45/4)'))])
def test_gate_text_chatter_goes_to_the_model_or_keeps_quiet(tmp_path, caplog, quiet):
    """Живое gate_text=off: болтовня уходит модели, она отвечает «—». Цель (gate_text=on): болтовня молчит без запроса модели (лог gate_text kind=talk). Вопрос про телефон озвучен ответом по смыслу."""
    mind = lambda r: 'Телефон изобрёл Александр Белл. Это было в позапрошлом веке.' if 'телефон' in N.asked(r) else '—'      # noqa: E731
    call = N.Call(tmp_path, mind=mind, **{**LIVE, 'topic_recap': 'off'})
    try:
        for line in CHAT + ['Кто изобрёл телефон?']:
            call.say(line)
        call.pump(2)
        asked, cues = [N.asked(r) for r in call.all_requests()], call.cues()
    finally:
        call.close()
    assert asked == (CHAT[:len(CHAT) - quiet] + ['Кто изобрёл телефон?']) and cues == ['Телефон изобрёл Александр Белл.'] and caplog.text.count('gate_text kind=talk') == quiet

# ---- чужой голос по громкости (near_voice) на Rig, звук синтетический (helpers_w5_near) ----
def mic(rig, packets, steps):
    for i, pkt in enumerate(packets):
        rig.detector.script.append(steps(i))
        rig.w.client({'type': 'input_audio_buffer.append', 'audio': base64.b64encode(pkt).decode()})
        rig.pump(TICK)
    return rig.ear.current

def utter(rig, voice, text, seed=0):
    """Голос (own/other, дБ) говорит text: пакеты по 100 мс, конец речи, текст от уха."""
    uid = mic(rig, say(voice[0], voice[1], seed=seed), lambda i: 'onset' if i == 0 else 'speech')
    mic(rig, hush(0.1), lambda i: 'end')
    rig.pump(0.15)
    rig.worker.heard(uid, text)
    rig.pump(0.3)

def room(call, monkeypatch, tmp_path, near, train=True):
    """Звонок на живом профиле (ECHO_REPLAY_PROFILE): озеро по порциям, тишина, владелец повторяет четыре порции (облако тоже слышит). Rig ждёт пятую."""
    (tmp_path / 'live.json').write_text(json.dumps(LIVE), encoding='utf-8')
    monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(tmp_path / 'live.json'))
    rig = call(near_voice=near)
    rig.asks('u1', 'Расскажи про озеро байкал', 0, LAKE)
    mic(rig, hush(0.6, 99), lambda i: 'quiet')
    for k in range(4 if train else 0):
        cue = rig.said()[-1]
        utter(rig, OWN, cue.lower().rstrip('.'), seed=k + 1)
        rig.w.feed(S.turn_created(f'r{k}', 'user', cue.split()[0]))
        rig.w.feed(S.turn_done(f'r{k}', 'user', cue))
        rig.pump(0.3)
    return rig

def stopped(rig, caplog, voice):
    """Остановило ли «стоп» этого голоса подсказку (решение stop_pauses_the_answer в логе)."""
    caplog.clear()
    utter(rig, voice, 'стоп', seed=11)
    rig.pump(1.5)
    return 'reason=stop_pauses_the_answer' in caplog.text

def asked(rig, voice):
    """Ушёл ли вопрос этого голоса (ухо и облако слышат его) модели."""
    utter(rig, voice, 'сколько лет живут черепахи', seed=21)
    rig.w.feed(S.turn_created('q1', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('q1', 'user', 'Сколько лет живут черепахи?'))
    rig.pump(1)
    return any('черепах' in r.request['input'][-1]['content'][0]['text'].lower() for r in rig.fake.runs)

@pytest.mark.parametrize('voice, want', [(OWN, True), (FOREIGN, True), pytest.param(FOREIGN, False, marks=xfail('выключено - near_voice=off: чужой голос останавливает подсказку наравне с владельцем'))])
def test_near_voice_stop_of_whose_voice_stops_the_cue(call, monkeypatch, tmp_path, caplog, voice, want):
    """Живое near_voice=off: «стоп» и своим, и чужим тихим голосом (-36 при своём -22 дБ) останавливает. Цель (near_voice=act): чужой не останавливает (ear act=no reason=other_voice)."""
    assert stopped(room(call, monkeypatch, tmp_path, LIVE['near_voice']), caplog, voice) is want

@pytest.mark.parametrize('near, voice, want', [('act', OWN, True), pytest.param('act', FOREIGN, False, marks=xfail('чужие голоса: даже при near_voice=act вопрос чужого голоса уходит модели (ворота гасят стоп, подтверждения, шум)'))])
def test_near_voice_question_of_whose_voice_is_asked_of_the_model(call, monkeypatch, tmp_path, near, voice, want):
    """При near_voice=act вопрос владельца уходит модели (контроль). Цель (молчать на чужие голоса): вопрос чужого тихого голоса (-36 дБ) не уходит."""
    assert asked(room(call, monkeypatch, tmp_path, near), voice) is want

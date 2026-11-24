"""Реестр 1.02 «Локальное ухо: распознавание речи на ноутбуке». Реестр: РАБОТАЕТ НА СЕРВЕРЕ (подтверждено на сервере 13.11); живые local_ear=act, ear_early_ms=0, ear_vocab=off.
Стенд: test_h3_tempo.Rig - настоящие ControlledMedia + NativeMediaSocket + ShadowEar, виртуальное время; подделаны детектор речи уха, работник распознавания (текст приходит, когда скажет тест),
события облака и текстовая модель (FakeStream, сети нет). Профиль: весь живой файл настроек сервера (LIVE, 65 ключей) пишется во временный файл и идёт в стенд через ECHO_REPLAY_PROFILE, стенд
собирает controller_settings и флаги хоста сам. Отступления от живого файла - только в test_the_transports_own_ear...: input_state=off в двух вариантах (иначе оно держит повтор само и маскирует local_onset).
Ключи ear_job/ear_lookup/cloud_form при resolve() гаснут (prepare_wide=off в живом файле) - так же, как на хосте. Снаружи: подсказки и их время. Звук и модели ноутбука тест не меряет."""
import base64
import json

import pytest

import helpers_s6_state as S
from test_h3_tempo import TICK, Rig

LIVE = {"preset": "meaning", "portion_sense": "off", "abbreviations": {}, "local_ear": "act", "ear_early_ms": 0, "ear_vocab": "off", "fast_text": "on",
        "text_transport": "http", "ear_release": "on", "prepare_wide": "off", "ear_job": "on", "turn_mark": "off", "cloud_form": "on", "ear_lookup": "on",
        "material_pick": "on", "warm_start": "on", "instant": "on", "stumble_place": "on",
        "fast_private": "off", "stop_in_flight": "on", "gate_text": "off", 
        "bank_rejoin": "on", "brain_short": "off", "pcm_cache_mb": 800, "pcm_record": "on",
        "pcm_record_calls": 200, "pcm_record_mb": 8192, "pcm_record_call_mb": 1200, "facts_journal": "on", "v5_answer_gate": "shadow", "adopt_missing_words": 1, "spare_helper": "on",
        "near_voice": "off", "voice_gain": 4.0, "voice_presence": 3.0, "open_overlap": "on", "inline_repeat": False, "max_auto_repeats": 3, 
        "local_fallback": "on", "conversation_ledger": "memory", "recall_words": "on", "lang_turn": "shadow"}
LOUD, QUIET = (base64.b64encode(pcm * 2400).decode('ascii') for pcm in (b'\x00\x40', b'\x00\x00'))      # 100 мс: громкий звук (детектор транспорта слышит речь) и тишина
CASES = [('тридцать вторая статья налогового кодекса', 'Статья 32 Налогового кодекса —', 'статья тридцать два налогового кодекса', 'статья тридцать третья налогового кодекса', 'обязанности налоговых органов.'),
         ('восемьдесят первая статья трудового кодекса', 'Статья 81 Трудового кодекса —', 'статья восемьдесят один трудового кодекса', 'статья восемьдесят вторая трудового кодекса', 'расторжение трудового договора'),
         ('что такое сорок вторая статья налогового кодекса', 'Статья 42 Налогового кодекса —', 'статья сорок два налогового кодекса', 'статья сорок три налогового кодекса', 'доходы от источников')]
ids = ['nk32', 'tk81', 'nk42']


@pytest.fixture
def call(monkeypatch, tmp_path):
    made = []

    def make(**over):
        profile = tmp_path / 'profile.json'
        profile.write_text(json.dumps(dict(LIVE, **over), ensure_ascii=False), encoding='utf-8')
        monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(profile))
        monkeypatch.delenv('ECHO_REPLAY_SET', raising=False)
        made.append(Rig(monkeypatch))
        return made[-1]
    yield make
    for rig in made:
        assert rig.w.violations == [], rig.w.violations
        rig.close()


def speaks(rig, text, turn=None, speech=2.0, lag=0.15):
    """Фраза: начало по уху, облако объявляет ход через 0,5 с (turn), конец, через lag текст уха и тик. Возвращает момент конца речи."""
    uid = rig.onset()
    rig.pump(0.5)
    if turn:
        rig.w.feed(S.turn_created(turn, 'user', text.split()[0]))
    rig.pump(speech - 0.5)
    ended = rig.offset()
    rig.pump(lag)
    rig.worker.heard(uid, text)
    rig.pump(TICK)
    return ended


def cloud_asks(rig, asked):
    rig.w.feed(S.turn_created('u1', 'user', asked.split()[0]))
    rig.w.feed(S.turn_done('u1', 'user', asked))
    rig.pump(2 * TICK)


@pytest.mark.parametrize('ear, head, repeat, wrong, second', CASES, ids=ids)
def test_the_bank_answers_on_the_ears_text_before_the_cloud_final(call, ear, head, repeat, wrong, second):
    rig = call()
    ended = speaks(rig, ear, turn='u1')
    assert rig.said() == [head], 'подсказка справочника по тексту уха: облако ход объявило, финала нет'
    assert rig.cues()[0].t - ended <= 0.15 + 2 * TICK + 0.01, 'через долю секунды после конца речи'


@pytest.mark.parametrize('ear, head, repeat, wrong, second', CASES[:2], ids=ids[:2])
def test_the_cloud_final_that_comes_later_adds_no_second_answer(call, ear, head, repeat, wrong, second):
    rig = call()
    speaks(rig, ear, turn='u1')
    rig.pump(0.3)
    assert rig.said() == [head], 'предусловие: подсказка уже есть, финала облака ещё нет'
    rig.w.feed(S.turn_done('u1', 'user', ear.capitalize() + '?'))
    rig.pump(0.5)
    assert rig.said() == [head] and not rig.cues()[0].cleared, 'финал облака лишь подтвердил то, что услышало ухо'


@pytest.mark.parametrize('ear, head, repeat, wrong, second', CASES, ids=ids)
def test_a_repeat_the_ear_heard_moves_to_the_next_portion_before_the_cloud_final_and_another_number_does_not(call, ear, head, repeat, wrong, second):
    rig = call()
    cloud_asks(rig, ear.capitalize())
    assert rig.said() == [head], 'предусловие: банк ответил по облаку'
    rig.pump(1.0)
    speaks(rig, wrong, turn='u2', speech=1.5)
    rig.pump(1.0)
    assert set(rig.said()) == {head}, 'повтор с чужим номером ухо не засчитало: следующей порции нет'
    ended = speaks(rig, repeat, turn='u3', speech=1.5)
    assert rig.said()[-1].startswith(second) and set(rig.said()[:-1]) == {head}, 'повтор верный: следующая порция, облако ещё не закончило ход'
    assert rig.cues()[-1].t - ended <= 0.15 + 2 * TICK + 0.01


@pytest.mark.parametrize('ear, head, repeat, wrong, second', CASES[:2], ids=ids[:2])
def test_a_ready_cue_waits_while_the_ear_hears_the_listener_and_goes_at_the_offset(call, ear, head, repeat, wrong, second):
    rig = call()
    cloud_asks(rig, ear.capitalize())
    rig.onset()
    rig.w.feed(S.turn_done('u2', 'user', repeat.capitalize()))
    rig.pump(TICK)
    assert rig.said() == [head], 'облако уже считает повтор, но ухо слышит, что человек ещё говорит: порция ждёт'
    rig.offset()
    rig.pump(TICK)
    assert len(rig.said()) == 2 and rig.said()[1].startswith(second), 'речь кончилась по уху: пошла следующая порция'


def test_the_transports_own_ear_holds_the_repeat_into_speech_the_cloud_has_not_announced(call):
    """Ухо упало (стенд: работник failed), облако молчит о речи; громкий звук идёт в транспорт. Режим и движок детектора применяются как в хосте (load_onset): sherpa-onnx и модели Silero в облаке нет,
    движок откатывается на энергетический. Живое (первый вариант) держит и input_state=on через input_vad; local_onset=on сам по себе виден только при input_state=off."""
    rig = call()
    rig.w.run(rig.w.wire.load_onset())
    cloud_asks(rig, CASES[0][0].capitalize())
    rig.worker.state, rig.worker.reason = 'failed', 'broken'
    rig.pump(0.2)
    before = 0
    for audio, packets in ((QUIET, 10), (LOUD, 15)):
        before = len(rig.said())
        for _ in range(packets):
            rig.w.client({'type': 'input_audio_buffer.append', 'audio': audio})
            rig.pump(TICK)
    assert (len(rig.said()) > before) is False and set(rig.said()) == {CASES[0][1]}, 'автоповтор подсказки в речь, о которой облако ещё молчит: есть или нет'

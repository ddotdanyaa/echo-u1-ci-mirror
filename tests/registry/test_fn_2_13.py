"""Реестр 2.13 «Склейка обрывков одной реплики». По реестру: РАБОТАЕТ НА СЕРВЕРЕ (действие не измерено), жёстко coalesce_seconds=3.2, ключа нет.
Стенды: 1) настоящий controlled_host.serve() (helpers_s6_fault.HostRig, виртуальное время; подделаны телефон, облачный помощник, SAPI) - путь облака; 2) helpers_g28.Scene (настоящие
ControlledMedia, ухо local_ear=act, текстовый канал fast_text; подделаны речь, облако, модель) - путь текстовой модели. LIVE - живой файл сервера (65 ключей). Отклонения: на HostRig
fast_text=off (без поддельной модели он ходит в сеть, connect_tcp); ухо хоста в облаке не стартует (ear state=failed), ухо проверяет Scene; ack_match и on_mismatch хост не применяет
(CALL_SETTINGS: ru_aligned, silent), 2.13 их не называет. Живые настройки дошли: flags шапки call_open = отпечаток resolve(LIVE); у Scene модель получила заявки. Снаружи: подсказки,
decision журнала <home>/logs/echo_calls, заявки модели. Подделки отвечают ПО СОДЕРЖАНИЮ (облако - на обрывок одним, на целую реплику другим; модель - только на целый вопрос). Зелёное: обрывок в окне склеен (joined_question, pieces=2), звучит ответ на целую реплику; хвост позже 3,2 с - новая реплика. Контроль: неразрезанная реплика получает
подсказку; то же разрезание без ответа облака склеено при той же паузе. xfail: окно короче 3,2 с, когда облако ответило на обрывок; то же на пути текстовой модели; голова
«Перечисли» не склеивается совсем. Первая реплика звонка без подсказки - дефект 2.01. Не покрыто: настоящие паузы облака и уха."""
import hashlib
import json
import logging
from pathlib import Path

import pytest
import helpers_s6_fault as F
from echo_sync.settings import resolve
from helpers_g28 import Scene
from helpers_spoken_diagnostics import run_host

LIVE = {
    'preset': 'meaning', 'abbreviations': {}, 'local_ear': 'act',
    'ear_early_ms': 0, 'fast_text': 'on', 'text_transport': 'http', 
    'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on',     'instant': 'on', 
    
    
    'brain_short': 'off', 'pcm_cache_mb': 800, 
    'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 
    'v5_answer_gate': 'shadow', 'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0,
    'max_auto_repeats': 3, 
    
}
HOST = {**LIVE, 'fast_text': 'off'}
# (вопрос, первая подсказка, голова реплики, хвост, ответ облака на голову, ответ облака на целую реплику)
SAIL = ('Сколько ног у паука', 'Восемь.', 'Опиши', 'парусник', 'Парусник движется силой ветра, которая давит на паруса.', 'Он имеет мачту, корпус и руль, и ходит по ветру.')
JADE = ('Какого цвета бывает яшма', 'Чаще красная и зелёная.', 'Назови', 'столицу Перу', 'Столица Перу — Лима, город на берегу океана.', 'Лима — крупнейший город страны, основан давно.')
RIVER = ('Сколько стоит проезд', 'Пятьдесят рублей.', 'Перечисли', 'крупные реки Сибири', 'Обь, Енисей и Лена — крупнейшие реки Сибири.', 'Обь течёт на запад, а Енисей на север, к морю.')
LAKE = [('Сколько дней длится', 'беременность у слонихи', 'Около двадцати двух месяцев.'), ('Какая глубина', 'у озера Байкал', 'Около полутора километров.')]

@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')

def journal(home):
    [path] = [p for p in (Path(home) / 'logs' / 'echo_calls').glob('*.jsonl') if 'v5tap' not in p.name]
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]

def flags_of(settings):
    return hashlib.sha256(json.dumps(resolve(settings), sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:12]

def talk(tmp_path, monkeypatch, v, after=None, answered=True):
    """HostRig: вопрос и его подсказка; затем реплика целиком (after=None) или голова + хвост, начатый через ``after`` с после финала головы.
    ``answered``: облако успело ответить на голову. -> (решения журнала, озвученное)."""
    out, (question, first, head, tail, to_head, to_whole) = {}, v

    async def body(host):
        (host.home / 'materials').mkdir(parents=True, exist_ok=True)
        (host.home / 'materials' / 'echo_settings.json').write_text(json.dumps(HOST), encoding='utf-8')
        await host.handshake()
        await host.ask(question, tid='u1')
        await host.answer(' ' + first, tid='a1')
        await host.advance(2.0)
        if after is None:
            await host.ask(head + ' ' + tail, tid='u2')
        else:
            host.cloud(F.created('u2', 'user', head))
            host.cloud(F.done('u2', 'user', ' ' + head))
            await host.advance(0.3)
            if answered:
                host.cloud(F.created('a2', 'assistant', to_head[:30]))
                host.cloud(F.done('a2', 'assistant', to_head))
            await host.advance(after - 0.3)
            host.cloud(F.created('u3', 'user', tail.split()[0]))
            await host.advance(0.8)
            host.cloud(F.done('u3', 'user', ' ' + tail))
            await host.advance(0.3)
        host.cloud(F.created('a3', 'assistant', to_whole[:15]))
        host.cloud(F.done('a3', 'assistant', to_whole))
        await host.advance(1.5)
        out['rows'], out['spoken'] = journal(host.home), host.spoken()
    run_host(tmp_path, monkeypatch, body, handshake=False)
    rows = out['rows']
    assert rows[0]['ev'] == 'call_open' and rows[0]['flags'] == flags_of(dict(LIVE, fast_text='off')) != flags_of({}), rows[0]   # живые настройки дошли до звонка
    return [r for r in rows if r['ev'] == 'decision'], out['spoken']

def joined(decisions):
    return [r['pieces'] for r in decisions if r['reason'] == 'joined_question']

def heard_the_whole(spoken, v):
    """Человек услышал свою прежнюю подсказку и затем начало ответа на ЦЕЛУЮ реплику (не на обрывок, не прежнюю порцию снова)."""
    return len(spoken) >= 2 and set(spoken[:-1]) == {v[1]} and v[5].startswith(spoken[-1]) and not v[4].startswith(spoken[-1])      # the silence timer may say the first cue again before the answer to the whole

@pytest.mark.parametrize('v', [SAIL, RIVER])
def test_control_the_whole_utterance_is_cued_and_not_joined(tmp_path, monkeypatch, v):
    """Контроль: та же реплика без разреза - подсказка на целую реплику звучит, склейки нет."""
    decisions, spoken = talk(tmp_path, monkeypatch, v)
    assert heard_the_whole(spoken, v) and not joined(decisions), (spoken, [(r['kind'], r['reason']) for r in decisions])

NOT_HEAD = pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.13: работает; в единой ветке голова «Перечисли» не считается обрывком: хвост через 1,0 с не склеен '
                             '(unrelated_speech, затем cloud_admitted/new_question), при тех же словах и паузе другие головы склеены')

@pytest.mark.parametrize('v, after, answered', [(SAIL, 0.8, True), (SAIL, 2.0, False), (JADE, 3.0, False), pytest.param(RIVER, 1.0, False, marks=NOT_HEAD)])
def test_a_cut_utterance_inside_the_window_is_one_question(tmp_path, monkeypatch, v, after, answered):
    """Хвост начат в пределах окна: одно решение joined_question из 2 кусков, звучит ответ на целую реплику, как у неразрезанной."""
    decisions, spoken = talk(tmp_path, monkeypatch, v, after, answered)
    assert joined(decisions) == [2] and heard_the_whole(spoken, v), (spoken, [(r['kind'], r['reason']) for r in decisions])

@pytest.mark.parametrize('v', [SAIL])
def test_a_tail_after_three_point_two_seconds_is_a_new_utterance(tmp_path, monkeypatch, v):
    """Граница константы: через 3,6 с хвост - отдельная реплика (склейки нет), а через 3,0 с (см. выше) - склеен."""
    decisions, spoken = talk(tmp_path, monkeypatch, v, 3.6, False)
    assert not joined(decisions) and ('retire', 'new_question') in [(r['kind'], r['reason']) for r in decisions], spoken

@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.13: работает; в единой ветке окно короче обещанных 3,2 с: когда облако уже ответило на обрывок, '
                   'хвост через 2,0 с не склеен (cloud_admitted, затем unrelated_speech); при 0,8 с и без ответа облака склеен')
@pytest.mark.parametrize('v', [SAIL])
def test_the_window_is_three_point_two_seconds_after_the_cloud_answered_the_head(tmp_path, monkeypatch, v):
    decisions, spoken = talk(tmp_path, monkeypatch, v, 2.0, True)
    assert joined(decisions) == [2] and heard_the_whole(spoken, v), (spoken, [(r['kind'], r['reason']) for r in decisions])

def lake(head, tail, gap, whole=False):
    """Scene с живыми настройками: речь (0,33 с на слово), ухо и финал облака; модель отвечает только на вопрос целиком. -> (подсказки, заявки модели)."""
    answer = next(a for h, t, a in LAKE if h == head)
    s = Scene({(head + ' ' + tail).lower(): answer}, flags=LIVE)
    try:
        spoke = s.say(1.0, head + ' ' + tail if whole else head)
        if not whole:
            s.say(spoke.offset + gap, tail)
        s.until(14)
        return s.cues()[:1], [(j['heard'], j['answer']) for j in s.out.jobs]
    finally:
        s.close()

@pytest.mark.parametrize('head, tail, answer', LAKE[:1])
def test_text_path_control_the_whole_question_is_answered(head, tail, answer):
    cues, jobs = lake(head, tail, 0, whole=True)
    assert cues == [answer] and jobs, (cues, jobs)                       # jobs: fast_text=on дошёл, модель спрашивали

@pytest.mark.parametrize('head, tail, answer', LAKE)
def test_text_path_a_cut_question_is_asked_of_the_model_whole(head, tail, answer):
    """Пауза 1,0 с: модель получает вопрос целиком (на голову одну отвечала «—») и подсказка звучит; без окна склейки так не бывает."""
    cues, jobs = lake(head, tail, 1.0)
    assert cues == [answer] and jobs[0][1] == '—' and any(a == answer for _, a in jobs), (cues, jobs)

@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.13: работает; в единой ветке на пути текстовой модели хвост, начатый через 1,2 с после финала головы '
                   '(пауза речи 2,0 с), не склеен: модель получает два обрывка, подсказки нет (при паузе 1,0 с склеен)')
@pytest.mark.parametrize('head, tail, answer', LAKE[1:])
def test_text_path_the_window_is_three_point_two_seconds(head, tail, answer):
    cues, jobs = lake(head, tail, 2.0)
    assert cues == [answer], (cues, jobs)

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

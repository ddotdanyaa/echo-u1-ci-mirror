"""Функция 2.04 «Новый вопрос против попытки повтора и против поправки». Реестр: «РАБОТАЕТ НА СЕРВЕРЕ». Ключи: repeat_cover=0.8, attempt_extra_words=3 (умолч., в файле сервера их нет), on_mismatch=replay_if_attempt.
Стенд: tools/replay/quantity.Q.rig_of поверх test_h3_tempo.Rig (настоящие ControlledMedia, ухо, FastText, виртуальное время; подделаны речь, облако, поток модели). LIVE = весь файл сервера (65 ключей)
+ два умолчания функции, без отклонений; идёт стенду файлом через ECHO_REPLAY_PROFILE, тест проверяет, что Rig получил resolve(LIVE). Банк - Q.BANK (данные стенда), строки мои. Модель отвечает по числу в заявке.
Сцена: ответ про смету 118 озвучен порцией и ждёт повтора; человек говорит. Снаружи: decision/judge журнала echo-sync, подсказки, заявки модели. Зелёное: свой номер вопросом - новый вопрос, модель получает его;
«номер словами» со строкой банка - ответ банка, без строки - неверный повтор; промах в номер - неверный повтор; поправка идёт модели, звучит ответ про новое число; on_mismatch в звонке silent (не живое
replay_if_attempt). Контроль: повтор порции принят. xfail: вопрос в первые 6 с, если первый вопрос слышало только ухо. HostRig (controlled_host.serve) идёт с fast_text=off, local_ear=off: без модели он ходит в сеть.
Не покрыто: v5_gate.py:156 (U90, v5_answer_gate=shadow), repeat_cover для вопроса."""
import json
import logging
import re

import pytest

import helpers_s6_fault as F
from echo_sync.settings import resolve
from helpers_spoken_diagnostics import run_host
from test_ux_call_trace_host import settings_file
from tools.replay import quantity as Q, repeat_scenes as R

LIVE = {
    'preset': 'meaning', 'portion_sense': 'off', 'abbreviations': {}, 'ack_match': 'stem', 'on_mismatch': 'replay_if_attempt', 'local_ear': 'act', 'ear_early_ms': 0, 'ear_vocab': 'off', 'fast_text': 'on',
    'text_transport': 'http', 'prompt_tempo': 'ear', 'ear_release': 'on', 'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on', 
    'material_pick': 'on', 'warm_start': 'on', 'quick_math': 'on', 'instant': 'on', 'repeat_rule': 'on', 'dictation': 'off', 'dictation_cycle': 'on', 'stumble_place': 'on', 'resume_word': 'on', 'instant_rank': 'on',
    'instant_rank2': 'on', 'two_witnesses': 'on', 'fast_private': 'off', 'stop_in_flight': 'on', 'gate_text': 'off', 
    'bank_rejoin': 'on', 'brain_short': 'off', 'ear_command_early': 'off', 'pcm_cache_mb': 800, 'pcm_record': 'on', 'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 'facts_journal': 'on',
    'v5_answer_gate': 'shadow', 'adopt_missing_words': 1, 'spare_helper': 'on', 'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0, 'open_overlap': 'on', 
    'inline_repeat': False, 'max_auto_repeats': 3, 'record_mode': 'earned', 'local_onset': 'on', 'local_fallback': 'on', 'conversation_ledger': 'memory', 'recall_words': 'on', 'input_state': 'on',
    'lang_turn': 'shadow', 'repeat_cover': 0.8, 'attempt_extra_words': 3}
# вариант: (вопрос в банке и порции, ответ, число словами, промах в номер, поправка, новый вопрос, строка банка нового номера); числа и слова придуманы, не из живых звонков
V1 = ('Что такое смета 118 строительного отдела?', 'Смета 118 строительного отдела — про закупку бетона. Она утверждена весной.', 'смета двести семьдесят четыре строительного отдела',
      'смета 119 строительного отдела', 'Нет, не 118, а 274.', 'Что такое смета 274 строительного отдела?', 'Смета 274 строительного отдела — про аренду кранов. Она новая.')
V2 = ('Что такое накладная 56 склада?', 'Накладная 56 склада — про приём муки. Её подписывает кладовщик.', 'накладная восемьдесят три склада',
      'накладная 57 склада', 'Нет, не 56, а 83.', 'Что такое накладная 83 склада?', 'Накладная 83 склада — про отгрузку сахара. Она свежая.')

def row(q, a):
    return (q, a, [re.sub(r'^что такое ', '', q.lower().rstrip('?'))])

def model(rig, seen):
    """Подделка модели: отвечает по последнему числу после «Сейчас прозвучало», без числа - «—»."""
    for n in range(seen, len(rig.fake.runs)):
        nums = re.findall(r'\d+', rig.fake.runs[n].question.rsplit('Сейчас прозвучало:', 1)[-1])
        rig.job_says(n, ('Модель: номер %s — про штрафы. Он старый.' % nums[-1]) if nums else '—')
        rig.job_ends(n)
    return len(rig.fake.runs)

@pytest.fixture
def play(tmp_path, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    (tmp_path / 'live.json').write_text(json.dumps(LIVE), encoding='utf-8')
    monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(tmp_path / 'live.json'))
    made = []

    def run(rows, said, *, ear_first=False, pre=3.0, wait=10.0):
        monkeypatch.setattr(Q, 'BANK', rows)
        rig = Q.rig_of()
        made.append(rig)
        want = resolve(LIVE)
        assert all(rig.settings[k] == want[k] for k in LIVE) and rig.settings['repeat_cover'] == 0.8, 'живой файл дошёл стенду'
        (Q.ear_only if ear_first else R.utter)(rig, rows[0][0])
        rig.pump(pre)
        n, m, seen = len(caplog.records), len(rig.cues()), 0
        R.utter(rig, said)
        for _ in range(int(wait * 10)):
            rig.pump(0.1)
            seen = model(rig, seen)
        msgs = [r.message for r in caplog.records[n:]]
        return {'cues': [c.text for c in rig.cues()[m:]], 'jobs': [r.question for r in rig.fake.runs],
                'dec': [g.groups() for g in (re.search(r'decision kind=(\w+) reason=(\w+)', s) for s in msgs) if g],
                'judge': [re.search(r'judge tid=\S+ kind=(\w+) reason=(\w+)', s).groups() for s in msgs if ' judge tid=' in s]}
    yield run
    for rig in made:
        rig.close()
        rig._mp.undo()

@pytest.mark.parametrize('v', [V1, V2])
def test_1_a_question_with_its_own_number_is_new_and_asked_of_the_model_alone(play, v):
    out = play([row(*v[:2])], v[5])
    assert ('retire', 'new_question') in out['dec'] and ('replay', 'wrong_repeat') not in out['dec'], out
    assert [j.rsplit('Сейчас прозвучало: ', 1)[-1] for j in out['jobs']] == [v[5]], out        # модель спросили ровно новым вопросом
    assert out['cues'][0].startswith('Модель: номер ' + re.findall(r'\d+', v[5])[0]) and not any(re.findall(r'\d+', v[0])[0] in c for c in out['cues']), out

@pytest.mark.parametrize('v', [V1, V2])
def test_2_control_a_repeat_of_the_portion_is_not_a_new_question(play, v):
    out = play([row(*v[:2])], v[1].split(' — ')[0] + ' —')      # повтор первой порции (до тире): принят, дальше следующая порция
    assert ('ack', 'ack_ru_canonical') in out['dec'] and not out['jobs'] and ('retire', 'new_question') not in out['dec'], out
    assert out['cues'][:1] == [v[1].split('. ')[0].split(' — ', 1)[1] + '.'], out

@pytest.mark.parametrize('v', [V1, V2])
def test_3_a_number_in_words_with_a_bank_row_is_a_new_question_without_a_row_a_wrong_repeat(play, v):
    with_row = play([row(*v[:2]), row(v[5], v[6])], v[2])
    assert ('question', 'bank_question') in with_row['judge'] and ('retire', 'new_question') in with_row['dec'] and not with_row['jobs'], with_row
    assert with_row['cues'] == [v[6].split(' — ')[0] + ' —'], with_row                  # ответ банка про новый номер, модель не спрашивали
    no_row = play([row(*v[:2])], v[2])
    assert ('replay', 'wrong_repeat') in no_row['dec'] and ('retire', 'new_question') not in no_row['dec'] and not no_row['jobs'] and no_row['cues'] == [], no_row

@pytest.mark.parametrize('v', [V1, V2])
def test_4_a_slip_in_the_number_is_a_wrong_repeat_even_with_a_row_in_the_bank(play, v):
    out = play([row(*v[:2]), row(v[5], v[6])], v[3])
    assert ('replay', 'wrong_repeat') in out['dec'] and ('retire', 'new_question') not in out['dec'] and not out['jobs'], out

@pytest.mark.parametrize('v', [V1, V2])
def test_5_a_correction_goes_to_the_model_with_the_old_question_and_the_answer_for_the_new_number_sounds(play, v):
    out = play([row(*v[:2])], v[4])
    old, new = re.findall(r'\d+', v[4])
    assert [j.rsplit('Сейчас прозвучало: ', 1)[-1].rstrip('.') for j in out['jobs']] == [v[4].rstrip('.')] and v[1] in out['jobs'][0], out        # к модели ушла поправка при старом вопросе и ответе
    assert out['cues'][0].startswith('Модель: номер ' + new) and not any(old in c for c in out['cues']), out

def test_6_on_mismatch_in_the_call_is_silent_not_the_live_replay_if_attempt(play):
    out = play([row(*V1[:2])], 'смета 274')      # обрывок с общим словом: при replay_if_attempt это попытка (replay), при silent - тишина
    assert ('silent', 'mismatch_policy_silent') in out['dec'] and not any(k == 'replay' for k, _ in out['dec']) and not out['jobs'], out

@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.04: работает; в единой ветке вопрос со своим номером в первые 6 с после порции, когда первый вопрос слышало только ухо (без финала облака), '
                   'не получает ответа 24 с (ear_question_hold_no_replay); с финалом облака и через 7 с ответ есть (срок ожидания порции, 3.05)')
@pytest.mark.parametrize('v', [V1, V2])
def test_7_target_a_new_question_soon_after_an_ear_only_question_is_answered(play, v):
    rows = [row(*v[:2]), row(v[5], v[6])]
    assert play(rows, v[5], ear_first=True, pre=7.0)['cues'][:1] == [v[6].split(' — ')[0] + ' —'] and play(rows, v[5], pre=3.0)['cues'], 'контроль: через 7 с или с финалом облака ответ есть'
    assert play(rows, v[5], ear_first=True, pre=3.0, wait=24.0)['cues'], 'через 3 с после порции, слышало только ухо: ответа нет'

def host_scene(tmp_path, monkeypatch, said, caplog):
    """Настоящий controlled_host.serve (fast_text=off, local_ear=off - иначе сеть/нет модели): облако отвечает на оба вопроса само. -> (judge журнала звонка, озвучено)."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    out = {}

    async def body(host):
        settings_file(host.home, **{**LIVE, 'fast_text': 'off', 'local_ear': 'off'})
        await host.handshake()
        await host.advance(0.5)
        await host.ask(V1[0], tid='u1')
        await host.answer(V1[1] + ' Её меняли.', tid='a1')
        await host.advance(1.5)
        await host.ask(said, tid='u2')
        await host.answer(V1[6] + ' Её не меняли.', tid='a2')
        await host.advance(3)
        (log,) = [f for f in (host.home / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name]
        rows = [json.loads(x) for x in log.read_text(encoding='utf-8').splitlines()]
        out['judge'] = [(r['kind'], r['reason']) for r in rows if r['ev'] == 'judge' and r['tid'] == 'u2']
        out['dec'] = [(r['kind'], r['reason']) for r in rows if r['ev'] == 'decision']
        out['spoken'] = host.spoken()
    run_host(tmp_path, monkeypatch, body, handshake=False)
    return out

def test_8_host_the_judge_calls_a_correction_a_correction_and_a_numbered_question_a_question(tmp_path, monkeypatch, caplog):
    fixed = host_scene(tmp_path, monkeypatch, V1[4], caplog)
    asked = host_scene(tmp_path / 'b', monkeypatch, V1[5], caplog)
    assert fixed['judge'] == [('correction', 'corrected_number')] and asked['judge'] == [('question', 'question_mark')], (fixed, asked)
    assert all(('retire', 'new_question') in o['dec'] and o['spoken'][-1].endswith('про аренду кранов.') for o in (fixed, asked)), (fixed, asked)

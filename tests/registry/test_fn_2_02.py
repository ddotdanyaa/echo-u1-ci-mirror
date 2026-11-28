"""Функция 2.02 «Единый судья реплики». Реестр: «В ТЕНИ — judge_guard и followup_one выключены».
Стенды: (1) настоящий controlled_host.serve() (helpers_s6_fault.HostRig, виртуальное время): журнал звонка и лог echo-sync; (2) test_h3_tempo.Rig (настоящий контроллер, ухо,
текстовый канал с поддельной моделью, отвечающей по числу в запросе; профиль через ECHO_REPLAY_PROFILE). LIVE = весь живой файл настроек сервера (65 ключей); пяти ключей
функции в нём нет: умолчания кода (shadow, shadow, shadow, off, off). Отклонения от LIVE: HostRig - fast_text=off, local_ear=off (без поддельной модели текстовый канал идёт
в сеть, ухо без моделей); ключи функции в параметрах тестов. Зелёные: тень judge_once и addressed_gate; judge_guard off/shadow/on при сменённом числе. xfail(strict): addressed_gate,
followup_one, judge_guard=on - каждый с контролем «тот же сценарий при включённом ключе зелёный». judge_order: сценария с двумя говорящими правилами нет (см. JSON)."""
import json
import logging
import re

import pytest

import helpers_s6_fault as F
import helpers_s6_state as S
from test_h3_tempo import Rig

LIVE = dict(preset='meaning', portion_sense='off', abbreviations={}, local_ear='act', ear_early_ms=0,
    ear_vocab='off', fast_text='on', text_transport='http', ear_release='on', prepare_wide='off', ear_job='on',
    turn_mark='off', cloud_form='on', ear_lookup='on', material_pick='on', warm_start='on', instant='on', 
    stumble_place='on', stop_in_flight='on', gate_text='off', bank_rejoin='on',
    brain_short='off', pcm_cache_mb=800, pcm_record='on', pcm_record_calls=200, pcm_record_mb=8192, pcm_record_call_mb=1200,
    facts_journal='on', v5_answer_gate='shadow', adopt_missing_words=1, spare_helper='on', near_voice='off', voice_gain=4.0, voice_presence=3.0,
    open_overlap='on', inline_repeat=False, max_auto_repeats=3, local_fallback='on',
    conversation_ledger='memory', recall_words='on', lang_turn='shadow')

XF = lambda why: pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.02: ' + why)  # noqa: E731

CASES = [('Как устроен сифон?', 'Почему вода течёт сама: изогнутая трубка наполнена жидкостью, и вес столба по длинному колену тянет воду через высшую точку изгиба вниз.'),
         ('Зачем самолёту закрылки?', 'Затем чтобы на малой скорости подъёмная сила не падала: выпущенные закрылки увеличивают кривизну крыла и площадь, поэтому посадочная скорость ниже.'),
         ('Что такое маятник?', 'Как качели: груз на нити отклоняется от нижней точки, сила тяжести возвращает его назад, и колебания повторяются с постоянным периодом.')]
READ = (CASES[0], CASES[2])        # ответ начинается вопросительным словом; CASES[1] - нет (контроль)

def play(tmp_path, monkeypatch, caplog, case, then, **over):
    """Вопрос, ответ порциями, ``then(host, ответ)``; (строки журнала звонка, лог echo-sync). Живые значения дошли: call_open несёт dictation_cycle=on, record_mode=earned (умолчания off)."""
    caplog.set_level(logging.INFO, logger='echo-sync')

    async def main():
        F.patch_clock(monkeypatch)
        async with F.HostRig(tmp_path, monkeypatch) as host:
            (host.home / 'materials').mkdir(parents=True, exist_ok=True); (host.home / 'materials' / 'echo_settings.json').write_text(json.dumps(dict(LIVE, fast_text='off', local_ear='off', **over)), encoding='utf-8')
            await host.handshake()
            await host.ask(case[0], 'u1'); await host.answer(case[1], 'a1'); await host.advance(1)  # noqa: E702
            await then(host, case[1])
            (path,) = [p for p in (host.home / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap.' not in p.name]      # рядом журнал v5_tap (в LIVE он shadow)
            return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    rows = F.run(main)
    assert rows[0]['ev'] == 'call_open'
    return rows, caplog.text

async def say(host, tid, text):
    host.cloud(F.created(tid, 'user', 'x')); host.cloud(F.done(tid, 'user', text)); await host.advance(1)  # noqa: E702

async def read_aloud(host, answer):
    """Человек повторяет каждую порцию вслух, пока система даёт следующую, потом зачитывает весь ответ целиком."""
    done = 0
    while len(host.spoken()) > done:
        done = len(host.spoken())
        await say(host, 'r%d' % done, host.spoken()[-1])
    assert done >= 2
    await say(host, 'u9', answer[:-1])

counter_move = lambda host, answer: say(host, 'u9', 'если наоборот')  # noqa: E731

def judged(rows, tid):
    return [r for r in rows if r['ev'] == 'judge' and r['tid'] == tid]

def after_u9(rows):
    return [(r['kind'], r['reason']) for r in rows[[i for i, r in enumerate(rows) if r.get('id') == 'u9'][0]:] if r['ev'] == 'decision']

def test_judge_once_one_record_per_utterance(tmp_path, monkeypatch, caplog):
    rows, log = play(tmp_path, monkeypatch, caplog, CASES[2], read_aloud)
    finals = [r['id'] for r in rows if r['ev'] == 'user_final']
    assert finals[0] == 'u1' and finals[-1] == 'u9' and len(finals) >= 4
    for tid in finals:                    # ровно одна запись судьи и ровно одна строка решения на каждую реплику
        (one,) = judged(rows, tid)
        assert one['analyses'] == 1
        assert re.findall(r'echo-sync resolution tid=%s final_rev=1 resolution=\w+ cause=cloud_final outcome=new .*' % tid, log)
    assert [judged(rows, t)[0]['kind'] for t in ('u1', 'r1')] == ['question', 'ack']

def test_control_an_answer_read_aloud_with_no_question_word_is_silent_in_any_mode(tmp_path, monkeypatch, caplog):
    rows, log = play(tmp_path, monkeypatch, caplog, CASES[1], read_aloud)
    assert [(r['kind'], r['reason']) for r in judged(rows, 'u9')] == [('silent', 'not_a_question')] and 'addressed_gate' not in log

@pytest.mark.parametrize('case', READ)
def test_addressed_gate_listens_to_read_aloud_answer(tmp_path, monkeypatch, caplog, case):
    rows, log = play(tmp_path, monkeypatch, caplog, case, read_aloud)
    assert [(r['kind'], r['reason'], r['rule']) for r in judged(rows, 'u9')] == [('silent', 'not_addressed', 'not_addressed')]
    assert ('retire', 'new_question') not in after_u9(rows)

@pytest.mark.parametrize('case', READ)
def test_followup_one_short_followup_while_portion_waits_is_a_question(tmp_path, monkeypatch, caplog, case):
    rows, log = play(tmp_path, monkeypatch, caplog, case, counter_move)
    assert [(r['kind'], r['reason']) for r in judged(rows, 'u9')] == [('question', 'short_contextual_followup')]

# --- judge_guard: ухо слышит одно число, открытый ход облака другое (или без числа), финала нет ---------------------------------------------
TPL = ['сколько стоит билет на поезд до омска в вагоне {} на завтра', 'какая высота у башни номер {} в порту сегодня', 'через сколько минут вернётся автобус номер {} на конечную остановку']
NUM = [(17, 18), (23, 32), (41, 14)]

def guard_scene(tmp_path, monkeypatch, caplog, n, cloud):
    """Ухо слышит TPL[n] с числом NUM[n][0], облако за речью говорит ``cloud`` (финала нет); модель отвечает по числу в запросе. -> (что прозвучало, числа в запросах модели, лог)."""
    caplog.set_level(logging.INFO, logger='echo-sync')
    (tmp_path / 'profile.json').write_text(json.dumps(dict(LIVE)), encoding='utf-8')
    monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(tmp_path / 'profile.json'))
    rig, asked = Rig(monkeypatch), []
    try:
        uid, words = rig.onset(), cloud.split()
        rig.w.feed(S.turn_created('u1', 'user', words[0]))
        for k, word in enumerate(words[1:]):
            rig.pump(0.3); rig.w.feed(S.turn_delta('u1', ' ' + word, k), settle=False)  # noqa: E702
        rig.pump(0.3); rig.offset(); rig.pump(0.15)  # noqa: E702
        rig.worker.heard(uid, TPL[n].format(NUM[n][0]))
        for _ in range(60):
            rig.pump(0.1)
            for run in rig.fake.runs[len(asked):]:
                asked.append(re.findall(r'\d+', run.request['input'][-1]['content'][0]['text'].rsplit('Сейчас прозвучало: ', 1)[-1]))
                run.say('Ответ для номера %s: двенадцать рублей.' % (asked[-1] or ['?'])[0]); run.finish()  # noqa: E702
        return rig.said(), asked, caplog.text
    finally:
        rig.close()

def answered_on_the_ears_number(n, scene):
    one = 'Ответ для номера %d: двенадцать рублей.' % NUM[n][0]
    return bool(scene[1]) and scene[1][0] == [str(NUM[n][0])] and scene[0] in ([one], [one, one])

@pytest.mark.parametrize('n', [0, 1, 2])
def test_guard_a_changed_number_in_the_open_cloud_turn_keeps_the_ear_quiet(tmp_path, monkeypatch, caplog, n):
    said, asked, log = guard_scene(tmp_path, monkeypatch, caplog, n, TPL[n].format(NUM[n][1]))
    assert said == [] and 'reason=no_final_the_ear_is_contradicted' in log                      # решение прежнее: ухо отменено, ничего не звучит
    assert 'late_correction verdict=differs' in log

@pytest.mark.parametrize('n', [0, 1])
def test_control_the_cloud_that_agrees_lets_the_ear_answer_on_its_number(tmp_path, monkeypatch, caplog, n):
    assert answered_on_the_ears_number(n, guard_scene(tmp_path, monkeypatch, caplog, n, TPL[n].format(NUM[n][0])))

@pytest.mark.parametrize('n', [0, 1])
def test_guard_an_open_cloud_turn_that_only_lacks_words_does_not_silence_the_ear(tmp_path, monkeypatch, caplog, n):
    cloud = TPL[n].format(NUM[n][0]).replace(' %d' % NUM[n][0], '')
    assert answered_on_the_ears_number(n, guard_scene(tmp_path, monkeypatch, caplog, n, cloud))

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

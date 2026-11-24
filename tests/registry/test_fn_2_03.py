"""Функция 2.03 «Вопрос внутри длинной речи, в хвосте, после склейки; пересказ против вопроса».
Реестр: СЛОМАНО - исправление ТОЛЬКО В ВЕТКЕ v6-x1-chaos 9ce67d0. В единой ветке исправление слито (b8f6af2): замок SAID_BACK_OWN = 0, расхождение с реестром.

Стенд: настоящий controlled_host.serve() целиком (helpers_s6_fault.HostRig: поддельные телефон, облачный помощник и SAPI, виртуальное время).
Настройки: LIVE (живые значения сервера, 65 ключей) пишутся настоящим файлом <home>/materials/echo_settings.json; тест их не правит.
Снаружи видно: решения в журнале звонка <home>/logs/echo_calls (запись decision) и озвученное телефону (host.spoken()).
Сцена: на вопрос озвучена порция ответа и ждёт повтора. Дальше человек говорит:
 1 свой вопрос, который кончается словами ждущей порции, но добавляет свой смысл («что говорит учебник про мосты из дерева и стали») - вопрос, retire/new_question, ответ звучит;
 2 порцию своими словами («так что соответственно из дерева и стали») - пересказ, не вопрос: ответ облака не звучит, нового вопроса нет;
 3 длинное вступление и вопрос в хвосте - вопрос по слову, ответ звучит;
 4 реплика о том, что подходит его очередь говорить, не вопрос (judge rule doubt, U47).
Не покрыто: склейка на слух (ухо, wide_breath) - нужен стенд уха tools/replay; живая речь и звук телефона."""
import logging
import re

import pytest

from helpers_spoken_diagnostics import run_host
from test_ux_call_trace_host import read_trace, settings_file

LIVE = {
    'preset': 'meaning', 'portion_sense': 'off', 'abbreviations': {}, 'local_ear': 'act',
    'ear_early_ms': 0, 'ear_vocab': 'off', 'fast_text': 'on', 'text_transport': 'http', 
    'ear_release': 'on', 'prepare_wide': 'off', 'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on',     'material_pick': 'on', 'warm_start': 'on', 'instant': 'on', 
    'stumble_place': 'on', 
    'fast_private': 'off', 'stop_in_flight': 'on', 'gate_text': 'off', 
    'bank_rejoin': 'on', 'brain_short': 'off', 'pcm_cache_mb': 800, 'pcm_record': 'on',
    'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 'facts_journal': 'on', 
    'v5_answer_gate': 'shadow', 'adopt_missing_words': 1, 'spare_helper': 'on', 'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0,
    'open_overlap': 'on', 'inline_repeat': False, 'max_auto_repeats': 3, 
    'local_fallback': 'on', 'conversation_ledger': 'memory', 'recall_words': 'on', 'lang_turn': 'shadow',
}
PORTION = 'Мосты раньше строили из камня, дерева и стали.'
FIRST = PORTION + ' Они служили по сто лет.'
SECOND = 'Утки живут около десяти лет.'


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')


def say(tmp_path, monkeypatch, caplog, said, *, waiting=True, answer=SECOND):
    """A question and the first portion of its answer (waiting for a repeat); then ``said``, and the cloud answers it with ``answer`` (or not)."""
    out = {}

    async def body(host):
        settings_file(host.home, **LIVE)
        if waiting:
            await host.ask('Из чего строили мосты', tid='u1')
            await host.answer(FIRST, tid='a1')
            await host.advance(1)
            assert host.spoken() == [PORTION], host.spoken()
        await host.ask(said, tid='u2')
        if answer:
            await host.answer(answer, tid='a2')
        await host.advance(1)
        out['decisions'] = [(r['kind'], r['reason']) for r in read_trace(host.home) if r['ev'] == 'decision']
        out['spoken'], out['errors'] = host.spoken(), host.errors()
        out['judged'] = re.findall(r'judge tid=u2 kind=(\w+) reason=(\w+)', caplog.text)      # the controller's own line: kind and reason of the utterance
    run_host(tmp_path, monkeypatch, body)
    return out


def test_1_a_question_that_ends_like_the_waiting_portion_but_adds_its_own_meaning_is_asked_and_answered(tmp_path, monkeypatch, caplog):
    out = say(tmp_path, monkeypatch, caplog, 'что говорит учебник про мосты из дерева и стали')
    assert out['judged'] == [('question', 'question_word')] and out['decisions'][1:] == [('retire', 'new_question'), ('question', 'question_word')], out
    assert out['spoken'] == [PORTION, SECOND] and not out['errors'], out


def test_2_the_portion_said_in_ones_own_way_is_no_question_and_the_cloud_answer_is_not_cued(tmp_path, monkeypatch, caplog):
    out = say(tmp_path, monkeypatch, caplog, 'так что соответственно из дерева и стали')
    assert out['judged'] and all(kind == 'silent' for kind, _ in out['judged']), out
    assert out['decisions'].count(('question', 'question_word')) == 1 and ('retire', 'new_question') not in out['decisions'], out
    assert SECOND not in out['spoken'] and not out['errors'], out


@pytest.mark.parametrize('waiting', [True, False])
def test_3_a_question_in_the_tail_of_a_long_speech_is_asked_and_answered(tmp_path, monkeypatch, caplog, waiting):
    out = say(tmp_path, monkeypatch, caplog, 'Вчера мы долго гуляли по парку и видели много уток. Сколько лет живёт утка', waiting=waiting)
    assert out['decisions'][-1] == ('question', 'question_word'), out
    assert out['spoken'][-1] == SECOND and not out['errors'], out


def test_4_a_remark_that_my_turn_to_speak_comes_is_no_question(tmp_path, monkeypatch, caplog):
    out = say(tmp_path, monkeypatch, caplog, 'Что ж, теперь моя очередь говорить', waiting=False, answer=None)
    assert out['judged'] and not any(kind == 'question' for kind, _ in out['judged']), out

"""Функция 2.05 «Зачёт повтора: человек повторил порцию». Реестр: РАБОТАЕТ НА СЕРВЕРЕ; `prompt_pace` и `ack_garble` ВЫКЛЮЧЕНЫ.
Стенды: (1) helpers_night_memory.Call - цепочка настоящего контроллера, как её собирает controlled_host (настройки через controller_settings), поддельная текстовая модель отвечает по числу в вопросе,
ухо не подключено, повтор приходит финалом облака с ошибками уха; (2) test_h3_tempo.Rig - настоящий контроллер с ухом на виртуальном времени, профиль через ECHO_REPLAY_PROFILE: место запинки и темп.
LIVE - весь файл настроек сервера (65 ключей). Отступления: `ack_garble` и `prompt_pace` в файле нет - умолчания (false, off), включаются только в проверках-выключателях; Call: v6_memory/topic_recap=off
(в файле их нет, стенд по умолчанию ставит on); Rig: input_state=shadow (микрофон Rig - цифровая тишина, при on она глушит подсказку по запинке).
РАСХОЖДЕНИЕ С РЕЕСТРОМ: `ack_match=stem` на звонке не действует: controlled_host.controller_settings оставляет CALL_SETTINGS (on_mismatch=silent). Реплики выдуманы.
Снаружи: опубликованные порции (кадры телефону), решения в логе echo-sync (ack_ru_canonical)."""
import json
import logging
import re

import pytest

import helpers_night_memory as N
from test_h3_tempo import GRID, Rig

LIVE = {'preset': 'meaning', 'abbreviations': {}, 'local_ear': 'act', 'ear_early_ms': 0,
        'fast_text': 'on', 'text_transport': 'http', 'prepare_wide': 'off',
        'ear_job': 'on', 'turn_mark': 'off', 'cloud_form': 'on', 'ear_lookup': 'on', 
        'instant': 'on', 
        
        'brain_short': 'off', 'pcm_cache_mb': 800, 
        'pcm_record_calls': 200, 'pcm_record_mb': 8192, 'pcm_record_call_mb': 1200, 'v5_answer_gate': 'shadow',
        'near_voice': 'off', 'voice_gain': 4.0, 'voice_presence': 3.0, 
        'max_auto_repeats': 3, 
        'lang_turn': 'shadow'}
NUM = {7: ('семь', 'шестьдесят один'), 12: ('двенадцать', 'семьдесят шесть')}
FORMS = {'clean': 'мост номер {n} тянется на {l} метров', 'words': 'мост номер {nw} тянется на {lw} метров', 'ending': 'мост номер {n} тянется на {l} метра', 'filler': 'ну мост мост номер {n} тянется на {l} метров',
         'runs_on': 'мост номер {n} тянется на {l} метров он построен', 'restart': 'мост номер {n} тянется на мост номер {n} тянется на {l} метров'}


def parts(q):
    """Что отвечает поддельная модель: порции зависят от числа в вопросе (по ним видно, ЧТО подсказали)."""
    n = int(re.search(r'\d+', q).group())
    return (['Мост номер %d тянется на %d метров.' % (n, 3 * n + 40), 'Он построен в %d году.' % (1900 + n), 'Через него ходят трамваи.'] if 'мост' in q else
            ['Башню %d очень долго и тщательно измеряли.' % n, 'Высота оказалась %d метров.' % (2 * n + 30), 'Потом вокруг разбили сквер.'])


def ear_said(form, n):
    return FORMS[form].format(n=n, l=3 * n + 40, nw=NUM[n][0], lw=NUM[n][1])


@pytest.fixture
def stand(tmp_path, caplog):
    made = []
    caplog.set_level(logging.INFO, logger='echo-sync')
    def make(topic, n, **over):
        call = N.Call(tmp_path, mind=lambda request: ' '.join(parts(N.asked(request))), **{**LIVE, 'topic_recap': 'off', **over})
        made.append(call)
        call.say('Расскажи про %s %d?' % (topic, n))
        call.pump(2)
        return call
    yield make
    for call in made:
        call.close()


def says(call, text):
    call.say(text)
    call.pump(1.5)
    return call.cues()


def counted(caplog):
    return sum('decision kind=ack reason=ack_ru_canonical' in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize('form, n', [('clean', 7), ('words', 12), ('ending', 12), ('filler', 7), ('runs_on', 12), ('restart', 7)])
def test_a_repeat_with_the_ears_mistakes_is_counted_and_the_next_portion_comes(stand, caplog, form, n):
    call, want = stand('мост', n), parts('мост %d' % n)
    assert call.cues() == want[:1] and counted(caplog) == 0
    assert says(call, ear_said(form, n)) == want[:2] and counted(caplog) == 1


def test_a_wrong_number_or_a_half_is_not_counted_and_the_right_repeat_after_it_is(stand, caplog):
    call, want = stand('мост', 7), parts('мост 7')
    for wrong in ('мост номер 7 тянется на 67 метров', 'мост номер 7 тянется на'):
        assert says(call, wrong) == want[:1] and counted(caplog) == 0, wrong
    assert says(call, ear_said('words', 7)) == want[:2] and counted(caplog) == 1




GARBLED = [(5, 'башню 5 очень долго и тщательно измерали'), (9, 'башню 9 очень долго и тшательно измеряли')]


@pytest.mark.parametrize('n', [5, 9])
def test_control_the_clean_repeat_of_the_same_portion_counts(stand, caplog, n):
    assert says(stand('башню', n), 'башню %d очень долго и тщательно измеряли' % n) == parts('башню %d' % n)[:2] and counted(caplog) == 1


@pytest.mark.parametrize('n, said', [(5, GARBLED[0][1]), (9, GARBLED[1][1])])
def test_a_word_garbled_into_a_non_word_counts_always(stand, caplog, n, said):
    """The key ``ack_garble`` is gone: the classifier's ack heals one word the ear garbled into a non-word (the last word and a word in the middle alike)."""
    assert says(stand('башню', n), said) == parts('башню %d' % n)[:2] and counted(caplog) == 1


@pytest.mark.parametrize('word', ['изменяли', pytest.param('мерили', marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason='U53 (one-input): «изменяли» counts (>= 0.8 of «измеряли»); «мерили» is another word, not near: stays said again'))])
def test_a_repeat_whose_last_word_the_ear_took_for_another_word_still_counts(stand, caplog, word):
    assert says(stand('башню', 5), 'башню 5 очень долго и тщательно ' + word) == parts('башню 5')[:2] and counted(caplog) == 1


@pytest.fixture
def rigs(monkeypatch, tmp_path):
    made = []
    def make(n, **over):
        (tmp_path / 'profile.json').write_text(json.dumps({**LIVE, **over}), encoding='utf-8')
        monkeypatch.setenv('ECHO_REPLAY_PROFILE', str(tmp_path / 'profile.json'))
        made.append(Rig(monkeypatch))
        made[-1].asks('u1', 'Расскажи про мост номер %d?' % n, 0, 'Мост номер %d тянется на %d метров. Через него ходят трамваи каждые пять минут без остановок до самой ночи. Он построен в %d году.' % (n, 3 * n + 40, 1900 + n))
        made[-1].pump(0.5)
        return made[-1]
    yield make
    for rig in made:
        rig.close()


def stumbled(rig, n, said):
    """Первая порция повторена (слышит ухо), вторая начата как сказано и брошена: когда и что подсказали."""
    rig.says('мост номер %d тянется на %d метров' % (n, 3 * n + 40), speech=1.5)
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == 'Через него ходят трамваи каждые пять минут', rig.said()
    rig.pump(1.0)
    ended = rig.says(said, speech=0.8)
    return ended, rig.next_cue(4)


@pytest.mark.parametrize('said, rest, n', [('трамваи каждые', 'пять минут', 12), ('ну через него через него ходят', 'трамваи каждые пять минут', 7)])
def test_a_start_from_the_middle_or_a_stammer_that_stopped_is_helped_with_the_rest_only(rigs, said, rest, n):
    ended, cue = stumbled(rigs(n), n, said)
    assert cue is not None and cue.text == rest and cue.t - ended <= 1.5


@pytest.mark.parametrize('said', ['так через него ходят', pytest.param('нет через него ходят', marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.05: найдено проверкой: «вернулся к началу» через «нет, ...» не понят (ухо: dispute, mismatch_policy_silent), помощи нет; с «так, ...» помощь есть'))])
def test_a_restart_from_the_beginning_is_helped_with_the_rest_whatever_the_word_before_it(rigs, said):
    ended, cue = stumbled(rigs(7), 7, said)
    assert cue is not None and cue.text == 'трамваи каждые пять минут'


@pytest.mark.parametrize('pace', [pytest.param('off', marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 2.05: prompt_pace выключен: помощь после остановки приходит через 1,25 с после конца реплики, не по темпу человека')), 'on'])
def test_the_help_after_a_stop_comes_inside_the_owners_window_of_the_pace(rigs, pace):
    ended, cue = stumbled(rigs(7, prompt_pace=pace), 7, 'через него ходят')
    assert cue is not None and cue.text == 'трамваи каждые пять минут', 'помощь вообще не пришла'
    assert 0.39 <= cue.t - ended <= 0.9 + GRID, cue.t - ended      # окно владельца 0,7-1,2 с после последнего слова = 0,4-0,9 с после конца реплики

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

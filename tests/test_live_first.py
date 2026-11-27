"""``live_first``: the first cue of a question the base does not answer goes before the cloud's final, on the cloud's own input text.

The calls of 6 Nov, real questions only, from the ear's end of speech (phone n=16, probe n=20): the cloud holds the text of the question at 1.67 s and 0.73 s, its final at 3.17 s and 1.67 s, and GPT-Live's first fragment comes with the final, not
before it: a whole clause of its reply is there at 6.9 s and 5.6 s (an estimate: the fragments' text is not logged). A job started on the ear has its first text at 1.1-1.5 s, and on the phone 5 of 6 of them were right and none reached the sound.
So the reply of GPT-Live is never first; what it heard is. A still partial alone is no end of a question: with the ear silent for 0.9 s, 14 of 18 first still partials were a head of the final. A partial whose last word is the ear's last word
was: 26 turns, 18 the very final, 8 a head (the next utterance glued to the turn, 13-21 s later, or no question), 0 with another word, number or «не». Numbers, «не» and codes are not loosened: the ear, the cloud and the job must agree.
The logic only: nothing here is a measurement of a call.
"""
import json
import struct

import pytest

import helpers_s6_state as S
from echo_sync import fast_text as FT
from echo_sync.call_trace import CallTrace
from echo_sync.classifier import strip_fillers
from echo_sync.controlled_host import probe_flags
from echo_sync.settings import CALL_SETTINGS, resolve
from test_c16_ear_job import cloud, jobs
from test_h1_fast_text import settled       # noqa: F401
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture

FLAGS = {'fast_text': 'on', 'ear_release': 'on', 'prepare_wide': 'on', 'two_witnesses': 'on', 'live_first': 'on'}
SILENCE = 0.9


NUMBER = 'что учитывается на счёте семьдесят девять'      # a number at the end of the turn: the stable piece never holds it (``two_witnesses``), so without this flag only the final opens it


def strip(text):
    return strip_fillers(text, CALL_SETTINGS)


def live(call, **flags):
    rig = call(**{**FLAGS, **flags})
    rig.c.two_witnesses = True        # as the host sets it (``controlled_host.serve``)
    return rig


def asks(rig, ear, words, *, turn='u1', speech=1.0, lag=0.15):
    """One utterance: the ear hears it, its text comes, the cloud's open turn takes its words after it and stands still, the ear silent for ``SILENCE`` by then."""
    rig.onset()
    rig.pump(0.3)
    rig.w.feed(S.turn_created(turn, 'user', ''))
    rig.pump(speech - 0.3)
    uid = rig.ear.current
    rig.offset()
    rig.pump(lag)
    rig.worker.heard(uid, ear)
    rig.pump(TICK)
    cloud(rig, words, turn=turn)
    rig.pump(SILENCE)


def answers(rig, text, *, last=None):
    """The job of what the cloud heard says ``text``."""
    at = len(rig.fake.runs) - 1 if last is None else last
    rig.job_says(at, text)
    rig.pump(TICK * 4)
    return rig.said()


# ---- the flag ------------------------------------------------------------------------------------------------------------------------------------

def test_the_flag_is_off_by_default_and_needs_its_four():
    assert resolve({})['live_first'] == 'off'
    assert resolve({'local_ear': 'act', **FLAGS})['live_first'] == 'on'
    for flag in ('prepare_wide', 'ear_release', 'two_witnesses', 'fast_text'):
        assert resolve({'local_ear': 'act', **{**FLAGS, flag: 'off'}})['live_first'] == 'off', flag
    assert resolve({'local_ear': 'shadow', **FLAGS})['live_first'] == 'off', 'an ear that does not act opens nothing'


def test_with_the_flag_off_nothing_sounds_before_the_final(call):
    rig = live(call, live_first='off')
    asks(rig, NUMBER, ['Что ', 'учитывается ', 'на счёте ', '79'])
    assert rig.fast.count >= 1
    assert answers(rig, 'На счёте 79 учитывают внутрихозяйственные расчёты.') == []


# ---- the three readings ----------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('heard,text,same', [
    ('какая ставка ндс', 'Какая ставка НДС', True),
    ('так счёт пятьдесят восемь', 'Счет 58', True),                                   # a number by its value
    ('что значит подробнее про пятьдесят первый счёт', 'Так, это что? 51-ый счет', True),
    ('куда это вообще идёт', 'А почему так? Ну, откуда это вообще идет', True),       # the ear's text is rough, its last word is the same
    ('сам решит увалиться за сколько ему нужно предупредить работодателя', 'работодателя', True),
    ('какая ставка ндс', 'Какая ставка', False),                                      # the cloud is behind the ear
    ('счёт пятьдесят один расчётные счета', 'Счёт 51 - расчетные', False),            # 6 Nov: «счета» came 1.5 s later
    ('статья двадцать первая', 'Статья двадцать', False),                             # a number that may still grow
    ('как отразить покупку', '', False),
])
def test_the_cloud_has_caught_up_with_the_ear(heard, text, same):
    assert FT.caught_up(heard, text, strip=strip) is same


@pytest.mark.parametrize('heard,text,disputed', [
    ('счёт пятьдесят восемь', 'Счет 58', False),
    ('какая ставка ндс', 'Какая ставка НДС', False),
    ('счёт пятьдесят восемь', 'Счет 59', True),                                       # another number
    ('можно ли платить налог', 'Можно ли не платить налог', True),                    # «не» lost by the ear
    ('можно ли не платить налог', 'Можно ли платить налог', True),                    # «не» lost by the cloud
    ('что такое рко два', 'Что такое РКО, КО-2', True),                               # a code the ear cannot read: the final decides
    ('ка два', 'КО-2', True),
    ('добрый день что такое актив', 'Добрый день. Что такое актив', False),
])
def test_the_ear_may_dispute_what_the_cloud_heard(heard, text, disputed):
    assert FT.ear_disputes(heard, text, strip=strip) is disputed


@pytest.mark.parametrize('asked,text,heard', [
    ('какая ставка ндс', 'Какая ставка НДС', True),
    ('кто такое статья пятнадцать налогового кодекса', 'Что такое статья 15 Налогового кодекса', True),              # the ear's rough words
    ('налог на доходы и физических лиц с него удерживаете', 'Дальше, пособие по беременности, ну, налог на доходы физических лиц с него удерживаете', False),      # «с него»: the job did not hear of what
    ('какой максимальный срок', 'Испытательный срок для главного бухгалтера, какой максимальный срок', False),        # 7:37: the end of it
    ('какой максимум', 'Испытательный срок для главного бухгалтера, какой максимум', False),
    ('', 'Какая ставка НДС', False),
])
def test_a_job_serves_only_what_it_was_asked(asked, text, heard):
    assert FT.heard_all(asked, text, strip=strip) is heard


@pytest.mark.parametrize('asked,answer,keeps', [
    ('Счет 58', 'Счёт 58 — финансовые вложения.', True),
    ('Счет 58', 'Финансовые вложения, активный счёт.', True),                         # it does not name the number
    ('Счет 61', 'Счёт 62 — расчёты с покупателями.', False),                          # it answers another account
    ('Статья 15 Налогового кодекса', 'Статья 16 определяет обязанности.', False),
    ('Что учитывается на счёте 80', 'На счёте 80 учитывают уставный капитал.', True),
    ('пятьдесят восьмой счёт', 'Счёт 58 — финансовые вложения.', True),               # the word after the number
    ('Какая ставка НДС', '22 процента.', True),                                       # a number of the answer is the answer's
    ('Сколько стоит 5 билетов', 'За 5 билетов 500 рублей.', True),
])
def test_the_job_keeps_the_number_it_was_asked(asked, answer, keeps):
    assert FT.answer_keeps(asked, answer, strip=strip) is keeps


# ---- it opens before the final ---------------------------------------------------------------------------------------------------------------------

def test_the_first_cue_goes_before_the_final_when_the_cloud_and_the_job_agree(call):
    rig = live(call)
    asks(rig, 'что такое актив в балансе организации', ['Что ', 'такое ', 'актив ', 'в балансе ', 'организации'])
    said = answers(rig, 'Ресурс, которым владеет организация.')
    assert any('Ресурс' in text for text in said), said
    assert rig.c.user_boundaries.get('u1') == 'ear_first'
    rig.w.feed(S.turn_done('u1', 'user', 'Что такое актив в балансе организации'))
    rig.pump(TICK * 4)
    assert rig.c.question_id == 'u1'
    assert not [frame for frame in rig.w.frames if frame[2].get('type') == 'output_audio_buffer.clear' and frame[1] > rig.w.clock.t - TICK], 'the final confirms it: nothing is cut'


def test_a_number_the_ear_and_the_cloud_agree_on_goes_too(call):
    """The account the bank has no line for, the question of 7:49: 4.6 s then."""
    rig = live(call)
    asks(rig, NUMBER, ['Что ', 'учитывается ', 'на счёте ', '79'])
    said = answers(rig, 'На счёте 79 учитывают внутрихозяйственные расчёты.')
    assert any('79' in text for text in said), said
    assert rig.c.user_boundaries.get('u1') == 'ear_first'


def test_a_short_question_of_the_cloud_gets_a_job(call):
    """«Счет 58»: two words of the cloud, three of the ear: 10 of 16 questions of the phone had no job before the final."""
    rig = live(call)
    rig.c._reference = lambda text: None      # no line of the base for it
    asks(rig, 'счёт семьдесят девять', ['Счет ', '79'])
    assert len(jobs(rig)) == 1, 'the job of the ear fits what the cloud heard: no second one'
    said = answers(rig, 'Счёт 79 — внутрихозяйственные расчёты.')
    assert any('79' in text for text in said), said


# ---- what is never loosened -------------------------------------------------------------------------------------------------------------------------

def test_a_cloud_behind_the_ear_opens_nothing(call):
    rig = live(call)
    asks(rig, NUMBER, ['Что ', 'учитывается ', 'на счёте'])
    assert answers(rig, 'На счёте 79 учитывают расчёты.') == []


def test_a_partial_that_goes_on_cuts_nothing_and_opens_nothing_until_it_stands(call):
    rig = live(call)
    asks(rig, 'что такое актив в балансе организации', ['Что ', 'такое ', 'актив ', 'в балансе ', 'организации'])
    cloud(rig, [' и в отчёте'], start=9)
    assert answers(rig, 'Ресурс.') == [], 'what was asked is no longer what the cloud holds'


def test_another_number_of_the_ear_opens_nothing_and_the_final_decides(call):
    rig = live(call)
    asks(rig, NUMBER, ['Что ', 'учитывается ', 'на счёте ', '76'])
    assert rig.said() == [], 'the ear says 79, the cloud 76: nothing before the final'
    assert not any('76' in text for text in jobs(rig)), 'the cloud has not caught up with the ear: no job on it'
    rig.w.feed(S.turn_done('u1', 'user', 'Что учитывается на счёте 76'))
    rig.pump(TICK * 4)
    assert answers(rig, 'Расчёты с разными дебиторами.'), 'the final opens it, the job on the final answers'


def test_a_lost_not_opens_nothing(call):
    rig = live(call)
    asks(rig, 'можно ли платить налог с дохода', ['Можно ', 'ли ', 'не платить ', 'налог ', 'с дохода'])
    assert answers(rig, 'Нельзя.') == []


def test_a_code_the_ear_cannot_read_waits_for_the_final(call):
    rig = live(call)
    asks(rig, 'так значит что такое рко два', ['Так, ', 'значит, ', 'что такое ', 'РКО, ', 'КО-2'])
    assert answers(rig, 'Расходный кассовый ордер.') == []


def test_a_job_that_answers_another_number_opens_nothing(call):
    rig = live(call)
    asks(rig, NUMBER, ['Что ', 'учитывается ', 'на счёте ', '79'])
    assert answers(rig, 'На счёте 76 учитывают расчёты с дебиторами.') == []


def test_the_fragment_the_ear_heard_is_no_job_of_the_question(call):
    """The ear heard the end of a question: the rule of an adoption lets that end stand for all of it. The job that answers is the one asked what the cloud heard (``heard_all``). A safety of the reading only: «3 месяца» of 7:37 on 6 Nov was another thing, a job that had heard all of it."""
    assert FT.wide_refusal('какой максимальный срок', 'Испытательный срок для главного бухгалтера, какой максимальный срок', strip=strip, whole=True) is None, 'the rule of an adoption lets the end stand for the question'
    rig = live(call)
    asks(rig, 'какой максимальный срок', ['Испытательный ', 'срок ', 'для главного ', 'бухгалтера, ', 'какой ', 'максимальный ', 'срок'])
    assert 'бухгалтера' in jobs(rig)[-1], jobs(rig)
    said = answers(rig, 'Шесть месяцев для главного бухгалтера.')
    assert any('Шесть месяцев' in text for text in said), said


def test_speech_that_begins_closes_the_door(call):
    rig = live(call)
    asks(rig, 'что такое актив в балансе организации', ['Что ', 'такое ', 'актив ', 'в балансе ', 'организации'])
    rig.onset()
    rig.pump(TICK)
    assert answers(rig, 'Ресурс.') == []


def test_a_final_with_something_else_cuts_the_cue_and_the_next_answers_it(call):
    """The correction: what was said went on a partial, the final says more. The cue is cut, the question is the final's, its job answers it at once."""
    rig = live(call)
    asks(rig, 'что такое актив в балансе организации', ['Что ', 'такое ', 'актив ', 'в балансе ', 'организации'])
    assert any('Ресурс' in text for text in answers(rig, 'Ресурс, которым владеет организация.'))
    runs = len(rig.fake.runs)
    rig.w.feed(S.turn_done('u1', 'user', 'Что такое актив в балансе организации и чем он отличается от пассива'))
    rig.pump(TICK * 4)
    assert rig.c.user_boundaries.get('u1') != 'ear_first' or len(rig.fake.runs) > runs
    assert len(rig.fake.runs) > runs, 'a new job on what the cloud really heard'
    said = answers(rig, 'Актив это имущество, пассив это источники.')
    assert 'Актив это имущество' in ' '.join(said), said


def test_a_question_of_the_base_is_the_bases(call):
    """Rule 1 of the ear stands: the base is faster than any job."""
    rig = live(call)
    rig.first_portion()
    assert rig.fast.count == 0


# ---- a probe may ask for it, a phone call may not ----------------------------------------------------------------------------------------------------

def test_only_a_probe_may_ask_for_the_flag():
    profile = {'local_ear': 'act', 'fast_text': 'on', 'ear_release': 'on', 'two_witnesses': 'on'}
    assert probe_flags(profile, {'echo_live_first': '1'}, False) is profile, 'a phone call never: the query of a call is not the profile'
    assert probe_flags(profile, {}, True) is profile, 'a probe that does not ask'
    assert probe_flags(profile, {'echo_live_first': '0'}, True) is profile
    asked = probe_flags(profile, {'echo_live_first': '1'}, True)
    assert resolve(asked)['live_first'] == 'on' and resolve(asked)['prepare_wide'] == 'on'
    assert 'live_first' not in profile, 'the profile stays as it is'
    assert resolve(probe_flags({'fast_text': 'on'}, {'echo_live_first': '1'}, True))['live_first'] == 'off', 'what it needs stays the profile\'s'
    assert probe_flags(profile, {'echo_answer_witness': '1'}, False) is profile, 'nor the witness'
    assert resolve(probe_flags(profile, {'echo_answer_witness': '1'}, True))['answer_witness'] == 'shadow'


# ---- what the trace keeps of the cloud ----------------------------------------------------------------------------------------------------------------

def traced(tmp_path):
    clock = {'t': 100.0}
    trace = CallTrace(tmp_path, 'abc', clock=lambda: clock['t'])
    trace.open()
    trace.live_watch = True
    return trace, clock


def lines(trace, tmp_path):
    trace.close()
    return [json.loads(line) for path in tmp_path.iterdir() for line in path.read_text(encoding='utf-8').splitlines()]


def test_the_user_final_names_the_language_of_the_text_and_the_assistant_final_does_not(tmp_path):
    trace, _ = traced(tmp_path)
    trace.provider({'type': 'turn.done', 'turn': {'id': 'u1', 'role': 'user', 'transcript': 'Что такое инерция?'}})
    trace.provider({'type': 'turn.done', 'turn': {'id': 'u2', 'role': 'user', 'transcript': 'What is the meaning of this?'}})
    trace.provider({'type': 'turn.done', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': 'Инерция'}})
    rows = {line['id']: line for line in lines(trace, tmp_path) if line['ev'] in ('user_final', 'assistant_final')}
    assert (rows['u1']['lang'], rows['u2']['lang']) == ('ru', 'en')
    assert 'lang' not in rows['a1']


def test_the_trace_keeps_the_pieces_of_the_reply_and_not_those_of_the_user(tmp_path):
    trace, clock = traced(tmp_path)
    trace.provider({'type': 'turn.created', 'turn': {'id': 'u1', 'role': 'user', 'transcript': ''}})
    trace.provider({'type': 'turn.delta', 'turn_id': 'u1', 'delta': 'Какая'})
    trace.provider({'type': 'turn.created', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': ''}})
    clock['t'] += 0.2
    trace.provider({'type': 'turn.delta', 'turn_id': 'a1', 'delta': 'Сейчас'})
    found = [line for line in lines(trace, tmp_path) if line['ev'] == 'live_delta']
    assert [(line['t'], line['text']) for line in found] == [(200, 'Сейчас')]


def test_without_the_flag_the_trace_keeps_no_piece(tmp_path):
    trace, _ = traced(tmp_path)
    trace.live_watch = False
    trace.provider({'type': 'turn.created', 'turn': {'id': 'a1', 'role': 'assistant', 'transcript': ''}})
    trace.provider({'type': 'turn.delta', 'turn_id': 'a1', 'delta': 'Сейчас'})
    assert not [line for line in lines(trace, tmp_path) if line['ev'] == 'live_delta']


def test_the_start_of_the_clouds_voice_is_one_line_with_numbers_only(tmp_path):
    trace, clock = traced(tmp_path)
    quiet, voiced = struct.pack('<480h', *[10] * 480), struct.pack('<480h', *[2000] * 480)
    trace.live_audio(quiet)
    for _ in range(5):
        clock['t'] += 0.02
        trace.live_audio(voiced)
    clock['t'] += 1.0
    trace.live_audio(voiced)
    trace.live_audio(b'')
    found = [line for line in lines(trace, tmp_path) if line['ev'] == 'live_audio']
    assert [line['t'] for line in found] == [20, 1100]
    assert all(set(line) == {'t', 'ev', 'peak'} for line in found)

"""g25-silence (WAVE20): the kinds of silence and the words of help, and what each does. By the ear, fast, with no cloud: the real NativeMediaSocket, ShadowEar and controller on the
injected clock with the candidate's flags; only the ear's detector and recognizer, the cloud's events and the job's stream are scripted (the rig of test_h3_tempo). Each case says when the next
cue comes, what it says (from the right word) and that nothing is said twice. Nothing here is a measurement of a call."""
import pytest

import helpers_s6_state as S
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS, REFUSE_BEFORE_DROP_SECONDS, EAR_BIND_SECONDS, EAR_PILE_SECONDS, ECHO_MIN_LAG_SECONDS, TEMPO_FILLER_SECONDS, TEMPO_PAUSE_SECONDS, TEMPO_START_SECONDS
from test_h3_tempo import GRID, TICK, Rig

CANDIDATE = dict(fast_text='on', ear_release='on', two_witnesses='on', instant='on', material_pick='on', quick_math='on', spare_helper='on', warm_start='on', open_overlap='on')
ASKED = 'Что такое пассивный счёт'
ANSWER = 'Пассивный счёт учитывает источники образования имущества. Сальдо у него всегда кредитовое. Примеры: уставный капитал, кредиты и займы.'
P1, P2, P3 = 'Пассивный счёт учитывает источники образования имущества.', 'Сальдо у него всегда кредитовое.', 'Примеры: уставный капитал, кредиты и займы.'
REST = 'учитывает источники образования имущества.'
ACK_ALONE = EAR_BIND_SECONDS + 0.5      # a whole repeat the cloud never announced: the ear waits for its turn, then confirms alone
FAST = 1.0          # a command by the ear: EAR_COMMAND_SETTLE_SECONDS and the cue's way out, well under the cloud's final (up to 3.7 s behind on the phone)


@pytest.fixture
def call(monkeypatch):
    made = []

    def make(**profile):
        rig = Rig(monkeypatch, **{**CANDIDATE, **profile})
        made.append(rig)
        return rig
    yield make
    for rig in made:
        assert rig.w.violations == [], rig.w.violations
        rig.close()


def answered(rig):
    rig.asks('u1', ASKED, 0, ANSWER)
    assert rig.said() == [P1], 'precondition: the first portion was said'
    return rig.ended()


def after(rig, within):
    """Every cue said in the next ``within`` seconds, as (seconds from now, text)."""
    began, count = rig.w.clock.t, len(rig.cues())
    rig.pump(within)
    return [(round(c.t - began, 1), c.text) for c in rig.cues()[count:]]


def late_final(rig, uid, text, announce=0.6, final=3.0):
    """The cloud of the phone: its turn announced ``announce`` s after the onset, its final ``final`` s after the end of the speech. The ear's text comes 0.15 s after the end."""
    ear = rig.onset()
    rig.pump(announce)
    rig.w.feed(S.turn_created(uid, 'user', (text.split() or ['м'])[0]))
    rig.pump(0.2)
    ended = rig.offset()
    rig.pump(0.15)
    rig.worker.heard(ear, text)
    rig.pump(TICK)
    rig.pump(max(0.0, final - rig.w.clock.t + ended))
    rig.w.feed(S.turn_done(uid, 'user', text))
    return ended


# =====================================================================================================================================
# the kinds of silence
# =====================================================================================================================================

def test_silence_at_the_start_of_the_call_says_nothing(call):
    rig = call()
    assert after(rig, 30) == []


def test_thinks_three_seconds_in_the_middle_of_a_portion_gets_what_is_missing(call):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says('пассивный счёт', speech=0.6)
    cues = after(rig, 3.0)
    assert [text for _, text in cues] == [REST], 'what is missing, once, never the whole portion over the start'
    assert rig.cues()[-1].t - ended <= TEMPO_START_SECONDS + GRID


def test_the_portion_said_to_its_end_brings_the_next_and_no_repeat(call):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    rig.says('пассивный счёт учитывает источники образования имущества', speech=2.0)
    cues = after(rig, ACK_ALONE)
    assert [text for _, text in cues] == [P2]


def test_thirty_seconds_of_silence_then_the_owner_goes_on_from_his_word(call):
    rig = call()
    answered(rig)
    quiet = after(rig, 30)
    assert quiet and all(text == P1 for _, text in quiet) and len(quiet) <= rig.settings['max_auto_repeats'], 'the silence is bounded'
    ended = rig.says('пассивный счёт учитывает', speech=0.8)
    cues = after(rig, 2.0)
    assert [text for _, text in cues] == ['источники образования имущества.']
    assert rig.cues()[-1].t - ended <= TEMPO_START_SECONDS + GRID


def test_after_the_last_portion_silence_brings_no_old_answer(call):
    rig = call()
    answered(rig)
    for portion, nxt in ((P1, P2), (P2, P3)):
        rig.pump(0.4)
        rig.says(portion.rstrip('.').replace(':', '').replace(',', ''), speech=1.5)
        assert after(rig, ACK_ALONE)[-1][1] == nxt
    rig.pump(0.4)
    rig.says('примеры уставный капитал кредиты и займы', speech=1.5)
    assert after(rig, 30) == [], 'the answer is over: silence is silence'


@pytest.mark.parametrize('speech', [3.0, 6.0], ids=['3s', '6s'])
def test_a_long_er_brings_the_portion_after_it(call, speech):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says('э-э-э', speech=speech)
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == P1 and cue.t - ended == pytest.approx(TEMPO_FILLER_SECONDS, abs=GRID)


@pytest.mark.parametrize('said', ['', 'кхм', 'кхе кхе', 'ха-ха-ха', 'ха ха', 'хм', 'ой'], ids=['breath', 'cough', 'cough2', 'laugh', 'laugh2', 'hm', 'oj'])
def test_breath_cough_laugh_are_no_speech_and_bring_the_portion(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says(said, speech=0.3)
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == P1 and cue.t - ended <= TEMPO_FILLER_SECONDS + GRID


@pytest.mark.parametrize('said', ['', 'кхм', 'ха-ха-ха'], ids=['breath', 'cough', 'laugh'])
def test_a_cough_after_a_start_keeps_the_word(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    rig.says('пассивный счёт', speech=0.6, lag=0.1)
    rig.pump(0.2)
    rig.says(said, speech=0.3, lag=0.1)
    cues = after(rig, 2.5)
    assert [text for _, text in cues] == [REST]


# =====================================================================================================================================
# the words of help
# =====================================================================================================================================

@pytest.mark.parametrize('said', ['как там', 'как его', 'что там', 'забыл', 'забыла', 'вылетело', 'не помню', 'блин забыл', 'сейчас вспомню', 'дай вспомнить', 'секунду забыл'])
def test_the_word_will_not_come_brings_the_portion_at_once(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says(said, speech=0.5)
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == P1 and cue.t - ended <= TEMPO_FILLER_SECONDS + GRID


@pytest.mark.parametrize('said', ['как там', 'забыл', 'как его'])
def test_the_word_will_not_come_after_a_start_brings_what_is_missing(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says('пассивный счёт ' + said, speech=0.8)
    cues = after(rig, 2.5)
    assert [text for _, text in cues] == [REST] and rig.cues()[-1].t - ended <= TEMPO_START_SECONDS + GRID


PAUSES = ['секунду', 'секундочку', 'сейчас', 'щас', 'минутку', 'минуточку', 'момент', 'сейчас сейчас', 'дай подумать', 'сейчас скажу', 'одну секунду', 'так сейчас']


@pytest.mark.parametrize('said', PAUSES)
def test_a_pause_asked_for_is_given_then_the_portion(call, said):
    """«секунду»: the owner asks for time («вспомн-» is stuck: help at once, the case above). No cue into it, nor a job of the cloud: TEMPO_PAUSE_SECONDS of quiet, then the portion; one cue."""
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says(said, speech=0.5)
    cues = after(rig, TEMPO_PAUSE_SECONDS + 1.0)
    assert [text for _, text in cues] == [P1], cues
    assert rig.cues()[-1].t - ended == pytest.approx(TEMPO_PAUSE_SECONDS, abs=GRID)


@pytest.mark.parametrize('said', ['секунду', 'сейчас', 'минутку'])
def test_a_pause_after_a_start_brings_what_is_missing_after_it(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says('пассивный счёт ' + said, speech=0.8)
    cues = after(rig, TEMPO_PAUSE_SECONDS + 1.0)
    assert [text for _, text in cues] == [REST], cues
    assert rig.cues()[-1].t - ended == pytest.approx(TEMPO_PAUSE_SECONDS, abs=GRID)


@pytest.mark.parametrize('said', ['секунду', 'сейчас', 'минутку'])
def test_a_pause_with_the_clouds_late_final_is_still_the_same_pause(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = late_final(rig, 'u2', said)
    cues = after(rig, TEMPO_PAUSE_SECONDS)
    assert [text for _, text in cues] == [P1], cues
    assert rig.cues()[-1].t - ended == pytest.approx(TEMPO_PAUSE_SECONDS, abs=GRID)
    assert rig.fake is None or len(rig.fake.runs) == 1, 'no job is spent on «секунду»'


def test_a_pause_then_the_owner_goes_on_himself_is_not_cut(call):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    rig.says('сейчас', speech=0.4)
    rig.pump(1.5)
    rig.says('пассивный счёт учитывает источники образования имущества', speech=2.0)
    cues = after(rig, 2.0)
    assert [text for _, text in cues] == [P2]


@pytest.mark.parametrize('back', ['ещё раз', 'дальше', 'повтори'])
def test_wait_stops_and_a_request_brings_the_portion_back_by_the_ear(call, back):
    """«подожди»: a stop. Silence for as long as the owner keeps it (no timer: he said it); his stray try leaves the pause alone (engine, ruling 1: a pause ends on a request).
    «ещё раз», «дальше» (the cut portion first, A1-F6) end it at once, by the ear, and the cloud's late final of the same words acts no more."""
    rig = call(repeat_seconds=6)
    answered(rig)
    rig.pump(0.5)
    rig.says('подожди', speech=0.4)
    assert after(rig, 20) == []
    ended = late_final(rig, 'u3', back, announce=0.6, final=3.5)
    cues = rig.cues()
    assert [c.text for c in cues] == [P1, P1] and cues[-1].t - ended <= FAST
    assert after(rig, 2) == [], 'one act (the timer of 6 s is later)'


def test_wait_then_the_clouds_final_first_seen_late_is_a_piece(call):
    rig = call(repeat_seconds=6)
    answered(rig)
    rig.pump(0.5)
    rig.says('подожди', speech=0.4)
    rig.pump(8)
    rig.says('дальше', speech=0.6)
    rig.pump(3.5)
    rig.w.feed(S.turn_done('u5', 'user', 'дальше'))
    rig.pump(1.0)
    assert rig.said() == [P1, P1], 'the cloud announced its turn of «дальше» only with its final, 4 s after: no second step'


@pytest.mark.parametrize('said', ['дальше', 'давай дальше'])
def test_next_by_the_ear_alone_is_fast(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says(said, speech=0.4)
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == P2 and cue.t - ended <= FAST
    assert after(rig, 1.0) == []


@pytest.mark.parametrize('said', ['ещё раз', 'повтори', 'повтори пожалуйста', 'не расслышал'])
def test_again_by_the_ear_alone_is_fast(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says(said, speech=0.4)
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == P1 and cue.t - ended <= FAST


HEARING = ['громче', 'погромче', 'говори громче', 'громче пожалуйста', 'медленнее', 'помедленнее', 'не слышу', 'не слышно', 'плохо слышно', 'чётче']


@pytest.mark.parametrize('said', HEARING)
def test_louder_slower_cannot_hear_say_the_portion_again_at_once(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    ended = rig.says(said, speech=0.4)
    cue = rig.next_cue(3)
    assert cue is not None and cue.text == P1 and cue.t - ended <= FAST


@pytest.mark.parametrize('said', ['ещё раз', 'громче', 'не слышу', 'дальше'])
def test_a_command_the_cloud_finals_late_acts_once(call, said):
    """The ear acted; the cloud's turn of the same words comes later: it is a piece of the ear's take, never a second repeat or a second step."""
    rig = call(repeat_seconds=6)        # the timer's own repeat of the portion is no double
    answered(rig)
    rig.pump(0.5)
    ended = late_final(rig, 'u2', said)
    rig.pump(0.5)
    want = P2 if said == 'дальше' else P1
    assert rig.said() == [P1, want], rig.said()
    assert rig.cues()[-1].t - ended <= FAST


@pytest.mark.parametrize('said', ['ещё раз', 'громче', 'дальше'])
def test_a_command_the_cloud_never_announces_still_acts_once(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    rig.says(said, speech=0.4)
    rig.pump(1.5)
    want = P2 if said == 'дальше' else P1
    assert rig.said() == [P1, want]


@pytest.mark.parametrize('said', ['громче', 'не слышу', 'ещё раз'])
def test_a_hearing_request_on_the_second_portion_says_the_second(call, said):
    rig = call()
    answered(rig)
    rig.pump(0.4)
    rig.says('пассивный счёт учитывает источники образования имущества', speech=2.0)
    assert after(rig, ACK_ALONE)[-1][1] == P2
    rig.pump(0.4)
    rig.says(said, speech=0.4)
    assert after(rig, FAST)[-1][1] == P2


def test_two_agains_are_two_repeats_not_three(call):
    rig = call()
    answered(rig)
    for _ in range(2):
        rig.pump(0.6)
        rig.says('ещё раз', speech=0.4)
        rig.pump(FAST)
    assert rig.said() == [P1, P1, P1]


def test_next_on_the_last_portion_says_nothing_old(call):
    rig = call()
    answered(rig)
    for _ in range(2):
        rig.pump(0.5)
        rig.says('дальше', speech=0.4)
        rig.pump(FAST)
    assert rig.said() == [P1, P2, P3]
    rig.pump(0.5)
    rig.says('дальше', speech=0.4)
    assert after(rig, 10) == []


# =====================================================================================================================================
# more of the same, broken on purpose
# =====================================================================================================================================

def test_a_friends_question_nobody_can_answer_gets_one_honest_phrase_and_then_silence(call):
    """The roads give nothing and the cloud has no answer: the honest sentence of the roads (``reserve_text.REFUSAL``, its first portion) once, ``REFUSE_BEFORE_DROP_SECONDS`` before the 8 s drop, never silence after a question, never a loop (the silence timer does not say it again)."""
    rig = call()
    rig.w.feed(S.turn_created('u1', 'user', 'Сколько'))
    rig.w.feed(S.turn_done('u1', 'user', 'Сколько стоит билет до Казани'))
    asked = rig.w.clock.t
    rig.pump(40)
    said = [(c.t - asked, c.text) for c in rig.w.cues]
    assert len(said) == 1 and said[0][1] == 'Ответа пока нет.' and ANSWER_WAIT_SECONDS - REFUSE_BEFORE_DROP_SECONDS - 0.1 <= said[0][0] <= ANSWER_WAIT_SECONDS, said      # hold8: due before the drop, inside the owner's 8 s


@pytest.mark.parametrize('late', [2.0, 3.5])
def test_a_late_final_keeps_the_eight_seconds_of_the_speech_and_the_late_answer_takes_the_phrases_place(call, late):
    """fix5 (Р001 seed 3 q15: the cloud's final 1.7 s after the speech, the phrase 9.3 s after it): the owner's 8 s count from the END OF THE QUESTION'S SPEECH, never from the final's arrival.
    The final ``late`` s after the speech and the job silent: the roads' sentence by 8 s after the speech (the old clock said it at final + 7.5); the job goes on, and its text that comes
    after the sentence takes its place and is cued (F20: it used to be a portion after the sentence that nobody cued)."""
    rig = call()
    ended = late_final(rig, 'u1', 'Сколько стоит билет до Казани', final=late)
    rig.pump(ended + ANSWER_WAIT_SECONDS + 0.5 - rig.w.clock.t)
    said = [(round(c.t - ended, 2), c.text) for c in rig.cues()]
    assert len(said) == 1 and said[0][1] == 'Ответа пока нет.' and said[0][0] <= ANSWER_WAIT_SECONDS - REFUSE_BEFORE_DROP_SECONDS + GRID, said
    job = len(rig.fake.runs) - 1
    rig.job_says(job, ANSWER)
    rig.job_ends(job)
    rig.pump(1.0)
    assert [text for _, text in [(c.t, c.text) for c in rig.cues()]] == ['Ответа пока нет.', P1], rig.said()


def test_now_as_the_first_word_of_the_portion_is_a_start_not_a_pause(call):
    rig = call()
    rig.asks('u1', 'Какая ставка НДС', 0, 'Сейчас основная ставка НДС двадцать процентов.')
    rig.pump(0.5)
    ended = rig.says('сейчас', speech=0.3)
    cues = after(rig, 2.5)
    assert [text for _, text in cues] == ['основная ставка НДС двадцать процентов.'] and rig.cues()[-1].t - ended <= TEMPO_START_SECONDS + GRID


def test_a_pause_when_nothing_waits_says_nothing(call):
    rig = call()
    answered(rig)
    for portion in ('пассивный счёт учитывает источники образования имущества', 'сальдо у него всегда кредитовое', 'примеры уставный капитал кредиты и займы'):
        rig.pump(0.4)
        rig.says(portion, speech=1.5)
        rig.pump(ACK_ALONE)
    assert rig.said() == [P1, P2, P3]
    rig.pump(0.5)
    rig.says('секунду', speech=0.4)
    assert after(rig, 15) == []


def test_a_pause_then_silence_helps_once_then_the_timer_as_ever(call):
    rig = call(max_auto_repeats=2)
    answered(rig)
    rig.pump(0.5)
    ended = rig.says('секунду', speech=0.4)
    rig.pump(40)
    cues = [(c.t - ended, c.text) for c in rig.cues()[1:]]
    assert [text for _, text in cues] == [P1] * rig.settings['max_auto_repeats'], 'the help after the pause is the first of the bounded repeats'
    assert cues[0][0] == pytest.approx(TEMPO_PAUSE_SECONDS, abs=GRID)


def test_two_pauses_in_a_row_are_one_longer_pause(call):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    rig.says('секунду', speech=0.4)
    rig.pump(2.0)
    ended = rig.says('сейчас', speech=0.6)
    cues = after(rig, TEMPO_PAUSE_SECONDS + 1)
    assert [text for _, text in cues] == [P1] and rig.cues()[-1].t - ended == pytest.approx(TEMPO_PAUSE_SECONDS, abs=GRID)


def test_a_pause_then_a_start_then_silence_gets_what_is_missing_fast(call):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    rig.says('секунду', speech=0.4)
    rig.pump(1.5)
    ended = rig.says('пассивный счёт учитывает', speech=0.8)
    cues = after(rig, 2.5)
    assert [text for _, text in cues] == ['источники образования имущества.'] and rig.cues()[-1].t - ended <= TEMPO_START_SECONDS + GRID


def test_the_word_will_not_come_said_again_and_again_is_bounded(call):
    rig = call(max_auto_repeats=2)
    answered(rig)
    for _ in range(6):
        rig.pump(0.5)
        rig.says('как там', speech=0.4)
        rig.pump(2.5)
    assert all(text == P1 for text in rig.said()) and len(rig.said()) <= 7, 'help each time he asks, never a storm'


def test_a_cough_in_the_wait_does_not_put_the_portion_off(call):
    rig = call()
    answered(rig)
    rig.pump(1.0)
    ended = rig.says('кхм', speech=0.2)
    cue = rig.next_cue(4)
    assert cue is not None and cue.text == P1 and cue.t - ended <= TEMPO_FILLER_SECONDS + GRID


@pytest.mark.parametrize('said', ['громче', 'ещё раз', 'плохо слышно'])      # «не слышу, не слышу» joined is no phrase of hearing_repair yet (report: left)
def test_a_hearing_request_twice_in_one_breath_is_one_repeat(call, said):
    rig = call(repeat_seconds=6)
    answered(rig)
    rig.pump(0.5)
    rig.says(said, speech=0.4, lag=0.1)
    rig.pump(0.1)
    rig.says(said, speech=0.4, lag=0.1)
    rig.pump(2.0)
    assert rig.said() in ([P1, P1], [P1, P1, P1]), rig.said()
    assert len(rig.said()) <= 3


def test_louder_said_with_a_question_is_the_question(call):
    rig = call()
    answered(rig)
    rig.pump(0.5)
    rig.says('кто говорит громче всех', speech=1.0)
    rig.pump(1.5)
    assert rig.said() == [P1], 'a question with «громче» in it is no request to repeat'


# =====================================================================================================================================
# seeds: chains of silences and words of help, the invariants of all of them
# =====================================================================================================================================

STEPS = ('quiet', 'er', 'cough', 'start', 'pause', 'again', 'louder', 'blank', 'whole')
SAID = {'er': 'э-э', 'cough': 'кхм', 'again': 'ещё раз', 'louder': 'громче', 'blank': 'как там', 'pause': 'секунду'}
BOUND = {'er': TEMPO_FILLER_SECONDS, 'cough': TEMPO_FILLER_SECONDS, 'blank': TEMPO_FILLER_SECONDS, 'again': FAST, 'louder': FAST, 'start': TEMPO_START_SECONDS, 'pause': TEMPO_PAUSE_SECONDS,
         'whole': ACK_ALONE}


def chain(rig, seed, steps=6):
    """One call: the answer, then ``steps`` random kinds. Returns the faults found: (step, what)."""
    import random
    rnd, faults = random.Random(seed), []
    answered(rig)
    for n in range(steps):
        state = rig.c.state()
        portion = (state.get('chunks') or [None])[state.get('chunk_index', 0)] if not state.get('completed') else None
        if portion is None:
            break
        kind = rnd.choice(STEPS)
        rig.pump(rnd.choice((0.4, 0.8, 1.5)))
        if kind in ('start', 'whole') and rig.cues() and rig.w.clock.t < rig.ended() + ECHO_MIN_LAG_SECONDS:
            rig.pump(rig.ended() + ECHO_MIN_LAG_SECONDS - rig.w.clock.t)      # the portion's own words that soon after it may be its echo: the timer's wait stands then (H3)
        unjudged = rig.c.tempo_unjudged
        if kind in ('er', 'cough') and unjudged and rig.w.clock.t < unjudged[-1][0] + EAR_PILE_SECONDS:
            rig.pump(unjudged[-1][0] + EAR_PILE_SECONDS - rig.w.clock.t + GRID)      # the speech of a step before that no final judged (this rig has no cloud for it) and a cough within EAR_PILE_SECONDS of it are ONE pile of talk: the ear's text «сальдо у кхм» is words of the answer, a try, and the silence timer is re-armed from it (h28, ``_at_the_answer``), not helped at the cough: a cough that is its own utterance comes after the pile (seeds 5 and 28)
        count = len(rig.cues())
        if kind == 'quiet':
            rig.pump(rnd.choice((3.0, 10.0, 30.0)))
            continue
        if rig.c.auto_repeats >= rig.c.max_auto_repeats and kind in ('er', 'cough'):
            kind = 'blank'          # the cap stands for noise: a filler or a cough after it is no call for help (the owner's words are)
        judging = bool(rig.c.candidate and 'job' in rig.c.candidate)        # a job judges earlier speech (the ear's text with no final, H6 item 6): a cough waits for its verdict
        words = portion.rstrip('.').replace(':', '').replace(',', '').lower().split()
        text = SAID.get(kind) or (' '.join(words[:max(1, len(words) // 2)]) if kind == 'start' else ' '.join(words))
        ended = rig.says(text, speech=rnd.choice((0.3, 0.6, 1.2)))
        rig.pump(BOUND[kind] + GRID + TICK)
        new = rig.cues()[count:]
        judging = judging or bool(rig.c.candidate and 'job' in rig.c.candidate)      # or one began in the wait (the stand's job never answers; a real one does within ~1 s)
        if not new and kind == 'whole' and rig.c.state().get('completed'):
            pass                                                            # the last portion said: the answer is over
        elif not new and judging and kind in ('er', 'cough'):
            pass
        elif not new:
            faults.append((n, kind, 'no help'))
        elif new[0].t - ended > BOUND[kind] + GRID:
            faults.append((n, kind, 'late %.1f' % (new[0].t - ended)))
        elif kind == 'whole' and not (rig.c.state().get('completed') or new[0].text != portion):
            faults.append((n, kind, 'the portion again after it was said'))
        elif kind != 'whole' and not portion.endswith(new[0].text):         # the portion, or what is missing of a start said a moment ago
            faults.append((n, kind, 'other text: ' + new[0].text))
        times = [c.t for c in rig.cues()]
        if any(b - a < 0.3 for a, b in zip(times, times[1:])):
            faults.append((n, kind, 'two cues at once'))
    return faults


@pytest.mark.parametrize('seed', range(60))
def test_chains_of_silence_and_help_hold_on_every_seed(call, seed):
    rig = call(max_auto_repeats=10)
    assert chain(rig, seed) == []

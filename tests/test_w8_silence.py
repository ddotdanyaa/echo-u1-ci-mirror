"""W8-silence (N35, N36, N48, N49; E25.1, E85, E42.1, E37, E26.2, E43, E90): silence and holds, replayed on the real controller, the real socket and the real ear with the injected clock and a scripted job (no model, no network,
no phone). What is proved is the logic of the code: the device half (does the Conduit keep listening after 120 s, does the mic stay shut during a cue) is E24's and is not measured here.
Tests marked xfail(strict=True) are red on production code; the patch that turns each green is in cloud_context/reports/w8-silence.md.
"""
import pytest

from echo_sync import reserve_text as RT
import helpers_s6_state as S
from test_h4_ear_first import slow
from test_h3_tempo import in_flight
from test_h6 import INERTIA, NOTICE, stopped
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_h5_live import LIVE, asked, job_mark, plan, said_to_the_room, spoken_failures

CHAT = ['Ну в общем вчера было прикольно', 'Да мы вообще не ожидали', 'Погода конечно сегодня', 'Ладно потом расскажу', 'Слушай а ты куда в субботу']


def decline(rig, n):
    rig.job_says(n, '—')
    rig.job_ends(n)


def talk(rig, lines, first=0, gap=6.0):
    """Lines of an ordinary talk, each declined by the job; returns the next job number."""
    for n, line in enumerate(lines, first):
        said_to_the_room(rig, f'c{n}', line)
        decline(rig, n)
        rig.pump(gap)
    return first + len(lines)


def question(rig, uid, text, n, answer):
    asked(rig, text, uid=uid)
    rig.job_says(n, answer)
    rig.job_ends(n)


# =====================================================================================================================================
# N35 / E25.1: 60 and 120 s of silence, then a question with no touch; 20 questions in a row
# =====================================================================================================================================

@pytest.mark.parametrize('silence', [60.0, 120.0])
def test_e25_1_a_question_after_silence_is_answered_and_the_silence_said_nothing(call, silence):
    rig = call(**LIVE)
    rig.pump(silence)
    assert rig.said() == [] and not spoken_failures(rig) and rig.fake.runs == [], 'silence is silence: no cue, no «Не нашёл», no job'
    question(rig, 'u1', 'А какая столица Австралии', 0, 'Канберра.')
    assert rig.said() == ['Канберра.'] and not spoken_failures(rig)


def test_e25_1_silence_after_an_answer_does_not_repeat_it_for_ever(call):
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(120.0)
    assert rig.said().count('Инерция — свойство тела.') <= 1 + LIVE['max_auto_repeats'] and not spoken_failures(rig)
    count = len(rig.said())
    rig.pump(120.0)
    assert len(rig.said()) == count, 'the repeats of a silent listener are bounded'


def test_e25_1_twenty_questions_in_a_row_each_get_their_answer(call):
    rig = call(**LIVE)
    for n in range(20):
        question(rig, f'u{n}', f'А какая столица страны номер {n + 1}', n, f'Город номер {n + 1}.')
        rig.pump(8.0)
    firsts = list(dict.fromkeys(t for t in rig.said() if t.startswith('Город')))     # the timer repeats a portion nobody repeated back (max_auto_repeats): every answer is there, in order
    assert firsts == [f'Город номер {n + 1}.' for n in range(20)], rig.said()
    assert not spoken_failures(rig)


# =====================================================================================================================================
# N36 / E85: switched on and just talking: no false «Не нашёл», then a normal first help
# =====================================================================================================================================

def test_e85_ninety_seconds_of_talk_say_nothing_then_a_question_is_answered(call):
    rig = call(**LIVE)
    n = talk(rig, CHAT * 3)
    assert rig.said() == [] and not spoken_failures(rig), 'talk with no question: no cue and no failure said'
    question(rig, 'u9', 'А какая столица Австралии', n, 'Канберра.')
    assert rig.said() == ['Канберра.'] and not spoken_failures(rig)


def test_e85_talk_the_job_fails_on_is_not_a_spoken_failure(call):
    """The job of a talk that fails (a broken stream) must not say «Не нашёл»: nobody asked. One failed line leaves the channel on (three failures in a row switch it off), the next question is the job's."""
    rig = call(**LIVE)
    said_to_the_room(rig, 'c0', CHAT[0])
    rig.fake.run(0).fail()
    rig.pump(6.0)
    assert rig.said() == [] and not spoken_failures(rig), (rig.said(), [c.text for c in spoken_failures(rig)])
    n = len(rig.fake.runs)
    question(rig, 'u9', 'А какая столица Австралии', n, 'Канберра.')
    assert rig.said() == ['Канберра.'] and not spoken_failures(rig)


def test_e85_three_failures_on_talk_switch_the_channel_off_and_say_nothing(call):
    """The breaker is the call's own cure (fast_text off=breaker): after it a question goes the cloud's way, and still no failure is said for the talk."""
    rig = call(**LIVE)
    for n, line in enumerate(CHAT):
        said_to_the_room(rig, f'c{n}', line)
        for run in list(rig.fake.runs):
            run.fail()
        rig.pump(6.0)
    assert rig.said() == [] and not spoken_failures(rig), (rig.said(), [c.text for c in spoken_failures(rig)])


# =====================================================================================================================================
# E43: every hold has a bound, measured through the final with a job that never gives text
# =====================================================================================================================================

def decision_time(rig, began, limit=40.0):
    """Seconds from ``began`` until the listener got anything (a cue or a spoken failure), or None."""
    while rig.w.clock.t - began < limit:
        if rig.cues() or spoken_failures(rig):
            return rig.w.clock.t - began
        rig.pump(TICK)
    return None


def test_e43_through_a_final_the_listener_gets_a_decision_within_eight_seconds(call):
    rig = call(**LIVE)
    began = rig.w.clock.t
    asked(rig, 'В каком году было крещение Руси')
    t = decision_time(rig, began)
    assert t is not None and t <= 8.0, t


def test_e43_a_hung_job_ends_its_walk_inside_the_bound_and_the_failure_is_said_once(call):
    """hold8: the decision on the question is due inside the 8 s of the question; whatever comes after (the hand back, the cloud's own window) says no second phrase. fix5 (F20): with the
    cloud silent the decision at the due is the roads' provisional sentence, and the walk goes on to GIVE_UP_S (the old pin let the job go at 8 s, so a real text after the sentence
    could never take its place: the anchor at the end of speech turned answers into refusals, 31 reds of f0fab6d); it is let go there, never later."""
    rig = call(**LIVE)
    began = rig.w.clock.t
    asked(rig, 'В каком году было крещение Руси')
    rig.pump(8.5 - (rig.w.clock.t - began))
    assert len(rig.said()) + len(spoken_failures(rig)) == 1, ('the decision inside the 8 s', rig.said(), [c.text for c in spoken_failures(rig)])
    assert not rig.fake.run(0).cancelled.is_set(), 'the job walks on past the sentence: a text of it would take the place of the sentence'
    rig.pump(RT.GIVE_UP_S + 0.5 - (rig.w.clock.t - began))
    assert rig.fake.run(0).cancelled.is_set(), 'the job that never spoke is let go at GIVE_UP_S'
    rig.pump(20.0)
    assert len(rig.said()) + len(spoken_failures(rig)) == 1, ('the failure phrase once', rig.said(), [c.text for c in spoken_failures(rig)])


def test_e43_the_ears_text_with_no_final_is_decided_within_eight_seconds(call):
    """The other path of the table (no final at all): the job runs on the ear's text, its verdict stands."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    ended = rig.says('а какая столица австралии', speech=2.0)
    rig.pump(8.0)
    assert len(rig.fake.runs) >= 2 and rig.w.clock.t - ended >= 8.0 and rig.c.tempo_unjudged == [], 'a job is asked on the ear text and nothing waits on a final that never comes'


# =====================================================================================================================================
# N49 / E37 / E26.2: the stop over a cue; the mic is shut during the cue, so only the command of the Conduit's button (response.cancel / input_audio_buffer.clear) arrives
# =====================================================================================================================================

def cue_over(rig):
    """An answer of two portions with its first cue in flight (frames of 200 ms in virtual time)."""
    slow(rig)
    rig.w.feed(S.turn_created('u0', 'user', 'Что'))
    rig.w.feed(S.turn_done('u0', 'user', 'Что такое инерция'))
    rig.job_says(0, NOTICE + ' Это статья восемьдесят.')
    rig.fake.run(0).finish()
    rig.pump(TICK)
    return in_flight(rig)


def test_e26_2_the_button_cuts_the_sound(call):
    rig = call(**LIVE)
    cue = cue_over(rig)
    rig.w.client({'type': 'response.cancel'})
    assert cue.cleared, 'the command needs no microphone'


@pytest.mark.parametrize('signal', ['response.cancel', 'input_audio_buffer.clear'])
@pytest.mark.xfail(strict=True, reason='W8-S2: a bare cancel is taken for the start of speech that may come; no word comes, and the timer says the cut portion again up to max_auto_repeats times: patch w8-silence.button_stop.diff')
def test_e26_2_after_the_button_the_plan_does_not_come_back_by_itself(call, signal):
    rig = call(**LIVE)
    cue_over(rig)
    rig.c.button_stop_enabled = True       # the patch's flag; on the production code this is an attribute nobody reads
    rig.w.client({'type': signal})
    said = len(rig.said())
    rig.pump(60.0)
    assert len(rig.said()) == said and not spoken_failures(rig), rig.said()


def test_e37_a_stop_of_the_cloud_final_over_a_cue_with_the_mic_shut_pauses_the_plan_for_good(call):
    """The mic is shut during the cue (MAP11): the ear hears nothing, the cloud's final «Стоп» comes up to 3.7 s later (R1, R4)."""
    rig = call(**LIVE)
    cue_over(rig)
    rig.pump(3.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.w.feed(S.turn_done('u1', 'user', 'Стоп'))
    rig.pump(TICK * 2)
    assert rig.c.state().get('paused') is True
    said = len(rig.said())
    rig.pump(120.0)
    assert len(rig.said()) == said and rig.c.state().get('paused') is True and not spoken_failures(rig), 'a stopped plan stays stopped'


def test_e37_a_stop_then_a_resume_says_the_portion_once(call):
    rig = call(**LIVE)
    stopped(rig)
    said = len(rig.said())
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Продолжайте'))
    rig.pump(TICK * 3)
    assert not rig.c.state().get('paused') and rig.said()[said:].count(NOTICE) == 1, rig.said()


def test_e37_a_stop_with_no_plan_in_play_is_silence_not_a_failure(call):
    rig = call(**LIVE)
    rig.pump(30.0)
    said_to_the_room(rig, 'u1', 'Стоп')
    rig.pump(10.0)
    assert rig.said() == [] and not spoken_failures(rig), 'a bare stop with nothing in play: no cue, no «Не нашёл»'


# =====================================================================================================================================
# N48 / E42.1: «дальше» after the end of an answer
# =====================================================================================================================================

def finish(rig):
    plan(rig, asked=INERTIA, answer='Срок уведомления две недели.')
    said_to_the_room(rig, 'u1', 'Срок уведомления две недели')
    assert rig.c.state().get('completed') is True


@pytest.mark.parametrize('word', ['Дальше', 'Ну давай дальше', 'Продолжай'])
def test_e42_1_a_next_after_the_end_of_an_answer_is_silence_and_no_failure(call, word):
    """Pinned as it is (H6R «NOT done»): the word needs a phrase of the owner's list with a WAV; until then nothing is said and nothing is called a failure."""
    rig = call(**LIVE)
    finish(rig)
    count = len(rig.said())
    said_to_the_room(rig, 'u2', word)
    job_mark(rig, 1, '[дальше]')
    rig.pump(20.0)
    assert len(rig.said()) == count and not spoken_failures(rig)
    asked(rig, 'Какая столица Австралии?', uid='u3')
    rig.job_says(2, 'Канберра.')
    rig.job_ends(2)
    assert rig.said()[-1] == 'Канберра.'


def test_e42_1_a_repeat_after_the_end_of_an_answer_has_its_way_back(call):
    rig = call(**LIVE)
    finish(rig)
    count = len(rig.said())
    said_to_the_room(rig, 'u2', 'Повтори')
    rig.pump(2.0)
    assert rig.said()[count:] == ['Срок уведомления две недели.']


# =====================================================================================================================================
# E90: the two rests of 01 §5
# =====================================================================================================================================

def test_e90_the_release_profile_carries_no_repeat_seconds_and_the_tempo_rule_stands():
    from echo_sync.settings import resolve
    for profile in ({'local_ear': 'act', 'prompt_tempo': 'ear', 'fast_text': 'on', 'ear_release': 'on'}, {'local_ear': 'act', 'prompt_tempo': 'ear'}):
        assert 'repeat_seconds' not in profile and resolve(profile)['repeat_seconds'] == 2.0, 'rule 2 of the tempo (each repeat waits longer) is in force while the profile does not name a wait'


def test_e90_an_ear_turn_of_the_phone_order_does_not_answer_turn_elsewhere(call):
    """The phone's order: the ear's text first, the cloud's turn 3.1-3.7 s after the onset, its final later. Nothing of it is a spoken failure or a «turn elsewhere» cue."""
    rig = call(**LIVE)
    plan(rig, asked=INERTIA, answer='Инерция — свойство тела.')
    rig.pump(1.0)
    uid = rig.onset()
    rig.pump(0.6)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, 'а какая столица австралии')
    rig.pump(3.0)
    rig.w.feed(S.turn_created('u5', 'user', ''))
    rig.pump(0.7)
    rig.w.feed(S.turn_done('u5', 'user', 'А какая столица Австралии?'))
    rig.pump(0.5)
    rig.job_says(len(rig.fake.runs) - 1, 'Канберра.')
    rig.job_ends(len(rig.fake.runs) - 1)
    rig.pump(2.0)
    assert 'Канберра.' in rig.said() and not spoken_failures(rig)

"""H4: the ear first (it needs ``fast_text`` = "on" and ``local_ear`` = "act"; rule 2 has no key of its own since f84a05a9). No network, no sleep: the real NativeMediaSocket, ShadowEar and controller on the
injected clock; only the speech detector, the recognizer's worker, the cloud's events and the job's stream are scripted.

The case is the owner's call of 4 Nov 20:34 (.superpowers/sdd/wave2/owner-call-2034-timeline.txt): on the phone the cloud's final came ~3 s after the ear's (59.0/56.4, 150.4/147.1, 244.8/241.7). A plain
reference the base answers does not wait for it (rule 1), and neither does a question in a strong form the job prepared on the ear has already answered (rule 2). The cloud's final then only says whether
the ear heard right. Neighbours are here too, never a rule for one phrase. What this proves is the logic: nothing here is a measurement of a call.
"""
import logging

import pytest

import helpers_s6_state as S
from echo_sync import fast_text as FT
from echo_sync import reference_kb
from echo_sync.controlled_media import EAR_FIRST_BIND_SECONDS
from echo_sync.settings import resolve
from test_h1_fast_text import settled
from test_h3_tempo import ASKED, GRID, HEAD, PORTION, TICK, WAIT_OF_H3, call, cloud_of, into_speech, the_whole_call       # noqa: F401 - call is the fixture

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

EAR_17 = 'семнадцатая статья налогового кодекса'
EAR_21 = 'двадцать первая статья налогового кодекса'
FINAL_21 = 'А с двадцать первой статье Налогового кодекса'
HEAD_21 = 'Статья 21 Налогового кодекса — права налогоплательщиков,'
EAR_QUESTION = 'так в каком году было крещение руси'
FINAL_QUESTION = 'Так, в каком году было крещение Руси'
ANSWER = 'Крещение Руси произошло в 988 году.'
SILENCE = 0.9                                   # rule 2: the ear's silence
INERTIA = 'Что такое инерция?'


def speaks(rig, text, *, speech=3.1, lag=0.15, turn=None, announced=None, partial=''):
    """One utterance: the detector's start, the cloud's ``turn`` announced ``announced`` seconds after it (before the end of the speech: the call's own order), the end, ``lag`` seconds later the recognizer's
    text and the tick that takes it. Returns when the speech ended."""
    uid = rig.onset()
    if turn and announced is not None:
        rig.pump(announced)
        rig.w.feed(S.turn_created(turn, 'user', partial))
        rig.pump(max(0.0, speech - announced))
    else:
        rig.pump(speech)
    ended = rig.offset()
    rig.pump(lag)
    rig.worker.heard(uid, text)
    rig.pump(TICK)
    return ended


def final(rig, turn, text, after=0.5):
    rig.w.feed(S.turn_done(turn, 'user', text))
    rig.pump(after)


def history(rig):
    return [entry for entry in rig.c.state()['history'] if isinstance(entry, dict)]


def decisions(caplog, word):
    return [record.getMessage() for record in caplog.records if word in record.getMessage()]


def slow(rig):
    """A cue that stays in flight: the world's 200 ms of PCM in place of the half second of voice the rig gives, played by frames in virtual time."""
    rig.w.wire.synthesize = rig.w._synthesize


# =====================================================================================================================================
# the settings
# =====================================================================================================================================

def test_rule_two_has_no_setting_of_its_own_and_it_needs_the_channel_and_an_acting_ear(call):
    """f84a05a9: ``ear_release`` is the rule of the call, no key (a profile that still says it is told it is unknown and nothing changes). It still needs a brain and an ear that acts: a shadow ear opens nothing, no channel no job."""
    assert 'ear_release' not in resolve({}) and 'ear_release' not in resolve({'local_ear': 'act', 'fast_text': 'on', 'ear_release': 'on'})
    once = resolve({'local_ear': 'act', 'fast_text': 'on'})
    assert resolve(once) == once
    rig = call(fast_text='on', ear='shadow')
    speaks(rig, EAR_QUESTION, speech=1.0, turn='u1', announced=0.5, partial='Так в каком году было крещение Руси')
    rig.pump(2.0)
    assert rig.said() == [] and rig.c.question_id is None, 'a shadow never acts'
    final(rig, 'u1', FINAL_QUESTION)
    rig.job_says(len(rig.fake.runs) - 1, ANSWER)
    rig.job_ends(len(rig.fake.runs) - 1)
    assert any('988' in text for text in rig.said())


def test_with_the_channel_off_the_ear_opens_nothing(call):
    rig = call()
    speaks(rig, EAR_17, turn='u1', announced=3.1)
    assert rig.said() == [] and rig.c.question_id is None
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD]


def test_with_the_channel_off_the_base_reads_as_it_did():
    """«с» reads only behind the channel: with it off not one line of behaviour changes."""
    assert reference_kb.lookup(FINAL_21, prepositions=True) is not None
    assert reference_kb.lookup(FINAL_21) is None


def test_with_the_channel_off_a_final_with_the_preposition_goes_as_it_did(call):
    rig = call()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', FINAL_21)
    assert rig.c._reference(FINAL_21) is None


def test_a_shadow_ear_opens_nothing(call):
    rig = call(fast_text='on', ear='shadow')
    speaks(rig, EAR_17, turn='u1', announced=3.1)
    assert rig.said() == [] and rig.c.question_id is None
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD]


# =====================================================================================================================================
# rule 1: a plain reference the base answers
# =====================================================================================================================================

def test_the_article_of_the_call_is_cued_from_the_ears_text_on_the_open_turn(call):
    """53.07-56.22 the speech, 56.2 the cloud's turn, 56.4 the ear's text, 59.0 the final. In the call the cue came at 59.4."""
    rig = call(fast_text='on')
    ended = speaks(rig, EAR_17, turn='u1', announced=3.1, speech=3.15)
    assert rig.said() == [HEAD], 'not at the final'
    assert rig.cues()[0].t - ended <= 0.15 + 2 * TICK + 0.01
    assert rig.c.question_id == 'u1' and rig.c.user_boundaries['u1'] == 'ear_first', 'OWNER_DECISION 26.11-3: the cloud has no word of the turn yet: the ear\'s question opens on that turn at once (``_ear_first_turn``), the final then only says whether it heard right'


def test_the_final_that_comes_later_opens_nothing_twice(call):
    rig = call(fast_text='on', **WAIT_OF_H3)
    speaks(rig, EAR_17, turn='u1', announced=3.1, speech=3.15)
    revision, epoch = rig.c.state()['revision'], rig.c.epoch
    rig.pump(2.5)
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD] and not rig.cues()[0].cleared
    assert (rig.c.state()['revision'], rig.c.epoch) == (revision, epoch), 'the answer is the one that was opened'


@pytest.mark.parametrize('said', ['Семнадцатая статья Налогового кодекса', 'Так, семнадцатая статья Налогового кодекса', 'Статья 17 Налогового кодекса', '17-я статья НК',
                                  'Ну, статья семнадцать НК, пожалуйста'])
def test_any_final_of_the_same_reference_changes_nothing(call, said):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=3.1, speech=3.15)
    final(rig, 'u1', said)
    assert rig.said() == [HEAD] and not rig.cues()[0].cleared


@pytest.mark.parametrize('ear, said, answer', [
    (EAR_21, FINAL_21, HEAD_21),
    ('статья двадцать один налогового кодекса', 'Статья 21 НК', HEAD_21),
    ('статья сто сорок трудового кодекса', 'Статья 140 Трудового кодекса', 'Статья 140 Трудового кодекса —'),
    ('двадцать первая статья гражданского кодекса', 'Двадцать первая статья Гражданского кодекса', 'Статья 21 Гражданского кодекса —'),
    ('что за шестьдесят второй счёт', 'Что за 62 счёт?', 'Счёт 62 —'),
    ('семьдесят первый счёт', '71 счёт', 'Счёт 71 —'),
], ids=lambda value: value.replace(' ', '_'))
def test_its_neighbours_of_the_base(call, ear, said, answer):
    rig = call(fast_text='on')
    speaks(rig, ear, turn='u1', announced=1.0, speech=1.5)
    assert len(rig.said()) == 1 and rig.said()[0].startswith(answer), rig.said()
    final(rig, 'u1', said)
    assert len(rig.said()) == 1 and not rig.cues()[0].cleared


@pytest.mark.parametrize('heard', ['а с двадцать первой статье налогового кодекса', 'с двадцать первой статьи налогового кодекса', 'со статьи двадцать один налогового кодекса'],
                         ids=lambda value: value.replace(' ', '_'))
def test_a_reference_the_classifier_has_no_form_for_is_the_bases_all_the_same(call, heard):
    """244.8 of the call: «А с двадцать первой статье …» is no question for the classifier, and the base answers it: a candidate the reference base admits, here from the ear."""
    rig = call(fast_text='on')
    speaks(rig, heard, turn='u1', announced=1.0, speech=1.5)
    assert rig.said() == [HEAD_21]
    final(rig, 'u1', FINAL_21)
    assert rig.said() == [HEAD_21] and not rig.cues()[0].cleared


def test_the_two_pieces_of_241_are_one_reference(call):
    """238.1-239.16 «с», 239.36-241.45 «двадцать первая …», 241.4 the cloud's turn, 244.8 its final; the cue came at 253.0 in the call, from memory."""
    rig = call(fast_text='on', **WAIT_OF_H3)
    speaks(rig, 'с', speech=1.0)
    rig.pump(0.05)
    ended = speaks(rig, EAR_21, speech=2.1, turn='u1', announced=2.0)
    assert rig.said() == [HEAD_21] and rig.cues()[0].t - ended <= 0.35
    rig.pump(3.0)
    final(rig, 'u1', FINAL_21)
    assert rig.said() == [HEAD_21]


def test_a_reference_cut_by_a_breath_is_read_joined(call):
    rig = call(fast_text='on')
    speaks(rig, 'семнадцатая статья', speech=0.8)
    assert rig.said() == []
    rig.pump(0.1)
    speaks(rig, 'налогового кодекса', speech=0.8, turn='u1', announced=0.4)
    assert rig.said() == [HEAD]
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD]


def test_a_number_cut_by_a_breath_is_read_joined_too(call):
    """«первая статья …» alone is article 1: the longest reading comes first."""
    rig = call(fast_text='on')
    speaks(rig, 'двадцать', speech=0.5)
    rig.pump(0.1)
    speaks(rig, 'первая статья налогового кодекса', speech=1.5, turn='u1', announced=1.0)
    assert rig.said() == [HEAD_21]


def test_a_follow_up_takes_its_code_from_the_history(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', ASKED)
    rig.pump(1.0)
    speaks(rig, 'а двадцать седьмая', speech=0.8, turn='u2', announced=0.4)
    assert rig.said()[-1].startswith('Статья 27 Налогового кодекса'), rig.said()
    final(rig, 'u2', 'А двадцать седьмая?')
    assert rig.said()[-1].startswith('Статья 27 Налогового кодекса') and len(rig.said()) == 2


def test_the_turn_not_announced_yet_the_answer_waits_for_it_as_an_ack_does(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, speech=1.5)
    assert rig.said() == [HEAD] and rig.c.question_id is not None, 'OWNER_DECISION 26.11-3: a question only the ear has heard is answered at once; the base answers on the ear alone (``_bank_first``, h28)'
    rig.pump(EAR_FIRST_BIND_SECONDS - 0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(TICK)
    assert rig.said() == [HEAD] and rig.c.ear_first is None, 'the turn the cloud announces later opens nothing twice'
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD]


def test_a_turn_that_does_not_come_in_time_leaves_it_to_the_final(call, caplog):
    rig = call(fast_text='on')
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        speaks(rig, EAR_17, speech=1.5)
        rig.pump(EAR_FIRST_BIND_SECONDS + 3 * TICK)
    assert decisions(caplog, 'ear first=dropped'), 'H6 item 6 moved this test: at the same bound the text of the ear stands in for the final'
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(TICK)
    assert rig.said() == [HEAD]
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD], 'and nothing opens twice'


def test_speech_that_begins_meanwhile_gives_the_wait_up(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, speech=1.5)
    rig.onset()
    rig.pump(0.2)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(TICK)
    assert rig.said() == [HEAD] and rig.c.ear_first is None, 'OWNER_DECISION 26.11-3: answered at once on the ear alone (``_bank_first``, h28) before the new speech began; that speech opens nothing more'


def test_a_reference_said_with_speech_going_on_is_not_decided(call):
    """«Статья 17 Налогового кодекса | а какая там ставка»: the ear's text came, but the speech had already gone on."""
    rig = call(fast_text='on')
    uid = rig.onset()
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.1)
    rig.onset()
    rig.pump(0.1)
    rig.worker.heard(uid, EAR_17)
    rig.pump(TICK)
    assert rig.said() == [] and rig.c.question_id is None


# -- what is no reference, or not said to the base ---------------------------------------------------------------------------------------

@pytest.mark.parametrize('heard', ['двадцать первая статья конституции', 'статья семьдесят тысяч налогового кодекса', 'что сказано в семнадцатой статье налогового кодекса о ставках',
                                   'какая ставка в двадцать первой статье налогового кодекса', 'семнадцатая статья налогового кодекса пример'], ids=lambda value: value.replace(' ', '_'))
def test_what_the_base_does_not_answer_is_not_the_ears(call, heard):
    rig = call(fast_text='on')
    speaks(rig, heard, turn='u1', announced=1.0, speech=1.5)
    assert rig.said() == [] and rig.c.question_id is None


def test_a_try_at_the_portion_stays_a_try(call):
    """«Статья 17 Налогового кодекса —» waits, and the base would answer its words: they are said to the portion."""
    rig = call(fast_text='on')
    rig.first_portion()
    rig.pump(1.0)
    speaks(rig, 'статья семнадцать', speech=0.8, turn='u2', announced=0.4)
    assert rig.c.question_id == 'u1' and rig.said() == [HEAD]


def test_the_repeat_of_the_portion_is_a_repeat(call):
    rig = call(fast_text='on')
    rig.first_portion()
    rig.pump(1.0)
    speaks(rig, 'статья семнадцать налогового кодекса', speech=1.5, turn='u2', announced=0.5)
    assert rig.said() == [HEAD, PORTION] and rig.c.user_boundaries['u2'] == 'local_ear'


def test_the_answer_in_play_is_not_opened_again(call):
    """The next portion waits, and the listener goes back over the reference: nothing new is asked of the base. The cloud's final decides what it always did."""
    rig = call(fast_text='on')
    rig.second_portion()
    rig.pump(1.0)
    speaks(rig, 'статья семнадцать налогового кодекса', speech=1.5, turn='u3', announced=0.5)
    assert rig.c.question_id == 'u1' and rig.said() == [HEAD, PORTION]


def test_said_over_a_cue_it_stays_the_clouds(call):
    rig = call(fast_text='on')
    rig.first_portion()
    rig.c.cue_window = [rig.w.clock.now(), rig.w.clock.now() + 2.0]     # the speech begins before the end of the cue has been heard
    speaks(rig, EAR_21, turn='u2', announced=0.3, speech=0.8)
    assert rig.c.question_id == 'u1' and rig.said() == [HEAD]


def test_a_new_question_replaces_what_is_running(call):
    """A job at work for another question: the reference is a new question, as at a final."""
    rig = call(fast_text='on')
    rig.w.feed(S.turn_created('u1', 'user', 'Что'))
    rig.w.feed(S.turn_done('u1', 'user', INERTIA))
    rig.pump(TICK)
    job = rig.fake.run(0)
    speaks(rig, EAR_17, turn='u2', announced=1.0, speech=1.5)
    assert rig.said() == [HEAD] and job.cancelled.is_set()
    final(rig, 'u2', ASKED)
    assert rig.said() == [HEAD]


def test_the_clouds_reply_to_that_turn_is_nobodys(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', ASKED)
    rig.w.feed(S.turn_created('a1', 'assistant', 'Ну'))
    rig.w.feed(S.turn_done('a1', 'assistant', 'Ну давай такой сначала вопрос.'))
    rig.pump(1.0)
    assert rig.said() == [HEAD]


def test_the_repeat_goes_on_from_the_ears_answer(call):
    """The cue, the listener's repeat, its cloud turn: the answer goes on as any other."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=3.1, speech=3.15)
    rig.pump(1.0)
    final(rig, 'u1', ASKED, after=0.2)
    speaks(rig, 'статья семнадцать налогового кодекса', turn='u2', announced=1.0, speech=1.5)
    assert rig.said() == [HEAD, PORTION]


def test_a_repeat_that_ends_before_the_questions_final(call):
    """The final of the question comes ~3 s late: the ear hears the repeat before it. Its verdict waits for a turn, and the next turn is the repeat's."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=3.1, speech=3.15)
    rig.pump(0.6)
    speaks(rig, 'статья семнадцать налогового кодекса', speech=1.2)
    assert rig.said() == [HEAD], 'nothing is confirmed on the question\'s own turn'
    final(rig, 'u1', ASKED, after=0.1)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(TICK * 2)
    assert rig.said() == [HEAD, PORTION]


def test_the_silence_timer_runs_from_the_end_of_the_ears_cue(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=3.1, speech=3.15)
    ended = rig.ended()
    cue = rig.next_cue(4.5)
    assert cue is not None and cue.text == HEAD and cue.t - ended == pytest.approx(rig.settings['repeat_seconds'], abs=GRID + TICK)


# -- the final disagrees -----------------------------------------------------------------------------------------------------------------

def test_a_final_of_another_article_cuts_the_cue_and_is_a_final_of_its_own(call):
    """The ear heard «семнадцатая», the cloud «двадцать первая»."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=3.1, speech=3.15)
    rig.w.feed(S.turn_done('u1', 'user', 'Двадцать первая статья Налогового кодекса'))
    rig.pump(0.5)
    assert rig.said() == [HEAD, HEAD_21]
    assert rig.c.question_id == 'u1' and rig.c.user_boundaries['u1'] == 'provider_turn_done'


def test_a_cue_still_in_flight_is_cut(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=3.1, speech=3.15)
    sent = len(rig.w.frames)
    rig.w.feed(S.turn_done('u1', 'user', 'Двадцать первая статья Налогового кодекса'))
    assert any(frame.get('type') == 'output_audio_buffer.clear' for _, _, frame in rig.w.frames[sent:])


def test_a_final_that_goes_on_past_the_reference_is_a_final_of_its_own(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    said = 'Семнадцатая статья Налогового кодекса, а какая там ставка налога?'
    rig.w.feed(S.turn_done('u1', 'user', said))
    rig.pump(TICK)
    assert rig.c.question_text.endswith('ставка налога?'), rig.c.question_text
    assert rig.c.user_boundaries['u1:rest'] == 'provider_turn_done', 'Fable 10.11: the question the ear opened stands, the rest is a turn of its own'


def test_a_final_that_is_a_remark_is_the_jobs_to_judge(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Ну ты, конечно, долго думаешь'))
    rig.pump(TICK)
    assert rig.c.candidate is not None and rig.c.question_id is None
    rig.job_says(0, '—')
    rig.job_ends(0)
    assert rig.said() == [HEAD] and rig.c.candidate is None


def test_the_plan_the_overruled_question_took_over_comes_back(call):
    """A plan waited, the ear opened a reference on a misheard word, the cloud's final is a repeat of the portion: the world as if the ear had not acted, and the repeat confirms."""
    rig = call(fast_text='on')
    rig.second_portion()
    plan = rig.c.state()['answer']
    rig.pump(1.0)
    speaks(rig, EAR_21, turn='u3', announced=1.0, speech=1.5)
    assert rig.said() == [HEAD, PORTION, HEAD_21]
    rig.w.feed(S.turn_done('u3', 'user', 'общие условия установления налогов и сборов'))
    rig.pump(0.5)
    state = rig.c.state()
    assert 'условия' in state['answer'], state
    assert not any(entry.get('status') == 'interrupted' and str(entry.get('answer')).startswith('Статья 21') for entry in history(rig)), 'no «продолжай» finds what nobody asked'


# =====================================================================================================================================
# rule 2: a question in a strong form the job has already answered (the owner's rule of fast_text on + an acting ear, no key since f84a05a9)
# =====================================================================================================================================

def question(rig, text=EAR_QUESTION, *, speech=1.0, turn='u1', announced=0.5, partial=None):
    """A strong question, the job prepared on it at work. Returns when the speech ended. The ear opens a question only on the stable piece of the cloud's open turn (E86, no key: the owner's profile),
    so the cloud has its words: three of them when the turn is announced and the rest in a delta, as it hears them. ``partial``: what the cloud holds instead (nothing more is fed)."""
    head, rest = cloud_of(text) if partial is None else (partial, '')
    ended = speaks(rig, text, speech=speech, turn=turn, announced=announced, partial=head)
    rig.pump(TICK * 2)      # two looks at the stable part of the cloud's words (the second witness, 53808581) before the job is judged prepared
    assert rig.fake.runs, 'precondition: the job was prepared on the ear'
    if rest:
        rig.w.feed(S.turn_delta(turn, rest, 1))
    return ended


def test_the_question_opens_on_the_ear_and_the_answer_is_cued_before_the_final(call):
    rig = call(fast_text='on')
    ended = question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u1' and rig.c.user_boundaries['u1'] == 'ear_first'
    assert any('988' in text for text in rig.said()), 'before the final'
    assert rig.cues()[0].t - ended <= SILENCE + 0.6


def test_the_job_is_adopted_and_the_final_opens_nothing_twice(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    said, revision, epoch = rig.said(), rig.c.state()['revision'], rig.c.epoch
    final(rig, 'u1', FINAL_QUESTION)
    assert rig.said() == said and not rig.cues()[0].cleared
    assert (rig.c.state()['revision'], rig.c.epoch) == (revision, epoch) and len(rig.fake.runs) == 1


def test_off_nothing_opens_before_the_final(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(1.0)
    assert rig.said() == [] and rig.c.question_id is None
    final(rig, 'u1', FINAL_QUESTION)
    rig.job_ends(0)
    assert any('988' in text for text in rig.said()) and len(rig.fake.runs) == 1, 'the job prepared on the ear is adopted at the final: H1'


def test_not_before_the_silence_has_lasted(call):
    rig = call(fast_text='on')
    ended = question(rig)
    rig.job_says(0, ANSWER)
    assert rig.c.question_id is None and rig.w.clock.t - ended < SILENCE, 'the job was faster than the silence'
    while rig.w.clock.t - ended < SILENCE + GRID + TICK:      # + one look: the stable piece of the cloud is read twice (E86)
        rig.pump(TICK)
    assert rig.c.question_id == 'u1'
    assert rig.cues()[0].t - ended == pytest.approx(SILENCE, abs=GRID + 2 * TICK)


def test_not_before_the_job_has_given_its_first_sentence(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE + 0.5)
    assert rig.c.question_id is None and rig.said() == []
    rig.job_says(0, 'Крещение Руси произошло')
    assert rig.c.question_id is None, 'half a sentence'
    rig.job_says(0, ' в 988 году.')
    rig.pump(TICK * 3)      # the look that finds the job ready, the look that keeps the cloud's piece, the cue
    assert rig.c.question_id == 'u1' and any('988' in text for text in rig.said())


def test_a_sentence_that_ends_with_the_job_counts(call):
    """«25» with no mark: the job is over, it is whole."""
    rig = call(fast_text='on')
    question(rig, 'сколько будет пять в квадрате')
    rig.pump(SILENCE)
    rig.job_says(0, '25')
    assert rig.c.question_id is None
    rig.job_ends(0)
    assert rig.c.question_id == 'u1' and rig.said()


@pytest.mark.parametrize('mark', ['—', ' — ', '–'])
def test_the_prepared_job_says_nothing_to_answer_nothing_opens(call, mark):
    """The remarks of the call in the form of a question («какой ещё раз вопрос», «это зачем такие ответы»): the job says «—». That is a verdict only once the final adopts it (H2 rule 9)."""
    rig = call(fast_text='on')
    question(rig, 'да какой ещё раз вопрос', turn='u1')
    rig.pump(SILENCE)
    rig.job_says(0, mark)
    rig.job_ends(0)
    rig.pump(1.0)
    assert rig.said() == [] and rig.c.question_id is None
    final(rig, 'u1', 'Да, какой ещё раз вопрос')
    rig.pump(1.0)
    assert rig.said() == [] and rig.c.question_id is None


def test_a_road_that_ends_with_no_word_is_a_failed_road_and_no_verdict_of_nothing_to_answer(call):
    """The one road: a stream that ends with no word at all (not even the dash) is a road that failed (``ReserveError('empty')``), never the model's «nothing to answer»; the question goes on to the next road and, with none left, back to the cloud, so after its final the question is open."""
    rig = call(fast_text='on')
    question(rig, 'да какой ещё раз вопрос', turn='u1')
    rig.pump(SILENCE)
    rig.job_ends(0)
    rig.pump(1.0)
    assert rig.said() == [] and rig.c.question_id is None
    rig.fake.run(1).finish()      # the next road of the same walk: it ends with no word too
    settled(rig.fast)
    final(rig, 'u1', 'Да, какой ещё раз вопрос')
    rig.pump(1.0)
    assert rig.c.question_id == 'u1'


def test_a_job_that_talks_about_itself_opens_nothing(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, 'Понял тебя, буду реагировать быстрее.')
    rig.pump(TICK * 2)
    assert rig.c.question_id is None and rig.said() == []


@pytest.mark.parametrize('heard, why', [
    ('столица австралии', 'a bare topic'),
    ('пять в квадрате', 'no form'),
    ('у тебя ответы тупо вообще неправильные какие', 'a question word at the end'),
    ('расскажи про инерцию', 'a change of topic'),
    ('является ли земля шаром', 'not one of the forms the brief names'),
], ids=lambda value: value.replace(' ', '_'))
def test_what_has_no_strong_form_waits_for_the_final(call, heard, why):
    rig = call(fast_text='on')
    speaks(rig, heard, speech=1.0, turn='u1', announced=0.5)
    if rig.fake.runs:
        rig.job_says(0, 'Канберра.')
    rig.pump(1.5)
    assert rig.said() == [] and rig.c.question_id is None, why


@pytest.mark.parametrize('heard', ['назови столицу австралии', 'вопрос какая столица австралии', 'скажи какая столица австралии', 'какая столица австралии', 'объясни что такое инерция'],
                         ids=lambda value: value.replace(' ', '_'))
def test_the_strong_forms(call, heard):
    rig = call(fast_text='on')
    question(rig, heard)
    rig.pump(SILENCE)
    rig.job_says(0, 'Столица Австралии — Канберра.')
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u1' and rig.said(), heard


def test_a_question_that_stops_at_a_function_word_is_not_over(call):
    rig = call(fast_text='on')
    question(rig, 'сколько будет пять умножить на')
    rig.pump(SILENCE)
    rig.job_says(0, 'Неполный вопрос.')
    rig.pump(1.0)
    assert rig.c.question_id is None and rig.said() == []


def test_a_question_the_lookup_takes_has_no_job_and_waits_for_the_final(call):
    rig = call(fast_text='on')
    speaks(rig, 'какая сейчас ставка ндс в россии', speech=1.0, turn='u1', announced=0.5)
    rig.pump(1.5)
    assert rig.fake.runs == [] and rig.c.question_id is None


# -- what the cloud has so far ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('heard, partial, agrees', [
    ('в каком году было крещение руси', '', True),
    ('в каком году было крещение руси', 'В каком', True),
    ('в каком году было крещение руси', 'В каком го', True),
    ('в каком году было крещение руси', 'В каком году было кре', True),
    ('в каком году было крещение руси', 'В каком году было крещение Руси', True),
    ('в каком году было крещение руси', 'Кака', True),
    ('в каком году было крещение руси', 'В каком городе было', False),
    ('в каком году было крещение руси', 'Какая столица Австралии', False),
    ('в каком году было крещение руси', 'Когда родился Пушкин и', False),
    ('сколько будет двадцать пять на два', 'Сколько будет 25 на', True),
    ('сколько будет двадцать пять на два', 'Сколько будет 35 на', False),
    ('какая столица австралии', 'Какая столица Австралии, а ещё Новой Зеландии', False),
], ids=lambda value: str(value).replace(' ', '_'))
def test_the_partial_is_compared_on_what_it_has(heard, partial, agrees):
    assert FT.same_start(heard, partial) is agrees


def test_a_final_that_is_a_head_of_the_utterance_does_not_contradict_it():
    assert FT.same_start('в каком году было крещение руси', 'В каком году', open_end=False) is True
    assert FT.same_start('в каком году было крещение руси', 'В каком городе', open_end=False) is False
    assert FT.same_start('какая столица австралии', 'Ага', open_end=False) is False


def test_a_partial_that_agrees_lets_it_open(call):
    rig = call(fast_text='on')
    question(rig, partial='Так, в каком')
    rig.w.feed(S.turn_delta('u1', ' году', 1))
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u1'


def test_a_partial_that_disagrees_leaves_it_to_the_final(call, caplog):
    rig = call(fast_text='on')
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        question(rig, partial='Какая столица Австралии')
        rig.pump(SILENCE)
        rig.job_says(0, ANSWER)
        rig.pump(TICK * 2)
    assert rig.c.question_id is None and rig.said() == [] and decisions(caplog, 'ear first=dropped reason=cloud_disagrees')
    final(rig, 'u1', 'Какая столица Австралии?')
    assert rig.c.question_id == 'u1'


def test_no_turn_yet_the_question_waits_for_it(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_QUESTION, speech=1.0)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(0.5)
    assert rig.c.question_id is None
    rig.w.feed(S.turn_created('u1', 'user', 'Так, в каком году было крещение Руси'))
    rig.pump(0.5)      # the turn comes with its words: the first look at them is the one that finds the ear's job ready, the stable piece is what two looks later keep (E86)
    assert rig.c.question_id == 'u1' and rig.said()


def test_speech_in_the_silence_gives_it_up(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(0.3)
    rig.onset()
    rig.job_says(0, ANSWER)
    rig.pump(1.0)
    assert rig.c.question_id is None and rig.c.ear_first is None


def test_a_final_before_the_silence_is_the_final(call):
    rig = call(fast_text='on')
    question(rig)
    final(rig, 'u1', FINAL_QUESTION, after=TICK)
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    rig.pump(SILENCE)
    assert any('988' in text for text in rig.said()) and rig.c.user_boundaries['u1'] == 'provider_turn_done' and rig.c.ear_first is None


# -- the final says otherwise -------------------------------------------------------------------------------------------------------------

def test_the_final_of_another_question_cuts_the_cue_and_is_asked(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(TICK * 3)      # the look that finds the job ready, the look that keeps the cloud's piece, the cue
    assert rig.said()
    sent = len(rig.w.frames)
    final(rig, 'u1', 'В каком городе было крещение Руси', after=TICK * 2)
    assert any(frame.get('type') == 'output_audio_buffer.clear' for _, _, frame in rig.w.frames[sent:]), 'the cue is cut'
    assert rig.c.question_id == 'u1' and len(rig.fake.runs) == 2 and rig.fake.run(1).question.endswith('В каком городе было крещение Руси'), rig.fake.run(1).question


def test_a_final_with_nothing_asked_is_the_jobs_to_judge(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(TICK * 3)      # the look that finds the job ready, the look that keeps the cloud's piece, the cue
    said = rig.said()
    final(rig, 'u1', 'Ну ты, конечно, долго думаешь', after=TICK * 2)
    assert rig.c.candidate is not None and rig.c.question_id is None
    rig.job_says(1, '—')
    rig.job_ends(1)
    assert rig.said() == said and rig.c.candidate is None


def test_a_job_still_at_work_is_stopped_with_it(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER + ' Это сделал')
    rig.pump(TICK * 2)
    job = rig.fake.run(0)
    final(rig, 'u1', 'Какая столица Австралии?', after=TICK * 2)
    assert job.cancelled.is_set() and len(rig.fake.runs) == 2


def test_the_plan_that_gave_way_comes_back_when_the_final_was_a_repeat(call):
    rig = call(fast_text='on')
    rig.second_portion()
    plan = rig.c.state()['answer']
    rig.pump(1.0)
    question(rig, turn='u3')
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u3'
    final(rig, 'u3', 'общие условия установления налогов и сборов')
    state = rig.c.state()
    assert state['answer'] == plan or state['completed'], state


# -- what happens after it opened ---------------------------------------------------------------------------------------------------------

def test_a_job_that_fails_after_it_opened_hands_the_question_back(call):
    rig = call(fast_text='on')
    question(rig, 'какая столица австралии')
    rig.pump(SILENCE)
    rig.job_says(0, 'Столица Австралии')
    rig.c.prepared_job = lambda text: ('Столица Австралии — Канберра.', False)      # the sentence was whole when it opened; the stream then breaks with nothing published
    rig.pump(TICK * 4)
    assert rig.c.question_id == 'u1'
    rig.fake.run(0).fail()
    settled(rig.fast)
    rig.pump(TICK * 2)
    rig.fake.run(1).fail()                      # H5 item 7: one more job first (it walks the roads: the reserve first, the first road rests and is asked last)
    settled(rig.fast)
    rig.fake.run(2).fail()
    settled(rig.fast)
    rig.pump(TICK * 2)
    final(rig, 'u1', 'Какая столица Австралии?', after=TICK)
    rig.w.feed(S.turn_created('a1', 'assistant', 'Столица'))
    rig.w.feed(S.turn_done('a1', 'assistant', 'Столица Австралии — Канберра.'))
    rig.pump(TICK * 2)
    assert any('Канберра' in text for text in rig.said()), rig.said()


def test_the_clouds_turns_are_set_aside_as_at_a_final(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    said = rig.said()
    final(rig, 'u1', FINAL_QUESTION, after=TICK)
    rig.w.feed(S.turn_created('a1', 'assistant', 'Тысяча'))
    rig.w.feed(S.turn_done('a1', 'assistant', 'Тысяча девятьсот восемьдесят восьмой.'))
    rig.pump(1.0)
    assert rig.said() == said


def test_a_plan_that_waited_is_kept_as_at_a_final(call):
    rig = call(fast_text='on')
    rig.second_portion()
    rig.pump(1.0)
    question(rig, turn='u3')
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.suspended is not None and len(rig.fake.runs) == 1, 'and the job prepared with that plan in play is adopted'


def test_a_question_cut_by_a_breath_is_prepared_and_opened_joined(call):
    """«в каком году» | «было крещение руси»: the job prepared on the first piece is half a question, the joined text gets its own."""
    rig = call(fast_text='on')
    speaks(rig, 'в каком году', speech=0.6, turn='u1', announced=0.3, partial='В каком году')
    rig.pump(0.1)
    speaks(rig, 'было крещение руси', speech=0.7)
    rig.w.feed(S.turn_delta('u1', ' было крещение Руси', 1))      # the cloud's one turn holds both breaths: its words are the stable piece the joined text opens on
    assert len(rig.fake.runs) == 2 and rig.fake.run(1).question == 'в каком году было крещение руси', [run.question for run in rig.fake.runs]
    assert rig.fake.run(0).cancelled.is_set()
    rig.pump(SILENCE)
    rig.job_says(1, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u1' and rig.said()
    final(rig, 'u1', 'В каком году было крещение Руси')
    assert len(rig.fake.runs) == 2 and not rig.cues()[0].cleared


# -- the cloud's turn holds more than this utterance: 143.7-150.4 of the call ----------------------------------------------------------------

FINAL_150 = 'Двадцать пять. Хорошо, считаем быстро. Так, в каком году было крещение Руси'


def before_150(rig):
    """137.5 of the call: «Двадцать пять.» has been said; the listener repeats it, says a remark, and asks. One turn of the cloud from 143.7 to 150.4."""
    rig.asks('u1', 'Сколько будет пять в квадрате?', 0, '25')
    rig.pump(1.0)
    first = rig.onset()
    rig.pump(1.5)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(first, 'двадцать пять')
    rig.pump(0.2)
    second = rig.onset()                                                # 142.3: 0.2 s after the text, and the ear's ACK is dropped, as in the log
    rig.pump(1.4)
    rig.w.feed(S.turn_created('u2', 'user', ''))                        # 143.7
    rig.w.feed(S.turn_delta('u2', 'Двадцать', 1))
    rig.pump(2.0)
    rig.offset()
    rig.pump(0.2)
    rig.worker.heard(second, 'хорошо считаем быстро')
    rig.w.feed(S.turn_delta('u2', ' пять. Хорошо,', 2))
    rig.pump(TICK)


def test_the_turn_that_holds_what_was_said_before_the_question(call):
    """The question at 147.1 is a piece of a turn announced for what came before it. Its partial agrees with what the ear heard of that turn."""
    rig = call(fast_text='on')
    before_150(rig)
    said = len(rig.said())
    third = rig.onset()
    rig.pump(1.0)
    ended = rig.offset()
    rig.pump(0.15)
    rig.worker.heard(third, EAR_QUESTION)
    rig.pump(1.2)
    rig.job_says(1, '988 году.')
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u2' and any('988' in text for text in rig.said()[said:]), 'not at 150.4'
    assert rig.cues()[-1].t - ended <= 1.2 + SILENCE
    cues = rig.said()
    final(rig, 'u2', FINAL_150)
    assert rig.said() == cues and not rig.cues()[-1].cleared and len(rig.fake.runs) == 2


def test_a_turn_that_holds_something_else_is_left_to_the_final(call):
    rig = call(fast_text='on')
    before_150(rig)
    rig.w.feed(S.turn_delta('u2', ' а что там у нас с погодой', 3))
    third = rig.onset()
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(third, EAR_QUESTION)
    rig.pump(1.2)
    rig.job_says(1, '988 году.')
    rig.pump(TICK * 2)
    assert rig.c.question_id != 'u2'


def test_a_question_after_a_confirmation_the_ear_took(call):
    """The ear took the turn with the repeat, and the question comes in the same turn of the cloud: it opens there too, and the final does not open it again."""
    rig = call(fast_text='on')
    rig.asks('u1', 'Сколько будет пять в квадрате?', 0, '25')
    rig.pump(1.0)
    speaks(rig, 'двадцать пять', speech=1.5, turn='u2', announced=1.0)
    rig.pump(0.5)
    assert 'u2' in rig.c.seen and rig.c.state()['completed'], 'precondition: the repeat confirmed the last portion'
    rig.w.feed(S.turn_delta('u2', 'Двадцать пять.', 1))
    said = len(rig.said())
    rig.pump(0.3)
    third = rig.onset()
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(third, EAR_QUESTION)
    rig.pump(SILENCE)
    rig.job_says(1, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u2' and any('988' in text for text in rig.said()[said:])
    cues = rig.said()
    final(rig, 'u2', 'Двадцать пять. Так, в каком году было крещение Руси')
    assert rig.said() == cues and len(rig.fake.runs) == 2


# =====================================================================================================================================
# the cloud cut the utterance, the ear fails
# =====================================================================================================================================

def test_the_cloud_cuts_the_utterance_in_two_turns(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Семнадцатая статья'))
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.w.feed(S.turn_done('u2', 'user', 'Налогового кодекса'))
    rig.pump(0.5)
    assert rig.said() == [HEAD] and not rig.cues()[0].cleared


def test_a_fault_of_this_code_turns_the_ear_off_and_the_final_decides(call, monkeypatch):
    rig = call(fast_text='on')
    good = rig.c._reference
    monkeypatch.setattr(rig.c, '_reference', lambda text: 1 / 0)
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    assert rig.c.ear_off is True and rig.said() == []
    monkeypatch.setattr(rig.c, '_reference', good)
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD]


# =====================================================================================================================================
# the base: «с», «со»
# =====================================================================================================================================

@pytest.mark.parametrize('said, starts', [
    (FINAL_21, 'Статья 21 Налогового кодекса'),
    ('Со статьи 21 Налогового кодекса', 'Статья 21 Налогового кодекса'),
    ('С двадцать первая статья налогового кодекса', 'Статья 21 Налогового кодекса'),
    ('Со счётом 71', 'Счёт 71'),
], ids=lambda value: value.replace(' ', '_'))
def test_the_prepositions_stand_around_a_reference(said, starts):
    assert (reference_kb.lookup(said, prepositions=True) or '').startswith(starts)


@pytest.mark.parametrize('said', ['Статья 21 Налогового кодекса с комментариями', 'С какого года действует статья 21 Налогового кодекса', 'С 1 января статья 21 Налогового кодекса',
                                  'Сколько статей с 21 по 30 в Налоговом кодексе'], ids=lambda value: value.replace(' ', '_'))
def test_they_do_not_let_more_in(said):
    assert reference_kb.lookup(said, prepositions=True) is None


# =====================================================================================================================================
# the whole call, every utterance of the ear at the time its log gives
# =====================================================================================================================================

def at(cues, word):
    return [when for when, text, _ in cues if word in text]


def test_the_whole_call_rule_one(call):
    rig = call(fast_text='on')
    cues = the_whole_call(rig)
    assert at(cues, 'Статья 17')[0] <= 56.4 + 2 * TICK + 0.01, cues
    assert at(cues, 'Статья 21')[0] <= 242.5, cues
    assert into_speech(cues) == []


def test_the_whole_call_rule_two(call):
    rig = call(fast_text='on')
    cues = the_whole_call(rig)
    assert 148.0 <= at(cues, '988')[0] <= 149.0, cues
    assert into_speech(cues) == []
    said = [text for _, text, _ in cues]
    assert not any(word in text for text in said for word in ('Понял', 'реагировать', 'ещё вопрос', 'разобрать', 'наконец')), 'no meta tails, no «Ну наконец-то.»'


@pytest.mark.parametrize('late', [0.2, 0.6, 2.0, 3.5])
def test_the_whole_call_with_the_job_late(call, late):
    rig = call(fast_text='on')
    cues = the_whole_call(rig, late=late)
    assert into_speech(cues) == [] and at(cues, '988')


@pytest.mark.parametrize('fail', [(1,), (3,), (5,)], ids=lambda value: f'job{value[0]}')
def test_the_whole_call_with_a_job_failing(call, fail):
    rig = call(fast_text='on')
    cues = the_whole_call(rig, fail=fail)
    assert into_speech(cues) == []


def test_the_whole_call_says_the_same_things_as_without_rule_two(call):
    """Rule 2 moves answers in time, it changes none of them."""
    def told(rig):
        said = [text for _, text, _ in the_whole_call(rig)]
        return [text for n, text in enumerate(said) if not n or said[n - 1] != text]    # earlier, an automatic repeat may fit in before the listener speaks
    plain = call(fast_text='on')
    plain.c.prepared_job = None      # without rule two: ``fast_text.for_call`` gives the controller the look at the job prepared on the ear's text, and nothing else makes rule 2 act (f84a05a9: no key)
    assert told(call(fast_text='on')) == told(plain)


# =====================================================================================================================================
# what rereading the code found
# =====================================================================================================================================

def test_what_was_said_after_the_question_opened_is_no_agreement(call):
    """The ear opened the reference; the listener went on, in a piece of its own and in the same turn of the cloud. The final is more than the ear opened on: it is judged."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.pump(0.3)
    speaks(rig, 'а какая там ставка налога', speech=1.0)
    rig.w.feed(S.turn_done('u1', 'user', 'Семнадцатая статья Налогового кодекса, а какая там ставка налога?'))
    rig.pump(TICK)
    assert rig.c.question_text.endswith('ставка налога?'), rig.c.question_text


@pytest.mark.parametrize('rest', ['Налогового кодекса', 'Статья семнадцать', 'Семнадцатая статья Налогового кодекса'])
def test_a_later_turn_that_says_what_was_opened_opens_nothing(call, rest):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    revision = rig.c.state()['revision']
    rig.w.feed(S.turn_done('u1', 'user', 'Семнадцатая статья'))
    rig.w.feed(S.turn_created('u2', 'user', ''))
    final(rig, 'u2', rest)
    assert rig.said() == [HEAD] and rig.c.question_id == 'u1' and rig.c.state()['revision'] == revision


def test_the_question_of_a_turn_cut_by_the_cloud_opens_nothing_twice(call):
    """The ear opened on the turn that holds what came before; the cloud closes that one, and the question is a turn of its own."""
    rig = call(fast_text='on')
    before_150(rig)
    third = rig.onset()
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(third, EAR_QUESTION)
    rig.pump(1.2)
    rig.job_says(1, '988 году.')
    rig.job_ends(1)
    said = rig.said()
    final(rig, 'u2', 'Двадцать пять. Хорошо, считаем быстро.', after=TICK)
    rig.w.feed(S.turn_created('u3', 'user', ''))
    final(rig, 'u3', FINAL_QUESTION)
    assert rig.said() == said and rig.c.question_id == 'u2' and len(rig.fake.runs) == 2


def test_a_piece_that_comes_later_than_a_piece_may_opens_nothing_either(call):
    """The cloud's turn comes when the cue has been said and the window of a piece is over: its words are still what was opened."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Семнадцатая статья'))
    rig.pump(4.5)
    said = rig.said()
    rig.w.feed(S.turn_done('u2', 'user', 'Налогового кодекса'))
    rig.pump(0.5)
    assert rig.said() == said and rig.c.question_id == 'u1' and rig.fake.runs == [], 'no job for a tail of what was opened'


def test_the_same_question_said_again_is_a_final_as_ever(call):
    """Speech began after the ear opened it: this is no piece of what was opened, it is said again."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', ASKED)
    rig.pump(1.0)
    uid = rig.onset()
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(1.5)
    rig.offset()
    rig.w.feed(S.turn_done('u2', 'user', ASKED))
    rig.pump(0.5)
    assert 'u2' in rig.c.user_boundaries and rig.c.user_boundaries['u2'] != 'local_ear_piece'
    rig.worker.heard(uid, EAR_17)


def test_a_turn_with_a_clock_of_its_own_is_opened_all_the_same(call):
    """The cloud's start of speech on the phone stood at the end of the ear's utterance and after it (53.07-56.22 by the ear, 56.2 by the cloud): the words say whose it is, not the clock."""
    rig = call(fast_text='on')
    uid = rig.onset()
    rig.pump(1.5)
    rig.offset()
    rig.w.feed({'type': 'turn.created', 'turn': {'id': 'u1', 'role': 'user', 'transcript': '', 'start_ms': 0, 'end_ms': 200}})
    rig.pump(0.1)
    rig.worker.heard(uid, EAR_17)
    rig.pump(TICK)
    assert rig.said() == [HEAD]


def test_the_cue_is_not_held_by_a_transcript_that_grows(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_QUESTION, speech=1.0, turn='u1', announced=0.5, partial='Так')
    rig.w.feed(S.turn_delta('u1', ', в', 1))
    rig.pump(SILENCE)
    rig.w.feed(S.turn_delta('u1', ' каком', 2))
    rig.job_says(0, ANSWER)
    rig.w.feed(S.turn_delta('u1', ' году', 3))
    rig.pump(0.5)      # two looks at a piece that stands still: the stable piece of the cloud (E86)
    assert rig.c.question_id == 'u1' and rig.said(), 'the transcript growing is the cloud being late, not the listener speaking'
    assert not rig.cues()[0].cleared


def test_an_utterance_begun_before_the_cue_is_no_cue_heard_back(call):
    """241.6 of the replay: a plan the job's decline gave back began while the listener was saying the reference. The ear's text comes during that cue."""
    rig = call(fast_text='on')
    rig.first_portion()
    rig.pump(1.0)
    uid = rig.onset()
    rig.pump(1.0)
    rig.c.cue_window = [rig.w.clock.now(), rig.w.clock.now() + 2.0]     # the cue begins now, with the speech going on
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, EAR_21)
    rig.pump(TICK)
    assert rig.said() == [HEAD, HEAD_21]


def older_plan_behind_25(rig):
    """«Статья 17 …» was taken up, «Сколько будет …» took over: its answer waits, and the older plan stands behind it."""
    rig.second_portion()
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u3', 'user', ''))
    rig.pump(0.3)
    rig.w.feed(S.turn_done('u3', 'user', 'Сколько будет пять в квадрате?'))
    rig.job_says(0, '25')
    rig.job_ends(0)
    assert rig.c.suspended is not None, 'precondition: the older plan stands behind this answer'
    rig.pump(1.0)


def test_a_repeat_said_before_the_question_in_the_same_turn_takes_the_answer_up(call):
    """The final of that turn would have said so: the portion was repeated, so the older plan has no claim over it."""
    rig = call(fast_text='on')
    older_plan_behind_25(rig)
    uid = rig.onset()
    rig.pump(0.8)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(uid, 'двадцать пять')
    rig.pump(0.1)
    rig.onset()                                                         # the ear's ACK waits for the quiet and is dropped
    rig.pump(0.1)
    rig.w.feed(S.turn_created('u4', 'user', ''))
    rig.w.feed(S.turn_delta('u4', 'Двадцать', 1))
    entry = rig.c.state()['entry']
    rig.pump(0.9)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(rig.ear.uid, EAR_QUESTION)
    rig.pump(SILENCE)
    rig.job_says(1, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u4' and rig.c.suspended is not None and rig.c.suspended['entry'] == entry, 'the plan behind it is the answer in play, not the older one'


def test_the_plan_behind_a_question_is_the_newest_with_no_repeat_too(call):
    """H6 item 2 moved this test: one rule: an older plan has no claim over the answer in play, repeated or not."""
    rig = call(fast_text='on')
    older_plan_behind_25(rig)
    older = dict(rig.c.suspended)
    question(rig, turn='u4')
    rig.pump(SILENCE)
    rig.job_says(1, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u4' and rig.c.suspended['entry'] != older['entry']


@pytest.mark.parametrize('heard', ['статья двадцать два налогового кодекса', 'статья девятнадцать налогового кодекса'], ids=lambda value: value.replace(' ', '_'))
def test_a_number_the_ear_misheard_in_a_repeat_is_no_new_article(call, heard):
    """The ear gets numbers wrong (c9-numveto): «Статья 21 …» waits, the listener repeats it, the ear hears 22, and the base has that article too. The classifier reads a try: no wrong article is dictated."""
    rig = call(fast_text='on')
    speaks(rig, EAR_21, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', FINAL_21)
    rig.pump(1.0)
    speaks(rig, heard, turn='u2', announced=1.0, speech=1.5)
    assert rig.said() == [HEAD_21] and rig.c.question_id == 'u1'
    final(rig, 'u2', 'Статья 21 Налогового кодекса')
    assert rig.c.question_id == 'u1' and not any(text.startswith(('Статья 22', 'Статья 19')) for text in rig.said()), rig.said()


def test_the_next_article_after_the_portion_moved_on_is_at_once(call):
    rig = call(fast_text='on')
    rig.second_portion()
    rig.pump(1.0)
    speaks(rig, EAR_21, turn='u3', announced=1.0, speech=1.5)
    assert rig.said() == [HEAD, PORTION, HEAD_21]


# =====================================================================================================================================
# what a mutation check found unpinned
# =====================================================================================================================================

def test_words_at_the_plan_a_question_took_over_are_left_to_the_final(call):
    rig = call(fast_text='on')
    rig.first_portion()
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u2', 'user', 'Что'))
    rig.w.feed(S.turn_done('u2', 'user', INERTIA))
    rig.pump(TICK)
    assert rig.c.question_id == 'u2' and rig.c.suspended is not None, 'precondition: a question took the plan over'
    speaks(rig, 'статья семнадцать налогового кодекса', speech=1.5, turn='u3', announced=1.0)
    assert rig.c.question_id == 'u2' and 'u3' not in rig.c.seen
    final(rig, 'u3', 'Статья 17 Налогового кодекса')
    assert rig.said()[-1] == PORTION, 'G3: the words take the plan back, and confirm it'


def test_a_strong_piece_is_not_read_with_what_came_before_it(call):
    """The job prepared on it stays: what came before may be a remark, and a job on all of it is one more job."""
    rig = call(fast_text='on')
    speaks(rig, 'как дела', speech=0.4)
    rig.pump(0.1)
    speaks(rig, 'в каком году было крещение руси', speech=1.0, turn='u1', announced=0.5)
    assert len(rig.fake.runs) == 1 and rig.fake.run(0).question == 'в каком году было крещение руси', [run.question for run in rig.fake.runs]


def test_a_question_for_the_lookup_cut_by_a_breath_gets_no_job(call):
    rig = call(fast_text='on')
    speaks(rig, 'какая сейчас', speech=0.4, turn='u1', announced=0.2)
    rig.pump(0.1)
    speaks(rig, 'ставка ндс в россии', speech=0.8)
    assert [run.question for run in rig.fake.runs if 'какая' in run.question] == [] and rig.c.ear_first is None, [run.question for run in rig.fake.runs]


def test_a_job_over_with_nothing_to_say_ends_the_wait(call, caplog):
    rig = call(fast_text='on')
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        question(rig, 'да какой ещё раз вопрос')
        rig.pump(SILENCE)
        rig.job_says(0, '—')
        rig.job_ends(0)
    assert rig.c.ear_first is None and decisions(caplog, 'ear first=dropped reason=nothing_to_answer')


def test_an_empty_turn_older_than_the_utterance_is_not_its_own(call, caplog):
    rig = call(fast_text='on')
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(2.0)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        speaks(rig, EAR_17, speech=1.5)
    assert rig.said() == [] and rig.c.question_id is None
    assert not decisions(caplog, 'ear first=dropped'), 'the ear of a question does not ask the age of the cloud empty turn (``_ear_first_turn``): it has no word of the cloud, so it is cloud_behind and waits, not dropped as turn_began_before'


def test_a_turn_the_model_took_on_a_partial_is_left_to_its_final(call):
    """Its delegation opened the question on the partial: the base waits for the final, as it did (the final branch of ``provider``)."""
    rig = call(fast_text='on')
    rig.w.feed(S.turn_created('u1', 'user', 'Семнадцатая статья Налогового кодекса'))
    rig.w.feed({'type': 'delegation.created', 'item': {'id': 'd1', 'user_bidi_turn_id': 'u1', 'target': 'client'}})
    assert rig.c.question_id == 'u1' and rig.c.user_boundaries['u1'] == 'provider_delegation', 'precondition'
    speaks(rig, EAR_17, speech=1.5)
    assert rig.said() == []
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD]


def test_what_was_said_before_the_last_final_is_no_agreement(call, caplog):
    rig = call(fast_text='on')
    question(rig, 'какая столица австралии')
    final(rig, 'u1', 'Какая столица Австралии?', after=TICK)
    rig.job_says(0, 'Канберра.')
    rig.job_ends(0)
    rig.pump(1.0)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        question(rig, turn='u2', partial='Какая столица')
        rig.pump(SILENCE)
        rig.job_says(1, ANSWER)
        rig.pump(TICK * 2)
    assert rig.c.question_id == 'u1' and decisions(caplog, 'ear first=dropped reason=cloud_disagrees')


def test_a_turn_the_clock_counts_in_the_utterance_is_no_word_of_it(call):
    """53.07 the ear hears speech begin, 53.3 the cloud announces the turn of what came before, 55.2 its final, 56.2 this turn, 56.4 the ear's text, 59.0 its final: the older turn is no part of what the final says."""
    rig = call(fast_text='on')
    uid = rig.onset()
    rig.pump(0.2)
    rig.w.feed(S.turn_created('u0', 'user', ''))
    rig.pump(1.9)
    final(rig, 'u0', 'Да, какой ещё раз вопрос', after=TICK)
    rig.job_says(0, '—')
    rig.job_ends(0)
    rig.pump(0.8)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, EAR_17)
    rig.pump(TICK)
    assert rig.said() == [HEAD]
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD] and not rig.cues()[0].cleared and rig.c.user_boundaries['u1'] == 'ear_first'      # OWNER_DECISION 26.11-3: opened on the ear at once, the final confirms it


def test_two_open_turns_of_one_utterance(call):
    """The cloud cut it while the listener spoke: the second turn's final is a tail of what the ear heard, read with the first."""
    rig = call(fast_text='on')
    uid = rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u0', 'user', 'Семнадцатая статья'))
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.3)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, EAR_17)
    rig.pump(TICK)
    assert rig.said() == [HEAD]
    final(rig, 'u0', 'Семнадцатая статья', after=TICK)
    final(rig, 'u1', 'Налогового кодекса')
    assert rig.said() == [HEAD] and not rig.cues()[0].cleared and rig.c.user_boundaries['u1'] == 'ear_first'      # OWNER_DECISION 26.11-3: opened on the ear at once, the final confirms it


def test_a_final_that_is_a_remark_cuts_the_cue_too(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    sent = len(rig.w.frames)
    rig.w.feed(S.turn_done('u1', 'user', 'Ну ты, конечно, долго думаешь'))
    assert any(frame.get('type') == 'output_audio_buffer.clear' for _, _, frame in rig.w.frames[sent:])


def test_the_plan_is_what_waits_after_the_overruled_question(call):
    rig = call(fast_text='on')
    rig.second_portion()
    rig.pump(1.0)
    speaks(rig, EAR_21, turn='u3', announced=1.0, speech=1.5)
    rig.w.feed(S.turn_done('u3', 'user', 'Ну ты, конечно, долго думаешь'))
    rig.pump(TICK)
    assert 'условия' in rig.c.state()['answer'] and rig.c.question_id is None, rig.c.state()


def test_nothing_of_the_overruled_question_stays(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(TICK * 3)      # the look that finds the job ready, the look that keeps the cloud's piece, the cue
    assert rig.c.fast_turn is not None, 'precondition: the job owns the answer'
    final(rig, 'u1', 'Ну ты, конечно, долго думаешь', after=TICK)
    assert rig.c.fast_turn is None and rig.c.fast_asked is None and rig.c.ear_take is None


@pytest.mark.parametrize('said', ['Какая ставка налога на прибыль?', 'Двадцать первая статья Налогового кодекса'], ids=['other-words', 'other-number'])
def test_a_later_turn_that_says_something_else_is_judged(call, said):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', ASKED)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    final(rig, 'u2', said)
    assert rig.c.question_id == 'u2'


def test_what_is_a_part_of_the_utterance():
    heard = 'двадцать первая статья налогового кодекса'
    assert FT.said_within(heard, 'Налогового кодекса') and FT.said_within(heard, 'Статья 21') and FT.said_within(heard, heard)
    assert not FT.said_within(heard, 'Статья 22') and not FT.said_within(heard, 'Трудового кодекса') and not FT.said_within('это правильно', 'это не правильно')


def test_a_remark_before_the_question_in_the_same_turn_takes_nothing_up(call):
    rig = call(fast_text='on')
    older_plan_behind_25(rig)
    older = rig.c.suspended['entry']
    rig.w.feed(S.turn_created('u4', 'user', ''))
    speaks(rig, 'хорошо считаем быстро', speech=0.8)
    rig.w.feed(S.turn_delta('u4', 'Хорошо, считаем', 1))
    rig.pump(0.1)
    third = rig.onset()
    rig.pump(0.9)
    rig.offset()
    rig.pump(0.1)
    rig.worker.heard(third, EAR_QUESTION)
    rig.pump(SILENCE)
    rig.job_says(1, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u4' and rig.c.suspended['entry'] != older, 'H6 item 2 moved this test: the plan behind a question is the newest'


def test_a_piece_the_cloud_announces_late_does_not_cut_the_cue(call):
    """With nobody else to say it is old news (no the ear tempo): the window of a piece of a confirmation is 2 s, and the cloud's start of speech came 3 s late."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', 'Семнадцатая статья', after=2.5)
    sent = len(rig.w.frames)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    assert not any(frame.get('type') == 'output_audio_buffer.clear' for _, _, frame in rig.w.frames[sent:])


def test_a_slow_job_still_opens_while_no_final_has_come(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(3.0)
    rig.job_says(0, ANSWER)
    rig.pump(TICK * 2)
    assert rig.c.question_id == 'u1'


def test_words_that_open_nothing_after_all_leave_the_turn_to_the_final(call, monkeypatch):
    """The take goes through the path of a final, and that path has the last word. Whatever it decides, a turn that opened nothing is still the cloud's."""
    rig = call(fast_text='on')
    real = rig.c._accept_user
    monkeypatch.setattr(rig.c, '_accept_user', lambda turn, **kw: [] if kw.get('boundary') == 'ear_first' else real(turn, **kw))
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    assert rig.said() == [] and 'u1' not in rig.c.seen and 'u1' not in rig.c.user_boundaries
    monkeypatch.setattr(rig.c, '_accept_user', real)
    final(rig, 'u1', ASKED)
    assert rig.said() == [HEAD]


# =====================================================================================================================================
# H4: skeptic. Each of these failed on 6fcaf5f, driven through the production code.
# =====================================================================================================================================

EAR_71 = 'семьдесят первый счёт'
ANSWER_71 = 'Счёт 71'


def cut_since(rig, sent):
    return any(frame.get('type') == 'output_audio_buffer.clear' for _, _, frame in rig.w.frames[sent:])


def results_of(rig, delegation):
    return [frame for kind, frame in rig.w.source.frames if kind == 'E' and delegation in frame.decode('utf-8', 'replace')]


def delegates(rig, uid='u1', did='d1'):
    rig.w.feed({'type': 'delegation.created', 'item': {'id': did, 'user_bidi_turn_id': uid, 'target': 'client'}})
    rig.pump(0.2)


def opened_on_a_turn_of_what_came_before(rig, heard_before='да какой ещё раз вопрос', ear=EAR_17, speech=1.4, declined=False):
    """52.2-59.0 of the call with a shorter reference: the final of the utterance before that one comes while it is said, the turn of the utterance before is announced during the reference (53.07 the
    ear, 53.3 the cloud), with no word of it yet when the ear's text comes. The reference's own turn comes later."""
    rig.w.feed(S.turn_created('u9', 'user', ''))
    uid = rig.onset()
    rig.pump(2.2)
    rig.w.feed(S.turn_done('u9', 'user', 'Ну что, давайте задавайте любой вопрос, собственно, готов'))
    if declined:
        rig.job_says(0, '—')
        rig.job_ends(0)
    rig.pump(0.12)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, heard_before)
    rig.pump(0.45)
    uid = rig.onset()
    rig.pump(0.2)
    rig.w.feed(S.turn_created('u0', 'user', ''))
    rig.pump(speech - 0.2)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, ear)
    rig.pump(TICK)


def test_the_final_of_the_turn_before_is_no_word_on_what_was_opened(call):
    """The ear opened on the empty turn of the utterance before, the only open one. Its final is that utterance's: the first cause of a cue cut and said again at 59.0."""
    rig = call(fast_text='on')
    opened_on_a_turn_of_what_came_before(rig)
    assert rig.said() == [HEAD]
    sent, runs = len(rig.w.frames), len(rig.fake.runs)
    final(rig, 'u0', 'Да, какой ещё раз вопрос', after=1.0)
    assert not cut_since(rig, sent) and rig.c.state()['answer'].startswith(HEAD) and len(rig.fake.runs) == runs
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(2.8)
    final(rig, 'u1', ASKED)
    assert set(rig.said()) == {HEAD} and not cut_since(rig, sent), 'its own turn opens nothing twice'


def test_the_same_with_a_question_opened_on_the_job(call):
    rig = call(fast_text='on')
    opened_on_a_turn_of_what_came_before(rig, ear=EAR_QUESTION, declined=True)
    rig.pump(SILENCE)
    runs = len(rig.fake.runs)
    rig.job_says(runs - 1, ANSWER)
    rig.job_ends(runs - 1)
    assert rig.c.question_id == 'u0' and any('988' in text for text in rig.said())
    sent = len(rig.w.frames)
    final(rig, 'u0', 'Да, какой ещё раз вопрос', after=1.0)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', FINAL_QUESTION)
    assert not cut_since(rig, sent) and len(rig.fake.runs) == runs


@pytest.mark.parametrize('said', ['Ага', 'Угу', 'Да', 'Ну', 'Ммм', 'Хорошо', 'Спасибо'])
def test_a_backchannel_on_that_turn_is_no_word_on_it(call, said):
    """«Ага», 62.9 of the call: the ear's text of it was empty."""
    rig = call(fast_text='on')
    opened_on_a_turn_of_what_came_before(rig, heard_before='')
    sent = len(rig.w.frames)
    final(rig, 'u0', said)
    assert not cut_since(rig, sent) and rig.c.question_id == 'u0' and rig.c.state()['answer'].startswith(HEAD)


@pytest.mark.parametrize('said', ['Стоп', 'Повтори', 'Подожди'])
def test_a_command_on_that_turn_is_a_command(call, said):
    rig = call(fast_text='on')
    opened_on_a_turn_of_what_came_before(rig, heard_before='')
    sent = len(rig.w.frames)
    final(rig, 'u0', said)
    assert cut_since(rig, sent), said


@pytest.mark.parametrize('said', ['Разве?', 'Какая ставка налога на прибыль?', 'Ну ты, конечно, долго думаешь'])
def test_what_the_ear_did_not_hear_before_still_overrules(call, said):
    rig = call(fast_text='on')
    opened_on_a_turn_of_what_came_before(rig)
    sent = len(rig.w.frames)
    final(rig, 'u0', said)
    assert cut_since(rig, sent), said


def test_a_final_said_long_ago_is_no_excuse(call):
    """Only the utterances just before it count: what was heard minutes ago is no other turn."""
    rig = call(fast_text='on')
    for n, heard in enumerate(['какая столица австралии', 'ну вот так', 'да вот так', 'ага вот так']):
        speaks(rig, heard, speech=0.4, turn=f'o{n}', announced=0.2)
        rig.w.feed(S.turn_done(f'o{n}', 'user', 'Ага'))
        rig.pump(1.5)
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    assert rig.said()
    sent = len(rig.w.frames)
    final(rig, 'u1', 'Какая столица Австралии?')
    assert cut_since(rig, sent)


def test_what_an_overruling_final_is_judged_on_are_its_own_words(call):
    """A turn the cloud's clock counts in the utterance but that was final before the ear opened has had its verdict."""
    rig = call(fast_text='on')
    uid = rig.onset()
    rig.pump(0.2)
    rig.w.feed(S.turn_created('u0', 'user', ''))
    rig.pump(1.9)
    final(rig, 'u0', 'Да, какой ещё раз вопрос', after=TICK)
    rig.job_says(0, '—')
    rig.job_ends(0)
    rig.pump(0.8)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, EAR_17)
    rig.pump(TICK)
    assert rig.said() == [HEAD]
    final(rig, 'u1', INERTIA, after=TICK * 2)
    assert rig.c.question_text == INERTIA and rig.fake.runs[-1].question.endswith(INERTIA)


def test_a_turn_cut_while_it_was_open_is_still_read_with_its_rest(call):
    rig = call(fast_text='on')
    uid = rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u0', 'user', 'Двадцать первая статья'))
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    rig.pump(0.3)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, EAR_21)
    rig.pump(TICK)
    assert rig.said() == [HEAD_21]
    final(rig, 'u0', 'Двадцать первая статья', after=TICK)
    final(rig, 'u1', 'Трудового кодекса', after=TICK * 2)
    assert rig.said()[-1].startswith('Статья 21 Трудового кодекса'), rig.said()


# -- the repeat lands in the question's own turn: H4 moved the cue before the final (177.4-237.0 of the call: one turn held 2.2 s of silence) -----------

@pytest.mark.parametrize('ear, final_of_both, answer, repeat, heard', [
    ('сколько будет пять умножить на пять', 'Сколько будет пять умножить на пять? Двадцать пять.', '25', 'Двадцать пять', 'двадцать пять'),
    ('так в каком году было крещение руси', 'Так, в каком году было крещение Руси? Девятьсот восемьдесят восьмой год.', '988 год.', None, 'девятьсот восемьдесят восьмой год'),
    ('какая столица австралии', 'Какая столица Австралии? Канберра.', 'Канберра.', 'Канберра', 'канберра'),
], ids=['twenty-five', 'a-year', 'a-word'])
def test_the_repeat_in_the_questions_turn_is_a_repeat(call, ear, final_of_both, answer, repeat, heard):
    rig = call(fast_text='on')
    question(rig, ear)
    rig.pump(SILENCE)
    rig.job_says(0, answer)
    rig.job_ends(0)
    assert rig.c.question_id == 'u1' and rig.said()
    rig.pump(1.6)
    sent = len(rig.w.frames)
    speaks(rig, heard, speech=0.8)
    final(rig, 'u1', final_of_both)
    assert not cut_since(rig, sent) and len(rig.fake.runs) == 1 and rig.c.state()['completed'], rig.c.state()


def test_the_repeat_of_a_reference_in_the_questions_turn(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.pump(2.0)
    speaks(rig, 'статья семнадцать налогового кодекса', speech=1.5)
    sent = len(rig.w.frames)
    final(rig, 'u1', 'Семнадцатая статья Налогового кодекса. Статья семнадцать Налогового кодекса.')
    assert not cut_since(rig, sent) and rig.said() == [HEAD, PORTION], rig.said()


def test_the_repeat_in_a_turn_that_also_holds_what_came_before_the_question(call):
    """143.7-150.4 of the call, and now the repeat of the cue in it too."""
    rig = call(fast_text='on')
    before_150(rig)
    third = rig.onset()
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(third, EAR_QUESTION)
    rig.pump(1.2)
    rig.job_says(1, '988 году.')
    rig.job_ends(1)
    assert rig.c.question_id == 'u2'
    rig.pump(1.5)
    sent = len(rig.w.frames)
    speaks(rig, 'девятьсот восемьдесят восьмом году', speech=0.8)
    final(rig, 'u2', FINAL_150 + ' Девятьсот восемьдесят восьмом году.')
    assert not cut_since(rig, sent) and len(rig.fake.runs) == 2 and rig.c.state()['completed']


@pytest.mark.parametrize('said, heard', [('Стоп.', 'стоп'), ('Повтори.', 'повтори')])
def test_a_command_in_the_questions_turn_is_a_command(call, said, heard):
    rig = call(fast_text='on')
    question(rig, 'какая столица австралии')
    rig.pump(SILENCE)
    rig.job_says(0, 'Столица Австралии — это Канберра, город на юго-востоке страны.')
    rig.job_ends(0)
    rig.pump(0.2)
    speaks(rig, heard, speech=0.3)
    rig.pump(0.8)
    cues = rig.said()
    final(rig, 'u1', f'Какая столица Австралии? {said}', after=TICK * 2)
    assert len(rig.fake.runs) == 1, 'it is not asked again'
    assert rig.c.state().get('paused') if heard == 'стоп' else len(rig.said()) == len(cues) + 1 and rig.said()[-1] == cues[-1]


def test_a_stopped_try_in_the_questions_turn_is_a_try(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.pump(1.0)
    sent = len(rig.w.frames)
    final(rig, 'u1', 'Семнадцатая статья Налогового кодекса. Статья семнадцать', after=TICK)
    assert not cut_since(rig, sent) and rig.c.question_id == 'u1' and rig.c.state()['chunk_index'] == 0 and rig.fake.runs == []


def test_the_head_of_the_questions_turn_may_be_the_same_reference_in_other_words(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.pump(1.0)
    speaks(rig, 'статья семнадцать налогового кодекса', speech=1.5)
    sent = len(rig.w.frames)
    final(rig, 'u1', 'Ну, 17-я статья НК, пожалуйста. Статья семнадцать Налогового кодекса.')
    assert not cut_since(rig, sent) and rig.said() == [HEAD, PORTION], rig.said()


def test_a_new_question_after_the_one_opened_is_still_judged(call):
    rig = call(fast_text='on')
    question(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    rig.pump(1.0)
    final(rig, 'u1', 'Так, в каком году было крещение Руси? А кто тогда правил?', after=TICK * 2)
    assert len(rig.fake.runs) == 2 and rig.fake.run(1).question.endswith('то тогда правил?')      # Fable 10.11: the joining «А» is stripped on the way to the job


# -- what an overruled question leaves behind ----------------------------------------------------------------------------------------------

def overruled(rig, *, said='Ну ты, конечно, долго думаешь', turn='u1'):
    question(rig, turn=turn)
    rig.pump(SILENCE)
    rig.job_says(len(rig.fake.runs) - 1, ANSWER)
    rig.pump(TICK * 2)
    final(rig, turn, said, after=TICK * 2)


def test_what_was_overruled_is_no_answer_in_play_for_the_next_job(call):
    """Nobody asked it: «Твой ответ: …» would be the answer to a question that was never said."""
    rig = call(fast_text='on')
    overruled(rig, said='Какая столица Австралии?')
    assert rig.fake.run(1).question == 'Какая столица Австралии?', rig.fake.run(1).question


def test_nor_an_exchange_of_the_call(call):
    rig = call(fast_text='on')
    rig.asks('u0', INERTIA, 0, 'Инерция — свойство тела.')
    rig.job_ends(0)
    rig.pump(1.0)
    overruled(rig, said='Какая столица Австралии?')
    assert [entry['question'] for entry in rig.c.fast_exchanges()] == [INERTIA]
    assert 'крещение' not in rig.fake.run(2).question


def test_nor_what_a_follow_up_of_the_base_reads(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', ASKED)
    rig.pump(1.0)
    speaks(rig, 'статья двадцать один трудового кодекса', turn='u2', announced=1.0, speech=1.5)
    assert 'Трудового' in rig.said()[-1], 'the ear opened it'
    final(rig, 'u2', 'Ну ты, конечно, долго думаешь', after=TICK * 2)
    rig.job_says(0, '—')
    rig.job_ends(0)
    assert rig.c._reference('а двадцать седьмая').startswith('Статья 27 Налогового кодекса')


@pytest.mark.parametrize('before', ['Что такое инерция?', None], ids=['a-topic-before', 'none'])
def test_nor_the_topic_of_a_follow_up(call, before):
    rig = call(fast_text='on')
    if before:
        rig.asks('u0', before, 0, 'Инерция — свойство тела.')
        rig.job_ends(0)
        rig.pump(1.0)
    overruled(rig)
    rig.job_says(len(rig.fake.runs) - 1, '—')
    rig.job_ends(len(rig.fake.runs) - 1)
    rig.w.feed(S.turn_created('u5', 'user', ''))
    final(rig, 'u5', 'А почему?', after=TICK)
    assert 'крещение' not in str(rig.c.lookup_query), rig.c.lookup_query
    assert not before or before in rig.c.lookup_query


@pytest.mark.parametrize('said, job', [('Двадцать первая статья Налогового кодекса', None), ('Какая столица Австралии?', 'Канберра.'), ('Ну ты, конечно, долго думаешь', '—')],
                         ids=['a-reference', 'a-question', 'a-remark'])
def test_the_model_that_asked_for_a_search_on_that_turn_is_answered_all_the_same(call, said, job):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    delegates(rig)
    assert results_of(rig, 'd1') == [], 'precondition: a question that is not final yet'
    final(rig, 'u1', said, after=TICK * 2)
    if job:
        rig.job_says(0, job)
        rig.job_ends(0)
    rig.pump(0.5)
    assert len(results_of(rig, 'd1')) == 1


def test_nor_what_is_in_play_for_the_ear(call):
    """Overruled, then asked for real: the same words are no answer in play."""
    rig = call(fast_text='on')
    speaks(rig, EAR_21, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', 'Ну ты, конечно, долго думаешь', after=TICK * 2)
    rig.job_says(0, '—')
    rig.job_ends(0)
    rig.pump(1.0)
    speaks(rig, EAR_21, turn='u2', announced=1.0, speech=1.5)
    assert rig.said() == [HEAD_21, HEAD_21] and rig.c.question_id == 'u2'


def test_the_rest_of_a_final_that_was_only_a_head_says_what_the_cloud_heard(call):
    """The cloud cuts turns anywhere («Статья 17 Налогового» | «кодекса …», 68.8 of the call). The head agreed; together they name another code."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Семнадцатая статья'))
    rig.pump(0.2)
    sent = len(rig.w.frames)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    final(rig, 'u2', 'Трудового кодекса', after=TICK * 2)
    assert rig.said()[-1].startswith('Статья 17 Трудового кодекса'), rig.said()
    assert rig.c.question_id == 'u2' and cut_since(rig, sent)


def test_a_final_on_another_turn_is_no_head_of_what_comes_next(call):
    """«Ага» on the turn the ear opened on, then the listener's own words: they are read alone."""
    rig = call(fast_text='on')
    opened_on_a_turn_of_what_came_before(rig, heard_before='')
    final(rig, 'u0', 'Ага', after=TICK)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', INERTIA, after=TICK * 2)
    assert rig.c.question_id == 'u1' and rig.c.question_text == INERTIA


def test_a_turn_still_open_is_no_head(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    sent = len(rig.w.frames)
    final(rig, 'u2', 'Ну ты, конечно, долго думаешь', after=TICK * 2)
    assert not cut_since(rig, sent) and rig.c.question_id == 'u1'


def test_a_final_that_said_it_all_leaves_the_next_turn_its_own(call):
    rig = call(fast_text='on', **WAIT_OF_H3)
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', ASKED, after=2.0)
    sent = len(rig.w.frames)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    final(rig, 'u2', 'Трудового кодекса', after=TICK * 2)
    assert rig.said() == [HEAD] and not cut_since(rig, sent)


def test_the_plan_that_comes_back_has_its_timer_back(call):
    """Off the tempo nothing else runs it: a remark left a timer alone, and the opening stopped it. The portion was to be said again as if the ear had not acted."""
    rig = call(fast_text='on')
    rig.second_portion()
    rig.pump(1.0)
    speaks(rig, EAR_21, turn='u3', announced=1.0, speech=1.5)
    assert rig.said() == [HEAD, PORTION, HEAD_21]
    final(rig, 'u3', 'Ну ты, конечно, долго думаешь', after=TICK * 2)
    rig.job_says(0, '—')
    rig.job_ends(0)
    cue = rig.next_cue(rig.settings['repeat_seconds'] + 1.0)
    assert cue is not None and cue.text == PORTION


def test_the_note_that_the_plan_was_left_goes_with_it(call):
    rig = call(fast_text='on')
    rig.second_portion()
    rig.pump(1.0)
    speaks(rig, EAR_21, turn='u3', announced=1.0, speech=1.5)
    assert rig.c.note_due, 'precondition: the model was to be told'
    final(rig, 'u3', 'Ну ты, конечно, долго думаешь', after=TICK * 2)
    rig.job_says(0, '—')
    rig.job_ends(0)
    rig.pump(1.0)
    assert not [frame for _, frame in rig.w.source.frames if 'Служебная заметка'.encode() in frame], 'the plan was not left'


# -- the model's delegation and an answer that came before it -------------------------------------------------------------------------------

@pytest.mark.parametrize('when', ['before_it_opened', 'before_the_final', 'after_the_final'])
def test_the_model_that_asked_for_a_search_is_answered_when_the_job_has_spoken(call, when):
    """DEF-T-B15: the model waits for that result. ``published`` used to mean that the model itself was speaking, so it was not waiting. The job speaks now, and on the ear before the final is in."""
    rig = call(fast_text='on')
    question(rig)
    if when == 'before_it_opened':
        delegates(rig)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    assert rig.c.question_id == 'u1' and rig.said()
    if when == 'before_the_final':
        delegates(rig)
    assert results_of(rig, 'd1') == [], 'not before the final: what was decided on the ear is not the verdict on the question'
    final(rig, 'u1', FINAL_QUESTION)
    if when == 'after_the_final':
        delegates(rig)
    rig.pump(0.3)
    assert len(results_of(rig, 'd1')) == 1


def test_the_same_with_no_ear_in_it(call):
    rig = call(fast_text='on')
    rig.w.feed(S.turn_created('u1', 'user', 'Так'))
    rig.w.feed(S.turn_done('u1', 'user', FINAL_QUESTION))
    rig.job_says(0, ANSWER)
    rig.job_ends(0)
    assert rig.said()
    delegates(rig)
    assert len(results_of(rig, 'd1')) == 1


def test_a_delegation_before_the_job_has_spoken_is_answered_as_it_was(call):
    rig = call(fast_text='on')
    rig.w.feed(S.turn_created('u1', 'user', 'Так'))
    rig.w.feed(S.turn_done('u1', 'user', FINAL_QUESTION))
    assert rig.said() == []
    delegates(rig)
    assert rig.said() == [] and len(results_of(rig, 'd1')) == 1, 'a settled fact: no search, as it was'


@pytest.mark.parametrize('when', ['before_its_final', 'after_its_final'])
def test_a_delegation_on_a_piece_of_what_was_opened(call, when):
    """The cloud cut the utterance: the model answers its last turn, which is no question here. It waits for a result all the same."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.w.feed(S.turn_done('u1', 'user', 'Семнадцатая статья'))
    rig.w.feed(S.turn_created('u2', 'user', ''))
    if when == 'before_its_final':
        delegates(rig, 'u2')
    final(rig, 'u2', 'Налогового кодекса')
    if when == 'after_its_final':
        delegates(rig, 'u2')
    assert len(results_of(rig, 'd1')) == 1 and rig.said() == [HEAD]


# -- the wait of the ear and older finals ----------------------------------------------------------------------------------------------------

def test_the_final_of_what_came_before_does_not_end_the_wait(call, caplog):
    """The repeat, then the question, in one turn up to here: the cloud closes the turn of the repeat while the job works. That head of what the ear heard is not the question's final."""
    rig = call(fast_text='on')
    rig.asks('u1', 'Сколько будет пять в квадрате?', 0, '25')
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    speaks(rig, 'двадцать пять', speech=0.8)
    rig.pump(0.3)
    third = rig.onset()
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(third, EAR_QUESTION)
    rig.pump(TICK)
    final(rig, 'u2', 'Двадцать пять', after=TICK)
    assert rig.c.ear_first is not None
    rig.w.feed(S.turn_created('u3', 'user', ''))
    rig.job_says(1, '988 году.')
    rig.pump(TICK * 6)
    assert rig.c.question_id == 'u3' and any('988' in text for text in rig.said()), 'not at the final of u3'
    said = rig.said()
    final(rig, 'u3', FINAL_QUESTION)
    assert rig.said() == said and len(rig.fake.runs) == 2


def test_a_second_reference_before_the_final_of_the_first(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    rig.pump(1.0)
    speaks(rig, EAR_71, speech=1.5)
    assert len(rig.said()) == 2 and rig.said()[-1].startswith(ANSWER_71), 'OWNER_DECISION 26.11-3: the second reference only the ear has heard is answered at once (``_bank_first``, h28), not at the final of the first'
    final(rig, 'u1', ASKED, after=TICK)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    rig.pump(TICK)
    assert len(rig.said()) == 2 and rig.said()[-1].startswith(ANSWER_71), 'at its announcement, not at its final'
    said = rig.said()
    final(rig, 'u2', '71 счёт')
    assert rig.said() == said and not rig.cues()[-1].cleared


def test_a_final_that_says_the_question_after_what_came_before_ends_the_wait(call):
    rig = call(fast_text='on')
    before_150(rig)
    third = rig.onset()
    rig.pump(1.0)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(third, EAR_QUESTION)
    rig.pump(TICK)
    assert rig.c.ear_first is not None
    final(rig, 'u2', FINAL_150, after=TICK)
    assert rig.c.ear_first is None and rig.c.question_id == 'u2'


def test_a_final_of_these_words_with_less_than_the_ear_heard_ends_the_wait(call):
    rig = call(fast_text='on')
    speaks(rig, 'в каком году было крещение руси вообще', speech=1.0, turn='u1', announced=0.5)
    assert rig.c.ear_first is not None
    final(rig, 'u1', 'В каком году было крещение Руси', after=TICK)
    assert rig.c.ear_first is None and rig.c.question_id == 'u1' and rig.c.user_boundaries['u1'] == 'provider_turn_done'


# -- a piece that says something else -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('said', ['Пять в квадрате', 'Ну ты, конечно, долго думаешь'])
def test_a_turn_taken_for_a_piece_that_says_something_else_is_a_final_of_its_own(call, said):
    """H4 made the window of a piece 4 s. Within it speech the detector missed was taken for a piece, and what it says was lost."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', ASKED, after=2.0)
    rig.w.feed(S.turn_created('u2', 'user', ''))
    assert rig.c.user_boundaries.get('u2') == 'local_ear_piece', 'precondition'
    final(rig, 'u2', said, after=TICK)
    assert rig.c.candidate is not None and rig.fake.run(0).question.endswith(said)


# -- a reference, and a candidate's job that is at work ------------------------------------------------------------------------------------------

@pytest.mark.parametrize('how', ['the-ear', 'the-final'])
def test_a_reference_is_not_read_with_the_remark_before_it(call, how):
    """H2's join of a final with the one the job had not ruled on: «Ну ты долго» + «А с двадцать первой статье …» is no reference, and the base had the answer. Nothing was said at all."""
    rig = call(fast_text='on')
    rig.w.feed(S.turn_created('u0', 'user', ''))
    final(rig, 'u0', 'Ну ты, конечно, долго думаешь', after=TICK)
    job = rig.fake.run(0)
    assert rig.c.candidate and rig.c.candidate.get('job'), 'precondition'
    if how == 'the-ear':
        speaks(rig, 'а с двадцать первой статье налогового кодекса', turn='u1', announced=1.0, speech=1.5)
    else:
        rig.w.feed(S.turn_created('u1', 'user', ''))
        final(rig, 'u1', FINAL_21, after=TICK)
    assert rig.said() == [HEAD_21] and rig.c.question_id == 'u1' and rig.c.candidate is None and job.cancelled.is_set()


def test_the_remark_and_a_question_with_no_form_still_go_to_the_job_joined(call):
    rig = call(fast_text='on')
    rig.w.feed(S.turn_created('u0', 'user', ''))
    final(rig, 'u0', 'Пять в квадрате', after=TICK)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    final(rig, 'u1', 'Ну давай быстрее уже', after=TICK)
    assert rig.c.candidate['text'] == 'Пять умножить на пять Ну давай быстрее уже'


# -- what the ear must not open -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('said', ['а с пятого', 'а с двадцать седьмого', 'и с первого', 'а со второго', 'а с двадцать седьмой', 'а со второй', 'и с третьей', 'а с пятой', 'а с 27'])
@pytest.mark.parametrize('before', ['статья 17 налогового кодекса', '71 счёт'])
def test_a_bare_number_with_a_preposition_is_no_follow_up(said, before):
    """«а с пятого?» is a date: «с», «со» were let in for the reference with its word («А с двадцать первой статье …»)."""
    assert reference_kb.lookup(said, [before], prepositions=True) is None


@pytest.mark.parametrize('said, starts', [('а двадцать седьмая', 'Статья 27'), ('а с двадцать седьмой статьёй', 'Статья 27'), ('со статьёй двадцать семь', 'Статья 27')])
def test_a_follow_up_still_reads(said, starts):
    assert (reference_kb.lookup(said, ['статья 17 налогового кодекса'], prepositions=True) or '').startswith(starts), said


def test_the_ear_does_not_open_a_date(call):
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', ASKED)
    rig.pump(1.0)
    speaks(rig, 'а с пятого', speech=0.6, turn='u2', announced=0.3)
    assert rig.said() == [HEAD] and rig.c.question_id == 'u1'


@pytest.mark.parametrize('heard', ['статья сто двадцать три налогового кодекса', 'статья двести двадцать два налогового кодекса'], ids=lambda value: value.replace(' ', '_'))
def test_the_portion_with_a_reference_in_it_misheard_opens_nothing(call, heard):
    """The neighbour of «Статья 21 —» misheard, where the portion has words before the reference, so that the classifier reads no try. A wrong article would be in the earpiece for 3 s."""
    rig = call(fast_text='on')
    rig.asks('u1', 'Что об этом говорит закон?', 0, 'Об этом говорит статья 122 Налогового кодекса.')
    said = rig.said()
    rig.pump(1.0)
    speaks(rig, heard, turn='u2', announced=1.0, speech=1.5)
    assert rig.said() == said and rig.c.question_id == 'u1'


def test_a_follow_up_in_a_number_alone_is_no_portion_misheard(call):
    """It has no word of the portion to be taken for it."""
    rig = call(fast_text='on')
    speaks(rig, EAR_17, turn='u1', announced=1.0, speech=1.5)
    final(rig, 'u1', ASKED)
    rig.pump(1.0)
    speaks(rig, 'а двадцать семь', speech=0.8, turn='u2', announced=0.4)
    assert rig.said()[-1].startswith('Статья 27 Налогового кодекса'), rig.said()


def test_another_article_of_another_code_is_a_new_question_at_once(call):
    rig = call(fast_text='on')
    rig.asks('u1', 'Что об этом говорит закон?', 0, 'Об этом говорит статья 122 Налогового кодекса.')
    rig.pump(1.0)
    speaks(rig, 'статья сто сорок трудового кодекса', turn='u2', announced=1.0, speech=1.5)
    assert rig.said()[-1].startswith('Статья 140 Трудового кодекса')


# -- the plan a decline gives back and the speech that has just ended -----------------------------------------------------------------------

def test_the_whole_call_gives_no_old_plan_back_into_the_reference(call):
    """239.3 and 241.6 of the replay: «Крещение Руси …» cued in the gaps of «с» | «двадцать первая статья …»: the speech had ended and its text was on its way, 0.25 s. H4's own window."""
    rig = call(fast_text='on')
    cues = the_whole_call(rig)
    assert not [(when, text) for when, text, _ in cues if 238.0 < when < 243.0 and 'Статья 21' not in text], cues
    assert at(cues, 'Статья 21')[0] <= 242.0


def test_a_decline_gives_no_plan_back_over_what_the_ear_is_about_to_open(call):
    rig = call(fast_text='on')
    rig.second_portion()
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u3', 'user', ''))
    final(rig, 'u3', 'Да какой ещё раз вопрос', after=TICK)
    speaks(rig, EAR_71, speech=1.0)
    assert rig.c.ear_first is not None, 'precondition: its turn is not announced yet'
    rig.job_says(0, '—')
    rig.job_ends(0)
    assert rig.said()[-1] == PORTION and len(rig.said()) == 2
    rig.w.feed(S.turn_created('u4', 'user', ''))
    rig.pump(TICK)
    assert len(rig.said()) == 3 and rig.said()[-1].startswith(ANSWER_71)


def test_a_decline_still_gives_the_plan_back_when_the_text_says_nothing_new(call):
    rig = call(fast_text='on')
    rig.second_portion()
    rig.pump(1.0)
    rig.w.feed(S.turn_created('u3', 'user', ''))
    final(rig, 'u3', 'Да какой ещё раз вопрос', after=TICK)
    uid = rig.onset()
    rig.pump(0.4)
    rig.job_says(0, '—')
    rig.job_ends(0)
    rig.offset()
    rig.pump(0.2)
    assert rig.said()[-1] == PORTION and len(rig.said()) == 2, 'nothing while its text is on its way'
    rig.worker.heard(uid, 'ага')
    rig.pump(1.5)                               # H5 item 1: a plan given back is a replay: not within 1.5 s of the ear's last offset
    assert len(rig.said()) == 3 and rig.said()[-1] == PORTION

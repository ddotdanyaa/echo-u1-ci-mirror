"""Registry 5.05b: «Режим «пишу рукой»: ответ диктуется, последние слова порции говорятся». Registry state: ВЫКЛЮЧЕНО (key ``dictation`` = off).
Stands: helpers_s6_state.World (real ControlledMedia + NativeMediaSocket + engine on SQLite, no ear) and test_h3_tempo.Rig (the same plus the real ear and the wire); virtual time, only the boundaries are faked. Input: the owner's turns as the cloud sends them (in Rig also as the ear hears them), ``advance``/``pump`` for silence. Seen: the cues the phone hears and the clock of a cue.
Proved: (1) green: by voice «диктуй медленно» silence after a cough waits for the hand, then repeats (World), and with the ear the portion comes again only AFTER the hand's wait, later than the usual repeat (Rig);
(2) green: «хватит диктовать» gives the silence timer back; (3) green: the last words of the portion, said, give the next portion at once (plain and dictating); (4) strict xfail: the profile default does not wait for the hand; (5) strict xfail: by voice without the ear the portion is never said again; (6) strict xfail: the command that came only as the cloud's final (ear silent) does not wait for the hand, the portion repeats at ~2.5 s. ``dictation`` is never set by the test. Keys of other functions at live values: repeat_rule=on (code: off),
repeat_seconds=2.0 (code: 6.0), fast_text=on. Off-switch of the dummy check (private copy): (1)-(2) ``repeat_rule.dictation_command`` returns None, (3) repeat_rule=off in the live keys; (4) dictation='on' in the profile turns it green; (5)(6) NOT cured by dictation='on' (red with it too, a defect of the command path), cured by one line in the engine."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import helpers_night_memory as M      # noqa: E402
import helpers_s6_state as S      # noqa: E402
from test_h3_tempo import call      # noqa: E402,F401 - call is the fixture

T1, T2 = S.TOPICS[0], S.TOPICS[1]
ASK, P1, P2, P3 = 'Как проходит фотосинтез в листьях растений?', 'Свет попадает на хлорофилл в листьях.', 'Вода распадается на кислород и водород.', 'Углекислый газ превращается в глюкозу.'
LIVE = {'repeat_seconds': 2.0, 'fast_text': 'on'}      # keys of other functions at the server's live values


def world(**profile):
    """A World whose controller gets the profile the way controlled_host gives it (the default profile unless keys are given); the patch is undone before the call."""
    prof, original = M.resolve(profile or None), S.host_kwargs
    S.host_kwargs = lambda: {**original(), 'settings': M.controller_settings(prof), 'repeat_seconds': prof['repeat_seconds'], 'max_auto_repeats': prof['max_auto_repeats']}
    try:
        return S.World()
    finally:
        S.host_kwargs = original


def say(w, uid, text):
    w.feed(S.turn_created(uid, 'user', text.split()[0]))
    w.feed(S.turn_done(uid, 'user', text))


def answered(w, topic, n):
    """The owner asks, the cloud answers in one turn: the first portion is on the phone."""
    say(w, f'q{n}', topic.question)
    w.feed(S.turn_done(f'a{n}', 'assistant', topic.answer))
    assert len(w.cues) == n and w.cues[-1].text in topic.answer, 'the first portion of the answer is spoken'
    return w.cues[-1].text


def rig_of(call):      # the call with the ear: live keys of other functions, ``dictation`` untouched; three portions answered, the first one said
    rig = call(**LIVE)
    rig.c.settings = M.controller_settings(rig.settings)      # as controlled_host gives the controller of the profile
    rig.asks('u1', ASK, 0, f'{P1} {P2} {P3}')
    return rig


def utter(rig, text, n):
    """The owner says ``text``: the ear hears it, then the cloud's final of it."""
    uid = rig.onset()
    rig.pump(0.3)
    rig.w.feed(S.turn_created(f'v{n}', 'user', text.split()[0]))
    rig.pump(0.6)
    rig.offset()
    rig.pump(0.15)
    rig.worker.heard(uid, text)
    rig.pump(0.7)
    rig.w.feed(S.turn_done(f'v{n}', 'user', text + '.'))


def test_said_dictiruy_medlenno_silence_after_a_cough_waits_for_the_hand_and_then_repeats():
    w = world()
    try:
        first = answered(w, T1, 1)
        say(w, 'u2', 'Диктуй медленно')
        say(w, 'u3', 'ну')      # a cough: not a command (test 4 shows it repeats at repeat_seconds when the timer is back)
        w.advance(10)
        assert [c.text for c in w.cues] == [first] and w.synth_calls == [first], 'the command is no question and no cue, no cut-in'
        w.advance(30)
        assert [c.text for c in w.cues] == [first, first], 'after the wait for the hand the portion is said again'
    finally:
        w.close()


def test_said_dictiruy_medlenno_with_the_ear_the_portion_comes_again_only_after_the_hands_wait(call):
    rig = rig_of(call)
    utter(rig, 'Диктуй медленно', 7)
    end = rig.w.clock.t
    rig.pump(6.0)      # the usual silence repeat is ~2.5 s with these keys: here the hand is writing
    assert rig.said() == [P1], 'nothing cuts in while writing'
    cue = rig.next_cue(40.0)      # after the wait for the hand the portion is said again from its start
    assert cue is not None and cue.text == P1 and rig.w.clock.t - end > 10


def test_said_hvatit_diktovat_gives_the_silence_timer_back_for_the_next_question():
    w = world()
    try:
        answered(w, T1, 1)
        say(w, 'u2', 'Диктуй медленно')
        second = answered(w, T2, 2)      # dictating goes on across questions: the hand still writes
        w.advance(7)
        assert len(w.cues) == 2, 'while dictating the portion is not repeated at repeat_seconds'
        say(w, 'u3', 'Хватит диктовать')
        say(w, 'q4', T2.question)      # the same question asked again: the new answer, its first portion
        w.feed(S.turn_done('a4', 'assistant', T2.answer))
        n = len(w.cues)
        w.advance(10)
        assert [c.text for c in w.cues[n - 1:]] == [second, second], 'the timer of speech is back: the portion repeats'
    finally:
        w.close()


@pytest.mark.parametrize('dictating', [False, True], ids=['plain', 'dictating'])
def test_the_last_words_of_the_portion_said_give_the_next_portion_at_once(call, dictating):
    rig = rig_of(call)
    if dictating:
        utter(rig, 'Диктуй медленно', 7)
    utter(rig, 'в листьях', 9)      # only the last words of the portion
    rig.pump(1.2)
    assert rig.said() == [P1, P2], 'the next portion comes at once, once, the portion is not repeated'


@pytest.mark.xfail(strict=True, reason='реестр 5.05b: ВЫКЛЮЧЕНО (dictation=off по умолчанию): таймер тишины профиля по умолчанию не ждёт руку')
def test_the_profile_default_waits_for_the_hand():
    w = world()      # the profile as resolved by the code: dictation is not set by the test
    try:
        first = answered(w, T1, 1)
        w.advance(10)      # past repeat_seconds, well inside the owner's writing time
        assert [c.text for c in w.cues] == [first], 'dictation mode: nothing cuts in while the owner writes'
        w.advance(40)
        assert [c.text for c in w.cues] == [first, first], 'and after the whole wait the portion is said again from its start'
    finally:
        w.close()


@pytest.mark.xfail(strict=True, reason='реестр 5.05b: ВЫКЛЮЧЕНО; после голосового «диктуй медленно» без уха порция не повторяется вовсе (при dictation=on повтор приходит после ожидания руки)')
def test_said_dictiruy_medlenno_without_the_ear_the_portion_still_comes_again_after_the_wait():
    w = world()
    try:
        first = answered(w, T1, 1)
        say(w, 'u2', 'Диктуй медленно')
        w.advance(300)      # a long wait for the hand; with dictation=on the repeat arrives in ~20 s
        assert [c.text for c in w.cues] == [first, first], 'the timer waits for the hand, it is not switched off for good until «хватит диктовать»'
    finally:
        w.close()


@pytest.mark.xfail(strict=True, reason='реестр 5.05b: ВЫКЛЮЧЕНО; команда «диктуй медленно», пришедшая только финалом облака без слов уха, не ждёт руку: порция повторяется через обычные ~2,5 с')
def test_said_dictiruy_medlenno_as_the_clouds_final_alone_the_portion_still_waits_for_the_hand(call):
    rig = rig_of(call)      # the ear is on but did not catch the command: only the cloud's turn carries it
    rig.w.feed(S.turn_created('v7', 'user', 'Диктуй'))
    rig.w.feed(S.turn_done('v7', 'user', 'Диктуй медленно.'))
    end = rig.w.clock.t
    rig.pump(6.0)      # the usual silence repeat is ~2.5 s with these keys
    assert rig.said() == [P1], 'the command was heard by the cloud: nothing cuts in while the hand writes'
    cue = rig.next_cue(40.0)      # and not merely held back: the repeat comes after the wait of the hand
    assert cue is not None and cue.text == P1 and rig.w.clock.t - end > 10

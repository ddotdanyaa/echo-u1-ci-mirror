"""c24-a2: the system is not silent and does not lose its place over a long call (P05-P20 of c22-break, c23-final.md 6-7). Each test was red before its fix."""
import pytest

from echo_sync.ru_alignment import match_current


# P19 (half_hour seed 0/8): the number of an article said in words is the article's number: «триста сорок шесть двенадцать» is 346.12, with or without «точка»
@pytest.mark.parametrize('heard', ['статья триста сорок шесть двенадцать', 'Статья триста сорок шесть точка двенадцать', 'статья триста сорок шесть дробь двенадцать',
                                   'статья 346 12'])
def test_p19_an_article_number_in_words_is_its_digits(heard):
    assert match_current(heard, 'Статья 346.12') == 'ack'


@pytest.mark.parametrize('heard', ['статья триста сорок шесть тринадцать', 'статья триста сорок шесть', 'статья триста сорок двенадцать', 'статья тридцать четыре шесть двенадцать'])
def test_p19_another_number_is_still_another(heard):
    assert match_current(heard, 'Статья 346.12') != 'ack'


# P11 (half_hour seed 6 @1711): the ear's other number took the step back after the next portion had sounded; the owner then says that next portion whole: he is there
import logging  # noqa: E402

from test_ear_act import Ear  # noqa: E402
from test_ear_number_veto import CLOUD_988, EAR_989, PORTION, dictated  # noqa: E402
from test_stable_partial_ack import Speaker  # noqa: E402


def _taken_back(tmp_path, sounded):
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words(CLOUD_988)
    assert cloud.wait(0.6) == [d.chunks[1]] and d.index == 1
    if sounded:
        cue = [a for a in cloud.actions if a['type'] == 'speak'][-1]
        d.controller.cue_started(cue, voiced_seconds=1.0)
    ear.heard(EAR_989, speech=0.2, lag=0.1)
    assert d.index == 0 and d.current == PORTION, 'precondition: the step was taken back'
    cloud.final(CLOUD_988)
    d.clock.advance(2.0)
    return d


def test_p11_the_next_portion_said_after_its_cue_sounded_is_where_the_owner_is(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    d = _taken_back(tmp_path, sounded=True)
    nxt = Speaker(d, 'u-next').start().words(d.chunks[1])
    nxt.final(d.chunks[1])
    assert d.index == 2, 'the owner said the portion after the one taken back: both stand, the cursor is after it'
    assert any('next_after_veto' in r.getMessage() for r in caplog.records)


def test_p11_the_next_portion_said_with_no_cue_of_it_heard_takes_no_step(tmp_path):
    d = _taken_back(tmp_path, sounded=False)
    nxt = Speaker(d, 'u-next').start().words(d.chunks[1])
    nxt.final(d.chunks[1])
    assert d.index == 0, 'nothing of the next portion was heard: the number the ear heard stays in doubt'


# half_hour seed 4 @1667 (stuck + extra): the ear heard a stumble and helped with the same portion; the cloud's late final of that very speech says most of the portion and
# its last word: under the owner's rule that is the next portion. The P03 guard (speech begun before the cue) is for a cue of ANOTHER portion, not the help with this one.
def test_the_late_final_of_a_try_the_ear_helped_with_goes_on_under_the_rule(monkeypatch):
    import helpers_s6_state as S
    from test_h3_tempo import TICK
    from test_silence_kinds import ANSWER, ASKED, CANDIDATE, P1, P2, REST, Rig
    rig = Rig(monkeypatch, **{**CANDIDATE})
    try:
        rig.asks('u1', ASKED, 0, ANSWER)
        assert rig.said() == [P1]
        rig.ended()
        rig.pump(0.5)
        ear = rig.onset()
        rig.pump(0.6)
        rig.w.feed(S.turn_created('u3', 'user', 'Пассивный'))
        rig.pump(1.2)
        rig.offset()
        rig.pump(0.15)
        rig.worker.heard(ear, 'пассивный счёт')
        rig.pump(TICK)
        rig.pump(2.0)
        assert rig.said()[-1] == REST, 'precondition: the ear helped with the rest of the same portion'
        rig.w.feed(S.turn_done('u3', 'user', 'Пассивный счёт учитывает источники имущества.'))
        rig.pump(2.0)
        assert rig.said()[-1] == P2, rig.said()
        assert rig.w.violations == []
    finally:
        rig.close()


# half_hour seed 6 @926 (extra): the ear lost the first letter of the portion's last word («рганизацией»): it is still its last word under the owner's rule
from echo_sync.repeat_rule import verdict as rule_verdict  # noqa: E402


@pytest.mark.parametrize('heard, portion', [('долги перед рганизацией', 'долги других лиц перед организацией.'), ('ндс косвенный с добавленной стоимост', 'НДС косвенный налог с добавленной стоимости,')])
def test_the_last_word_the_ear_garbled_by_one_letter_is_the_last_word(heard, portion):
    assert rule_verdict(heard, portion) == 'next'


@pytest.mark.parametrize('heard, portion', [('долги перед рганизаций', 'долги других лиц перед организацией.'), ('пять раз', 'Это 5 раз по 5.')])
def test_a_last_word_two_letters_off_or_short_is_not(heard, portion):
    assert rule_verdict(heard, portion) is None


# P15/P03 (fuzz seeds 90, 148, 269, 860, A3): the friend asks the question in play again because its answer had not come yet; its late final retired the answer just cued and the
# same answer started again: the owner's repeat of the first copy confirmed the second with nobody speaking to it
@pytest.mark.parametrize('seed', [90, 148, 269, 860])
def test_the_question_asked_again_before_its_answer_was_heard_is_the_same_request(seed):
    from tools.replay import stand
    assert [v for v in stand.run(seed).violations if v[0] == 'A3'] == []


# P16 (ladder L4 seed 1 @105.24): a declined question gives the plan before it back, but not while the ear has just heard a newer question whose final is due:
# «Осталось 20 рублей.» (of the question before) was cued as the answer of «Что такое счета 66 и 67?»
def test_p16_the_old_plan_does_not_come_back_over_a_newer_question_the_ear_heard():
    from tools.ladder import scenes
    r = scenes.scene('L4', 1)
    assert [f[:3] for f in r['faults'] if f[0] in ('wrong', 'old_answer')] == []


# P17 (marathon 30 min, 12 of 12 seeds): the controller's maps keyed by turn grow for the whole call; they hold no more than the ledger's turns and a margin
def test_p17_the_maps_by_turn_stay_bounded_over_a_long_call(tmp_path):
    import helpers_s6_ack as H
    from echo_sync import controlled_media as CM
    d = H.Dictation(tmp_path / 'long', 'Первое предложение тут. Второе предложение там. Третье предложение здесь.')
    c = d.controller
    for n in range(600):
        tid = f'x{n}'
        c.provider(H.created(tid, 'user', ''))
        c.provider(H.done(tid, 'user', 'угу'))
        c.announced_at[tid] = c.user_done_at[tid] = c.user_started_at[tid] = c.turn_done_at[tid] = c.activity_at[tid] = 0.0
        c.seen.add(tid)
        c.blocked.add(tid)
        c.user_boundaries[tid] = 'x'
    for name in ('owners', 'seen', 'blocked', 'user_boundaries', 'announced_at', 'user_done_at', 'user_started_at', 'turn_done_at', 'activity_at'):
        assert len(getattr(c, name)) <= CM.TURN_MAP_CAP, name


# half_hour seed 8 @1516: the ear's try at the LAST portion went on (the answer is over); the cloud's late final of that very try was read as a new question
# (retire, a job, «Распознано: …»). It is the final of the try, as it is for any portion before the last.
def test_the_late_final_of_a_try_at_the_last_portion_is_that_try(monkeypatch, caplog):
    import logging
    import helpers_s6_state as S
    from test_silence_kinds import CANDIDATE, Rig
    P1, P2 = 'Налог на прибыль платят российские организации.', 'Первое: налог начисляют по итогам периода.'
    caplog.set_level(logging.INFO)
    rig = Rig(monkeypatch, **CANDIDATE)
    try:
        rig.asks('u1', 'Кто платит налог на прибыль', 0, P1 + ' ' + P2)
        for n, portion in enumerate((P1,)):
            rig.pump(0.5)
            rig.says(portion.lower().strip('.'), speech=1.0)
            rig.pump(1.5)
        assert rig.said()[-1] == P2, rig.said()
        rig.pump(0.5)
        uid = rig.onset()
        rig.w.feed(S.turn_created('u9', 'user', 'налог'))
        rig.pump(1.0)
        rig.offset()
        rig.pump(0.15)
        rig.worker.heard(uid, 'алог по итогам периода')
        rig.pump(1.0)
        caplog.clear()
        rig.w.feed(S.turn_done('u9', 'user', 'налог по итогам периода.'))
        rig.pump(3.0)
        lines = [r.getMessage() for r in caplog.records]
        assert not [m for m in lines if 'new_question' in m or 'fast_text job' in m], lines
    finally:
        rig.close()


# P18 (half_hour seed 11 @1813, the three unanswered half hours of c23): the job failed twice and was handed back to the cloud, which says nothing at all: the honest phrase came
# answer_wait_seconds after the SECOND job began (12-14 s after the question). The cloud's silence after the hand back is bounded by HANDED_BACK_WAIT_SECONDS of its own.
def test_p18_two_failed_jobs_and_a_silent_cloud_are_said_soon(monkeypatch):
    BAPTISM = 'В каком году было крещение Руси?'
    from test_h5_live import LIVE, asked, fails, spoken_failures
    from test_h3_tempo import Rig
    from echo_sync import controlled_media as CM
    rig = Rig(monkeypatch, **LIVE)
    try:
        asked(rig, BAPTISM)
        fails(rig, 0)
        fails(rig, 1)
        began = rig.w.clock.t
        rig.pump(CM.HANDED_BACK_WAIT_SECONDS + 0.5)
        said = spoken_failures(rig)
        assert said and said[0].t - began <= CM.HANDED_BACK_WAIT_SECONDS + 0.3, [(c.t - began, c.text) for c in said]
    finally:
        rig.close()


def test_p18_a_cloud_that_streams_after_the_hand_back_is_not_cut(monkeypatch):
    from test_h5_live import BAPTISM, LIVE, asked, fails, spoken_failures
    from test_h3_tempo import Rig
    import helpers_s6_state as S
    from echo_sync import controlled_media as CM
    rig = Rig(monkeypatch, **LIVE)
    try:
        asked(rig, BAPTISM)
        fails(rig, 0)
        fails(rig, 1)
        rig.pump(CM.HANDED_BACK_WAIT_SECONDS - 1.0)
        rig.w.feed(S.turn_created('a7', 'assistant', 'Крещение'))
        rig.pump(1.5)
        assert not spoken_failures(rig), 'a sign of life of the cloud restarts the count'
    finally:
        rig.close()


@pytest.mark.parametrize('heard, written', [('около тридцать шесть шесть градусов Цельсия', 'около 36,6 °C'), ('тридцать шесть точка шесть градусов', '36,6 градусов')])
def test_p19_a_decimal_written_with_a_comma_keeps_ruling_5(heard, written):
    assert match_current(heard, written) != 'ack'


# F1 (h5 n1_01 step 8, w3 scenes): speech that shares a word or a number with the waiting portion is no try when it is mostly words of its own: two such pieces of a long
# question («вклад ну сто тысяч рублей на два года», «под десять процентов годовых») counted as two tries and the answer went on under the question
from echo_sync.controlled_media import _like_a_try  # noqa: E402

BOUGHT = 'Купили материалы за 10 000 рублей:'


@pytest.mark.parametrize('said', ['вклад ну сто тысяч рублей на два года', 'под десять процентов годовых', 'нет не под десять а под двадцать', 'проценты простые сколько начислят'])
def test_f1_speech_of_its_own_is_no_try(said):
    assert not _like_a_try(said, BOUGHT)


@pytest.mark.parametrize('said', ['купили материалы за двадцать тысяч рублей', 'купили за десять', 'материалы', 'десять тысяч', 'за десять тысяч рублей', 'ну купили материалы'])
def test_f1_a_try_is_still_a_try(said):
    assert _like_a_try(said, BOUGHT)


# half_hour seed 4 @1334 (stuck, next never): a laugh right after the question («Хи-хи.», the same breath for the ear) was joined to it as its rest: the answer in play was retired
# and asked again while the owner repeated its first portion
@pytest.mark.parametrize('laugh', ['Хи-хи.', 'Ха-ха-ха!', 'Кхм.'])
def test_a_laugh_after_the_question_is_not_its_rest(monkeypatch, caplog, laugh):
    import logging
    import helpers_s6_state as S
    from test_silence_kinds import ANSWER, ASKED, CANDIDATE, P1, Rig
    caplog.set_level(logging.INFO)
    rig = Rig(monkeypatch, **CANDIDATE)
    try:
        rig.asks('u1', ASKED, 0, ANSWER)
        assert rig.said() == [P1]
        rig.c._ear_went_on = lambda since, qid=None: True      # the ear heard one breath from the question on (c24-final: c24-a1 added ``qid``)
        rig.w.feed(S.turn_created('u2', 'user', laugh))
        rig.pump(0.3)
        rig.w.feed(S.turn_done('u2', 'user', laugh))
        rig.pump(1.0)
        assert not [r.getMessage() for r in caplog.records if 'utterance_continued' in r.getMessage()]
    finally:
        rig.close()


# w3 n2_d10 step 15: «тридцать процентов сто пятьдесят тысяч пятьсот тысяч» (the ear writes no «/») is the 150 000 and 500 000 of the portion, not 100, 50, 1000, 500
def test_two_numbers_with_their_scales_the_ear_ran_together_are_no_other_number(tmp_path):
    from test_ear_number_veto import dictated
    c = dictated(tmp_path).controller
    portion = '30 процентов: 150 000 / 500 000.'
    assert not c._ear_other_number('тридцать процентов сто пятьдесят тысяч пятьсот тысяч', portion)
    assert c._ear_other_number('тридцать процентов сто шестьдесят тысяч пятьсот тысяч', portion)
    assert c._ear_other_number('две тысячи двадцать один', 'В 2020 году.')


# turn-memory: ONE place forgets turns (ControlledMedia.forget_turns): the maps of the controller and a set a caller keeps (the socket's ``transcribed``) are cut by the same rule,
# the turns in play and the ledger's turns stay
def test_turn_memory_one_place_forgets_the_maps_and_the_callers_set(tmp_path):
    import helpers_s6_ack as H
    from echo_sync import controlled_media as CM
    c = H.Dictation(tmp_path / 'one', 'Первое предложение тут. Второе предложение там.').controller
    c.question_id = 'q-live'
    mine = {f'm{n}' for n in range(CM.TURN_MAP_CAP + 40)} | {'q-live'}
    c.owners.update({f'o{n}': None for n in range(CM.TURN_MAP_CAP + 40)})
    c.forget_turns(mine)
    assert len(mine) <= CM.TURN_MAP_KEEP + 1 and 'q-live' in mine
    assert len(c.owners) <= CM.TURN_MAP_KEEP + len(c.ledger.history()) and 'o0' not in c.owners and 'o%d' % (CM.TURN_MAP_CAP + 39) in c.owners

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

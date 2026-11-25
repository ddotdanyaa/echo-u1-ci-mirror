"""c9-numveto (3 Nov, FIRST_DIVERGENCE w3_02 step 4): a wrong number must never be confirmed.

The portion «Крещение Руси обычно датируют 988 годом,» waits; the listener says «… 989 годом»; the CLOUD ASR (biased by the answer it
generated) returns «… 988 годом» and the controller acknowledged it, while the LOCAL EAR (Vosk, ``local_ear`` = "act") heard the very same
utterance and judged it a try that does not match. R-EAR-ACT already had the opposite direction (``_cloud_disagrees``: the cloud contradicts
a confirmation of the ear); this is the ear contradicting a confirmation of the cloud, for a NUMBER only: when the waiting portion has a
number and the ear's own words of the same utterance carry another one, the cloud's acknowledgement does not advance (the utterance is
judged as the ear heard it: a try, the portion stays and is repeated as for any try); when the ear's verdict arrives after the cloud's
acknowledgement has advanced, the step is taken back (``engine.rewind`` + cancel). An ear that heard no number (empty, garbled) or the
same number is no reason to doubt the cloud. The ear acts only in ``local_ear`` = "act", and so does this: with another mode no ear
utterance ever reaches the controller (``ear_heard``), so there is nothing to compare with.

Time is injected and nothing sleeps. The controller, its engine and the classifier are the production ones.
"""
import logging

import pytest

from echo_sync.controlled_media import EAR_JOIN_GAP_SECONDS
from test_ear_act import Ear
from test_stable_partial_ack import Speaker, dictation, speaks

ANSWER = 'Крещение Руси обычно датируют 988 годом, но точная дата спорна. Это было давно.'
PORTION = 'Крещение Руси обычно датируют 988 годом,'
CLOUD_988 = 'Крещение Руси обычно датируют 988 годом'
EAR_989 = 'крещение руси обычно датируют девятьсот восемьдесят девять годом'
EAR_988 = 'крещение руси обычно датируют девятьсот восемьдесят восемь годом'

NO_NUMBER_ANSWER = 'Кошка сидит на окне. Собака спит дома.'


def dictated(tmp_path, answer=ANSWER, at=0):
    return dictation(tmp_path, answer, at=at)


def veto_logged(caplog):
    return [r.getMessage() for r in caplog.records if 'local_ear_number_veto' in r.getMessage()]


def test_precondition_the_portion_under_test_waits(tmp_path):
    d = dictated(tmp_path)
    assert d.current == PORTION and d.index == 0, d.chunks


# ====================================================================================================================
# the ear is first: the cloud's acknowledgement over another number does not advance
# ====================================================================================================================

def test_989_heard_by_the_ear_blocks_the_stable_partial_988_of_the_cloud(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Крещение Руси обычно датируют 988')
    assert ear.heard(EAR_989, speech=0.6) == [], 'the ear takes a try at the portion for nothing'
    cloud.words('годом')                                    # the cloud's partial now confirms the portion word for word
    spoken = cloud.wait(1.0)                                # the stable partial would accept it after ACK_STABLE_SECONDS
    assert spoken == [] and d.index == 0, 'a wrong number was confirmed'
    assert cloud.final(CLOUD_988) == [] and d.index == 0, 'its final must not confirm it either'
    assert d.current == PORTION
    assert veto_logged(caplog), 'the block is logged'


def test_989_heard_by_the_ear_blocks_the_final_988_of_the_cloud(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start()
    assert ear.heard(EAR_989, speech=0.6) == []
    assert cloud.final(CLOUD_988 + '.') == [] and d.index == 0, 'the final alone must not confirm a number the ear heard otherwise'
    assert veto_logged(caplog)


def test_the_number_in_the_second_piece_of_an_utterance_the_ear_cut_counts(tmp_path):
    """The ear's detector cuts one utterance at a breath (EAR_JOIN_GAP_SECONDS): the pieces are judged joined, as for its own verdicts."""
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Крещение Руси обычно датируют')
    assert ear.heard('крещение руси обычно датируют', speech=0.5) == []
    assert ear.says('девятьсот восемьдесят девять годом', speech=0.5) == []
    cloud.words('988 годом')
    assert cloud.wait(1.0) == [] and d.index == 0 and cloud.final(CLOUD_988) == [] and d.index == 0


def test_the_blocked_utterance_is_a_try_the_portion_is_repeated_not_dropped(tmp_path):
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words(CLOUD_988)
    ear.heard(EAR_989, speech=0.6)
    cloud.wait(1.0)
    assert d.index == 0
    # the listener says nothing more: the prompter says the portion again (the repeat for a try / silence), never the next one
    spoken = cloud.wait(20.0)
    assert d.index == 0 and d.chunks[1] not in spoken, spoken


def test_a_correct_988_after_the_blocked_try_advances(tmp_path):
    """The ear's piece belongs to the utterance it heard: a later, correct utterance is not blocked by it."""
    d = dictated(tmp_path)
    ear, first = Ear(d), Speaker(d, 'u-1')
    ear.onset()
    d.clock.advance(0.3)
    first.start().words(CLOUD_988)
    ear.heard(EAR_989, speech=0.6)
    first.wait(1.0)
    first.final(CLOUD_988)
    assert d.index == 0
    d.clock.advance(8.0)
    second = Speaker(d, 'u-2')
    second.start().words(CLOUD_988)                         # the ear is still silent about this one
    assert second.wait(1.0) == [d.chunks[1]] and d.index == 1


# ====================================================================================================================
# the cloud is right, or the ear is no witness
# ====================================================================================================================

def test_988_from_both_advances_once(tmp_path, caplog):
    """The ear writes «девятьсот восемьдесят восемь годом»: since candidate 9 a three-digit cardinal before «годом» is the year 988, so the
    ear's own confirmation takes the turn (it used to be a try and the cloud decided) - and the cloud's later words never advance twice."""
    caplog.set_level(logging.INFO)
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Крещение Руси обычно датируют 988')
    spoken = [a['text'] for a in ear.heard(EAR_988, speech=0.8) + ear.settle() if a.get('type') == 'speak']
    assert spoken == [d.chunks[1]] and d.index == 1
    cloud.words('годом')
    assert cloud.wait(1.0) == [] and d.index == 1
    assert cloud.final(CLOUD_988) == [] and d.index == 1, 'the same utterance never advances twice'
    assert not veto_logged(caplog)


def test_988_confirmed_by_the_ear_itself_advances_once(tmp_path):
    """R-EAR-ACT as before: the ear's own confirmation (a number it writes in a form the classifier accepts) takes the turn."""
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Крещение Руси обычно датируют')
    out = ear.heard('крещение руси обычно датируют 988 годом', speech=0.8) + ear.settle()
    assert speaks(out) == [d.chunks[1]] and d.index == 1
    cloud.words('988 годом')
    assert cloud.wait(1.0) == [] and cloud.final(CLOUD_988) == [] and d.index == 1


def test_988_from_the_cloud_with_a_correct_number_heard_amid_other_words_advances(tmp_path):
    """The ear says the same number with a manner adverb changed («так» for «обычно»): a confirmation by the lenient rule - the ear takes the
    turn once, the cloud's words never advance again (no veto: the same number)."""
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Крещение Руси обычно датируют 988')
    spoken = [a['text'] for a in ear.heard('крещение руси так датируют девятьсот восемьдесят восемь годом', speech=0.6) + ear.settle()
              if a.get('type') == 'speak']
    assert spoken == [d.chunks[1]] and d.index == 1
    cloud.words('годом')
    assert cloud.wait(1.0) == [] and d.index == 1


@pytest.mark.parametrize('ear_text', [None, '', 'э', 'крещение руси обычно датируют годом', 'крещение руси'],
                         ids=['none', 'empty', 'garbled', 'words-no-number', 'beginning-only'])
def test_an_ear_that_heard_no_number_leaves_the_cloud_to_decide(tmp_path, ear_text):
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Крещение Руси обычно датируют 988')
    assert ear.heard(ear_text, speech=0.6) == []
    cloud.words('годом')
    assert cloud.wait(1.0) == [d.chunks[1]] and d.index == 1, 'a weak ear must not block the cloud'


def test_a_number_the_ear_is_still_saying_is_no_other_number(tmp_path):
    """«девятьсот восемьдесят» is the start of 988 (the ear cut where the speaker paused), not another number."""
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Крещение Руси обычно датируют 988')
    assert ear.heard('крещение руси обычно датируют девятьсот восемьдесят', speech=0.6) == []
    cloud.words('годом')
    assert cloud.wait(1.0) == [d.chunks[1]] and d.index == 1


def test_no_ear_at_all_the_cloud_decides_alone(tmp_path):
    d = dictated(tmp_path)
    cloud = Speaker(d)
    cloud.start().words(CLOUD_988)
    assert cloud.wait(1.0) == [d.chunks[1]] and d.index == 1


def test_a_portion_without_a_number_is_never_blocked_by_a_number_of_the_ear(tmp_path):
    d = dictated(tmp_path, NO_NUMBER_ANSWER)
    assert d.current == 'Кошка сидит на окне.', d.chunks
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words('Кошка сидит на')
    assert ear.heard('кошка сидит на двух окнах', speech=0.6) == []
    cloud.words('окне')
    assert cloud.wait(1.0) == [d.chunks[1]] and d.index == 1


# ====================================================================================================================
# the ear is late: the cloud has already advanced - the step is taken back
# ====================================================================================================================

def test_989_of_a_late_ear_takes_the_advance_on_988_back(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    cloud.start().words(CLOUD_988)
    assert cloud.wait(0.6) == [d.chunks[1]] and d.index == 1, 'precondition: the cloud\'s stable partial advanced, the ear has not spoken'
    out = ear.heard(EAR_989, speech=0.2, lag=0.1)
    assert d.index == 0 and d.current == PORTION, 'the step was not taken back'
    assert [a['type'] for a in out if a['type'] == 'cancel'], 'the next cue is cancelled'
    assert d.chunks[1] not in speaks(out)
    assert veto_logged(caplog)
    assert cloud.final(CLOUD_988) == [] and d.index == 0, 'the cloud\'s final cannot confirm it afterwards'


def test_a_late_ear_with_the_same_number_or_none_leaves_the_advance(tmp_path):
    for n, ear_text in enumerate([EAR_988, 'крещение руси так датируют девятьсот восемьдесят восемь годом', 'э', None]):
        d = dictated(tmp_path / f'late{n}')
        ear, cloud = Ear(d), Speaker(d)
        ear.onset()
        d.clock.advance(0.3)
        cloud.start().words(CLOUD_988)
        assert cloud.wait(0.6) == [d.chunks[1]] and d.index == 1
        ear.heard(ear_text, speech=0.2)
        assert d.index == 1, ear_text


def test_a_late_ear_piece_of_an_earlier_utterance_takes_nothing_back(tmp_path):
    """An ear utterance that began long before the cloud's turn was announced is not the utterance the cloud confirmed."""
    d = dictated(tmp_path)
    ear, cloud = Ear(d), Speaker(d)
    ear.onset()
    d.clock.advance(0.3)
    ear_out = ear.heard(EAR_989, speech=0.6)                # its verdict: a try; the cloud has announced nothing
    assert ear_out == [] and d.index == 0
    d.clock.advance(EAR_JOIN_GAP_SECONDS + 5.0)
    cloud.start().words(CLOUD_988)
    assert cloud.wait(1.0) == [d.chunks[1]] and d.index == 1

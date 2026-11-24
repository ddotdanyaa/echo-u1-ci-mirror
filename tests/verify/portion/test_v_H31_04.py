"""V4 H31-04: the seam «и» when phrases are joined (the owner: «не слышна разница между «и» и паузой»); F18: the pause before the last step of a sum (the same ACK delivered twice must not eat the last step or double it).
Backlog: a test. The «и» that joins two parts stays with the part it opens (it is not lost at the cut, no portion ends on it), the portions put back together are the answer, and a retransmitted final moves the cursor once.

Real ControlledMedia built as the host builds it (``helpers_s6_ack.Dictation``) and the rig ``call``. Not run on the laptop. A red test is a defect card for the family P (``portioner``).
"""
import re

from echo_sync.textutil import norm_words
from portion_kit import call, dictation_of      # noqa: F401 - call is the fixture

JOIN = 'Налоги бывают федеральные и региональные и местные. Каждый налог имеет ставку и срок уплаты, а также порядок расчёта и порядок оплаты.'
SUM = 'Сначала складываем пять и семь, получается двенадцать. Затем прибавляем три, получается пятнадцать. Итого пятнадцать рублей.'


def test_the_portions_put_back_together_lose_no_word_at_a_seam(tmp_path):
    d = dictation_of(tmp_path, JOIN)
    assert len(d.chunks) >= 3, f'precondition: the answer is cut: {d.chunks}'
    assert norm_words(' '.join(d.chunks)) == norm_words(JOIN), f'a word lost or added at a seam: {d.chunks}'


def test_no_portion_ends_on_a_bare_joining_word(tmp_path):
    d = dictation_of(tmp_path, JOIN)
    ends = [re.sub(r'[^\w]+$', '', c).split()[-1].lower() for c in d.chunks]
    assert not [e for e in ends if e in ('и', 'а', 'но', 'или')], f'a portion hangs on its conjunction: {d.chunks}'


def test_the_tail_help_after_a_stop_before_the_joining_word_keeps_the_word(call):
    """«общие условия установления налогов» and a stop: the help is «и сборов.», the «и» is said (E13 pins the time, here the word)."""
    rig = call()
    rig.second_portion()
    rig.pump(1.0)
    rig.says('общие условия установления налогов')
    cue = rig.next_cue(3)
    assert cue is not None and cue.text.startswith('и '), cue and cue.text


def test_a_retransmitted_final_of_a_step_moves_the_cursor_once_and_the_last_step_is_still_said(tmp_path):
    d = dictation_of(tmp_path, SUM)
    assert len(d.chunks) >= 3, d.chunks
    portion = d.current
    first = d.say(portion, gap=4.0, tid='u70')
    again = d.say(portion, gap=0.1, tid='u70', play=False)
    assert first.after == 1, 'precondition: the right repeat moved on'
    assert again.after == first.after, 'the same final delivered twice moved the cursor twice'
    for _ in range(len(d.chunks)):
        if d.completed:
            break
        d.say(d.current, gap=4.0)
    assert d.completed, 'the last step of the sum is reached, none was eaten by the retransmit'

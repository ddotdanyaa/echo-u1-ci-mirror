"""V3 Н2 (call 12:31, c25): the model's «Принял, сейчас посмотрю.» is never a hint: nothing of it sounds, the answer after it does. The unit rows are in test_c25_b_cases (``_announces``); this is the row on the wire.

Real ControlledMedia and wire (rig ``call``, the job's stream says the announcement and then the answer). Not run on the laptop."""
import pytest

from answer_kit import BAPTISM, LIVE, RIGHT, TICK, asked, call, texts      # noqa: F401

ANNOUNCEMENTS = ['Принял, сейчас посмотрю.', 'Принял, посмотрю в базе.', 'Хорошо, принял, сейчас гляну в базе.']


@pytest.mark.parametrize('announcement', ANNOUNCEMENTS)
def test_the_announcement_of_the_job_is_not_cued_and_its_answer_is(call, announcement):
    rig = call(**LIVE)
    asked(rig, BAPTISM)
    rig.job_says(0, announcement)
    rig.pump(1.0)
    assert not any('посмотр' in t.casefold() or 'принял' in t.casefold() or 'гляну' in t.casefold() for t in texts(rig)), texts(rig)
    rig.job_says(0, ' ' + RIGHT)
    rig.job_ends(0)
    rig.pump(TICK * 4)
    assert any('988' in t for t in texts(rig)), texts(rig)
    assert not any('принял' in t.casefold() or 'посмотрю' in t.casefold() or 'гляну' in t.casefold() for t in texts(rig)), texts(rig)

"""U117: another person already answered the question (not the one addressed): no prompt is needed. A row of the judge (``answered_elsewhere``): after the question, before our answer began, a
final that near_voice tags as somebody else's voice and that is no question and says the question's own words as an answer withholds the prompt. A remark («хороший вопрос»), an untagged
voice or the listener's own voice withholds nothing. Through the real controller (the rig of h31, a scripted model, the ear's records tagged by the test as near_voice would)."""
import pytest

from echo_sync.near_voice import NearGate
from test_h31_rules import model_says, new, rig      # noqa: F401 - rig is the fixture
from tools.replay import repeat_scenes as R

QUESTION = 'Сколько всего планет в Солнечной системе?'
THEIRS = 'В Солнечной системе восемь планет.'
MODEL = 'В Солнечной системе восемь планет, от Меркурия до Нептуна.'


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def listen(rig, tags):
    """The ear's records carry the voice near_voice tags them with (``tags``: text -> (kind, conf)); the gate is the real one, in act."""
    rig.c.speaker_gate = NearGate(speaking=lambda: False, clock=rig.c.clock)
    real = rig.c.ear_heard

    def heard(record):
        tag = next((tag for said, tag in tags.items() if said.strip('.?') == str(record.get('text')).strip('.?')), None)
        return real({**record, 'voice': {'kind': tag[0], 'conf': tag[1]}} if tag else record)
    rig.c.ear_heard = heard


def scene(rig, remark, tags):
    listen(rig, tags)
    R.utter(rig, QUESTION)
    rig.pump(2.0)      # the other person begins after a pause: a new utterance, not the same breath
    mark = len(rig.cues())
    R.utter(rig, remark)
    rig.pump(0.3)
    model_says(rig, MODEL)
    rig.pump(4.0)
    return mark


def test_a_question_another_person_answered_gets_no_prompt(rig):
    scene(rig, THEIRS, {THEIRS: ('other', 0.9)})
    assert not [c for c in rig.cues() if 'восемь планет' in c.text], [c.text for c in rig.cues()]


@pytest.mark.parametrize('remark', ['Хороший вопрос.', 'Хороший вопрос про планеты.', 'Угу.'])
def test_a_remark_that_is_no_answer_changes_nothing(rig, remark, caplog):
    """«хороший вопрос» in another voice is judged as it is with no tag at all (today: a new bare phrase replaces the question); never as an answer."""
    caplog.set_level('INFO')
    scene(rig, remark, {remark: ('other', 0.9)})
    assert 'answered_elsewhere' not in caplog.text
    if remark == 'Угу.':
        assert [c for c in rig.cues() if 'восемь планет' in c.text], [c.text for c in rig.cues()]


@pytest.mark.parametrize('tag', [None, ('own', 0.9), ('other', 0.3)])
def test_an_answer_not_known_to_be_another_voice_withholds_nothing(rig, tag):
    scene(rig, THEIRS, {THEIRS: tag} if tag else {})
    assert [c for c in rig.cues() if 'восемь планет' in c.text], [c.text for c in rig.cues()]

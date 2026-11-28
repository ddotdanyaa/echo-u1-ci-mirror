"""W13 item 4: the job started on the final (13 of 18 prepared jobs refused there). A new job starts as soon as the cloud's STABLE text
(``two_witnesses.Pieces``: two deltas agree) has changed by a content word, while the listener still speaks, not on the final; a ready job of the
same meaning is taken. Numbers and «не» are not loosened. And an idiom with a number word («в двух словах») is no number of the question."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import helpers_s6_state as S
from echo_sync.classifier import strip_fillers
from echo_sync.fast_text import refusal
from echo_sync.settings import CALL_SETTINGS
from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture


def strip(text):
    return strip_fillers(text, CALL_SETTINGS)


def test_an_idiom_with_a_number_word_is_no_number():
    assert refusal('что такое амортизация', 'Что такое амортизация, ну, в двух словах?', strip=strip) is None
    assert refusal('что такое амортизация', 'Что такое амортизация одним словом?', strip=strip) is None
    assert refusal('сколько будет два плюс два', 'Сколько будет три плюс два?', strip=strip) == 'numbers', 'numbers stay exact'
    assert refusal('в двух случаях платят ндс', 'В трёх случаях платят НДС?', strip=strip) == 'numbers'


def test_a_job_starts_on_the_stable_piece_while_the_listener_speaks(call):
    rig = call(fast_text='on', prepare_wide='on')
    rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    for n, word in enumerate(['Объясни, ', 'пожалуйста, ', 'что такое ', 'инерция ', 'в физике ', 'простыми словами']):
        rig.w.feed(S.turn_delta('u1', word, n))
        rig.pump(0.2)
    assert rig.ear.current is not None, 'still speaking'
    assert rig.fake.runs, 'a job on the stable piece before the end of the speech'
    assert 'инерц' in str(rig.fake.runs[-1].request).lower() and len(rig.fake.runs) <= 3, [str(r.request)[-60:] for r in rig.fake.runs]


def test_no_job_on_the_stable_piece_without_the_flag(call):
    rig = call(fast_text='on')
    rig.onset()
    rig.pump(0.5)
    rig.w.feed(S.turn_created('u1', 'user', ''))
    for n, word in enumerate(['Объясни, ', 'пожалуйста, ', 'что такое ', 'инерция ', 'в физике ', 'простыми словами']):
        rig.w.feed(S.turn_delta('u1', word, n))
        rig.pump(0.2)
    assert not rig.fake.runs

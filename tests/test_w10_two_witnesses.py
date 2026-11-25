"""w10 item 4, E86 ``two_witnesses`` (WAVE6 item 11): sound without the final when the ear and the STABLE piece of the cloud agree on numbers, «не»,
roles; a question with neither may go on the ear and the piece; a disagreement cuts. The ear's numbers are wrong in 2-20 %, «не» lost in 5-15 %."""
import pytest

from echo_sync import two_witnesses as TW
from echo_sync.settings import resolve

ARTICLE = 'что говорится в статье девятнадцать налогового кодекса'


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


@pytest.mark.parametrize('ear,piece,expected', [
    (ARTICLE, 'что говорится в статье 19', TW.SOUND),                    # the number is in both, by value
    (ARTICLE, 'что говорится в статье', TW.WAIT),                        # the ear's number has no second witness yet
    (ARTICLE, 'что говорится в статье 18', TW.CUT),                      # the ear misheard the number (or the cloud): never sound
    ('можно ли не платить налог', 'можно ли', TW.WAIT),                  # «не» not yet witnessed
    ('можно ли не платить налог', 'можно ли не платить', TW.SOUND),
    ('можно ли платить налог', 'можно ли не платить', TW.CUT),           # the ear lost «не»: the cloud's piece has it
    ('что такое амортизация', 'что такое амортизация', TW.SOUND),        # no number, no «не»: ear and piece
    ('что такое амортизация', 'что такое', TW.WAIT),                     # no content word of the question in the piece yet
    ('что такое амортизация', 'что такое инерция', TW.CUT),
    ('кто убил каина', 'кого убил', TW.CUT),                             # the roles differ
    ('было 80 рублей потратил 20 сколько осталось', 'было 20 рублей потратил 80', TW.CUT),
    ('', 'что такое', TW.WAIT),
])
def test_verdict(ear, piece, expected):
    assert TW.verdict(ear, piece) == expected


def test_the_piece_is_the_stable_part_of_the_cloud_turn_only():
    pieces = TW.Pieces()
    seen = [pieces.feed('u1', text) for text in ['что', 'что такое', 'что такое амор', 'что такое амортизация', 'что такое амортизация']]
    assert seen[0] == '' and 'амор' not in ' '.join(seen[:4]) and pieces.piece('u1') == seen[-1]
    assert 'статье' not in pieces.feed('u2', 'в статье') and pieces.piece('u3') == ''
    assert TW.verdict(ARTICLE, Pieces_stable(['что говорится в статье', 'что говорится в статье 19', 'что говорится в статье 19 налогового'])) == TW.WAIT     # «19» needs a word after it in two deltas
    assert TW.verdict(ARTICLE, Pieces_stable(['что говорится в статье 19', 'что говорится в статье 19 налогового', 'что говорится в статье 19 налогового кодекса', 'что говорится в статье 19 налогового кодекса РФ'])) == TW.SOUND
    still = TW.Pieces()
    for text in ['что такое', 'что такое амортизация']:
        still.feed('t', text)
    assert TW.verdict('что такое амортизация', still.piece('t')) == TW.WAIT          # its last word may still grow
    still.feed('t', 'что такое амортизация', still=True)
    assert TW.verdict('что такое амортизация', still.piece('t')) == TW.SOUND


def Pieces_stable(texts):
    pieces = TW.Pieces()
    for text in texts:
        pieces.feed('t', text)
    return pieces.piece('t')


def test_there_is_no_switch_for_the_second_witness():
    from echo_sync.settings import DEFAULTS
    assert not [key for key in DEFAULTS if key.startswith('two_wit')]


# ---- the controller (H4 rig): the ear's question opens only on the cloud's stable piece -----------------------------------------
import logging                                                                        # noqa: E402
import helpers_s6_state as S                                                          # noqa: E402
from test_h3_tempo import TICK, call                                                 # noqa: E402, F401 - call is the fixture
from test_h4_ear_first import ANSWER, SILENCE, decisions, question                   # noqa: E402


def witnesses(call):
    rig = call(fast_text='on')
    return rig


def test_on_no_word_of_the_cloud_is_no_second_witness(call, caplog):
    rig = witnesses(call)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        question(rig)
        rig.pump(SILENCE)
        rig.job_says(0, ANSWER)
        rig.pump(TICK * 2)
    assert rig.said() == [], 'nothing is said before the cloud witnesses the question'


def test_on_the_stable_piece_that_agrees_releases_the_sound_before_the_final(call):
    rig = witnesses(call)
    question(rig)
    for n, word in enumerate(['Так, в каком ', 'году было ', 'крещение ', 'Руси']):
        rig.w.feed(S.turn_delta('u1', word, n))
        rig.pump(TICK)
    rig.pump(SILENCE)
    rig.job_says(0, ANSWER)
    rig.pump(TICK * 4)
    assert any('988' in text for text in rig.said()), 'two witnesses agree: sound without the final'
    assert rig.c.user_boundaries.get('u1') == 'ear_first'


def test_on_a_piece_with_another_number_cuts(call, caplog):
    rig = witnesses(call)
    with caplog.at_level(logging.INFO, logger='echo-sync'):
        question(rig, 'сколько часов ехать от москвы до казани сто километров')
        for n, word in enumerate(['Сколько часов ', 'ехать от ', 'Москвы до ', 'Казани ', '200 ', 'километров']):
            rig.w.feed(S.turn_delta('u1', word, n))
            rig.pump(TICK)
        rig.pump(SILENCE)
        rig.job_says(0, 'Около двух часов.')
        rig.pump(TICK * 4)
    assert rig.said() == [] and decisions(caplog, 'reason=cloud_disagrees')

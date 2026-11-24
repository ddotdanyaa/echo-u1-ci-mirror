"""c23-final(C): the red tests of the fast channel and the brain, and c22-break P01/P02/P04/P09 at their first cause. Nothing here is a measurement of time on a laptop or a phone."""
from echo_sync import fast_text as FT
from echo_sync.textutil import spoken_lead


def test_a_start_with_a_confirming_word_is_said_once_the_next_word_confirms_nothing():
    """test_h1 ``test_the_join_of_a_cut_question_does_not_block_the_cloud_with_job_ones_text``: «Это называется сублим» was held whole as a confirmation that may still come («это» is a
    confirming word), so the job's turn never opened. A confirmation is ALL confirming words (``_confirmation``); a start of them is still held."""
    assert spoken_lead('Это называется сублим') == 'Это называется сублим'
    assert spoken_lead('Это') == '' and spoken_lead('Да, это верн') == '' and spoken_lead('Совершенно вер') == '' and spoken_lead('Сейчас провер') == ''
    assert spoken_lead('Всё верно.') == '' and spoken_lead('Всё верно.', '', True) == 'Всё верно.' and spoken_lead('Да, это так. Ответ сорок.') == 'Да, это так. Ответ сорок.'


def scene(seed, moves, length, inv):
    from tools.replay import ddmin
    return [v for v in ddmin.play_scene(seed, moves, length, faults=False).violations if v[0] == inv]


def test_p01_scene_a_question_said_over_the_old_final_holds_the_old_answer():
    """c22-break ddmin of P01 (seed 59 of the recorder, 2 moves, no faults): «Ну что, давайте … 40 рублей и … 50 рублей …» goes on 5.4 s past the final of «… 50 рублей и … 40 рублей …»; its final is lost.
    The ear's text shares the words of that final, so it counted as judged by it and the old answer was cued over the new question (``_said_past``)."""
    assert scene(59, [[13, 72.9, 'question', False], [14, 79.6, 'question', False]], 90.0, 'A2') == []


def test_p04_scene_the_next_utterance_is_not_glued_to_the_request():
    """c22-break ddmin of P04 (seed 8 of the recorder): the job of a final got the ear's next breath too («Распознано: A / B»), though the cloud had a turn of its own for it (``_split_after``)."""
    assert scene(8, [[1, 17.6, 'question', False], [2, 21.8, 'fix', False]], 26.4, 'A9') == []

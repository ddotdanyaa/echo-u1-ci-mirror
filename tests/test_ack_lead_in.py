"""Owner-delegated ruling (3 Nov, wave W1, w1_12 step 4): «Значит, …» / «То есть …» before a repeat of the waiting portion is the repeat;
the rest must still be the whole portion - a wrong number or a dropped «не» after the lead-in is never a confirmation."""
import pytest

from echo_sync.classifier import ACK, analyze

SETTINGS = {'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2}


def waiting(portion, nxt='дальше по тексту.'):
    return {'schema': 2, 'revision': 1, 'question': 'q', 'answer': portion + ' ' + nxt, 'chunks': [portion, nxt], 'chunk_index': 0,
            'completed': False, 'pending_turn': None, 'history': []}


@pytest.mark.parametrize('said', ['Значит, Байкал самое глубокое озеро', 'То есть Байкал самое глубокое озеро',
                                  'Итак, Байкал самое глубокое озеро', 'Так вот, Байкал самое глубокое озеро'])
def test_a_repeat_after_a_restatement_lead_in_is_a_repeat(said):
    assert analyze(said, waiting('Байкал — самое глубокое озеро.'), [], SETTINGS).kind == ACK


@pytest.mark.parametrize('said', ['Значит, Байкал самое мелкое озеро', 'То есть Байкал не самое глубокое озеро',
                                  'Значит, Байкал', 'Значит, вода кипит при ста двадцати градусах'])
def test_the_lead_in_never_excuses_a_wrong_or_partial_repeat(said):
    assert analyze(said, waiting('Байкал — самое глубокое озеро.'), [], SETTINGS).kind != ACK
    assert analyze('Значит, вода кипит при ста двадцати градусах', waiting('Вода кипит при ста градусах.'), [], SETTINGS).kind != ACK

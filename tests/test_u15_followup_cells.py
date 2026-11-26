"""U15-S7: one follow-up predicate. The cell report: the four old definitions and ``followup.is_followup`` over the same cells; the disagreements are printed
(``-s``) and pinned, so a new case of the old class moves the predicate, not another phrase list. The old definitions (regex, suffix, ``_follows_on``) are deleted: ``followup.is_followup`` is the only one."""
from echo_sync import settings as cfg
from echo_sync.controlled_media import ControlledMedia
from echo_sync.followup import is_followup, soft

HIST = ['Что учитывает активный счёт?']
CELLS = [
    'почему', 'почему так', 'а почему', 'приведи пример', 'а пример', 'пример', 'подробнее', 'что это', 'что это значит', 'если наоборот',
    'то есть', 'и ещё', 'ну а подробнее', 'а пассивный', 'а потом', 'а сегодня', 'а сколько стоит баррель нефти', 'что такое налог',
    'пример реализации', 'а Новой Зеландии', 'а для ИП', 'привет',
]


def test_the_unified_predicate_covers_the_three_phrases_of_the_classifier():
    for phrase in ('почему так', 'что это', 'а пример'):
        assert is_followup(phrase, strict=True), phrase


def test_bare_primer_is_read_aloud_but_a_primer_is_a_followup():
    assert not is_followup('пример') and not is_followup('пример', HIST)
    assert is_followup('а пример') and is_followup('приведи пример')


def test_strict_leaves_soft_and_single_word_openers_to_the_owner():
    for text in ('то есть', 'и ещё', 'почему', 'подробнее'):
        assert not is_followup(text, strict=True), text
    assert soft('то есть')


def test_a_whole_question_and_talk_are_no_followup():
    for text in ('что такое налог', 'а сколько стоит баррель нефти', 'привет', 'а потом', 'пример реализации', ''):
        assert not is_followup(text, HIST), text
        assert not is_followup(text, loose=False), text


def test_a_swap_is_a_followup_only_with_a_history():
    assert is_followup('а пассивный', HIST)
    assert not is_followup('а пассивный')


def test_loose_is_the_shape_of_a_followup_with_its_lead():
    assert is_followup('а Новой Зеландии', loose=True)
    assert not is_followup('привет', loose=True)
    assert not is_followup('а что такое налог', loose=True)


def test_never_raises_on_odd_input():
    for odd in (None, 5, [], {}, '   '):
        assert is_followup(odd, HIST) is False
        assert is_followup(odd, strict=True) is False


def test_the_switch_is_gone():
    assert 'followup_one' not in cfg.resolve({'followup_one': 'on'})


class _Probe(ControlledMedia):
    def __init__(self):                                   # only what the predicate reads
        self.settings = {}

    def state(self):
        return {'history': [{'question': HIST[0]}]}


def test_the_controller_uses_the_one_predicate():
    probe = _Probe()
    assert probe._follows_on('что это значит') and probe._follows_on('а пассивный')
    assert not probe._follows_on('пример')           # the old regex took a bare «пример»
    assert probe._follows_on('а Новой Зеландии', tail=True) and not probe._follows_on('а что такое налог', tail=True)


def test_classifier_site():
    from echo_sync.classifier import QUESTION, analyze
    state = {'history': [{'question': HIST[0]}], 'question': HIST[0]}
    assert analyze('почему так', state, [], {}).kind == QUESTION

"""The classes the fix of the answer gate rests on (v5_gate.py, rule "answers"): the closed classes (numbers in every spelling, days, a negation that is not one), the
revision of a question (the last one, closed classes only), the answers compared by number-with-unit, polarity and names; the veto that yields to a ready equal answer."""
from echo_sync import v5_gate
from test_v5_gate_same import CHANGED, job_gate


def forbidden(old, now):
    return v5_gate.veto(v5_gate.closed(old), v5_gate.closed(now))


def test_one_number_in_every_spelling_is_no_new_number():
    for old, now in [('Сколько человек 12 ноября', 'Сколько человек 12 ноябрь'), ('Поезд в 18:40', 'Поезд в восемнадцать сорок'), ('Бюджет на второй квартал', 'Бюджет на 2 квартал'),
                     ('Напомни, когда сдаём этап', 'Напомни одну вещь, когда сдаём этап'), ('Почему розетка мертва', 'Почему розетка мертва или нет')]:
        assert forbidden(old, now) is None, (old, now)


def test_a_closed_class_that_turned_is_a_veto_in_every_spelling():
    for old, now, kind in [('Сколько сторон у шестиугольника', 'Сколько сторон у пятиугольника', 'number'), ('Банк работает в пятницу', 'Банк работает в субботу', 'date'),
                           ('Когда придёт', 'Когда придёт послезавтра', 'date'), ('Кофе с сахаром', 'Кофе без сахара', 'negation'), ('Это семинар', 'Это семинар', None),
                           ('Какой третий квартал', 'Какой четвёртый квартал', 'date')]:
        assert forbidden(old, now) == kind, (old, now)


def test_only_the_last_revision_counts_and_a_pause_or_a_filler_is_none():
    assert v5_gate.revising('нет, пятьдесят на два') and v5_gate.revising('а в пятницу?') and v5_gate.revising('ой, всё, сорок')
    assert not v5_gate.revising('раз, два, подожди') and not v5_gate.revising('ну, не знаю') and not v5_gate.revising('одну секунду') and not v5_gate.revising('это длинная реплика про сорок разных дел')


def test_a_veto_yields_to_an_answer_for_the_present_form_that_is_there_and_does_not_differ_but_not_to_one_that_differs_or_is_not_there():
    q = ('Во сколько закрывается банк', 'Слушай, не подскажешь, во сколько закрывается банк')
    for newer, would, code in [(('Закрывается в шесть.', True), 'pass', 'veto_overruled'), (('Закрывается в семь.', True), 'refuse', 'veto_negation'), (None, 'refuse', 'veto_negation'),
                               (('Закрывается', False), 'refuse', 'veto_negation')]:
        c, gate, a, notes = job_gate(*q, 'Закрывается в шесть.', newer=newer)
        gate.handed(a, 101.0)
        assert (notes[0][1]['would_answers'], notes[0][1]['code_answers']) == (would, code), (newer, notes[0][1]['code_answers'])
        assert notes[0][1]['code_answers'] in v5_gate.CODES


def test_the_state_is_the_calls_not_the_gates():
    c, gate, a, notes = job_gate(*CHANGED, 'Около 2 миллионов.', newer=('Около', False), mode='on')
    again = v5_gate.attach({'v5_answer_gate': 'on'}, c, gate.wire)
    assert again.parked is gate.parked and again.refused is gate.refused and again.seen is gate.seen

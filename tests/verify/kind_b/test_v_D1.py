"""D1 (break world w09): the provider numbers its turns from the start once the microphone is re-opened: the same id with OTHER speech is a new utterance, never the clarification of the first. A refined transcript of the same speech stays a revision (DEF-STATE-03)."""
import helpers_s6_ack as H
from echo_sync.voice_turns import FramelessTurns

STORY = ('Инерция — это свойство тела сохранять скорость, пока на него не действует сила. '
         'Чем больше масса у тела, тем сильнее проявляется его инерция при разгоне. '
         'Именно поэтому тяжёлый грузовик останавливается дольше лёгкого автомобиля.')


def test_d1_reused_turn_id_with_other_speech_moves_the_cursor_through_the_real_controller(tmp_path):
    d = H.Dictation(tmp_path / 'd', STORY)
    before, plan = d.index, d.chunks
    assert d.say(plan[before], tid='u-1').after == before + 1
    again = d.say(plan[before + 1], tid='u-1')
    assert again.after == before + 2, f'the reused id was swallowed (cursor {again.after})'


def test_d1_a_retransmit_of_either_final_is_no_third_turn_and_a_refinement_stays_a_revision():
    f = FramelessTurns()
    first, second = 'раз два три четыре пять шесть', 'семь восемь девять десять одиннадцать двенадцать'
    f.apply(H.done('u-1', 'user', first))
    assert f.apply(H.done('u-1', 'user', second))['id'] != 'u-1'
    assert f.apply(H.done('u-1', 'user', first)) is None and f.apply(H.done('u-1', 'user', second)) is None
    f.apply(H.done('r', 'user', 'Сколько будет пятнадцать процентов от двухсот'))
    refined = f.apply(H.done('r', 'user', 'Сколько будет пятнадцать процентов от 200'))
    assert refined['id'] == 'r' and refined['revisions'] == 1


def test_d1_the_third_final_is_compared_with_the_last_speech_and_words_to_figures_is_no_new_turn():
    f = FramelessTurns()
    f.apply(H.done('u', 'user', 'раз два три четыре пять шесть'))
    second = f.apply(H.done('u', 'user', 'семь восемь девять десять одиннадцать двенадцать'))
    refined = f.apply(H.done('u', 'user', 'семь восемь девять десять одиннадцать тринадцать'))
    assert refined['id'] == second['id'] and refined['revisions'] == 1, 'the refinement of the second speech is no third turn'
    assert f.effective('u') == second['id']
    g = FramelessTurns()
    g.apply(H.done('n', 'user', 'сколько будет двести сорок пять тысяч шестьсот рублей без налога'))
    assert g.apply(H.done('n', 'user', 'сколько 245 600 руб без налога'))['id'] == 'n'
    g.apply(H.done('s', 'user', 'Амплитуда зависит от цвета подвеса.'))
    assert g.apply(H.done('s', 'user', 'Амплитуда должна быть небольшой.'))['id'] == 's'

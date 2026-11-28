"""U35 (a): a long ask with no question word («реформы Петра первого подробно, с датами и причинами …») whose model answer is substantive and on its subject is published;
chatter (the model's reply is not about the words) is still declined by ``_talk_no_question``. Through the real controller: the rig of h31."""
import pytest

from test_h31_rules import asked, model_says, new, rig      # noqa: F401 - rig is the fixture
from tools.replay import repeat_scenes as R

ASK = ('Реформы Петра первого подробно с датами и причинами каждой из них и с последствиями для страны и для народа и для соседей по Европе тоже')
ANSWER = 'Реформы Петра Первого изменили страну: армия, флот, налоги, управление, и причинами были война и отставание от Европы.'
CHATTER = ('Вот мы сегодня с другом проверяли это всё целый вечер и снова вернулись, а потом опять всё то же самое, причём уже поздно, '
           'мы поговорили четырнадцать минут, и опять вернулись к этому')


def run(rig, said, reply):
    asked(rig)
    mark = len(rig.cues())
    R.utter(rig, said)
    rig.pump(0.5)
    model_says(rig, reply)
    rig.pump(4.0)
    return mark


def test_a_long_ask_with_no_question_word_is_answered_by_the_model(rig):
    assert len(ASK.split()) >= 25 and rig.c._long_talk(ASK, rig.c.state())
    mark = run(rig, ASK, ANSWER)
    assert new(rig, mark, 'Реформы Петра Первого изменили'), [c.text for c in rig.cues()[mark:]]


@pytest.mark.parametrize('reply', ['Хорошо, понял вас, продолжайте, я слушаю внимательно.', 'Да, это понятно, так бывает, когда долго работаешь вечером.'])
def test_long_chatter_is_still_declined_whatever_the_model_replies(rig, reply):
    mark = run(rig, CHATTER, reply)
    assert not new(rig, mark, 'продолжайте') and not new(rig, mark, 'Да, это понятно')

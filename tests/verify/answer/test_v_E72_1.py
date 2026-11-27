"""V3 E72.1: a personal question about changing data (an account, the weather where the listener is, a calendar, a parcel) gets the short honest reply at once from the local source (``cm_route._personal_reply`` ->
``personal_volatile.honest_reply``), not 8 s of silence and «Нет ответа»; the privacy is not loosened: no public search for it. A question with a named place or a task is not taken for a personal one.

Real ControlledMedia and wire (rig ``call``, the profile of the working call). The bound «before 8 s» is taken as 2 s of the world's clock after the final. Not run on the laptop."""
import pytest

from answer_kit import LIVE, TICK, call, say_question, texts      # noqa: F401
from echo_sync.personal_volatile import honest_reply, personal_volatile
from echo_sync.textutil import normalize

PERSONAL = [('Сколько у меня сейчас на счету?', 'account'), ('Какая у меня погода?', 'weather'), ('Что у меня сегодня в календаре', 'calendar'), ('Где моя посылка?', 'parcel')]
OTHERS = ['Какая погода в Казани сегодня?', 'Если у меня на счету 5000 рублей, сколько будет через год?']


@pytest.mark.parametrize('text,kind', PERSONAL, ids=[kind for _, kind in PERSONAL])
def test_a_personal_question_gets_its_honest_reply_at_once(call, text, kind):
    assert personal_volatile(text) == kind, 'precondition: the classifier says so'
    rig = call(**LIVE)
    began = rig.w.clock.t
    say_question(rig, text)
    rig.pump(2.0)
    cues = rig.cues()
    assert cues, 'E72.1: nothing was said'
    assert cues[0].t - began <= 2.5, f'first sound after {cues[0].t - began:.1f} s'
    assert normalize(cues[0].text) in normalize(honest_reply(kind)), cues[0].text
    assert rig.w.lookup_calls == [], 'the privacy: a question about one\'s own data goes to no public search'


@pytest.mark.parametrize('text', OTHERS)
def test_a_question_that_is_not_personal_is_not_answered_with_the_honest_reply(call, text):
    rig = call(**LIVE)
    say_question(rig, text)
    rig.pump(2.0)
    replies = {normalize(honest_reply(kind)) for _, kind in PERSONAL}
    assert not any(normalize(t) in replies for t in texts(rig)), texts(rig)

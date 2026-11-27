# factory-backlog-id: E-Q05
"""E-Q05 (SC6 «a correction and three roads»): «Это неверно» after an answer gives the corrected answer at once, and only it sounds, whatever the order of the three roads.

Decision 26.11-2: a remark that denies the answer just said is a correction by its meaning; ECHO gives the corrected answer and does not ask what to correct; the answer is spoken once, whichever road brings it.
Scene in seconds: 0 s «Сколько будет двенадцать умножить на пять?», the answer «Шестьдесят.» sounds; at 6 s the person says «Это неверно».
After the correction the corrected answer «Семьдесят два.» can come from three roads: the cloud (GPT-Live), the first road of the text, the reserve road of the text; they are due 0.6 s, 1.8 s and 3.2 s after the correction (the reserve road counts from its own start) in all 6 orders.
At 4 s after the correction the cloud also brings the OLD answer «Шестьдесят.» of the first question, last of everything.
One rule for all 6 orders (the first 5.5 s after the correction): «Семьдесят два» is heard once, the old «Шестьдесят» is not heard after the correction, the system does not ask what to correct and says no phrase of itself.
The REAL host (controlled_host.serve, ControlledMedia, NativeMediaSocket), only the phone, the helper pipe, SAPI and the roads are the stand's."""
import itertools

import pytest

from bk_common import BStand, Heard, late, ok, run_stand

pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of this scene (tests/conftest.py)

QUESTION = 'Сколько будет двенадцать умножить на пять?'
OLD = 'Шестьдесят.'
NEW = 'Семьдесят два.'
CORRECTION = 'Это неверно'
ARRIVE_S = (0.6, 1.8, 3.2)           # after the correction: the first, the second, the third road
OLD_LATE_S = 4.0                     # after the correction: the old answer of the cloud comes, last of all
WINDOW_S = 5.5                       # what is judged: the first 5.5 s after the correction (a spoken answer that nobody confirmed is repeated by the host about 6 s later, that is another rule)
ROADS = ('cloud', 'codex', 'groq1')


def _norm(text):
    return ' '.join(str(text).casefold().replace('ё', 'е').split())


def _scene(tmp_path, order):
    """``order``: the roads in the order of their arrival. Returns what was heard after the correction."""
    at = dict(zip(order, ARRIVE_S))
    stand = BStand({'codex': ok(OLD)})

    async def body(host, stand):
        t1 = await stand.ask(host, QUESTION, uid='u1', lag=0.0)
        await host.advance(6.0)
        before = Heard(host, t1)
        assert 'шестьдесят' in _norm(before.text), f'the first answer did not sound before the correction: {before.text!r}'
        stand.plan.clear()
        stand.plan['codex'] = late(at['codex'], NEW)
        stand.plan['groq1'] = late(at['groq1'], NEW)
        t_c = await stand.ask(host, CORRECTION, uid='u2', lag=0.0)
        await host.advance(at['cloud'])
        await host.answer(NEW, tid='a2')
        await host.advance(OLD_LATE_S - at['cloud'])
        await host.answer(OLD, tid='a1')
        await host.advance(14.0)
        return Heard(host, t_c, until=t_c + WINDOW_S)
    return run_stand(tmp_path, stand, body)


def test_a_denied_answer_is_corrected_at_once_and_only_the_corrected_one_sounds_in_every_order_of_the_three_roads(tmp_path):
    faults = []
    for n, order in enumerate(itertools.permutations(ROADS)):
        saw = _scene(tmp_path / f'o{n}', order)
        text = _norm(saw.text)
        heard_new, old, service = text.count('семьдесят два'), 'шестьдесят' in text, len(saw.service)
        first = saw.first_sound(saw.answers)
        if heard_new != 1 or old or service:
            faults.append(f'[{" > ".join(order)}] 72 heard {heard_new}x (must be 1), old 60 heard: {old}, phrases of the system: {service}, first sound at {first} s')
    assert not faults, ' | '.join(faults)

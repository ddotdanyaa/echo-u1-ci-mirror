"""U237 break tests, families «answer» and «the road to the model / reserve»: the roads of the text say garbage, break in the middle, or all fail. What the owner met on the phone: a cloud that is silent,
an answer of one word, a model that returned nothing but a mark, a link that fell in the middle of a sentence. The REAL host with only the roads of the text faked (tests/helpers_always_answer.py).
A red test here is a found defect: it is never to be weakened."""
import pytest

import helpers_always_answer as H
from bk_common import ALIVE_BOUND_S, MARKS, Heard, BStand, M, Q_INERTIA, SYNTH_TICK_S, TOPIC, core, cut, fail, hang, late, ok, run_stand, words_of


def test_b08_every_road_torn_off_after_its_first_word_no_fragment_is_dictated_and_the_listener_is_not_left_silent(tmp_path):
    """Class «the link fell in the middle of the answer» + «the reserve fell too». Each road says one word and breaks (RemoteProtocolError). A one-word fragment is not an answer: the phone hears either a whole
    answer or the phrase of the system, within the bound of «never silence»."""
    plan = {'codex': cut('RemoteProtocolError'), 'groq1': cut('RemoteProtocolError'), 'groq2': cut('RemoteProtocolError'), 'gemini': cut('RemoteProtocolError')}
    stand = BStand(plan, default=cut('RemoteProtocolError'))

    async def body(host, stand):
        q = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.2)
        await host.advance(18.0)
        return Heard(host, q)
    saw = run_stand(tmp_path, stand, body)
    fragments = [i['text'] for i in saw.answers + saw.other if len(words_of(i['text'])) < 3]
    assert not fragments, f'a fragment of a road that broke was dictated: {fragments!r}'
    first = saw.first_sound()
    assert first is not None and first <= ALIVE_BOUND_S + SYNTH_TICK_S, f'silence after every road broke (first sound {first}): {saw.text!r}'


def test_b09_a_reserve_road_torn_off_after_its_word_the_next_reserve_road_answers_whole(tmp_path):
    """Class «the reserve is cut in the middle». Codex refuses, the first Groq says one word and breaks, the second Groq is healthy: the listener hears the whole answer of the second, not the word of the first."""
    stand = BStand({'codex': fail('http_429'), 'groq1': cut('RemoteProtocolError'), 'groq2': ok()})

    async def body(host, stand):
        q = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.2)
        await host.advance(16.0)
        return Heard(host, q)
    saw = run_stand(tmp_path, stand, body)
    assert MARKS['groq2'] in saw.text, f'the healthy road did not answer: {saw.text!r}'
    fragments = [i['text'] for i in saw.answers + saw.other if len(words_of(i['text'])) < 3]
    assert not fragments, f'a fragment of the broken road was dictated: {fragments!r}'
    first = saw.first_sound(saw.answers)
    assert first is not None and first <= M + SYNTH_TICK_S, f'the whole answer came {first} s after the question'


JUNK = ['...', '—', '​', ' . ', 'None', 'null', '[]']


@pytest.mark.parametrize('junk', JUNK, ids=['dots', 'dash', 'zero-width', 'dot', 'None', 'null', 'brackets'])
def test_b10_a_road_that_returns_a_mark_and_no_words_is_no_answer(tmp_path, junk):
    """Class «the model returned emptiness or rubbish». The first road streams a text with no word in it (a mark, a null, a zero-width space; a blank is already no word, a mark is not). The next road is healthy.
    The phone must not hear the rubbish as the answer: it hears a real answer or the phrase of the system, in time."""
    stand = BStand({'codex': ok(junk), 'groq1': late(0.5)})

    async def body(host, stand):
        q = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.2)
        await host.advance(18.0)
        return Heard(host, q)
    saw = run_stand(tmp_path, stand, body)
    rubbish = [i['text'] for i in saw.items if core(i['text']) in (core(junk), '') or core(i['text']) in ('none', 'null')]
    assert not rubbish, f'the rubbish of the road was dictated as the answer: {rubbish!r} (all: {saw.text!r})'
    first = saw.first_sound()
    assert first is not None and first <= ALIVE_BOUND_S + SYNTH_TICK_S, f'silence (first sound {first}): {saw.text!r}'
    assert TOPIC[Q_INERTIA] in saw.text or saw.service, f'neither the answer of the next road nor the phrase of the system was heard: {saw.text!r}'

"""W1F-B, class C2 for a request served locally (W1 group G4 TR-FRAG, w1_08 step 4): the fragments of one return never undo it.

w1_08 step 4 (W1 run 20261103-031522): the provider split «Вернёмся к цунами. На чём мы остановились?» into « Вернёмся к цунами»
(34.430 s) | « На чём мы» (36.095) | « остановились» (37.085). The first restored the unfinished tsunami answer at its saved cursor (cue
«всего начинается»); the second, alone a question («на чём»), retired it at once and the cloud's recap «Остановились на том, что…» was
dictated as a new answer.

The rule now: a fragment that began within ``coalesce_seconds`` of a request the controller served locally (going on: «дальше»,
«продолжай», a return to an unfinished answer) and that names nothing of its own (only question words, pronouns, function words) goes on
with that request when the request joined with it still is one: it changes nothing. A real question after it («А что это?» joined with
«Дальше» is a question) is answered as before.
"""
from helpers_w1f import Wire

TSUNAMI_Q = 'Расскажи, как возникает цунами'
TSUNAMI = ' Цунами чаще всего начинается с внезапного смещения морского дна — например, при землетрясении, оползне или извержении.'


def tsunami_left_for_the_guitar(tmp_path):
    w = Wire(tmp_path)
    w.user('u1', TSUNAMI_Q, 0.0, 2.0)
    w.assistant('a1', TSUNAMI, 2.05, 4.0)
    w.confirm(5.5)                                                # the first portion confirmed: the second waits
    w.user('u3', ' Теперь о другом, сколько струн у обычной гитары', 8.0, 9.0)
    w.assistant('a2', ' Обычная гитара обычно имеет шесть струн.', 9.05, 10.0)
    return w


def test_the_fragments_of_one_return_never_retire_the_answer_it_restored(tmp_path):
    w = tsunami_left_for_the_guitar(tmp_path)
    w.user('u4', ' Вернёмся к цунами', 12.0, 12.5)
    w.assistant('a3', ' Конечно, давай.', 12.55, 12.8)
    w.user('u5', ' На чём мы', 12.9, 14.2)
    w.assistant('a4', ' Остановились на том,', 14.25, 14.5)
    w.user('u6', ' остановились', 14.55, 15.2)
    w.assistant('a5', ' что при смещении дна поднимается огромный объём воды и расходится во все стороны.', 15.25, 17.0)
    w.until(24.0)
    later = w.played_after(12.0)
    assert later and later[0] == w.played[1][1], w.played           # the saved cursor: the portion after the confirmed one
    assert not any('Остановились' in text or 'при смещении' in text for text in later), w.played
    assert w.state().get('question') == TSUNAMI_Q, w.state().get('question')


def test_a_real_question_after_a_local_request_is_still_a_question(tmp_path):
    w = tsunami_left_for_the_guitar(tmp_path)
    w.user('u4', ' Вернёмся к цунами', 12.0, 12.5)
    w.user('u5', ' А что такое оползень', 13.0, 14.2)
    w.assistant('a4', ' Оползень — это сход грунта по склону.', 14.25, 15.5)
    w.until(24.0)
    assert w.c.question_id == 'u5' and any('грунта' in text or 'сход' in text for text in w.played_after(14.2)), w.played

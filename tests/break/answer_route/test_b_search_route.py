"""U237 break tests, family «the road to the search, the model and the reserve»: the search hangs, fails, returns garbage or someone else's document, finds nothing; a personal question must not reach
the PUBLIC search (neither the primary one nor the reserve); a question about a rate that changes is never answered from memory with an invented number. The REAL host (controlled_host.serve,
ControlledMedia, NativeMediaSocket, the lookup of the host) with only the network faked (tests/helpers_always_answer.py: the roads of the text and the reserve search; tests/helpers_s6_fault.py: the primary
search module, ``HostRig.search_module``). A red test here is a found defect: it is never to be weakened."""
import asyncio
import logging

import pytest

import helpers_s6_fault as F
from bk_common import ALIVE_BOUND_S, MARKS, Heard, BStand, M, Q_CODE, Q_INERTIA, Q_RATE, Q_VAT, SYNTH_TICK_S, fail, hang, late, local_call, ok, run_stand
from echo_sync.generator import CHANGES, route_need

LOOKUP_BOUND_S = 22.0           # the lookup is let go at 8 s, the cloud's wait for an answer after a lookup is 20 s (timer_policy.LOOKUP_ANSWER_WAIT_SECONDS): never silence beyond it


class Rows:
    """``api._echo_quick_lookup_module()`` that returns what the test gives (the primary search of the host); ``asked``: the question of every search."""

    def __init__(self, rows):
        self.rows, self.asked = rows, []

    def search(self, question, limit, home, timeout=None, force_refresh=False):
        self.asked.append(question)
        rows = self.rows(question) if callable(self.rows) else self.rows
        return {'success': True, 'data': {'web': rows}}


def public_queries(stand, host):
    """Everything that left for a PUBLIC search: the questions of the primary lookup and the bodies of the reserve search."""
    return [str(call[1]) for call in host.lookup_plan.calls] + list(stand.search_bodies)


@pytest.mark.parametrize('roads', ['dead', 'alive'])
def test_b11_the_primary_search_hangs_the_listener_is_not_left_in_silence(tmp_path, roads):
    """Class «the search hangs» (K-search, F17). The search of the host never answers (600 s), the reserve search is refused, the cloud is silent. The lookup is let go at 8 s: the listener hears the honest
    phrase or an answer, not silence, within the bound of the lookup."""
    stand = BStand({'codex': fail('http_429')} if roads == 'dead' else {'codex': ok('Это решает правительство, точную цифру не назову.')})

    async def body(host, stand):
        host.run_scoped_delay = 600.0
        q = await stand.ask(host, Q_VAT, uid='u1', lag=0.2)
        await host.advance(26.0)
        return Heard(host, q), host.finished
    saw, finished = run_stand(tmp_path, stand, body)
    first = saw.first_sound()
    assert first is not None and first <= LOOKUP_BOUND_S, f'silence: a search that hangs left the listener with nothing (first sound {first}): {saw.text!r}'
    assert not finished, 'the call ended because of a search that hangs'


def test_b12_a_search_that_fails_with_the_question_in_its_message_does_not_put_the_question_into_the_logs(tmp_path):
    """Class «the private text in the log» (the rule of the logs: class and reason, no user text). The search raises an error whose MESSAGE holds the question. The log of the host and the log of the
    process must not carry the question, whatever the level."""
    question = 'Какая сейчас ставка НДС для ООО Ромашка?'
    stand = BStand({'codex': fail('http_429')})

    async def body(host, stand):
        q = await stand.ask(host, question, uid='u1', lag=0.2)
        await host.advance(20.0)
        return Heard(host, q), host.logger.text(logging.DEBUG)
    with F.capture_logs() as logs:
        saw, host_log = run_stand(tmp_path, stand, body, lookup=['raise'])
    assert 'Ромашка' not in host_log, f'the question is in the log of the host: {host_log[:300]!r}'
    assert 'Ромашка' not in logs.text(logging.DEBUG), 'the question is in the log of the process'
    assert saw.first_sound() is not None, 'silence after a failed search'


def test_b13_garbage_rows_of_the_search_are_never_spoken_nor_given_to_the_model(tmp_path):
    """Class «the search returns garbage». The rows: None, a string, a number, a local file address with a text, and one good row. The local file and its text must reach neither a road of the model nor the phone;
    the call goes on and the listener hears something."""
    rows = [None, 'x', 7, {'url': 'file:///C:/secret', 'text': 'ФАЙЛ-СЕКРЕТ'}, {'url': 'https://example.org/ok', 'title': 'Ставка НДС', 'text': 'Ставка НДС задана законом.'}]
    stand = BStand({'codex': ok('Ставка НДС задана законом.')})

    async def body(host, stand):
        host.search_module = Rows(rows)
        q = await stand.ask(host, Q_VAT, uid='u1', lag=0.2)
        await host.advance(22.0)
        return Heard(host, q), host.finished
    saw, finished = run_stand(tmp_path, stand, body)
    assert 'ФАЙЛ-СЕКРЕТ' not in stand.asked_text(), 'the text of a local file went to the model'
    assert 'ФАЙЛ-СЕКРЕТ' not in saw.text, 'the text of a local file was spoken'
    assert not finished and saw.first_sound() is not None, f'the call fell or fell silent (finished={finished}, heard {saw.text!r})'


PERSONAL = [
    'Что мой врач сказал про анализы?',
    'Сколько мне осталось платить по кредиту в Сбербанке?',
    'Какая сейчас ставка НДС, если у меня ИП и мой ИНН 770123456789?',
    'Какой сейчас курс доллара, пишу вам с почты ivan.petrov@mail.ru?',
    'Проверь, не заблокирована ли карта 4276 1234 5678 9012 в Сбербанке.',
    'Сколько я должен налогов за прошлый год?',
]


@pytest.mark.parametrize('question', PERSONAL)
def test_b14_a_personal_question_never_reaches_a_public_search(tmp_path, question):
    """Class «a personal question in the public search» (w9-safe, E88). Neither the search of the host nor the reserve search (Groq's browser_search) may be asked a question about the owner: no call of the
    primary lookup, no request of the reserve search. Every road of the text is alive: the call is not an excuse."""
    stand = BStand({'codex': ok('Это личный вопрос, у меня нет ваших данных.')})

    async def body(host, stand):
        q = await stand.ask(host, question, uid='u1', lag=0.2)
        await host.advance(22.0)
        return Heard(host, q), public_queries(stand, host)
    saw, left = run_stand(tmp_path, stand, body)
    assert not left, f'a personal question went to a public search: {[x[:160] for x in left]}'


LEAKS = [
    ('Позвони по номеру восемь девятьсот шестнадцать сто двадцать три сорок пять шестьдесят семь и скажи, какой сейчас курс доллара.', 'девятьсот шестнадцать'),
    ('Напиши на почту иван точка петров собака мейл точка ру и скажи, какая сейчас ставка НДС.', 'собака'),
    ('Мы с женой хотим узнать, сколько сейчас стоит лечение онкологии у жены в онкоцентре на Каширке.', 'жены'),
]


@pytest.mark.parametrize('question, token', LEAKS, ids=['phone-in-words', 'mail-in-words', 'health-of-a-relative'])
def test_b15_what_the_gate_does_not_see_still_does_not_leave_for_the_public_search(tmp_path, question, token):
    """Class «a personal detail slips past the regular expressions». A phone and a mail said in WORDS (the ear writes words), a diagnosis of a relative. If the question goes to a public search at all, the
    detail must be cut out of it: the token must stand in no query of the primary lookup and no body of the reserve search."""
    stand = BStand({'codex': ok('Точных данных у меня нет.')})

    async def body(host, stand):
        q = await stand.ask(host, question, uid='u1', lag=0.2)
        await host.advance(22.0)
        return public_queries(stand, host)
    left = run_stand(tmp_path, stand, body)
    leaked = [x[:200] for x in left if token in x.casefold()]
    assert not leaked, f'a personal detail went to a public search: {leaked}'


def test_b16_the_rows_about_another_code_are_not_the_source_of_an_answer_about_this_one(tmp_path):
    """Class «the search found nothing in the materials, found someone else's document» (A3-1). The question is about article 19 of the TAX code; the only row is article 19 of the law on consumer
    rights. The text of the other law reaches neither the model nor the phone."""
    rows = [{'url': 'https://example.org/z', 'title': 'Статья 19. Права потребителя', 'text': 'Закон о защите прав потребителей ТРУДОВОЙ-ЯД: статья 19 устанавливает налоговые права потребителя.'}]
    stand = BStand({'codex': ok('Статья определяет налогоплательщиков.')})

    async def body(host, stand):
        host.search_module = Rows(rows)
        q = await stand.ask(host, Q_CODE, uid='u1', lag=0.2)
        await host.advance(22.0)
        return Heard(host, q)
    saw = run_stand(tmp_path, stand, body)
    assert 'ТРУДОВОЙ-ЯД' not in stand.asked_text(), 'the text of the other law was handed to the model as the source'
    assert 'ТРУДОВОЙ-ЯД' not in saw.text, 'the text of the other law was spoken'


@pytest.mark.parametrize('question, said, number', [(Q_VAT, 'Ставка НДС в России сейчас составляет 37 процентов.', '37'), (Q_RATE, 'Курс доллара сейчас составляет 123 рубля.', '123')],
                         ids=['vat', 'dollar'])
def test_b17_a_rate_that_changes_with_no_source_is_not_answered_from_memory_with_a_number(tmp_path, question, said, number):
    """Class «a search with no answer in the materials: the number is made up» (route_need CHANGES, «a rate is never made up»). No search finds anything (the primary is empty, the reserve is refused); a road of the
    model says a number nobody confirmed. The number must not be heard; the listener hears the honest «not found» (or anything without the number), in time."""
    F.precondition(route_need(question, ()) == CHANGES, 'the question must be of the level CHANGES')
    stand = BStand({'codex': ok(said)})

    async def body(host, stand):
        q = await stand.ask(host, question, uid='u1', lag=0.2)
        await host.advance(26.0)
        return Heard(host, q)
    saw = run_stand(tmp_path, stand, body, lookup=['empty'])
    assert number not in saw.text, f'a number that no source confirmed was spoken: {saw.text!r}'
    first = saw.first_sound()
    assert first is not None and first <= LOOKUP_BOUND_S, f'silence after a search with no answer (first sound {first})'


def test_b18_the_slow_search_of_the_old_question_does_not_feed_the_new_one(tmp_path):
    """Class «the old answer after the new question», on the road of the search. The search of question 1 (VAT) takes 6 s; question 2 (the dollar) is asked at 1.5 s and its search is quick. When the rows of
    question 1 arrive they are of another question: they reach no road of the model after question 2 and the phone does not hear them."""
    stand = BStand({'codex': ok('Курс устанавливает Центральный банк.')})

    async def body(host, stand):
        def rows_of(question):
            tag = 'ПЕРВЫЙ-ЯД' if 'НДС' in question else 'ВТОРОЙ-ОК'
            return [{'url': 'https://example.org/' + ('a' if tag == 'ПЕРВЫЙ-ЯД' else 'b'), 'title': question, 'text': tag + ' ' + question}]
        module = host.search_module = Rows(rows_of)

        async def run_scoped(profile, fn, executor=None):
            result = fn()
            if 'НДС' in module.asked[-1]:
                await asyncio.sleep(6.0)
            return result
        host.api._run_scoped = run_scoped
        await stand.ask(host, Q_VAT, uid='u1', lag=0.2)
        await host.advance(1.2)
        q2 = await stand.ask(host, Q_RATE, uid='u2', lag=0.2)
        await host.advance(22.0)
        return Heard(host, q2), q2
    saw, q2 = run_stand(tmp_path, stand, body)
    assert 'ПЕРВЫЙ-ЯД' not in stand.asked_text(q2), 'the rows of the old question were handed to a road of the model after the new question'
    assert 'ПЕРВЫЙ-ЯД' not in saw.text, 'the rows of the old question were spoken after the new question'
    assert saw.first_sound() is not None, 'the new question got no sound at all'


def test_b19_search_dead_roads_dead_and_no_cloud_one_phrase_in_time_not_a_loop(tmp_path):
    """Class «the reserve fell too». No GPT-Live, every road of the text refuses, the search raises: the listener hears ONE honest phrase in time (a phrase of the system is rate-limited, never a loop), and the
    call stays open."""
    stand = BStand({'codex': fail('http_429')})

    async def body(host, stand):
        await open_it(host)
        q = await stand.ask(host, Q_VAT, cloud=False, uid='u1')
        await host.advance(9.5)
        return Heard(host, q), host.finished
    saw, finished = run_stand(tmp_path, stand, body, lookup=['raise'], **local_call())
    first = saw.first_sound()
    assert first is not None and first <= M + SYNTH_TICK_S, f'silence: no phrase after every road and the search failed (first sound {first})'
    assert len(saw.service) <= 1, f'the phrase of the system was said {len(saw.service)} times in 9.5 s: {[i["text"] for i in saw.service]}'
    assert not finished, 'the call ended'


def test_b20_search_hangs_in_the_local_mode_the_listener_is_not_left_in_silence(tmp_path):
    """Class «the search hangs», local mode (no cloud). The search of the host never answers, the reserve search is refused, every road of the text refuses."""
    stand = BStand({'codex': fail('http_429')})

    async def body(host, stand):
        await open_it(host)
        host.run_scoped_delay = 600.0
        q = await stand.ask(host, Q_VAT, cloud=False, uid='u1')
        await host.advance(26.0)
        return Heard(host, q)
    saw = run_stand(tmp_path, stand, body, **local_call())
    first = saw.first_sound()
    assert first is not None and first <= LOOKUP_BOUND_S, f'silence in the local mode with a search that hangs (first sound {first}): {saw.text!r}'


def test_b21_the_link_to_the_model_falls_in_the_middle_of_its_answer_the_text_road_answers_whole(tmp_path):
    """Class «the link fell in the middle of the answer». The cloud begins to answer (a created turn and a first piece), then the pipe to the helper ends (EOF). The road of the text, asked in the same
    time, answers the question whole; the call goes on."""
    stand = BStand({'codex': fail('http_429'), 'groq1': late(3.0)})

    async def body(host, stand):
        q = await stand.ask(host, Q_INERTIA, uid='u1', lag=0.2)
        host.cloud(F.created('a1', 'assistant', 'Инерция — это'))
        await host.advance(0.3)
        host.bridge.inbox.put_nowait(None)
        await host.advance(18.0)
        return Heard(host, q), host.finished
    saw, finished = run_stand(tmp_path, stand, body)
    assert MARKS['groq1'] in saw.text, f'nobody answered after the link fell: {saw.text!r}'
    assert not finished, 'the call ended when the pipe to the helper ended'


async def open_it(host):
    from helpers_always_answer import open_local
    await open_local(host)
    await host.advance(1.0)

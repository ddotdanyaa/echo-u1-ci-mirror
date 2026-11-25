"""w3-integ (cloud_context/tasks/WAVE3.md items 14 and 15): queue 1а of BACKLOG_ECHO.md (E88, E87.1, E89, W17, W03) and the shared client of T1 (``_renew``). Every test here was red on the code
before its patch (cloud_context/reports/w3-integ.md has the commands and their output)."""
import pytest

from echo_sync.controlled_media import ControlledMedia

# ---- E88: the privacy gate of the public lookup knows «мою», «мне», «меня», «нам», «наш»; a general question that only says «скажи мне» keeps its lookup ----------------------------------------------

PERSONAL = ['какая ставка налога на мою зарплату', 'сколько мне платить налога', 'посчитай налог на мою зарплату сто тысяч', 'сколько меня ещё будут проверять', 'сколько нам начислят процентов по вкладу',
            'когда истекает наш договор аренды', 'какой налог на нашу квартиру', 'что будет с нашими вкладами в банке', 'почему мне отказали в вычете', 'когда меня вызовут в налоговую']
PUBLIC = ['скажи мне, что такое инфляция', 'объясни мне, как считается НДС', 'напомни мне, в каком году было крещение Руси', 'подскажи мне ставку НДС', 'расскажи мне про амортизацию',
          'мне интересно, что такое амортизация', 'меня интересует, какая ставка НДС', 'какая ставка НДС', 'в каком году была битва при Калке', 'что такое наша эра']


@pytest.mark.parametrize('question', PERSONAL)
def test_e88_a_personal_question_never_reaches_the_public_lookup(question):
    assert not ControlledMedia.public_lookup_allowed(question, True)


@pytest.mark.parametrize('question', PUBLIC)
def test_e88_a_general_question_with_a_word_of_the_first_person_keeps_its_lookup(question):
    assert ControlledMedia.public_lookup_allowed(question, True)


@pytest.mark.parametrize('remark', ['Какой следующий вопрос нам задать сейчас?', 'Так, а какой у нас дальше, ну, вопрос по списку'])
def test_e88_only_the_search_reads_the_wider_words_the_job_still_judges_the_remark(remark):
    """H6 n1_03 step 18: talk with «нам» in it goes to the job as before; it only never goes to the public search."""
    assert ControlledMedia.public_lookup_allowed(remark)


# ---- E87.1: the lookup prepared on the partial is adopted «by meaning» (search_identity.same_meaning): the rule of the early lookup, no key ------------------------------------------------------------

def _adopted(question='что в статье 19 НК РФ?'):
    import asyncio
    from echo_sync.native_prefetch import EarlyLookup

    async def run():
        calls = []

        async def fetch(q):
            calls.append(q)
            return [{'text': q}]

        async def trace(*a, **k):
            pass
        e = EarlyLookup(fetch, trace, enabled=True)
        e.observe('u', 'Что говорится в девятнадцатой статье Налогового кодекса', now=0)
        await e.tick(now=1)
        await asyncio.sleep(0)
        await e.resolve('u', question)
        await e.close()
        return len(calls)
    return asyncio.run(run())


def test_e87_1_another_wording_of_the_same_question_adopts_the_prepared_lookup():
    assert _adopted() == 1


def test_e87_1_another_number_is_another_request():
    assert _adopted('что в статье 20 НК РФ?') == 2


def test_e87_1_the_key_is_gone_from_the_settings():
    from echo_sync.settings import DEFAULTS, resolve
    assert 'prefetch_same_meaning' not in DEFAULTS and 'prefetch_same_meaning' not in resolve({'prefetch_same_meaning': 'on'})


# ---- E89: numbers aloud. The voice reads «40 000» as «сорок ноль ноль ноль» (WAV checked on the laptop 17:15): the path render_cue_pcm gives the synthesizer the number whole; ACK takes «сорок тысяч» for it -----

class _Worker:
    def __init__(self):
        self.said = []

    def synthesize(self, text, path, end=None):
        import wave
        self.said.append(text)
        with wave.open(path, 'wb') as audio:
            audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(24000); audio.writeframes(b'\x00\x00' * 240 + b'\x10\x00' * 240)


@pytest.mark.parametrize('portion, spoken', [
    ('Проценты составят 40 000 рублей.', 'Проценты составят сорок тысяч рублей.'), ('за 10 000 рублей', 'за десять тысяч рублей'), ('144 000', 'сто сорок четыре тысячи'),
    ('1 500 000 человек', 'один миллион пятьсот тысяч человек'), ('40 000 и 3 000', 'сорок тысяч и три тысячи'), ('20 %', 'двадцать процентов'),
    ('в 1998 году', 'в тысяча девятьсот девяносто восьмом году'), ('с 5 по 6 ноября, 12 300', 'с пяти по шестое ноября, двенадцать тысяч триста')])
def test_e89_the_synthesizer_gets_a_grouped_number_whole(tmp_path, portion, spoken):
    from echo_sync.controlled_host import render_cue_pcm
    worker = _Worker()
    render_cue_pcm(worker, portion, tmp_path)
    assert worker.said == [spoken]


def test_e89_two_numbers_side_by_side_are_not_glued():
    from echo_sync.speech_text import _whole_numbers as spoken_numbers
    assert spoken_numbers('в 2023 году 15 человек') == 'в 2023 году 15 человек'
    assert spoken_numbers('счёт 60 на 90') == 'счёт 60 на 90'
    assert spoken_numbers('5 000 000 и 7 1/2') == '5000000 и 7 1/2'


def test_e89_ack_takes_the_number_in_words_for_the_portion_in_digits(tmp_path):
    import helpers_s6_ack as H
    d = H.Dictation(tmp_path / 'e89', 'Проценты составят 40 000 рублей. Это доход за год.')
    assert d.current == 'Проценты составят 40 000 рублей.'
    d.controller.provider(H.created('u2', 'user', ''))
    d.controller.provider(H.done('u2', 'user', 'Проценты составят сорок тысяч рублей'))
    assert d.index == 1, 'the portion is confirmed'


def test_e89_another_number_in_words_is_no_ack(tmp_path):
    import helpers_s6_ack as H
    d = H.Dictation(tmp_path / 'e89n', 'Проценты составят 40 000 рублей. Это доход за год.')
    d.controller.provider(H.created('u2', 'user', ''))
    d.controller.provider(H.done('u2', 'user', 'Проценты составят четырнадцать тысяч рублей'))
    assert d.index == 0, 'a protected difference of numbers is not weakened'


# ---- W17 (Р-16): the BRAIN speaks of the listener in general words. fast_text.py is A2's file (CLAUDE.md): the exact patch is in cloud_context/reports/w3-integ.md, the test waits for it ----------------

def test_w17_the_brain_names_no_situation_of_the_listener():
    import re
    from echo_sync.fast_text import BRAIN
    assert not re.search(r'экзамен|собеседован|презентац', BRAIN, re.I), 'Р-16: universal product, general roles'


# ---- W03: «HTTP 200» is no proof of the loaded version: a fingerprint of the modules as the PROCESS holds them (their code objects), not of the files or the log ----------------------------------------

def test_w03_the_fingerprint_is_of_the_loaded_code_not_of_the_files(monkeypatch):
    import echo_sync
    from echo_sync import portioner
    first = echo_sync.fingerprint()
    assert first == echo_sync.fingerprint() and first['digest'] and 'echo_sync.portioner' in first['modules']
    assert first['build'] == echo_sync.build_id() and first['prompt']

    def other(*args, **kwargs):
        return []
    monkeypatch.setattr(portioner, 'portions', other)        # the file on disk is the same, the process is not
    second = echo_sync.fingerprint()
    assert second['modules']['echo_sync.portioner'] != first['modules']['echo_sync.portioner'] and second['digest'] != first['digest']
    assert {name: value for name, value in second['modules'].items() if name != 'echo_sync.portioner'} == {name: value for name, value in first['modules'].items() if name != 'echo_sync.portioner'}


def test_w03_the_flags_are_part_of_it():
    import echo_sync
    from echo_sync.settings import resolve
    assert echo_sync.fingerprint(resolve({}))['flags'] != echo_sync.fingerprint(resolve({'voice_gain': 2.0}))['flags']


# ---- item 15: T1, two jobs on one client (prepare_wide=on): the job whose socket died must not close the client under the other one's answer --------------------------------------------------------

def test_15_a_retry_of_one_job_does_not_close_the_client_under_the_other():
    import threading
    import time
    from test_t1_transport import Client, Resp, dead, sse, transport
    middle = Resp(sse({'type': 'response.output_text.delta', 'delta': 'Первая фраза. '}, {'type': 'response.output_text.delta', 'delta': 'Вторая.'}, {'type': 'response.completed'}))
    shared = Client(middle, dead())
    stream, factory = transport(shared)
    other = stream({'model': 'm'}, threading.Event())
    assert next(other) == 'Первая фраза. ', 'the wide job is in the middle of its answer on the shared client'
    assert list(stream({'model': 'm'}, threading.Event())) == ['Да.'], 'the second job lost its socket before any text: one retry on a new client'
    time.sleep(0.1)
    assert not shared.closed, 'the shared client is not closed under the answer still being read'
    assert list(other) == ['Вторая.']
    for _ in range(50):
        if shared.closed:
            break
        time.sleep(0.02)
    assert shared.closed, 'once its last job is over the dead client is let go'
    stream.close()

"""g13 (wave 17, the owner's calls 06.11): short follow-ups while a portion waits. The ear gave mismatch_policy_silent / not_a_question to
«а счёт пятьдесят восемь», «а РКО», «а КО-2 это что», «так а пятьдесят два это какой у нас счёт», «так что это за указание»: they are questions,
and the answer must start from the ear. «ещё пятьдесят один», «аа расчёт», «молодой» and a repeat of the cue stay quiet. 300 replicas, labelled
by hand rules below; the goal: no false cue at all, every follow-up a question. Real classifier with the call settings, no model."""
import itertools
import unittest

from echo_sync.classifier import QUESTION, analyze
from echo_sync.settings import CALL_SETTINGS


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def _state(chunks, question, index=0, completed=False):
    return {'revision': 1, 'question': question, 'answer': ' '.join(chunks), 'chunks': list(chunks), 'chunk_index': index, 'completed': completed,
            'pending_turn': None, 'history': [{'question': question, 'answer': ' '.join(chunks)}]}


# Portions that wait in the owner's calls (accounting, cash operations); none of them names what the follow-ups ask.
STATES = {
    's69': _state(['Счёт 69 — расчёты', 'по социальному страхованию и обеспечению.'], 'Счёт 69'),
    'pko': _state(['ПКО КО-1 — приходный кассовый ордер,', 'выдаётся при приёме наличных.'], 'Что такое ПКО'),
    'ukaz': _state(['Указание Банка России 3210-У', 'о порядке ведения кассовых операций.'], 'Каким документом регулируются кассовые операции'),
    's51': _state(['Счёт 51 «Расчётные счета» —', 'учёт денег на расчётных счетах.'], 'Счёт 51'),
    'done': _state(['Счёт 50 «Касса» — учёт наличных денег.'], 'Счёт 50', index=1, completed=True),
}

# --- questions: the owner's five, verbatim, and their kin --------------------------------------------------------------------------------
OWNER_QUESTIONS = ('а счёт пятьдесят восемь', 'а РКО', 'а КО-2 это что', 'так а пятьдесят два это какой у нас счёт', 'так что это за указание')
_LEADS = ('а', 'так а', 'ну а', 'а вот')
_TERMS = ('счёт пятьдесят восемь', 'счёт 58', 'счёт шестьдесят один', 'шестидесятый счёт', 'счёт девяносто девять', 'РКО', 'рко', 'НДС', 'НДФЛ',
          'КО-2', 'КО-4', 'ко два')
_ASKS = ('{lead} {term}', '{lead} {term} это что', '{lead} {term} это какой у нас счёт', '{lead} что такое {term}')
_WHAT_IS = ('так что это за указание', 'а что это за форма', 'так что это за документ', 'ну а что это за ордер', 'а что за указание',
            'так а пятьдесят два это какой у нас счёт', 'а семьдесят один это какой счёт', 'а КО-5 это какой документ',
            'так а девяносто первый это какой у нас счёт', 'а 62 это какой счёт')
QUESTIONS = tuple(dict.fromkeys(OWNER_QUESTIONS + tuple(ask.format(lead=lead, term=term) for ask, lead, term in itertools.product(_ASKS, _LEADS, _TERMS)
                                                         if not (ask.endswith('какой у нас счёт') and not term[0].isupper() and 'счёт' in term)) + _WHAT_IS))

# --- quiet: chat, a repeat of the cue, hesitations, counting ------------------------------------------------------------------------------
OWNER_QUIET = ('ещё пятьдесят один', 'аа расчёт', 'молодой')
_CHAT = ('ну да', 'ага понятно', 'так', 'так вот', 'ну вот', 'окей', 'ладно', 'хорошо', 'молодец', 'ну короче', 'щас щас', 'аа', 'ээ',
         'а понятно', 'а ну да', 'а вот оно что', 'а молодой', 'а хорошо', 'а точно', 'а ладно', 'ну-ну', 'да-да-да', 'вот так вот', 'ну и ну',
         'Маша иди сюда', 'подожди минутку', 'сейчас сейчас', 'раз два три', 'пятьдесят один пятьдесят два', 'ещё пятьдесят два', 'ещё один',
         'ещё шестьдесят девять', 'ещё раз пятьдесят', 'аа расчёты', 'ээ расчёт', 'ммм касса', 'аа счёт', 'ну счёт', 'так счёт', 'ээ счёт',
         'молодой человек', 'молодые', 'классно', 'супер', 'интересно', 'всё ясно', 'а всё ясно', 'ну ясно', 'так-так', 'угу', 'ну давай',
         'вот', 'вообще', 'короче', 'значит так', 'в общем', 'кстати да', 'ну это', 'это самое', 'как бы', 'типа того',
         'а да', 'а ну', 'а так', 'а вот', 'а это', 'а ага', 'ну а что', 'а нормально', 'а я понял', 'а потом', 'ещё', 'ещё чуть-чуть',
         'пятьдесят', 'восемь', 'ну пятьдесят', 'ещё пятьдесят восемь', 'ещё КО-2', 'ещё РКО', 'ну молодой', 'молодой ещё', 'ой', 'блин',
         'спасибо', 'ну спасибо', 'пожалуйста', 'извините', 'секунду', 'хм', 'ааа понял', 'а-а-а', 'эм ну', 'ну и вот', 'так-с', 'ну что ж', 'идём дальше нет', 'погоди', 'а ну-ка', 'да ну')
_REPEATS = {  # a repeat of (a piece of) the waiting portion, with ear slips
    's69': ('счёт шестьдесят девять расчёты', 'счёт 69 расчёты', 'расчёты', 'шестьдесят девять расчёты', 'счёт шестьдесят девять'),
    'pko': ('ПКО КО-1 приходный кассовый ордер', 'приходный кассовый ордер', 'пко ко один', 'КО-1 приходный', 'приходный ордер'),
    'ukaz': ('указание банка россии три тысячи двести десять у', 'Указание Банка России', 'указание банка россии 3210-У', 'банка россии'),
    's51': ('счёт пятьдесят один расчётные счета', 'счёт 51 расчётные счета', 'расчётные счета', 'пятьдесят один расчётные'),
}
QUIET = tuple(dict.fromkeys(OWNER_QUIET + _CHAT))


def _cases():
    asked = [(text, key) for text in QUESTIONS for key in ('s69', 'pko', 'ukaz', 's51')]
    quiet = [(text, key) for text in QUIET for key in ('s69', 'pko', 'ukaz', 's51')]
    quiet += [(text, key) for key, texts in _REPEATS.items() for text in texts]
    return asked, quiet


class FollowupRealTests(unittest.TestCase):
    def test_the_set_is_300_replicas(self):
        self.assertGreaterEqual(len(QUESTIONS) + len(QUIET) + sum(map(len, _REPEATS.values())), 300)

    def test_owner_followups_are_questions_from_the_ear(self):
        for text in OWNER_QUESTIONS:
            for key in ('s69', 'pko', 'ukaz', 's51', 'done'):
                with self.subTest(text=text, state=key):
                    decision = analyze(text, STATES[key], [], CALL_SETTINGS)
                    self.assertEqual(decision.kind, QUESTION, decision.reason)
                    self.assertTrue(decision.question)

    def test_every_followup_is_a_question(self):
        missed = [(text, key, analyze(text, STATES[key], [], CALL_SETTINGS).reason) for text, key in _cases()[0]
                  if analyze(text, STATES[key], [], CALL_SETTINGS).kind != QUESTION]
        self.assertEqual(missed, [])

    def test_no_false_cue_on_chat_and_repeats(self):
        false = [(text, key, analyze(text, STATES[key], [], CALL_SETTINGS).reason) for text, key in _cases()[1]
                 if analyze(text, STATES[key], [], CALL_SETTINGS).kind == QUESTION]
        self.assertEqual(false, [])

    def test_followup_keeps_the_number_and_the_term(self):
        for text, want in (('а счёт пятьдесят восемь', 'пятьдесят восемь'), ('а РКО', 'РКО'), ('а КО-2 это что', 'КО-2'),
                           ('так а пятьдесят два это какой у нас счёт', 'пятьдесят два')):
            with self.subTest(text=text):
                self.assertIn(want, analyze(text, STATES['pko'], [], CALL_SETTINGS).question)


if __name__ == '__main__':
    unittest.main()


# --- the stand: the answer starts from the ear, not from the cloud's final 5 s later (the flags of the candidate, c16's rig) ----------------
import pytest  # noqa: E402

import helpers_s6_state as S  # noqa: E402

from test_c16_ear_job import FLAGS as EAR_FLAGS, SILENCE, breath, jobs  # noqa: E402,F401
from test_h3_tempo import TICK, call  # noqa: E402,F401 - call is the fixture

STAND_ASKS = ('а счёт пятьдесят восемь', pytest.param('а РКО', marks=pytest.mark.xfail(strict=True, reason='controlled_media._ear_opens_job: PREPARE_MIN_WORDS; patch in the g13 report')), 'так а пятьдесят два это какой у нас счёт', 'а КО-2 это что', 'так что это за указание')


@pytest.mark.parametrize('said', STAND_ASKS)
def test_the_ear_opens_the_followup_before_the_cloud_final(call, said):
    rig = call(**EAR_FLAGS)
    rig.first_portion()
    rig.pump(3.0)
    count = len(rig.said())
    breath(rig, [said], turn='u2')
    rig.pump(SILENCE)
    if len(rig.said()) > count:
        return                                                    # the reference base answered it from the ear («Счёт 58 — финансовые вложения.»)
    assert jobs(rig), f'nothing opened on the ear for «{said}»'
    rig.job_says(len(rig.fake.runs) - 1, 'Это ответ на продолжение.')
    rig.pump(TICK * 4)
    assert any('ответ на продолжение' in text for text in rig.said()[count:]), rig.said()


@pytest.mark.parametrize('said', OWNER_QUIET)
def test_the_ear_opens_nothing_on_chat(call, said):
    rig = call(**EAR_FLAGS)
    rig.first_portion()
    rig.pump(3.0)
    count = len(rig.said())
    breath(rig, [said], turn='u2')
    rig.pump(SILENCE)
    assert len(rig.said()) == count, rig.said()                   # a job may weigh it (the model declines a remark); no cue is said


def test_the_cloud_final_5_s_later_says_nothing_twice(call):
    rig = call(**EAR_FLAGS)
    rig.first_portion()
    rig.pump(3.0)
    count = len(rig.said())
    breath(rig, ['а счёт пятьдесят восемь'], turn='u2')
    rig.pump(SILENCE)
    answered = rig.said()[count:]
    assert answered == ['Счёт 58 — финансовые вложения.'], answered
    rig.pump(5.0)
    runs = len(rig.fake.runs)
    rig.w.feed(S.turn_done('u2', 'user', 'А счёт пятьдесят восемь?'))
    rig.pump(TICK * 6)
    assert set(rig.said()[count:]) == {'Счёт 58 — финансовые вложения.'}, rig.said()[count:]   # its own repeats of the portion only
    assert len(rig.fake.runs) == runs and rig.c.user_boundaries.get('u2') == 'ear_first'
    assert not [f for f in rig.w.frames if f[2].get('type') == 'response.cancelled'], 'the final confirms what the ear opened'

"""Scenario matrix for the oral ECHO handshake across the three supported presets.

All prompts, answers, and contextual details here are synthetic fixtures.  No
acoustic/ASR behavior is modeled: calls are the text turns accepted by the engine.
"""
import tempfile
import unittest
from pathlib import Path

from echo_sync.engine import EchoEngine, SILENT
from echo_sync.textutil import normalize
from engine_say import engine_reply


PRESETS = ('strict_triples', 'adaptive', 'slow')
SCENARIOS = (
    ('authorized oral exam', 'Вопрос: объясните условный принцип для устного экзамена'),
    ('oral questioning', 'Вопрос: как в учебном примере связаны два понятия'),
    ('interview', 'Вопрос: расскажите о вымышленном рабочем процессе на интервью'),
    ('lesson explanation', 'Вопрос: поясните условное правило для занятия'),
    ('memory practice', 'Вопрос: как запомнить учебный пример'),
    ('unexpected conversation', 'Вопрос: что ответить в неожиданном разговоре'),
)

# Deliberately synthetic details exercise numbers, date-like text, abbreviation,
# formula, and a long word without asserting real-world facts.
ANSWER = (
    'В вымышленном макете АБ означает альфа-бета. '
    'Дата примера 21.10.2026, условный лимит 12 страниц. '
    'Формула-памятка: сумма равна 3 плюс 5. '
    'Электроэнцефалографический маркер придуман для тренировки.'
)
CONTEXT = 'Синтетический контекст сценарного теста; не источник сведений.'
SETTINGS = {
    'preset': None,  # Set per case below; keeps scenario comparisons attributable.
    
    'abbreviations': {'АБ': 'альфа-бета'},
}


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


class ScenarioMatrixTests(unittest.TestCase):
    def test_oral_scenarios_across_presets(self):
        case_count = 0
        for scenario, prompt in SCENARIOS:
            for preset in PRESETS:
                with self.subTest(scenario=scenario, preset=preset):
                    case_count += 1
                    with tempfile.TemporaryDirectory() as tmp:
                        calls = []

                        def generate(question, history, context, request, model):
                            calls.append((question, history, context))
                            return ANSWER

                        settings = {**SETTINGS, 'preset': preset}
                        path = Path(tmp) / 'state.sqlite3'
                        engine = EchoEngine(path, generate, context=CONTEXT, settings=settings)

                        def turn(text, turn_id):
                            return engine_reply(engine, session_id='matrix-session', turn_id=turn_id,
                                                text=text, request={}, model='synthetic-fixture')

                        first = turn(prompt, 'question-1')
                        initial = engine.state('matrix-session')
                        self.assertNotEqual(first, SILENT, scenario)
                        self.assertEqual(initial['revision'], 1)
                        self.assertEqual(initial['chunk_index'], 0)
                        self.assertEqual(initial['answer'], ANSWER)
                        self.assertEqual(len(calls), 1)
                        self.assertEqual(calls[0][0], prompt.removeprefix('Вопрос: ').strip())
                        self.assertEqual(calls[0][2], CONTEXT)

                        # Silence, a genuinely incomplete phrase, and unrelated
                        # continuous speech all retain the same pending position.
                        portion = initial['chunks'][0]
                        words = portion.split()
                        partial = ' '.join(words[:-1]) if len(words) > 1 else 'неверно'
                        self.assertNotEqual(normalize(partial), normalize(portion))
                        for turn_id, utterance in (
                            ('blank', ''), ('partial', partial),
                            ('background', 'сегодня продолжается длинное обсуждение другого вопроса без подтверждения'),
                        ):
                            self.assertEqual(turn(utterance, turn_id), SILENT, (scenario, preset, turn_id))
                            self.assertEqual(engine.state('matrix-session')['chunk_index'], 0)
                            self.assertEqual(engine.state('matrix-session')['revision'], 1)

                        # Explicit repeat reissues the same portion without moving.
                        self.assertEqual(normalize(turn('повтори', 'repeat-1')), normalize(first))
                        self.assertEqual(engine.state('matrix-session')['chunk_index'], 0)

                        # An exact ACK advances once; replaying that network turn
                        # ID after advancement is stale and must not advance again.
                        next_audio = turn(portion, 'ack-1')
                        after_ack = engine.state('matrix-session')
                        self.assertEqual(after_ack['chunk_index'], 1)
                        # Idempotent retry may replay its cached post-ACK
                        # response, but it must not consume another portion.
                        self.assertEqual(normalize(turn(portion, 'ack-1')), normalize(next_audio))
                        self.assertEqual(engine.state('matrix-session')['chunk_index'], 1)
                        self.assertEqual(turn(prompt, 'question-1'), SILENT)  # obsolete retry
                        self.assertEqual(engine.state('matrix-session')['chunk_index'], 1)

                        # A restart keeps full private history and the exact cursor.
                        restarted = EchoEngine(path, generate, context=CONTEXT, settings=settings)
                        persisted = restarted.state('matrix-session')
                        self.assertEqual(persisted['chunk_index'], 1)
                        self.assertEqual(persisted['answer'], ANSWER)
                        self.assertEqual(persisted['history'][0]['answer'], ANSWER)
                        current_before_repeat = persisted['chunks'][1]
                        self.assertEqual(normalize(engine_reply(restarted, 
                            session_id='matrix-session', turn_id='repeat-after-restart', text='повтори',
                            request={}, model='synthetic-fixture')),
                            normalize(current_before_repeat))
                        self.assertEqual(restarted.state('matrix-session')['chunk_index'], 1)

                        # Explicit new question supersedes the active answer,
                        # increments revision, carries the full old answer, and
                        # performs one generation for the question—not per chunk.
                        newer_prompt = 'Вопрос: уточните новый учебный пример'
                        newer_first = engine_reply(restarted, 
                            session_id='matrix-session', turn_id='question-2', text=newer_prompt,
                            request={}, model='synthetic-fixture')
                        newer_state = restarted.state('matrix-session')
                        self.assertNotEqual(newer_first, SILENT)
                        self.assertEqual(newer_state['revision'], 2)
                        self.assertEqual(newer_state['chunk_index'], 0)
                        self.assertEqual(calls[-1][0], 'уточните новый учебный пример')
                        self.assertEqual(calls[-1][1][0]['answer'], ANSWER)
                        self.assertEqual(len(calls), 2)

                        # Walk every portion by exact ACK, proving chunk turns do
                        # not trigger more provider work; the final ACK completes.
                        while not restarted.state('matrix-session')['completed']:
                            state = restarted.state('matrix-session')
                            ack = state['chunks'][state['chunk_index']]
                            response = engine_reply(restarted, 
                                session_id='matrix-session',
                                turn_id=f'exact-{state["chunk_index"]}', text=ack,
                                request={}, model='synthetic-fixture')
                            self.assertEqual(len(calls), 2)
                            if restarted.state('matrix-session')['completed']:
                                self.assertEqual(response, SILENT)
                            else:
                                self.assertNotEqual(response, SILENT)
                        self.assertEqual(restarted.state('matrix-session')['answer'], ANSWER)
                        self.assertEqual(len(calls), 2)

        self.assertEqual(case_count, len(SCENARIOS) * len(PRESETS))


if __name__ == '__main__':
    unittest.main()

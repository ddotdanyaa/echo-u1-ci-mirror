"""Bounded seeded offline stress matrix for EchoEngine turn invariants.

Fixtures are synthetic and the generator is deterministic. This exercises the
real SQLite-backed engine only; no provider, network, audio, or live profile is used.
"""
import json
import random
import tempfile
import unittest
from pathlib import Path

from echo_sync.engine import EchoEngine, SILENT
from echo_sync.textutil import normalize
from engine_say import engine_reply


SEED = 20261022
CASE_COUNT = 40
PRESETS = ('strict_triples', 'adaptive', 'slow')
TOPICS = ('учебного примера', 'вымышленного правила', 'условного макета',
          'тренировочного понятия', 'синтетической задачи', 'придуманного процесса')
ANSWER_TAIL = (' Это только синтетический текст для проверки продолжения ответа. '
               'Новые факты не утверждаются; контрольный раздел помогает сохранить курсор.')


def generated_fixtures(seed=SEED, count=CASE_COUNT):
    rng = random.Random(seed)
    fixtures = []
    for index in range(count):
        number = rng.randint(10, 89)
        topic = rng.choice(TOPICS)
        question = f'Вопрос: объясните {topic} в варианте {index + 1}'
        answer = f'знак плюс {number} условие.' + ANSWER_TAIL
        next_question = f'Вопрос: уточните другой {topic} в варианте {index + 1}'
        next_answer = f'знак плюс {number + 1} признак. Новый синтетический ответ для проверки revision и истории.' + ANSWER_TAIL
        fixtures.append((index, number, question, answer, next_question, next_answer))
    return fixtures


class BoundedScenarioMatrixTests(unittest.TestCase):
    def test_seeded_multiturn_matrix_across_presets(self):
        cases = 0
        assertions = 0
        events = 0
        first_case = None

        def check(condition, message, case):
            nonlocal assertions, first_case
            assertions += 1
            if not condition:
                first_case = case
                self.fail(f'first counterexample {case}: {message}')

        for preset in PRESETS:
            for index, number, question, answer, next_question, next_answer in generated_fixtures():
                case = {'preset': preset, 'fixture': index}
                with self.subTest(**case):
                    with tempfile.TemporaryDirectory(prefix='echo-scenario-') as tmp:
                        db_path = Path(tmp) / 'state.sqlite3'
                        generated = []

                        def generate(prompt, history, context, request, model):
                            generated.append((prompt, tuple(history)))
                            return answer if prompt == question.removeprefix('Вопрос: ').strip() else next_answer

                        settings = {'preset': preset}
                        engine = EchoEngine(db_path, generate, settings=settings)
                        sid = f'matrix-{preset}-{index}'

                        def turn(turn_id, text, owner=engine):
                            nonlocal events
                            events += 1
                            return engine_reply(owner, session_id=sid, turn_id=turn_id, text=text,
                                               request={}, model='deterministic-fixture')

                        first = turn('question-1', question)
                        state = engine.state(sid)
                        check(first == state['chunks'][0], 'first response must equal persisted current chunk', case)
                        check(state['revision'] == 1 and state['chunk_index'] == 0,
                              'new question starts revision 1 at cursor 0', case)
                        check(state['answer'] == answer and len(generated) == 1,
                              'one fixture generation stores the full answer', case)

                        # Re-delivery of the same question turn is idempotent.
                        retry_question = turn('question-1', question)
                        check(normalize(retry_question) == normalize(first),
                              'same question turn must return its cached response', case)
                        check(len(generated) == 1 and engine.state(sid)['chunk_index'] == 0,
                              'question retry cannot regenerate or advance the cursor', case)

                        # Silence, wrong numeric ACK, wrong sign ACK, and a partial
                        # phrase are allowed to be silent or replay the same chunk,
                        # but cannot change revision/cursor or invoke the generator.
                        current = state['chunks'][0]
                        wrong_number = current.replace(str(number), str(number + 100), 1)
                        if wrong_number == current:
                            # Presets may break the number onto a later chunk; the
                            # generator's first chunk is expected to retain it.
                            check(False, f'number {number} absent from initial portion {current!r}', case)
                        wrong_sign = current.replace('плюс', 'минус', 1)
                        check(wrong_sign != current, 'initial portion must include the sign fixture', case)
                        words = current.split()
                        partial = ' '.join(words[:-1]) if len(words) > 1 else 'неподтверждённый'
                        for label, utterance in (('silence', ''), ('wrong_number', wrong_number),
                                                 ('wrong_sign', wrong_sign), ('partial', partial)):
                            before_calls = len(generated)
                            response = turn(label, utterance)
                            now = engine.state(sid)
                            check(now['revision'] == 1 and now['chunk_index'] == 0 and not now['completed'],
                                  f'{label} must retain the active chunk', case)
                            check(len(generated) == before_calls == 1,
                                  f'{label} must not call the answer generator', case)
                            check(response in (SILENT, current),
                                  f'{label} may be ignored or replay the same chunk, got {response!r}', case)

                        # A complete current portion advances exactly one position;
                        # redelivery of that network turn ID is idempotent.
                        after_ack = turn('ack-1', current)
                        state = engine.state(sid)
                        check(state['chunk_index'] == 1 and state['revision'] == 1,
                              'correct full ACK advances exactly to cursor 1', case)
                        check(len(generated) == 1, 'ACK cannot invoke the generator', case)
                        ack_retry = turn('ack-1', current)
                        state = engine.state(sid)
                        check(normalize(ack_retry) == normalize(after_ack) and state['chunk_index'] == 1,
                              'same ACK turn retry preserves its cached response and cursor', case)

                        # Reopen the same database as a separate engine instance.
                        restarted = EchoEngine(db_path, generate, settings=settings)
                        resumed = restarted.state(sid)
                        check(resumed['revision'] == 1 and resumed['chunk_index'] == 1
                              and resumed['answer'] == answer,
                              'reconnect retains the full answer and cursor', case)
                        if resumed['chunk_index'] < len(resumed['chunks']):
                            next_chunk = resumed['chunks'][resumed['chunk_index']]
                            turn('ack-2', next_chunk, restarted)
                            check(restarted.state(sid)['chunk_index'] == 2,
                                  'second exact ACK advances to cursor 2 after reconnect', case)

                        # A genuinely new question supersedes the old revision;
                        # late retries from the prior revision must not replay.
                        old_revision = restarted.state(sid)['revision']
                        next_first = turn('question-2', next_question, restarted)
                        new_state = restarted.state(sid)
                        check(new_state['revision'] == old_revision + 1 and new_state['chunk_index'] == 0,
                              'new question increments revision and resets cursor', case)
                        check(new_state['answer'] == next_answer and len(generated) == 2,
                              'new question causes exactly one new deterministic generation', case)
                        stale_retry = turn('question-1', question, restarted)
                        check(stale_retry == SILENT and restarted.state(sid)['revision'] == old_revision + 1,
                              'old question turn cannot replay into the new revision', case)
                        check(turn('ack-1', current, restarted) == SILENT
                              and restarted.state(sid)['chunk_index'] == 0,
                              'old revision ACK cannot advance or play the new answer', case)

                        cases += 1
                # unittest records subTest failures and otherwise continues its
                # loop; explicitly leave after the first counterexample.
                if first_case is not None:
                    return

        summary = {'seed': SEED, 'fixtures_per_preset': CASE_COUNT, 'presets': list(PRESETS),
                   'scenario_cases': cases, 'turn_events': events, 'assertions': assertions,
                   'first_counterexample': first_case, 'network_or_provider_calls': 0}
        print('SCENARIO_MATRIX_SUMMARY ' + json.dumps(summary, ensure_ascii=True, sort_keys=True))
        self.assertEqual(cases, CASE_COUNT * len(PRESETS))


if __name__ == '__main__':
    unittest.main()

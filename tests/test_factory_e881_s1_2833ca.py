# factory-backlog-id: E881.s1
from echo_sync.engine import conversation_map


def test_quiz_context_persistence():
    history = []
    for i in range(4):
        history.append({'status': 'complete', 'at': 100, 'question': f'Gen {i}', 'answer': 'ans'})
    for i in range(16):
        history.append({'status': 'complete', 'at': 100, 'question': f'Quiz {i}', 'answer': 'ans', 'quiz_id': 'quiz_123'})

    state = {'history': history}
    rows = conversation_map(state, now=100, limit=15, window_s=1000)

    quiz_questions = [r['question'] for r in rows if r['question'].startswith('Quiz')]
    assert quiz_questions == [f'Quiz {i}' for i in range(16)]
    assert rows[-1]['question'] == 'Quiz 15'

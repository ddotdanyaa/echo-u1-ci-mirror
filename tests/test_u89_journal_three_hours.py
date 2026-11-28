"""U89 (b): does ONE call journal file (MAX_FILE_BYTES, 8 MB) hold a three-hour call? A synthetic stream, dense on purpose: 2250 exchanges (one every 4.8 s, the call of the gate check), the facts journal
and the shadows on, a microphone packet every 100 ms, every line with its real shape through the real CallTrace. It is an ESTIMATE from invented text of the stand's length, not a measurement of the
laptop's call: the real size is in the file of a real call (not done here: a measurement on the laptop)."""
import json
import os

from echo_sync.call_trace import CallTrace, MAX_FILE_BYTES, MIC_BUDGET_BYTES

EXCHANGES, THREE_HOURS_S = 2250, 3 * 3600
QUESTION = 'а сколько стоит доставка до склада в Казани если заказ больше трёхсот единиц и когда он придёт'      # ~95 chars
ANSWER = ('Доставка до склада в Казани стоит пятьсот рублей за единицу при заказе до трёхсот штук, а свыше трёхсот скидка пять процентов. '
          'Срок девять рабочих дней, первая партия придёт в понедельник.')      # ~190 chars
AUDIO = 'AAAA' * 640      # 100 ms of 24 kHz 16-bit mono is 4800 bytes; the journal reads the length only


class Clock:
    now = 5000.0

    def __call__(self):
        return self.now


def play_call(tmp_path):
    clock = Clock()
    trace = CallTrace(tmp_path / 'logs', 'abc123def456', clock=clock, facts=True)
    assert trace.open(source='phone')
    step = THREE_HOURS_S / EXCHANGES
    for n in range(EXCHANGES):
        for _ in range(int(step * 10)):      # the microphone, 10 packets a second
            clock.now += .1
            trace.mic({'audio': AUDIO})
        tid = 'u%d' % n
        trace.provider({'type': 'turn.created', 'turn': {'id': tid, 'role': 'user'}})
        trace.provider({'type': 'turn.done', 'turn': {'id': tid, 'role': 'user', 'transcript': QUESTION, 'start_ms': n * 4800, 'end_ms': n * 4800 + 3100}})
        trace.provider({'type': 'response.created', 'item': {'id': 'r%d' % n, 'user_bidi_turn_id': tid}})
        trace.provider({'type': 'turn.created', 'turn': {'id': 'a%d' % n, 'role': 'assistant'}})
        trace.provider({'type': 'turn.done', 'turn': {'id': 'a%d' % n, 'role': 'assistant', 'transcript': ANSWER}})
        for line in ('echo-sync decision kind=answer reason=final revision=1 index=%d' % n, 'echo-sync decision kind=cue reason=portion revision=1 index=%d' % n,
                     'echo-sync decision kind=judge reason=same revision=1 index=%d' % n):
            trace.decision(line)
        trace.why('echo-sync why kind=gate subject=q%d rule=addressed const=0.6' % n)
        trace.why('echo-sync why kind=order subject=q%d rule=judge_order const=2' % n)
        trace.judge('echo-sync judge rule=answered chain=final>judge>route analyses=3')
        trace.note('shadow', gate='would', rule='stale_return', turn=tid, ms=412)
        trace.note('cue_end', status='done', frames=300, first_ms=n * 4800, last_ms=n * 4800 + 6000)
    trace.close(elapsed_ms=THREE_HOURS_S * 1000)
    return trace


def test_one_file_holds_three_dense_hours(tmp_path):
    trace = play_call(tmp_path)
    size = os.path.getsize(trace.path)
    lines = [json.loads(line) for line in trace.path.read_text(encoding='utf-8').splitlines()]
    kinds = [r['ev'] for r in lines]
    assert 'trace_full' not in kinds and kinds[-1] == 'call_close', (size, kinds[-3:])
    assert size < MAX_FILE_BYTES * .8, 'the synthetic three hours take %d of %d bytes' % (size, MAX_FILE_BYTES)      # room is left for a denser call than the guess
    assert kinds.count('user_final') == kinds.count('assistant_final') == EXCHANGES      # the last minute of the call is in the file as the first


def test_the_microphone_lines_do_not_take_more_than_their_budget(tmp_path):
    trace = play_call(tmp_path)
    mic = sum(len(line.encode('utf-8')) for line in trace.path.read_text(encoding='utf-8').splitlines() if json.loads(line)['ev'] == 'mic')
    assert mic <= MIC_BUDGET_BYTES + 400

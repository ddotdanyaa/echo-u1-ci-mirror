"""c24-c: one connected talk of the owner (FOLLOWUP §8) and the paired scenes of §11.4, through the real chain of the h3 rig (``repeat_scenes.make_rig``: ControlledMedia,
NativeMediaSocket, ShadowEar, FastText on the injected clock; the detector, the recognizer, the cloud and the job scripted). Every step says before it runs what it expects: the cues (exact
texts, or none), the portion index after it, how many NEXT. The host's synthesizer is stood in by ``pcm_cache.cached`` over the call's cache, as ``controlled_host`` does: renders are counted.

Counted over a run (``Board``):
  steps          steps judged
  missed         a NEXT expected and none came (a lost move)
  double         more NEXT than expected (a skip: a portion never written)
  wrong_place    the cue said is not the one expected (a tail from the wrong word, the whole portion for a tail)
  old_sound      a cue of a plan that a newer question replaced
  cut_in         a cue while the owner writes in silence and nothing was asked
  extra_jobs     model jobs opened beyond what the step expects (a repeat or a landmark taken for a question)
  renders        TTS renders of a text already rendered in this call (a repeat that synthesized again)
  tail_s         seconds from the end of the owner's words to the expected tail cue (each)

``python -m tools.replay.c24_lecture [--mode cyclic|adaptive]`` prints the board. Seconds are the rig's clock: not a laptop's, not a phone's, not a person's.
"""
import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT / 'tests'), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools.replay import repeat_scenes as R      # noqa: E402

DICTATING = {}                 # dictation by voice («я буду записывать»), as the owner turns it on
A_ASK = 'Какая ставка налога на доходы физических лиц?'
A = ('Основная ставка налога на доходы составляет 13 процентов.', 'Для доходов свыше пяти миллионов ставка выше.')
B_ASK = 'Что такое налоговый вычет?'
B = ('Налоговый вычет уменьшает облагаемый доход гражданина.', 'Пособие по беременности не облагается налогом.', 'Вычет на лечение составляет до 150 тысяч рублей.',
     'Заявление подают в налоговую инспекцию.')
C_ASK = 'Нет, я спрашивал про социальный вычет на обучение.'
C = ('Социальный вычет на обучение дают за себя и детей.', 'Его оформляют через личный кабинет.')
from echo_sync.controlled_media import ANSWER_WAIT_SECONDS as ANSWER_WAIT_S      # noqa: E402
WRITE_S = 8.0          # the owner writes in silence this long: nothing is to cut in


class Board:
    KEYS = ('steps', 'missed', 'double', 'wrong_place', 'old_sound', 'cut_in', 'extra_jobs', 'renders', 'talk_jobs')

    def __init__(self):
        self.n = {k: 0 for k in self.KEYS}
        self.tail_s, self.episodes = [], []

    def bad(self):
        return {k: v for k, v in self.n.items() if k not in ('steps', 'talk_jobs') and v}


class Talk:
    """One call. ``step`` runs an action and judges what came of it against what was said before it ran."""

    def __init__(self, flags, board, name):
        from echo_sync import pcm_cache
        self.rig, self.board, self.name = R.make_rig(flags), board, name
        self.memo, self.renders = pcm_cache.PcmCache(), []
        self.old_plans = []
        self.audio_s = 0.5            # the length of every cue's sound

        async def synthesize(text, end=None):
            def render(said):
                self.renders.append(said)
                return b'\x00\x40' * int(24000 * self.audio_s)
            return pcm_cache.cached(self.memo, render, text, f'v|{end}', 24000)
        self.rig.w.wire.synthesize = synthesize

    def close(self):
        try:
            self.rig.close()
            self.rig._mp.undo()
        except Exception:
            pass

    def where(self):
        s = self.rig.c.state() or {}
        return s.get('revision'), s.get('chunk_index'), tuple(s.get('chunks') or ())

    def answer(self, text):
        """The job of the latest question says ``text``."""
        n = len(self.rig.fake.runs) - 1
        self.rig.job_says(n, text)
        self.rig.job_ends(n)

    def step(self, label, act, *, cues=(), index=None, nexts=0, jobs=0, wait=2.5, writing=False, tail=False, answer=None, talk=False):
        """``act``: ('say', text) | ('silence', s) | ('ask', question, answer) | ('call', fn). ``cues``: the texts expected, in order (() none). ``index``: the portion after it.
        ``nexts``: NEXT within the same plan. ``jobs``: model jobs it may open. ``writing``: the owner writes meanwhile (a cue nobody asked for cuts in). ``tail``: time the first cue.
        ``talk``: speech of the talk (no question, no word to the plan): the jobs the arbiter opens to judge it are counted apart (``talk_jobs``), they are the existing design."""
        rig, b = self.rig, self.board
        b.n['steps'] += 1
        rev0, at0, plan0 = self.where()
        mark, runs, renders0 = len(rig.cues()), len(rig.fake.runs), len(self.renders)
        ended = rig.w.clock.t
        kind = act[0]
        if kind == 'say':
            _, ended = R.utter(rig, act[1])
        elif kind == 'silence':
            rig.pump(act[1])
        elif kind == 'ask':
            rig.asks(f'q{runs}', act[1], runs, act[2])
        elif kind == 'call':
            act[1](self)
        if answer is not None:
            rig.pump(0.3)
            self.answer(answer)
        R.pump_dashing(rig, wait) if not cues and not jobs and answer is None else rig.pump(wait)      # a step that expects no cue and no job: the stand's model answers what the arbiter asks of the talk with the dash (what the engine's model says to what asks nothing), it does not hang
        got = rig.cues()[mark:]
        texts = [c.text for c in got]
        rev1, at1, plan1 = self.where()
        if rev1 != rev0 and plan0:
            self.old_plans.append(set(plan0) - set(plan1))
        new_jobs = len(rig.fake.runs) - runs
        if talk:
            b.n['talk_jobs'] += new_jobs
        elif new_jobs > jobs:
            b.n['extra_jobs'] += new_jobs - jobs
            self.note(label, f'{new_jobs} job(s), expected {jobs}')
        moved = (at1 - at0) if rev1 == rev0 and at0 is not None and at1 is not None else None
        if moved is not None and moved < nexts:
            b.n['missed'] += nexts - moved
            self.note(label, f'NEXT {moved}, expected {nexts}; cues {texts}')
        if moved is not None and moved > nexts:
            b.n['double'] += moved - nexts
            self.note(label, f'NEXT {moved}, expected {nexts}; cues {texts}')
        if index is not None and at1 != index:
            self.note(label, f'index {at1}, expected {index}')
            if moved is None or moved == nexts:
                b.n['wrong_place'] += 1
        if list(texts) != list(cues):
            if writing and texts and not cues:
                b.n['cut_in'] += len(texts)
            else:
                b.n['wrong_place'] += 1
            self.note(label, f'cues {texts}, expected {list(cues)}')
        for text in texts:
            if any(text in old and text not in plan1 for old in self.old_plans):
                b.n['old_sound'] += 1
                self.note(label, f'old sound {text!r}')
        again = [said for said in self.renders[renders0:] if said in self.renders[:renders0]]
        if again:
            b.n['renders'] += len(again)
            self.note(label, f'rendered again {again}')
        if tail and got and list(texts) == list(cues):
            b.tail_s.append(round(got[0].t - ended, 2))
        return texts

    def note(self, label, what):
        self.board.episodes.append(f'{self.name}/{label}: {what}'[:300])


def connected(flags=DICTATING):
    """§8: intro, talk, a question of the hall, the answer said, back to the talk, a question read from the sheet, silence while writing, the end of a portion by its last word, the words
    before the last, an ASR error in the number and in «не», a stranger with the same word, the question corrected, on from the right place, STOP."""
    board = Board()
    t = Talk(flags, board, 'talk')
    try:
        t.step('intro', ('say', 'Добрый день, коллеги. Сегодня я расскажу о налогах.'), talk=True)
        t.step('talk', ('say', 'Налоги делятся на прямые и косвенные.'), talk=True)
        t.step('hall question', ('ask', A_ASK, ' '.join(A)), cues=[A[0]], index=0, jobs=1, wait=0.5)
        t.step('answer aloud', ('say', A[0]), cues=[A[1]], index=1, nexts=1, wait=0.5)      # aloud, not writing: the silence timer of talk repeats it 2 s after its end
        t.step('answer aloud end', ('say', A[1]), index=2, nexts=1)
        t.step('back to the talk', ('say', 'Хорошо, вернёмся к презентации о налогах.'), talk=True, wait=ANSWER_WAIT_S + 0.5)      # round 3: the remark the classifier took for a question is let go at ANSWER_WAIT_SECONDS (8 s): the stand waits that out in its own step, else the drop lands in the next one
        t.step('dictation on', ('say', 'я буду записывать'), wait=1.0)
        t.step('sheet question', ('say', B_ASK), cues=[B[0]], index=0, jobs=1, answer=' '.join(B), wait=1.0)
        t.step('silence writing', ('silence', WRITE_S), writing=True, index=0)
        t.step('last word', ('say', 'гражданина'), cues=[B[1]], index=1, nexts=1)
        t.step('words before the last', ('say', 'не облагается'), cues=['налогом.'], index=1, wait=6.0, tail=True)
        t.step('last word 2', ('say', 'налогом'), cues=[B[2]], index=2, nexts=1)
        t.step('ASR number', ('say', 'до 160 тысяч рублей'), index=2, wait=6.0, writing=True)
        t.step('last word 3', ('say', 'рублей'), cues=[B[3]], index=3, nexts=1)
        t.step('stranger same word', ('say', 'а мы пришли в инспекцию'), index=3, wait=3.0, talk=True)
        t.step('question corrected', ('say', C_ASK), cues=[C[0]], index=0, jobs=1, answer=' '.join(C), wait=1.5)
        t.step('on from the right place', ('say', 'детей'), cues=[C[1]], index=1, nexts=1)
        t.step('stop', ('say', 'стоп'), wait=1.0)
        t.step('quiet after stop', ('silence', 20.0), writing=True)
    finally:
        t.close()
    return board


def _answered(flags, ask, answer, before=()):
    t = Talk(flags, Board(), 'pair')
    for said in before:
        R.utter(t.rig, said)
        t.rig.pump(1.0)
    t.rig.asks('q0', ask, len(t.rig.fake.runs), answer)
    t.rig.pump(0.5)
    return t


BB = ' '.join(B)
PAIRS = {
    # same words, other actions
    'from_word': (BB, [('повтори со слова облагаемый', dict(cues=['облагаемый доход гражданина.'], index=0, tail=True))]),
    'after_word': (BB, [('последнее записанное слово облагаемый', dict(cues=['доход гражданина.'], index=0, tail=True))]),
    'last_word_alone': (BB, [('гражданина', dict(cues=[B[1]], index=1, nexts=1))]),
    'from_last_word': (BB, [('повтори со слова гражданина', dict(cues=['гражданина.'], index=0, tail=True))]),
    'last_written_is_last': (BB, [('последнее записанное слово гражданина', dict(cues=[B[1]], index=1, nexts=1))]),
    'next_portion_word': (BB, [('я записал покупке', dict(index=0, writing=True, wait=4.0))]),
    'twin_first': ('Налог платят с дохода, и налог платят вовремя. Его считают сами.', [('я записал налог', dict(cues=['платят с дохода, и налог платят вовремя.'], index=0, tail=True))]),
    'twin_second': ('Налог платят с дохода, и налог платят вовремя. Его считают сами.', [('я записал и налог', dict(cues=['платят вовремя.'], index=0, tail=True))]),
    'final_twice': (BB, [('доход гражданина', dict(cues=[B[1]], index=1, nexts=1)), ('доход гражданина', dict(index=1, wait=3.0, writing=True))]),
    'number_wrong': (B[2] + ' ' + B[3], [('до 160 тысяч рублей', dict(index=0, wait=4.0, writing=True))]),
    'number_right': (B[2] + ' ' + B[3], [('до 150 тысяч рублей', dict(cues=[B[3]], index=1, nexts=1))]),
    'neg_dropped': (B[1] + ' ' + B[3], [('облагается налогом', dict(index=0, wait=4.0, writing=True))]),
    'neg_kept': (B[1] + ' ' + B[3], [('не облагается налогом', dict(cues=[B[3]], index=1, nexts=1))]),
    'noise': (BB, [('кхм', dict(index=0, wait=3.0, writing=True, talk=True))]),
    'question_again': (BB, [(B_ASK, dict(cues=[B[0]], index=0))]),
    'question_changed': (BB, [('Что такое имущественный налоговый вычет?', dict(index=0, jobs=1, wait=3.0))]),
    'stop_and_back': (BB, [('стоп', dict(wait=1.0)), ('продолжай', dict(cues=[B[0]], index=0))]),
    'long_writing': (BB, [(None, dict(index=0, wait=0.0))]),
}


def pair(name, flags=DICTATING):
    answer, steps = PAIRS[name]
    board = Board()
    t = _answered(flags, B_ASK, answer, before=('я буду записывать',))
    t.board, t.name = board, name
    try:
        for said, expect in steps:
            if said is None:      # long writing without speech: bounded repeats, the place kept
                mark = len(t.rig.cues())
                t.rig.pump(90.0)
                cues = [c.text for c in t.rig.cues()[mark:]]
                board.n['steps'] += 1
                if len(cues) > t.rig.c.max_auto_repeats or any(c != B[0] for c in cues) or (t.rig.c.state() or {}).get('chunk_index') != 0:
                    board.n['cut_in'] += max(0, len(cues) - t.rig.c.max_auto_repeats)
                    t.note('long writing', f'cues over 90 s {cues}')
                continue
            t.step(said, ('say', said), **expect)
    finally:
        t.close()
    return board


def timer_and_ack(flags=DICTATING):
    """The last word said just as the silence timer comes due: one NEXT, no repeat over it."""
    board = Board()
    t = _answered(flags, B_ASK, ' '.join(B), before=('я буду записывать',))
    t.board, t.name = board, 'timer_and_ack'
    try:
        due = t.rig.c.repeat_at
        if due is not None:
            t.rig.pump(max(0.0, due - t.rig.w.clock.t - 0.3))
        t.step('last word at the timer', ('say', 'гражданина'), cues=[B[1]], index=1, nexts=1)
    finally:
        t.close()
    return board


def hall_and_back(flags=DICTATING, back='вернёмся к прошлому ответу'):
    """§8 item 5: a question of the hall while a portion is being written: the plan waits, the new answer is said; after it the old one comes back only when the owner says so, at the
    portion being written (not its start, not past it). No old sound in between."""
    board = Board()
    t = _answered(flags, B_ASK, BB, before=('я буду записывать',))
    t.board, t.name = board, 'hall_and_back'
    try:
        t.step('last word', ('say', 'гражданина'), cues=[B[1]], index=1, nexts=1)
        t.step('hall question', ('say', A_ASK), cues=[A[0]], index=0, jobs=1, answer=' '.join(A), wait=1.0)
        t.step('A said', ('say', 'процентов'), cues=[A[1]], index=1, nexts=1)
        t.step('A done', ('say', 'выше'), index=2, nexts=1, wait=2.0)
        t.step('no return by itself', ('silence', 25.0), writing=True)
        t.step('back by intent', ('say', back), cues=[B[1]], wait=3.0)
    finally:
        t.close()
    return board


def echo(flags=DICTATING):
    """§11.4: the cue heard back by the microphone while it plays (its words, its last word): no NEXT."""
    board = Board()
    t = _answered(flags, B_ASK, BB, before=('я буду записывать',))
    t.board, t.name = board, 'echo'
    try:
        t.audio_s = 3.0      # a cue that plays 3 s: its tail heard back while it plays

        def heard_back(talk):
            talk.rig.asks('q9', 'Что такое налоговый вычет для пенсионеров?', len(talk.rig.fake.runs), BB)      # a new cue of B[0] begins now
            R.utter(talk.rig, 'облагаемый доход гражданина', speech=0.3, lag=0.05, final_after=0.3)        # its tail heard back over it
        t.step('heard back over the cue', ('call', heard_back), index=0, jobs=1, cues=[B[0]], wait=1.0)
    finally:
        t.close()
    return board


def run_all(flags=DICTATING):
    out = {'connected': connected(flags), 'timer_and_ack': timer_and_ack(flags), 'hall_and_back': hall_and_back(flags), 'echo': echo(flags)}
    for name in PAIRS:
        out[name] = pair(name, flags)
    return out


def total(out):
    board = Board()
    for b in out.values():
        for k, v in b.n.items():
            board.n[k] += v
        board.tail_s += b.tail_s
        board.episodes += b.episodes
    return board


def table(out):
    keys = Board.KEYS
    lines = ['| scene | ' + ' | '.join(keys) + ' | tail_s |', '|' + '---|' * (len(keys) + 2)]
    for name, b in list(out.items()) + [('ALL', total(out))]:
        lines.append(f'| {name} | ' + ' | '.join(str(b.n[k]) for k in keys) + f' | {",".join(str(x) for x in b.tail_s) or "-"} |')
    return '\n'.join(lines)


# -- cyclic repeat vs adaptive wait, on the same writers ---------------------------------------------------------------------------------------------------------------------
MODES = {
    'cyclic': {'repeat_seconds': 2.0, 'max_auto_repeats': 10},          # the portion again every 2 s after its end (the owner's start values), by an explicit mode
    'adaptive': {'dictation': 'on'},                                       # DictationPace: the wait learned from the owner's writing, bounded repeats
}
WRITERS = (1.0, 1.6, 2.5)      # seconds a word takes to write (a guess per writer, not a measurement of a person)


def writer(mode, per_word, answers=R.ANSWERS[:3]):
    """A writer takes ``per_word`` s a word, then says the last two words of the portion; counts the repeats that came while they wrote, the wait from their words to the next portion,
    lost/double moves."""
    flags = MODES[mode]
    out = {'portions': 0, 'repeats_while_writing': 0, 'moves': 0, 'missed': 0, 'double': 0, 'renders': 0}
    t = Talk(flags, Board(), f'{mode}@{per_word}')
    try:
        for n, (ask, portions) in enumerate(answers):
            t.rig.asks(f'w{n}', ask, len(t.rig.fake.runs), ' '.join(portions))
            plan = list((t.rig.c.state() or {}).get('chunks') or [])
            for k, portion in enumerate(plan):
                out['portions'] += 1
                mark = len(t.rig.cues())
                t.rig.pump(per_word * len(R.words_of(portion)))
                out['repeats_while_writing'] += len(t.rig.cues()) - mark
                before = (t.rig.c.state() or {}).get('chunk_index')
                R.utter(t.rig, ' '.join(R.words_of(portion)[-2:]))
                t.rig.pump(R.WAIT_NEXT_S)
                after = (t.rig.c.state() or {}).get('chunk_index')
                moved = (after or 0) - (before or 0)
                out['moves'] += 1
                out['missed'] += moved < 1
                out['double'] += max(0, moved - 1)
            t.rig.pump(2.0)
        out['renders'] = sum(1 for i, said in enumerate(t.renders) if said in t.renders[:i])
    finally:
        t.close()
    return out


def stalled(mode, seconds=60.0):
    """The other side: the owner stopped and waits to hear the portion again, saying nothing. Seconds from the end of the cue to each repeat over ``seconds`` (the place must stay)."""
    t = Talk(MODES[mode], Board(), f'{mode}@stall')
    try:
        ask, portions = R.ANSWERS[0]
        t.rig.asks('s0', ask, 0, ' '.join(portions))
        first = t.rig.cues()[-1].t
        t.rig.pump(seconds)
        again = [round(c.t - first, 1) for c in t.rig.cues()[1:]]
        return {'repeats_s': again, 'index': (t.rig.c.state() or {}).get('chunk_index')}
    finally:
        t.close()


def compare():
    out = {mode: {per: writer(mode, per) for per in WRITERS} for mode in MODES}
    for mode in MODES:
        out[mode]['stall'] = stalled(mode)
    return out


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--episodes', type=int, default=40)
    parser.add_argument('--compare', action='store_true')
    parser.add_argument('--json', default='')
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    if args.compare:
        result = compare()
        print('| mode | s/word | portions | repeats while writing | moves | missed | double | TTS renders again |')
        print('|---|---|---|---|---|---|---|---|')
        for mode, rows in result.items():
            for per, r in rows.items():
                if per == 'stall':
                    continue
                print(f'| {mode} | {per} | {r["portions"]} | {r["repeats_while_writing"]} | {r["moves"]} | {r["missed"]} | {r["double"]} | {r["renders"]} |')
        for mode, rows in result.items():
            print(f'{mode}: silent stall 60 s, repeats at {rows["stall"]["repeats_s"]} s after the cue, index {rows["stall"]["index"]}')
        if args.json:
            Path(args.json).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
        return
    out = run_all()
    print(table(out))
    episodes = total(out).episodes
    for line in episodes[:args.episodes]:
        print('  -', line)
    if len(episodes) > args.episodes:
        print(f'  ... {len(episodes) - args.episodes} more')
    if args.json:
        Path(args.json).write_text(json.dumps({name: {**b.n, 'tail_s': b.tail_s} for name, b in out.items()}, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()

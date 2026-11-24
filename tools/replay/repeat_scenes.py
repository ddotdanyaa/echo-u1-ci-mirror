"""c22-repeat: the owner's rule of repeats, scene by scene, through the real chain of the h3 rig (``tests/test_h3_tempo.Rig``: ControlledMedia, NativeMediaSocket, ShadowEar,
FastText on the injected clock; the detector, the recognizer, the cloud and the job scripted). A listener walks through answers portion by portion and does what the scene says.

The owner's rule (c22-repeat): the system follows how far the owner got repeating the cue. The last word of the portion, or most of it: the next portion at once. A stumble: on from the
word they stopped at, not from the start. Silence, nothing said: the portion again from its start. Dictation: the question said, the answer written by hand, the last words of the portion
said; the system waits longer while they write and does not cut in.

What is counted over a run (``board``):
  ack_first      utterances the rule says move on, after which the next portion was the very next cue (of all such utterances)
  lost           portions of an answer that were never cued, whole or in part, before a later one was
  loops          a portion cued on its own more than ``LOOP_CUES`` times in a row with no word of the listener between
  false_steps    the next portion came after an utterance the rule says does not move on (a stumble, silence, a filler)
  wrong_help     a stumble helped from another word than the one after the stop (the whole portion, or another place)
  silence_whole  of the silences: the portion again from its start (after the help of a stumble: the help from the same word again)
  false_jobs     jobs of the text model opened on the listener's repeats (a repeat taken for a question)
  cut_in         a cue begun while the listener was speaking or within ``WRITE_S`` of a dictation pause
  lost_answer    an answer whose first portion never came (the 3rd, the 15th ...)

``python -m tools.replay.repeat_scenes [--flags k:v,k:v]`` prints the board, scene by scene. Seconds are the rig's clock, not a laptop's or a phone's.
"""
import argparse
import json
import logging
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT / 'tests'), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

LOOP_CUES = 3
from echo_sync.repeat_rule import DICTATION_START_SECONDS      # noqa: E402
WRITE_S = 6.0            # a dictation scene's pause of writing
WAIT_NEXT_S = 1.6        # how long a move on may take after the utterance's end (the ear's text 0.15 s, a tick, the tempo)
ANSWERS = (
    ('Как проходит фотосинтез в листьях растений?', ('Свет попадает на хлорофилл в листьях.', 'Вода распадается на кислород и водород.', 'Углекислый газ превращается в глюкозу.')),
    ('Что такое инфляция?', ('Инфляция это устойчивый рост общего уровня цен.', 'Деньги со временем теряют покупательную способность.', 'Её измеряют индексом потребительских цен.')),
    ('Что такое налоговый вычет?', ('Налоговый вычет уменьшает облагаемый доход гражданина.', 'Его получают при покупке жилья или лечении.', 'Заявление подают в налоговую инспекцию.')),
    ('Какие бывают формы правления?', ('Основные формы правления монархия и республика.', 'Монархия бывает абсолютной и ограниченной.', 'Республика бывает президентской и парламентской.')),
)
CANDIDATE = dict(fast_text='on', ear_release='on', instant='on', material_pick='on', spare_helper='on', warm_start='on', open_overlap='on')


def words_of(text):
    return re.findall(r'[0-9A-Za-zА-Яа-яЁё-]+', text.lower().replace('ё', 'е'))


def flat(text):
    return ' '.join(words_of(text))


# -- what the listener does with one portion: a list of ('say', text) / ('wait', s) / ('help', ...) by behaviour -----------------------------
def most_of(words):
    """More than half of the portion's words from its start (the owner's «большую часть»), at least one word short of it."""
    k = max(len(words) * 3 // 4, len(words) // 2 + 1)
    return words[:min(k, len(words) - 1)]


def stumble_at(words):
    """A stop after a third of the portion (a stumble), at least one word said and most of it not."""
    return words[:max(1, len(words) // 3)]


BEHAVIOURS = ('whole', 'last', 'last2', 'most', 'stumble', 'silence', 'stammer', 'write', 'jump', 'stumble_silent')
MOVES_ON = ('whole', 'last', 'last2', 'most', 'write')


class Board:
    def __init__(self):
        self.n = {k: 0 for k in ('moves', 'ack_first', 'lost', 'loops', 'false_steps', 'stumbles', 'wrong_help', 'silences', 'silence_whole', 'cut_in', 'answers', 'lost_answer', 'portions', 'false_jobs')}
        self.episodes = []

    def add(self, other):
        for key, value in other.n.items():
            self.n[key] += value
        self.episodes += other.episodes


def make_rig(flags):
    import pytest
    import test_h3_tempo as H
    from test_repeat_cases import HOST_PASSES, HOST_SYNCS_ENGINE
    mp = pytest.MonkeyPatch()
    rig = H.Rig(mp, **{**CANDIDATE, **flags})
    rig.c.settings = {**rig.c.settings, **{key: rig.settings[key] for key in HOST_PASSES if key in rig.settings}}
    if HOST_SYNCS_ENGINE:
        rig.c.engine.settings = rig.c.settings
    rig._mp = mp
    return rig


def pump_dashing(rig, seconds, step=0.1):
    """Pump ``seconds``; the stand's text model answers every request of the chatter with «—» (nothing to say: what the engine's model says to what asks nothing), as soon as it is made. A model that hangs on every remark
    is another scene (the honest sentence of the one road is owed to it: ``test_roads_refusal``); here the question is what the garbage costs the next one."""
    done = set()
    for _ in range(max(1, round(seconds / step))):
        rig.pump(step)
        for n, run in enumerate(list(rig.fake.runs)):
            if n not in done and not run.ended.is_set() and not run.cancelled.is_set():
                done.add(n)
                run.script.put(('delta', '—'))
                run.script.put(('end', None))


def utter(rig, text, speech=None, lag=0.15, final_after=0.6, uid=[0]):
    """One utterance through the ear, then the cloud's final of it. Returns (begin, end)."""
    import helpers_s6_state as S
    from test_h3_tempo import TICK
    uid[0] += 1
    tid = f'r{uid[0]}'
    speech = speech if speech is not None else max(0.4, 0.38 * len(words_of(text)))
    began = rig.w.clock.t
    ear = rig.onset()
    rig.pump(min(0.3, speech))
    rig.w.feed(S.turn_created(tid, 'user', text.split()[0]))
    rig.pump(max(0.0, speech - 0.3))
    ended = rig.offset()
    rig.pump(lag)
    rig.worker.heard(ear, text)
    rig.pump(TICK)
    rig.pump(final_after)
    rig.w.feed(S.turn_done(tid, 'user', text + '.'))
    rig.pump(TICK)
    return began, ended


def cues_since(rig, count):
    return rig.cues()[count:]


def which(cue_text, portions, at):
    """('whole', k) / ('rest', k) / None: what a cue is of the answer's portions, looked for from ``at`` on."""
    said = flat(cue_text)
    for k in range(at, len(portions)):
        own = flat(portions[k])
        if said == own:
            return 'whole', k
        if said and own.endswith(said):
            return 'rest', k
    return None


def scene(flags, behaviours, answers=ANSWERS, rounds=1, name=''):
    """One call: ``rounds`` passes over ``answers``; portion j of every answer gets ``behaviours[j % len]``."""
    from test_h3_tempo import TICK
    board = Board()
    rig = make_rig(flags)
    try:
        if name in SAY_FIRST:
            utter(rig, SAY_FIRST[name])
            rig.pump(1.0)
        job = 0
        for r in range(rounds):
            for ask, portions in answers:
                board.n['answers'] += 1
                before = len(rig.cues())
                extra = len(rig.fake.runs) - job
                if extra > 0:
                    board.n['false_jobs'] += extra
                    board.episodes.append(f'{name} before answer {board.n["answers"]}: {extra} job(s) opened on the listener\'s repeats: {[r.request for r in rig.fake.runs[job:]][:2]!r}'[:300])
                job = len(rig.fake.runs)
                try:
                    rig.asks(f'q{job}', ask, job, ' '.join(portions))
                except AssertionError:
                    pass
                job += 1
                plan = list((rig.c.state() or {}).get('chunks') or [])
                got = [which(c.text, plan, 0) for c in cues_since(rig, before)]
                lost_words = len(words_of(' '.join(portions))) - len(words_of(' '.join(plan)))
                if lost_words > 3:
                    board.episodes.append(f'{name} answer {job}: the plan has {lost_words} words fewer than the answer: {plan!r}')
                portions = plan
                if not got or got[0] != ('whole', 0):
                    board.n['lost_answer'] += 1
                    board.episodes.append(f'{name} answer {job}: first cue {[c.text for c in cues_since(rig, before)]}')
                    rig.pump(8)
                    continue
                rig.pump(0.5)
                at = 0
                while at < len(portions):
                    board.n['portions'] += 1
                    portion = portions[at]
                    words = words_of(portion)
                    kind = behaviours[(at + r) % len(behaviours)]
                    last = at == len(portions) - 1
                    mark = len(rig.cues())
                    if kind == 'silence':
                        board.n['silences'] += 1
                        rig.pump(rig.c._repeat_wait() + 1.5)
                        new = cues_since(rig, mark)
                        if new and which(new[0].text, portions, at) == ('whole', at):
                            board.n['silence_whole'] += 1
                        elif new:
                            board.episodes.append(f'{name} silence at {at}: {new[0].text!r}')
                        else:
                            board.episodes.append(f'{name} silence at {at}: nothing')
                        kind = 'whole'
                        mark = len(rig.cues())
                    if kind in ('stumble', 'stammer', 'jump', 'stumble_silent'):
                        board.n['stumbles'] += 1
                        head = stumble_at(words) if kind != 'jump' else words[:1]
                        said = ' '.join(head) if kind in ('stumble', 'stumble_silent') else ('э-э ' + head[0][:2 if len(head[0]) > 3 else 1] + '-' + ' '.join(head)) if kind == 'stammer' \
                            else ' '.join([words[0]] + words[2:3])      # a word jumped over: help from it
                        _, ended = utter(rig, said)
                        rig.pump(3.0 + (DICTATION_START_SECONDS if rig.c.dictation else 0.0))      # dictating, a stop is helped later (the pen)
                        new = cues_since(rig, mark)
                        want = ' '.join(words[len(head):])
                        if new and which(new[0].text, portions, at) and which(new[0].text, portions, at)[1] > at:
                            board.n['false_steps'] += 1
                            board.episodes.append(f'{name} {kind} {said!r} at {at}: went on {new[0].text!r}')
                            at += 1
                            continue
                        if not new or flat(new[0].text) != want:
                            board.n['wrong_help'] += 1
                            board.episodes.append(f'{name} {kind} {said!r} at {at}: help {[c.text for c in new]!r}, want {want!r}')
                        if kind == 'stumble_silent' and new:
                            board.n['silences'] += 1
                            mark2 = len(rig.cues())
                            rig.pump(rig.c._repeat_wait() + 1.5)
                            again = new[1:] + cues_since(rig, mark2)
                            if again and flat(again[0].text) == want:
                                board.n['silence_whole'] += 1      # here: the help from the same word again
                            else:
                                board.episodes.append(f'{name} silence after the help at {at}: {[c.text for c in again]!r}, want {want!r}')
                        mark = len(rig.cues())
                        kind = 'rest'
                        words = words[len(head):]
                    if kind == 'write':
                        rig.pump(WRITE_S)
                        early = cues_since(rig, mark)
                        if early:
                            board.n['cut_in'] += 1
                            board.episodes.append(f'{name} write at {at}: cue while writing {[c.text for c in early]!r}')
                        mark = len(rig.cues())
                        said = ' '.join(words[-2:])
                    elif kind in ('whole', 'rest'):
                        said = ' '.join(words)
                    elif kind == 'last':
                        said = words[-1]
                    elif kind == 'last2':
                        said = ' '.join(words[-2:])
                    elif kind == 'most':
                        said = ' '.join(most_of(words))
                    board.n['moves'] += 1
                    _, ended = utter(rig, said)
                    deadline = rig.w.clock.t + WAIT_NEXT_S
                    while rig.w.clock.t < deadline and len(rig.cues()) == mark:
                        rig.pump(TICK)
                    new = cues_since(rig, mark)
                    if last:
                        rig.pump(1.0)
                        new = cues_since(rig, mark)
                        if not new:
                            board.n['ack_first'] += 1
                        else:
                            board.episodes.append(f'{name} {kind} {said!r} at the last portion: {[c.text for c in new]!r}')
                        at += 1
                        continue
                    w = which(new[0].text, portions, at) if new else None
                    if w == ('whole', at + 1):
                        board.n['ack_first'] += 1
                        at += 1
                        continue
                    board.episodes.append(f'{name} {kind} {said!r} at {at}: next {[c.text for c in new]!r}')
                    if w and w[1] > at + 1:
                        board.n['lost'] += w[1] - at - 1
                        at = w[1]
                        continue
                    # not moved on: the listener says it whole once more (twice at most), then the next answer
                    for _ in range(2):
                        mark = len(rig.cues())
                        utter(rig, ' '.join(words_of(portion)))
                        rig.pump(WAIT_NEXT_S)
                        new = cues_since(rig, mark)
                        w = which(new[0].text, portions, at) if new else None
                        if w and w[1] > at:
                            break
                    if w and w[1] > at + 1:
                        board.n['lost'] += w[1] - at - 1
                    at = w[1] if w and w[1] > at else len(portions)
                rig.pump(2.0)
        board.n['loops'] += loops_of(rig)
    finally:
        try:
            rig.close()
            rig._mp.undo()
        except Exception:
            pass
    return board


def loops_of(rig):
    """A portion cued more than LOOP_CUES times in a row with no onset of the listener between: the onsets are the detector's script."""
    cues = rig.cues()
    run, count = None, 0
    loops = 0
    spoke = [t for t, kind in getattr(rig, 'onsets', [])]
    for cue in cues:
        key = flat(cue.text)
        count = count + 1 if key == run else 1
        run = key
        if count == LOOP_CUES + 1:
            loops += 1
    return loops


SCENES = {
    'whole': ['whole'],
    'last_word': ['last'],
    'last_two': ['last2'],
    'most': ['most'],
    'stumble': ['stumble'],
    'stammer': ['stammer'],
    'silence': ['silence'],
    'dictation': ['write'],
    'mixed': ['whole', 'stumble', 'last', 'silence', 'most', 'last2'],
    'jump': ['jump'],
    'stumble_silent': ['stumble_silent'],
    'voice_dictation': ['write'],
}
SAY_FIRST = {'voice_dictation': 'Диктуй медленно'}      # said before the first question of the scene


def run_all(flags, scenes=None, long_rounds=4):
    out = {}
    for name in scenes or SCENES:
        out[name] = scene(flags, SCENES[name], name=name)
    out['marathon16'] = scene(flags, ['whole', 'last2', 'most'], rounds=long_rounds, name='marathon16')
    return out


def total(out):
    board = Board()
    for b in out.values():
        board.add(b)
    return board


def table(out):
    keys = ('answers', 'lost_answer', 'portions', 'moves', 'ack_first', 'lost', 'loops', 'false_steps', 'stumbles', 'wrong_help', 'silences', 'silence_whole', 'cut_in', 'false_jobs')
    lines = ['| scene | ' + ' | '.join(keys) + ' |', '|' + '---|' * (len(keys) + 1)]
    for name, b in list(out.items()) + [('ALL', total(out))]:
        lines.append(f'| {name} | ' + ' | '.join(str(b.n[k]) for k in keys) + ' |')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--flags', default='')
    parser.add_argument('--scenes', default='')
    parser.add_argument('--episodes', type=int, default=20)
    parser.add_argument('--json', default='')
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    flags = dict(item.split(':', 1) for item in args.flags.split(',') if item)
    out = run_all(flags, args.scenes.split(',') if args.scenes else None)
    print(f'flags: {flags or "(defaults)"}')
    print(table(out))
    episodes = total(out).episodes
    for line in episodes[:args.episodes]:
        print('  -', line)
    if len(episodes) > args.episodes:
        print(f'  ... {len(episodes) - args.episodes} more')
    if args.json:
        Path(args.json).write_text(json.dumps({name: b.n for name, b in out.items()}, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()

"""I1b (U128, U83, U106): the owner's transcribed lectures and exam (U1/05_WORK/TRANSCRIBE_NIGHT) as the scenes of the real-sound stand.

A transcript is a folder of ``part_NNN.txt`` (ten minutes each, no punctuation, no time marks). Here it gives the WORDS: a question read aloud, a «подождите» in the middle of counting, a long speech without a question.
``scan`` finds those places, ``phrases_of`` makes of them the phrases ``real_sound.scenes`` wants, ``tone_bank`` makes a bank in which every word of those phrases is a tone of its own (the transcripts have no
audio and no time marks, so no word can be cut from a recording here; with a real bank, ``real_sound.Bank.of``, the same phrases are said with the owner's voice), ``run_scenes`` gives every scene of the catalog, under
several shapes of the packets (clean, a stall, losses), to the real ControlledMedia through ``stand.run_sound`` and returns the decisions and the times.

What is real: the words (what was really said in a lecture), the detector, the controller, the wire. What is not: the sound (tones), the recognizer's text (the labels), the cloud and the model (scripted), the clock
(virtual). So the times are the order of events of a stand, never a measurement on a laptop or a phone (07_METRICS_PROVENANCE.md §6).

The transcripts are the owner's: nothing of them is copied into the repository, and the report names a scene by folder/part/word number and counts, never by its words.
"""
import hashlib
import json
import random
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.replay import real_sound as RS
from echo_sync.textutil import normalize

QUESTION_WORDS = ('вопрос', 'вопросы', 'вопроса')
STOP_WORDS = ('подождите',)
DOUBT_MARK = ('то', 'есть')
ANSWER = 'Ответ.'
SECOND_ANSWER = 'Другой ответ.'
FIXED_ANSWER = 'Исправленный ответ.'
QUESTION_LEN = 8                       # words of a question phrase, from two before the marker
CHATTER_LEN = 8
LONG_LEN = 40                          # words of a stretch of a lecture without a question («молчать»)
MARKS = set(QUESTION_WORDS) | set(STOP_WORDS)

# where TR_scenes.md found them (addresses only): (folder, part, kind)
ADDRESSES = (
    ('7_нояб_14_38', 5, 'question'), ('7_нояб_14_38', 9, 'question'), ('6_нояб_13_02', 16, 'question'), ('10_нояб_13_16', 9, 'question'),
    ('6_нояб_13_02', 9, 'stop'), ('13_нояб_12_51', 2, 'stop'), ('13_нояб_12_51', 5, 'stop'), ('10_нояб_10_51', 3, 'stop'),
    ('10_нояб_13_16', 10, 'long'), ('11_нояб_14_31', 3, 'long'),
)


def words_of_text(text):
    return normalize(text).split()


def read_part(root, folder, part):
    """The words of ``<root>/<folder>/part_NNN.txt``; ``None`` when the file is not there."""
    path = Path(root) / folder / f'part_{int(part):03d}.txt'
    if not path.is_file():
        return None
    return words_of_text(path.read_text(encoding='utf-8', errors='replace'))


@dataclass(frozen=True)
class Source:
    """A place in a transcript and the words of it. ``words`` stay in memory; ``address`` is all a report says."""
    kind: str                           # question stop long doubt chatter
    folder: str
    part: int
    at: int                             # the number of the first word in the part
    words: tuple

    @property
    def address(self):
        return f'{self.folder}/part_{self.part:03d}@{self.at}+{len(self.words)}'


def _plain(window):
    """A window of words that holds no marker and whose words are short enough to be a word of speech."""
    return len(window) >= 2 and not (MARKS & set(window)) and all(1 <= len(w) <= 20 for w in window)


def scan(tokens, folder, part, kind, count=1, length=None):
    """The first ``count`` places of ``kind`` in the words of a part. A question: ``QUESTION_LEN`` words from two before «вопрос»; a stop: the run of «подождите» (as said, up to three); a long speech: the
    first stretch of ``LONG_LEN`` words without a marker, from the middle of the part; a doubt: «то есть» with the three words after it; chatter: a stretch of ``CHATTER_LEN`` words without a marker."""
    out, n = [], len(tokens)
    if kind == 'question':
        for i, w in enumerate(tokens):
            if w in QUESTION_WORDS:
                lo = max(0, i - 2)
                win = tuple(tokens[lo:lo + (length or QUESTION_LEN)])
                if len(win) >= 4 and not (set(STOP_WORDS) & set(win)):
                    out.append(Source(kind, folder, part, lo, win))
                    if len(out) >= count:
                        break
    elif kind == 'stop':
        i = 0
        while i < n and len(out) < count:
            if tokens[i] in STOP_WORDS:
                j = i
                while j < n and tokens[j] in STOP_WORDS and j - i < 3:
                    j += 1
                out.append(Source(kind, folder, part, i, tuple(tokens[i:j])))
                i = j
            else:
                i += 1
    elif kind == 'doubt':
        for i in range(n - 4):
            if tuple(tokens[i:i + 2]) == DOUBT_MARK and _plain(tokens[i + 2:i + 5]):
                out.append(Source(kind, folder, part, i, tuple(tokens[i:i + 5])))
                if len(out) >= count:
                    break
    elif kind in ('long', 'chatter'):
        size = length or (LONG_LEN if kind == 'long' else CHATTER_LEN)
        for i in range(n // 2, max(n // 2, n - size), size):
            win = tokens[i:i + size]
            if len(win) == size and _plain(win):
                out.append(Source(kind, folder, part, i, tuple(win)))
                if len(out) >= count:
                    break
    else:
        raise ValueError(f'unknown kind of a source: {kind!r}')
    return out


def collect(root, addresses=ADDRESSES):
    """The sources of the addresses TR_scenes.md names that the root has; ``(sources, absent)``: absent is ``[(folder, part)]`` of files not there."""
    sources, absent, seen = [], [], {}
    for folder, part, kind in addresses:
        key = (folder, part)
        if key not in seen:
            seen[key] = read_part(root, folder, part)
        tokens = seen[key]
        if tokens is None:
            if key not in absent:
                absent.append(key)
            continue
        sources += scan(tokens, folder, part, kind, count=2 if kind == 'question' else 1)
        if kind == 'stop' or kind == 'long':
            sources += scan(tokens, folder, part, 'chatter')
        if kind == 'question':
            sources += scan(tokens, folder, part, 'doubt')
    return sources, absent


def phrases_of(sources):
    """The phrases ``real_sound.scenes`` wants from the sources; a missing kind is made up of the others and ``made_up`` lists which (``(phrases, made_up)``). Answers are the stand's scripted ones."""
    by = {}
    for s in sources:
        by.setdefault(s.kind, []).append(s)
    made_up = []

    def text(source):
        return ' '.join(source.words)
    questions = by.get('question', [])
    if not questions:
        raise ValueError('no question in the transcripts: nothing for a scene to ask')
    q1 = questions[0]
    if len(questions) > 1 and questions[1].words != q1.words:
        q2 = questions[1]
    else:
        q2 = Source('question', q1.folder, q1.part, q1.at, tuple(reversed(q1.words[-4:])))             # the same words in another order: a different question
        made_up.append('question2')
    fixed = q1.words[:-1] + (next((w for w in (q2.words + ('другой',)) if w != q1.words[-1] and w not in q1.words), 'другой'),)
    stop = (by.get('stop') or [None])[0]
    chatter = (by.get('chatter') or by.get('long') or [None])[0]
    doubt = (by.get('doubt') or [None])[0]
    if stop is None:
        stop = Source('stop', q1.folder, q1.part, 0, ('подождите',))
        made_up.append('stop')
    if chatter is None:
        chatter = Source('chatter', q1.folder, q1.part, 0, q1.words[:CHATTER_LEN][::-1])
        made_up.append('chatter')
    if doubt is None:
        doubt = Source('doubt', q1.folder, q1.part, 0, ('то', 'есть', 'еще', 'раз'))
        made_up.append('doubt')
    phrases = {'question': text(q1), 'answer': ANSWER, 'question2': text(q2), 'answer2': SECOND_ANSWER, 'stop': text(stop), 'chatter': ' '.join(chatter.words[:CHATTER_LEN]),
               'fix': ' '.join(fixed), 'fixed_answer': FIXED_ANSWER, 'doubt': text(doubt)}
    longs = by.get('long') or []
    if longs:
        phrases['long'] = text(longs[0])
    return phrases, made_up


# =====================================================================================================================================
# a bank of tones for the words
# =====================================================================================================================================

def word_tone(word, rate=RS.RATE):
    """A voiced stand-in for a word: the pitch from a hash of the word, the length from its letters (never shorter than the bank's own minimum), so a word is the same every time."""
    h = int(hashlib.sha256(word.encode('utf-8')).hexdigest()[:8], 16)
    return RS.tone(max(0.15, 0.065 * len(word)), 140 + h % 260, rate)


def tone_bank(vocabulary, seed=0):
    """``Bank`` of ``vocabulary``: every word a tone, room tone (low random noise) between and at both ends (the bank takes its room tone from a quiet stretch)."""
    rng = random.Random(f'lecture-bank-{seed}')

    def room(seconds):
        from array import array
        return array('h', (rng.randint(-15, 15) for _ in range(int(seconds * RS.RATE))))
    a, words = room(1.0), []
    for word in sorted(set(vocabulary)):
        body = word_tone(word)
        words.append({'w': word, 'start': len(a) / RS.RATE, 'end': (len(a) + len(body)) / RS.RATE, 'conf': 0.9, 'clean': True})
        a.extend(body)
        a.extend(room(0.30))
    a.extend(room(1.0))
    recording = RS.Recording(RS.pcm_of(a), RS.RATE)
    return RS.Bank.of(recording, RS.words_of({'utterances': [{'words': words}]}))


def vocabulary_of(phrases):
    """The words a bank must have to say the phrases (the answers are the stand's text, nobody says them)."""
    return sorted({t for k, v in phrases.items() if k not in ('answer', 'answer2', 'fixed_answer') for t in normalize(v).split()})


# =====================================================================================================================================
# the scenes through the real chain
# =====================================================================================================================================

SHAPES = {
    'clean': {},
    'stall': {'stalls': ((2.0, 1.2), (9.0, 0.8))},
    'loss': {'loss': 0.03},
}


def scene_catalog(phrases):
    """The catalog of ``real_sound.scenes`` and, when the transcripts gave a long speech, a scene that must stay silent: a lecture stretch without a question, said twice."""
    catalog = RS.scenes(phrases)
    if phrases.get('long'):
        catalog['lecture_without_question'] = [RS.Step('chatter', phrases['long'], 1.0), RS.Step('chatter', phrases['long'], 2.0)]
    return catalog


def run_scenes(phrases, bank=None, *, seed=1, shapes=('clean', 'stall', 'loss'), names=None):
    """``[row]`` one per scene and shape: ``{scene, shape, said, violations, crash, decisions, silent_ok}``. ``silent_ok``: no cue over the utterances that are not a question (the lecture is not answered)."""
    from tools.replay import stand
    bank = bank or tone_bank(vocabulary_of(phrases), seed)
    rows = []
    for name, steps in scene_catalog(phrases).items():
        if names and name not in names:
            continue
        audio = RS.build(bank, steps, seed=seed)
        for shape in shapes:
            packets = RS.arrivals(audio.pcm, rate=audio.rate, seed=seed, **SHAPES[shape])
            out = stand.run_sound(seed, audio, packets=packets)
            rows.append({'scene': name, 'shape': shape, 'said': len(audio.items), 'skipped': len(audio.skipped), 'violations': [v for v in out.violations if v[0] != 'A2e'], 'crash': out.crash,
                         'decisions': stand.decisions(out), 'silent_ok': all(d['first_cue'] is None for d in stand.decisions(out) if d['kind'] == 'chatter' and name == 'lecture_without_question')})
    return rows


def summary(rows):
    """The numbers of a run: how many scene runs, how many violated, the times of the first cue after a question's end (stand time) with the passport."""
    after = [d['after_offset_s'] for r in rows for d in r['decisions'] if d['kind'] in ('question', 'fix') and d['after_offset_s'] is not None]
    asked = sum(1 for r in rows for d in r['decisions'] if d['kind'] in ('question', 'fix'))
    out = {'runs': len(rows), 'with_violations': sum(1 for r in rows if r['violations'] or r['crash']), 'questions': asked, 'answered': len(after),
           'silent_broken': sum(1 for r in rows if not r['silent_ok'])}
    if after:
        s = sorted(after)
        out.update(median_s=round(statistics.median(s), 2), p95_s=s[min(len(s) - 1, int(0.95 * len(s)))], max_s=s[-1])
    out['passport'] = 'virtual clock of the stand, tones for the words, scripted cloud/model: the order of events, not a measurement on a laptop or a phone'
    return out


def report(rows, sources, made_up, absent):
    """A report of a run that has no word of the transcripts in it: addresses and counts."""
    return {'sources': [s.address + ':' + s.kind for s in sources], 'made_up': made_up, 'absent_parts': [f'{f}/part_{p:03d}' for f, p in absent], 'summary': summary(rows),
            'runs': [{'scene': r['scene'], 'shape': r['shape'], 'said': r['said'], 'violations': [(v[0], v[1]) for v in r['violations']], 'crash': bool(r['crash']),
                      'after_s': [d['after_offset_s'] for d in r['decisions'] if d['kind'] in ('question', 'fix')]} for r in rows]}


def main(argv=None):
    """``python -m tools.replay.lecture_scenes <root of TRANSCRIBE_NIGHT> <report.json>`` (the report goes where it is told, never into the repository)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print(main.__doc__)
        return 2
    sources, absent = collect(argv[0])
    phrases, made_up = phrases_of(sources)
    rows = run_scenes(phrases)
    Path(argv[1]).write_text(json.dumps(report(rows, sources, made_up, absent), ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(summary(rows), ensure_ascii=False))
    return 0 if not summary(rows)['with_violations'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

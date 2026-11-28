"""W5 stumble: the 300-row table and the simulation of tempos for ``echo_sync.pace``. Nothing here reads the code under test to make an expectation: the speaker, the scene and what must
come of it are built from the scene alone. Seeded: the same rows every run. ``python tests/helpers_w5_pace.py --csv FILE --sim FILE`` writes both out.

A speaker: seconds per syllable, the median gap inside a group, of a breath at a comma, of the start after the microphone opens (log-normal around them). Before the scene, they say three other
portions with no stumble (``WARM_PORTIONS``): what the module may learn of them in this call. «Their normal pause»: the longest of that warm-up, of its kind; a fluent scene never pauses longer.
"""
import csv
import math
import random
import sys
from collections import namedtuple
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from echo_sync.pace import Pace  # noqa: E402

Tempo = namedtuple('Tempo', 'name syllable inner boundary start')
TEMPOS = (
    Tempo('very_fast', 0.085, 0.05, 0.30, 0.30),
    Tempo('fast', 0.10, 0.08, 0.40, 0.35),
    Tempo('normal', 0.13, 0.13, 0.55, 0.45),
    Tempo('calm', 0.16, 0.20, 0.70, 0.55),
    Tempo('slow', 0.20, 0.30, 0.90, 0.70),
    Tempo('very_slow', 0.25, 0.45, 1.20, 0.90),
)
SIGMA = {'inner': 0.35, 'boundary': 0.25, 'start': 0.25, 'word': 0.15}
DELIVERY = 0.13          # decision → first PCM (12_LATENCY_CHAIN, «последнее событие журнала → первый PCM» 0.13 с, телефон, повтор): a measurement of the laptop, not of the cloud
TARGET = (0.7, 1.2)      # help this long after the stumble (WAVE5)
CAP = 2.0
WARM_PORTIONS = 3
EAR_QUIET = 0.3         # the ear's detector ends an utterance after 300 ms of quiet (08_LATENCY_BRAINSTORM row 5)
TEXT_LAG = 0.2          # its text comes ~0.2 s after the offset (12_LATENCY_CHAIN: «Ухо: отсечка → текст 0.20», the class «повтор», phone)

# The portions: the words as written, and how a number in them is said. «,» and «—» and a conjunction after a word: the end of a group (the spec of the scene, not read from the module).
PORTIONS = (
    ('Общие условия установления налогов, и сборов в 1999 году не менялись.', {'1999': 'тысяча девятьсот девяносто девятом'}),
    ('Встреча перенесена на 14 марта, потому что директор не успевает.', {'14': 'четырнадцатое'}),
    ('Мы не подписали договор, а только обсудили его условия.', {}),
    ('Температура поднялась до 38 градусов, и врач назначил лекарство.', {'38': 'тридцати восьми'}),
    ('Компания потеряла 300 000 рублей за первый квартал.', {'300 000': 'триста тысяч'}),
    ('Я хочу сказать, что проект не закрыт и работа продолжается.', {}),
    ('Москва была основана в 1147 году князем Юрием Долгоруким.', {'1147': 'тысяча сто сорок седьмом'}),
    ('Отчёт нужно сдать до пятницы, иначе премии не будет.', {}),
    ('В докладе три части: история, современное состояние и прогноз.', {}),
    ('Без этой подписи банк не выдаст кредит на квартиру.', {}),
)
FREE = 'а скажите пожалуйста сколько сейчас стоит билет до казани на завтра'.split()
PROCLITIC = {'не', 'ни', 'в', 'во', 'на', 'с', 'со', 'к', 'по', 'о', 'об', 'от', 'до', 'за', 'из', 'у', 'без', 'для', 'при', 'про', 'и', 'а', 'но', 'или'}
CONJ = {'а', 'но', 'что', 'чтобы', 'потому', 'иначе', 'если', 'когда'}
KINDS = ('fluent', 'stall_inner', 'filler', 'breath_long', 'stall_boundary', 'stretch', 'restart', 'cut', 'stall_number', 'filler_through', 'not_started', 'other_speech')

Spoken = namedtuple('Spoken', 'words surface boundary number')     # one written word: the words it is said with
Row = namedtuple('Row', 'id portion tempo kind stop events mic expect')
Expect = namedtuple('Expect', 'kind index lo hi ref')               # kind: none (no prompt before the end), prompt (index, at ref+lo..ref+hi), hold, start


def spoken(portion, numbers):
    out, raw = [], portion.split()
    i = 0
    while i < len(raw):
        w = raw[i]
        key = next((k for k in numbers if ' '.join(raw[i:i + len(k.split())]).rstrip('.,') == k), None)
        if key:
            n = len(key.split())
            last = raw[i + n - 1]
            out.append(Spoken(numbers[key].split(), ' '.join(raw[i:i + n]), last[-1] in ',.:;', True))
            i += n
            continue
        clean = w.strip('.,:;—').lower().replace('ё', 'е')
        if not clean:
            i += 1
            continue
        out.append(Spoken([clean], w, w[-1] in ',.:;—', False))
        i += 1
    for j in range(len(out) - 1):
        if out[j + 1].words[0] in CONJ:
            out[j] = out[j]._replace(boundary=True)
    return out


def anchor(words, k):
    """The spec: the word they stopped on, with up to two hanging «не», prepositions, conjunctions before it."""
    back = 0
    while k > 0 and back < 2 and not words[k - 1].number and words[k - 1].words[0] in PROCLITIC and not words[k - 1].boundary:
        k -= 1
        back += 1
    return k


def syllables(w):
    return max(1, sum(c in 'аеёиоуыэюя' for c in w))


class Speaker:
    def __init__(self, tempo, rng):
        self.t, self.rng = tempo, rng

    def draw(self, kind):
        median = getattr(self.t, kind)
        return median * math.exp(self.rng.gauss(0, SIGMA[kind]))

    def dur(self, w):
        return syllables(w) * self.t.syllable * math.exp(self.rng.gauss(0, SIGMA['word'])) + 0.04


def say(speaker, words, t, events, cap_inner=None, cap_boundary=None, stats=None):
    """The portion fluently from ``t`` (its first word starts at t). Returns the end of the last word."""
    first = True
    for i, sw in enumerate(words):
        for j, w in enumerate(sw.words):
            if not first:
                kind = 'boundary' if j == 0 and words[i - 1].boundary else 'inner'
                gap = speaker.draw(kind)
                cap = cap_boundary if kind == 'boundary' else cap_inner
                if cap is not None:
                    gap = min(gap, cap)
                if stats is not None:
                    stats[kind].append(gap)
                t += gap
            first = False
            d = speaker.dur(w)
            events.append((w, t, t + d))
            t += d
    return t


def warm(speaker, pace, portion_index, t=0.0):
    """Three other portions, no stumble: what the module may know of this person. Returns (stats, t)."""
    stats = {'inner': [], 'boundary': [], 'start': []}
    for j in range(1, WARM_PORTIONS + 1):
        text, nums = PORTIONS[(portion_index + j) % len(PORTIONS)]
        words = spoken(text, nums)
        pace.cue(text, t)
        start = speaker.draw('start')
        stats['start'].append(start)
        events = []
        end = say(speaker, words, t + start, events, stats=stats)
        for w, a, b in events:
            pace.word(w, a, b)
        t = end + 3.0
    return stats, t


def build_rows():
    rows, n = [], 0
    for p, (text, nums) in enumerate(PORTIONS):
        words = spoken(text, nums)
        inner_stops = [k for k in range(1, len(words) - 1) if not words[k - 1].boundary and not words[k].number and not words[k - 1].number]
        boundary_stops = [k for k in range(1, len(words)) if words[k - 1].boundary]
        number_at = [k for k, sw in enumerate(words) if sw.number]
        for ti, tempo in enumerate(TEMPOS):
            for j in range(5):
                kind = KINDS[((p * len(TEMPOS) + ti) * 5 + j) % len(KINDS)]
                if kind == 'stall_number' and not number_at:
                    kind = 'stall_inner'
                if kind in ('breath_long', 'stall_boundary') and not boundary_stops:
                    kind = 'fluent' if kind == 'breath_long' else 'stall_inner'
                rows.append((n, p, tempo, kind, (p * 31 + ti * 7 + j * 3) % 97, words, inner_stops, boundary_stops, number_at))
                n += 1
    return [scene(*r) for r in rows]


def scene(n, p, tempo, kind, seed, words, inner_stops, boundary_stops, number_at):
    rng = random.Random(1000 + n)
    speaker = Speaker(tempo, rng)
    text = PORTIONS[p][0]
    pace = Pace()
    stats, t0 = warm(speaker, pace, p)
    max_inner, max_boundary = max(stats['inner']), max(stats['boundary'] or [tempo.boundary])
    max_boundary = min(max_boundary, CAP - 0.05)       # a breath longer than the wait of today is prompted today too: out of this table (see the simulation)
    mic = t0
    events = []
    start = min(speaker.draw('start'), max(stats['start']))
    pick = lambda xs: xs[seed % len(xs)]
    if kind in ('fluent', 'breath_long'):
        cap_b = max_boundary
        if kind == 'breath_long':
            cap_b = None
        end = say(speaker, words, mic + start, events, cap_inner=max_inner, cap_boundary=cap_b)
        if kind == 'breath_long':            # every breath as long as their longest of the warm-up
            events, t = [], mic + start
            for i, sw in enumerate(words):
                for j, w in enumerate(sw.words):
                    if events:
                        t += max_boundary if (j == 0 and words[i - 1].boundary) else min(speaker.draw('inner'), max_inner)
                    d = speaker.dur(w)
                    events.append((w, t, t + d))
                    t += d
        expect = Expect('none', None, None, None, None)
        stop = None
    elif kind == 'not_started':
        stop = 0
        expect = Expect('prompt', 0, 0.0, CAP, mic)
    elif kind == 'other_speech':
        stop = None
        t = mic + start
        for w in FREE[:4 + seed % 5]:
            d = speaker.dur(w)
            events.append((w, t, t + d))
            t += d + min(speaker.draw('inner'), max_inner)
        expect = Expect('hold', None, None, None, None)
    else:
        if kind == 'stall_boundary':
            stop = pick(boundary_stops)
        elif kind == 'stall_number':
            stop = pick(number_at)
        else:
            stop = pick(inner_stops)
        end = say(speaker, words[:stop], mic + start, events, cap_inner=max_inner, cap_boundary=max_boundary) if stop else mic + start
        quick_hi = 0.6
        if kind in ('stall_inner', 'stall_number'):
            if kind == 'stall_number' and len(words[stop].words) > 1:        # half of the number said, then silence: the help says all of it
                first = words[stop].words[0]
                t = end + min(speaker.draw('inner'), max_inner)
                d = speaker.dur(first)
                events.append((first, t, t + d))
                end = t + d
            lo = max_inner
            hi = 1.07 if tempo.inner < 0.4 else CAP + 0.01      # in the target (≤1.2 s with delivery), but for a person whose usual pause inside a group is 0.4 s and more: their own pauses come first
            expect = Expect('prompt', anchor(words, stop), lo, hi, end)
        elif kind == 'stall_boundary':
            expect = Expect('prompt', anchor(words, stop), max_boundary, CAP + 0.01, end)
        elif kind == 'filler':
            f = ('э', 'ну', 'как его', 'эээ', 'вот', 'мм', 'это самое', 'забыл')[seed % 8]
            t = end + min(speaker.draw('inner'), max_inner)
            for w in f.split():
                d = 0.25 + 0.2 * (w.startswith('э') and len(w) > 1)
                events.append((w, t, t + d))
                t += d + 0.05
            end = events[-1][2]
            expect = Expect('prompt', anchor(words, stop), 0.0, quick_hi, end)
        elif kind == 'filler_through':
            t = end + min(speaker.draw('inner'), max_inner)
            events.append(('э', t, t + 0.25))
            end = say(speaker, words[stop:], t + 0.25 + min(speaker.draw('inner'), tempo.inner), events, cap_inner=max_inner, cap_boundary=max_boundary)     # on with a gap of theirs, no longer than their usual one
            expect = Expect('none', None, None, None, None)
        elif kind == 'stretch':
            w, a, b = events[-1]
            d = (b - a) * 2.5 + 0.35
            events[-1] = (w, a, a + d)
            expect = Expect('prompt', anchor(words, stop), 0.0, quick_hi, a + d)
        elif kind == 'restart':
            t = end + min(speaker.draw('inner'), max_inner)
            w = words[0].words[0]
            d = speaker.dur(w)
            events.append((w, t, t + d))
            expect = Expect('prompt', anchor(words, 1), 0.0, quick_hi, t + d)
        elif kind == 'cut':
            w = words[stop].words[0]
            part = w[:max(2, len(w) // 2)] if len(w) >= 5 else w[:1]
            t = end + min(speaker.draw('inner'), max_inner)
            events.append((part, t, t + 0.18))
            expect = Expect('prompt', anchor(words, stop), 0.0, quick_hi, t + 0.18)
    return Row(n, text, tempo.name, kind, stop, tuple(events), mic, expect), pace


def utterances(events, quiet=EAR_QUIET):
    """The ear's detector: a run of words with less than ``quiet`` between them is one utterance; its offset comes ``quiet`` after its last word."""
    out = []
    for w, a, b in sorted(events, key=lambda e: e[1]):
        if out and a - out[-1][2] < quiet:
            out[-1] = (out[-1][0] + [(w, a, b)], out[-1][1], b)
        else:
            out.append(([(w, a, b)], a, b))
    return [(ws, a, b + quiet) for ws, a, b in out]


def drive(pace, portion, mic, events, lag=TEXT_LAG, until=None):
    """The ear as it is: its detector says onset and offset; the text of an utterance comes ``lag`` after its offset, all its words with their times at once. The module is asked whenever it said
    to look again. First decision that is not a wait: ``(decision, t)``."""
    pace.cue(portion, mic)
    queue = []
    for ws, on, off in utterances(events):
        queue.append((on, 0, ('on', on)))
        queue.append((off, 1, ('off', off)))
        queue.append((off + lag, 2, ('text', ws)))
    queue.sort(key=lambda q: (q[0], q[1]))
    t, i = mic, 0
    until = until if until is not None else (queue[-1][0] if queue else mic) + 4.0
    while t <= until:
        while i < len(queue) and queue[i][0] <= t + 1e-9:
            what, data = queue[i][2]
            if what == 'text':
                for w, a, b in data:
                    pace.word(w, a, b)
            else:
                pace.voice(data, what == 'on')
            i += 1
        d = pace.decide(t)
        if d.kind == 'prompt' or d.kind == 'hold' or (d.kind == 'done' and i == len(queue)):
            return d, t
        nxt = t + (d.wait_ms / 1000 if d.kind == 'wait' else 0.05)
        if i < len(queue):
            nxt = min(nxt, queue[i][0])
        t = max(nxt, t + 0.001)
    return None, t


def verdict(row, decision, t, pace):
    e = row.expect
    if e.kind == 'none':
        return 'OK' if decision is not None and decision.kind == 'done' else 'FALSE' if decision is not None and decision.kind == 'prompt' else 'OTHER'
    if e.kind == 'hold':
        return 'OK' if decision is not None and decision.kind == 'hold' else 'FALSE' if decision is not None and decision.kind == 'prompt' else 'OTHER'
    if decision is None or decision.kind != 'prompt':
        return 'MISSED'
    if decision.index != e.index:
        return 'INDEX'
    late = t - e.ref
    if late < e.lo - 1e-6:
        return 'EARLY'
    if late > e.hi + 1e-6:
        return 'LATE'
    return 'OK'


def run_table():
    out = []
    for row, pace in build_rows():
        d, t = drive(pace, row.portion, row.mic, row.events)
        v = verdict(row, d, t, pace)
        lat = None if (d is None or d.kind != 'prompt' or row.expect.ref is None) else t - row.expect.ref
        out.append((row, d, t, lat, v, pace.text(d.index) if d is not None and d.kind == 'prompt' else ''))
    return out


# ---- the simulation: tempos from fast to slow, random pauses with no cap, three policies, the price of each mistake ----------------------------------------------------------
PRICE_FALSE = 2.6        # a prompt over a breath: the cue plays over them (~1.2 s of tail), the microphone stays shut 0.8-1 s more, what they said meanwhile is lost; ~0.5 s to find the place again
PRICE_LATE = 1.0         # each second of silence past the first 0.7 s after a real stumble


def today(kind, ref_word_end, signal):
    """The code of today (H3/H7): a start that stopped is helped TEMPO_START_SECONDS 1.2 s after the ear's offset, which comes ~0.3 s after the speech; a filler waits TEMPO_FILLER_SECONDS
    1.5 s from its offset; nothing is said within 1.5 s of an offset. So: the last word's end + 0.3 + 1.2, a filler's + 0.3 + 1.5; a pause longer than 1.5 s inside a portion is a prompt."""
    return ref_word_end + 0.3 + (1.5 if signal else 1.2)


def simulate(n_per_tempo=400, seed=7, lag=TEXT_LAG):
    """Per tempo: ``n`` fluent portions with pauses drawn with no cap (how often a breath gets a false prompt), and ``n`` silent stalls inside a group plus ``n`` at a comma plus ``n`` fillers (how late).
    Policies: pace (this module), today (see ``today``), fixed_1_0 (1.0 s after the last word, any word)."""
    rng = random.Random(seed)
    res = {}
    for tempo in TEMPOS:
        r = {pol: {'fluent': 0, 'false': 0, 'stalls': 0, 'lat': [], 'lat_boundary': [], 'lat_filler': []} for pol in ('pace', 'today', 'fixed_1_0')}
        for i in range(n_per_tempo):
            p = rng.randrange(len(PORTIONS))
            text, nums = PORTIONS[p]
            words = spoken(text, nums)
            speaker = Speaker(tempo, random.Random(rng.random()))
            pace = Pace()
            _, t0 = warm(speaker, pace, p)
            # fluent, no cap on the pauses
            events = []
            start = speaker.draw('start')
            say(speaker, words, t0 + start, events)
            d, _ = drive(pace, text, t0, events, lag=lag)
            gaps = [events[j + 1][1] - events[j][2] for j in range(len(events) - 1)]
            for pol in r:
                r[pol]['fluent'] += 1
            r['pace']['false'] += bool(d is not None and d.kind == 'prompt')
            r['today']['false'] += any(g > 1.5 for g in gaps)
            r['fixed_1_0']['false'] += any(g > 1.0 for g in gaps) or start > 1.0 + 0.9
            # a silent stall inside a group, at a comma, a filler
            inner_stops = [k for k in range(1, len(words) - 1) if not words[k - 1].boundary and not words[k].number and not words[k - 1].number]
            boundary_stops = [k for k in range(1, len(words)) if words[k - 1].boundary]
            for what, stops in (('lat', inner_stops), ('lat_boundary', boundary_stops), ('lat_filler', inner_stops)):
                if not stops:
                    continue
                stop = stops[rng.randrange(len(stops))]
                pace2 = Pace()
                speaker2 = Speaker(tempo, random.Random(rng.random()))
                _, t1 = warm(speaker2, pace2, p)
                ev = []
                end = say(speaker2, words[:stop], t1 + speaker2.draw('start'), ev)
                ref = end
                if what == 'lat_filler':
                    t = end + speaker2.draw('inner')
                    ev.append(('э', t, t + 0.35))
                    ref = t + 0.35
                d, t = drive(pace2, text, t1, ev, lag=lag)
                lat_pace = (t - end + DELIVERY) if d is not None and d.kind == 'prompt' else None
                r['pace'][what].append(lat_pace)
                r['today'][what].append(today(what, ref, what == 'lat_filler') - end + DELIVERY)
                r['fixed_1_0'][what].append(ref + 1.0 - end + DELIVERY)
                for pol in r:
                    r[pol]['stalls'] += 1
        res[tempo.name] = r
    return res


def price(r, stumble_share=0.2):
    """The price of a portion, in seconds of a broken flow: a false prompt on a fluent portion and the lateness past 0.7 s of a stumble's help, by the share of stumbling portions."""
    lats = [x for k in ('lat', 'lat_boundary', 'lat_filler') for x in r[k]]
    missed = sum(x is None for x in lats)
    late = sum(max(0.0, (x if x is not None else 4.0) - TARGET[0]) * PRICE_LATE for x in lats) / max(1, len(lats))
    false = r['false'] / max(1, r['fluent'])
    return (1 - stumble_share) * false * PRICE_FALSE + stumble_share * late, false, late, missed


def pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return float('nan')
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))]


def sim_report(res):
    lines = ['| темп | политика | ложных подсказок на беглой порции | задержка внутри группы p50 / p90 | на запятой p50 / p90 | после заполнителя p50 / p90 | в цели 0,7-1,2 с (внутри группы) | цена при 10 % / 20 % / 40 % запинок |',
             '|---|---|---|---|---|---|---|---|']
    for name, r in res.items():
        for pol, x in r.items():
            inside = [v for v in x['lat'] if v is not None]
            in_target = sum(TARGET[0] - 1e-9 <= v <= TARGET[1] + 1e-9 for v in inside) / max(1, len(x['lat']))
            prices = ' / '.join(f'{price(x, s)[0]:.2f}' for s in (0.1, 0.2, 0.4))
            lines.append(f"| {name} | {pol} | {x['false']}/{x['fluent']} ({100 * x['false'] / max(1, x['fluent']):.1f} %) | {pct(x['lat'], .5):.2f} / {pct(x['lat'], .9):.2f} | "
                         f"{pct(x['lat_boundary'], .5):.2f} / {pct(x['lat_boundary'], .9):.2f} | {pct(x['lat_filler'], .5):.2f} / {pct(x['lat_filler'], .9):.2f} | {100 * in_target:.0f} % | {prices} |")
    return '\n'.join(lines)


def write_csv(path, table):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['id', 'tempo', 'kind', 'portion', 'stop', 'said', 'expect', 'expect_index', 'window_s', 'decision', 'index', 'help_text', 'after_s', 'verdict'])
        for row, d, t, lat, v, help_text in table:
            said = ' '.join(f'{w}@{a - row.mic:.2f}-{b - row.mic:.2f}' for w, a, b in row.events)
            e = row.expect
            win = '' if e.lo is None else f'{e.lo:.2f}..{e.hi:.2f}'
            w.writerow([row.id, row.tempo, row.kind, row.portion, '' if row.stop is None else row.stop, said, e.kind, '' if e.index is None else e.index, win,
                        '' if d is None else d.kind, '' if d is None or d.index is None else d.index, help_text, '' if lat is None else f'{lat:.2f}', v])


if __name__ == '__main__':
    args = dict(zip(sys.argv[1::2], sys.argv[2::2]))
    table = run_table()
    if '--csv' in args:
        write_csv(args['--csv'], table)
    from collections import Counter
    print('table:', len(table), dict(Counter(v for *_, v, _ in table)))
    print('by kind:', dict(Counter((r.kind, v) for r, _, _, _, v, _ in table)))
    if '--sim' in args:
        out = []
        for lag in (TEXT_LAG, 0.5):
            out.append(f'### Задержка текста уха {lag:.1f} с\n\n' + sim_report(simulate(lag=lag)))
        Path(args['--sim']).write_text('\n\n'.join(out) + '\n', encoding='utf-8')
        print('\n\n'.join(out))

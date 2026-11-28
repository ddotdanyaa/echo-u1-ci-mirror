"""w5-flow: how many seconds of silence an answer of 20 portions costs the speaker, now and with ``flow_ahead`` (echo_sync/flow_ahead.py).

A simulation, not a measurement: the speaker and the path are models with the numbers of ``cloud_context/analysis/12_LATENCY_CHAIN.md`` and
``08_LATENCY_BRAINSTORM.md`` (each named below with its status). The REAL ``FlowAhead`` and ``portioner.portions`` decide;
the simulation only makes the times. Run: ``python tools/flow_sim.py [seeds]`` (prints the markdown tables of the report).

Silence of a transition: from the end of the last word of the repeat to the first sound of the next cue at the ear. A stumble's own wait
is counted apart (w5-stumble's lever, the same in every row here: TEMPO_REPEAT_SECONDS 2.0 s).
"""
from __future__ import annotations

import math
import random
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from echo_sync import flow_ahead as F                       # noqa: E402
from echo_sync.portioner import portions                    # noqa: E402
from echo_sync.textutil import syllables                    # noqa: E402

ANSWER = ('Пятнадцатая статья Налогового кодекса перечисляет местные налоги. Это земельный налог, налог на имущество физических лиц и '
          'торговый сбор. Земельный налог платят владельцы участков, а ставку устанавливает муниципалитет, но не выше полутора процентов. '
          'Налог на имущество считают от кадастровой стоимости, ставка обычно от одной десятой до двух процентов. Торговый сбор пока '
          'введён только в Москве, его платят магазины и рынки. Все три налога идут в местный бюджет и не делятся с регионом. Сроки '
          'уплаты для граждан одни: до первого декабря следующего года. Организации платят авансы ежеквартально, если муниципалитет их '
          'не отменил. Льготы по местным налогам тоже устанавливает муниципалитет своим решением. Узнать ставки своего города можно на сайте налоговой службы.')
BASE = {'preset': 'meaning'}
N_PORTIONS = 20

# --- the path (seconds). Status: [д] proven in the logs, [р] estimate.
UP = (0.05, 0.12)            # packet 0-100 ms (mean 50) [д size, р mean]; phone -> laptop one way 70-180 ms [р]
OFFSET = 0.30                # the ear's silence before the end of an utterance [д const OFFSET_MS]
T0_TO_PCM = (1.30, 2.07)     # «повтор» class, ear cutoff -> first PCM, median / p90, n=13 [д, 12_LATENCY_CHAIN §3.1]
EAR_LAG = 0.11               # ear decode after the cutoff, lag_ms 109 [д]
SYNTH = 0.054                # SAPI [д, C14]
DOWN = (0.07, 0.18)          # laptop -> phone [р]
PLAY = (0.10, 0.25)          # iOS voice mode to the ear [р]
SAPI_SPS = 0.20              # the cue's own speed, s per syllable (settings sec_per_syllable) [р]
STUMBLE_WAIT = 2.0           # TEMPO_REPEAT_SECONDS: the help of a stumble today [д const]
RECUE = 1.0                  # a withdrawn cue: the current portion's tail is cued again [р]

# --- the speaker [р: a model, not a person]
TEMPOS = {'slow': (0.30, 12), 'mid': (0.22, 18), 'fast': (0.16, 24)}     # s per syllable, syllables held comfortably
JITTER = 0.12                # word-to-word variation of the tempo (cv)
P_BASE_STUMBLE = 0.04
P_WRONG_LAST = 0.02          # the last word said in another form / another word


def lognormal(rng, med, p90):
    sigma = math.log(p90 / med) / 1.2816
    return med * math.exp(rng.gauss(0, sigma))


def stumble_p(syl, cap):
    return min(0.7, P_BASE_STUMBLE + 0.6 * max(0, syl - cap) / cap)


def path_down(rng):
    return rng.uniform(*DOWN) + rng.uniform(*PLAY)


def answer_portions(settings):
    got = portions(ANSWER, settings)
    return got


def simulate(rng, tempo, *, flow, duplex='full', ear=False):
    sps, cap = TEMPOS[tempo]
    plan = answer_portions(BASE)[:N_PORTIONS]
    text = ' '.join(plan)
    done, i = [], 0
    fa = F.FlowAhead(duplex=duplex) if flow else None
    out = {'silence': 0.0, 'stumble': 0.0, 'false_sent': 0, 'withdrawn_held': 0, 'ahead': 0, 'transitions': 0, 'lost': 0.0,
           'overlap': 0, 'portions': 0}
    t = 0.0
    while plan:
        portion, rest = plan[0], plan[1:]
        nxt = rest[0] if rest else None
        out['portions'] += 1
        words = portion.replace(',', ' ').replace('.', ' ').replace(':', ' ').split()
        syl = syllables(portion)
        stumble = rng.random() < stumble_p(syl, cap)
        stop_at = rng.randint(1, len(words) - 1) if stumble and len(words) > 1 else None
        wrong_last = not stumble and rng.random() < P_WRONG_LAST and len(words) > 1
        # the times the speaker ends each word
        start = t + rng.gauss(0.45, 0.1)
        ends, now_t = [], start
        for k, w in enumerate(words):
            if stop_at is not None and k == stop_at:
                now_t += STUMBLE_WAIT                     # stuck before word k, helped after 2.0 s
                out['stumble'] += STUMBLE_WAIT
            now_t += max(1, syllables(w)) * sps * max(0.4, rng.gauss(1, JITTER))
            ends.append(now_t)
        end = ends[-1]
        heard = list(words)
        if wrong_last:
            heard[-1] = 'домами'
        sent = None
        if fa is not None:
            fa.cue(portion, nxt, start - 0.45)
            shown, tick = 0, start - 0.45
            show_at = [e + F.EAR_SEEN_S + rng.gauss(0, 0.04) for e in ends]
            stumbled = False
            while tick < end + 2.5:
                while shown < len(words) and show_at[shown] <= tick:
                    shown += 1
                    fa.heard(' '.join(heard[:shown]), tick)
                if stop_at is not None and not stumbled and tick >= ends[stop_at - 1] + STUMBLE_WAIT * 0.6:
                    stumbled = True
                    fa.p.off = fa.p.off or 'stumble'          # the help of the stumble was cued: nothing ahead in this portion
                d = fa.decide(tick)
                if d.action == 'release' and d.at <= tick:
                    sent = tick
                if d.action == 'withdraw':
                    if d.reason.endswith(':sent'):
                        out['false_sent'] += 1
                        out['lost'] += (syllables(nxt) * SAPI_SPS if nxt else 0) + RECUE
                    else:
                        out['withdrawn_held'] += 1
                    sent = None
                    break
                tick += 0.02
            if sent is not None and (wrong_last or (duplex == 'half' and sent + rng.uniform(*DOWN) < end + F.MIC_PACKET_S)):
                # sent, and the last word is wrong or clipped by the gate: the withdraw comes (the ear's text says so) - counted as false
                if not wrong_last:
                    out['false_sent'] += 1
                    out['lost'] += (syllables(nxt) * SAPI_SPS if nxt else 0) + RECUE
                sent = None
        if wrong_last:
            out['lost'] += RECUE                          # the portion is asked again, in every row
        if nxt is not None:
            out['transitions'] += 1
            if sent is not None:
                at_ear = sent + path_down(rng)
                gap = at_ear - end
                out['ahead'] += 1
                if gap < 0:
                    out['overlap'] += 1
                out['silence'] += max(0.0, gap)
                out.setdefault('gaps', []).append(gap)
            elif flow or ear:                             # flow on needs the acting ear: its confirmation is the fallback
                out['silence'] += rng.uniform(*UP) + OFFSET + EAR_LAG + SYNTH + path_down(rng)
            else:
                out['silence'] += rng.uniform(*UP) + OFFSET + lognormal(rng, *T0_TO_PCM) + path_down(rng)
        t = end + 0.5 + syl * SAPI_SPS
        done.append(portion)
        plan = rest
    assert ' '.join(done).split() == text.split()
    return out


def run(seeds=300, duplex='full'):
    rows = {}
    for tempo in TEMPOS:
        rows[tempo] = {}
        for name, flow, ear in (('now', False, False), ('ear', False, True), ('flow', True, True)):
            got = [simulate(random.Random(s * 7919 + list(TEMPOS).index(tempo) * 100003), tempo, flow=flow, duplex=duplex, ear=ear)
                   for s in range(seeds)]
            tr = sum(g['transitions'] for g in got)
            rows[tempo][name] = {
                'silence_med': statistics.median(g['silence'] for g in got),
                'silence_p90': sorted(g['silence'] for g in got)[int(0.9 * len(got))],
                'per_transition': sum(g['silence'] for g in got) / max(1, tr),
                'stumble_med': statistics.median(g['stumble'] for g in got),
                'total_med': statistics.median(g['silence'] + g['stumble'] + g['lost'] for g in got),
                'ahead_rate': sum(g['ahead'] for g in got) / max(1, tr),
                'false_sent_rate': sum(g['false_sent'] for g in got) / max(1, tr),
                'overlap_rate': sum(g['overlap'] for g in got) / max(1, tr),
                'portions_med': statistics.median(g['portions'] for g in got),
            }
    return rows


def table(rows):
    lines = ['| Темп | Режим | Порций (мед.) | Тишина переходов, с: медиана / p90 | на переход, с | Ожидание запинок, с | Тишина + запинки + потери, с | Ушло заранее | Ложно отправлено | Наложение на слово |',
             '|---|---|---|---|---|---|---|---|---|---|']
    names = {'now': 'сейчас (облако, кусок)', 'ear': 'ухо act, без упреждения', 'flow': 'flow_ahead'}
    for tempo, row in rows.items():
        for name, r in row.items():
            lines.append(f"| {tempo} | {names[name]} | {r['portions_med']:.0f} | {r['silence_med']:.1f} / {r['silence_p90']:.1f} | {r['per_transition']:.2f} | "
                         f"{r['stumble_med']:.1f} | {r['total_med']:.1f} | {r['ahead_rate']:.0%} | {r['false_sent_rate']:.1%} | {r['overlap_rate']:.1%} |")
    return '\n'.join(lines)


if __name__ == '__main__':
    seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    for duplex in ('full', 'half'):
        print(f'\n### duplex={duplex}, {seeds} ответов на темп\n')
        print(table(run(seeds, duplex)))

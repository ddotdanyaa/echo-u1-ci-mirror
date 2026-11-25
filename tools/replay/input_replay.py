"""U17-S6: the offline input replay. A fixture with the ``mic`` key (``tools.harvest``: each second of the phone's microphone as ``[first, last, packets, bytes]``) feeds the InputMeter on the call's own time,
without the controller: for each repeat of the journal (a cue with the words of the cue before it) the sound received in the window since that cue began, and the state the meter reads from it.
  A3  the repeat came after half_listen sound. Live (HostRig, the meter's own log, to the packet) the need is ``half_listen_seconds``; here the rows are seconds wide, so ``got_s >= need - PRECISION_S``.
      A repeat past the last mic second (the call's budget of rows ended) is ``ok=None`` (unknown), not a failure.
  A4  the meter's state label at each repeat (pending_asr, unintelligible, no_packets ... as the design names them).
  A2  the shows of the cue from a second on (default: the call's first cue) and the call's total.
Every metric goes through ``contract.run`` (U25-R1): a replay of the controller whose cues differ from the journal's marks the metrics from that second ``open_replay`` ("controller bound only"); the journal's own cues are the closed case.
The offline measure carries the +-1 s of its rows into the passport; the live A3 is measured on HostRig from the meter log."""
from echo_sync.input_state import HALF_LISTEN_S, InputMeter
from tools.harvest import words
from tools.replay import contract

PRECISION_S = 1.0           # the mic rows are one second wide: the offline need is the live need less this
COVER_S = 2.0               # a repeat later than this after the last mic second is outside the rows (their budget ended)


def packets(mic):
    """``(second, bytes)`` of the packets of the mic rows: a row's packets evenly from its first second to its last, its bytes evenly among them."""
    for first, last, n, size in mic:
        n = max(int(n), 1)
        each, extra = divmod(int(size), n)
        for i in range(n):
            yield (first if n == 1 else first + (last - first) * i / (n - 1)), each + (extra if i == n - 1 else 0)


def repeated(cues):
    """The indexes of the cues that say the words of the cue before them."""
    return [i for i in range(1, len(cues)) if words(cues[i][1]) and words(cues[i][1]) == words(cues[i - 1][1])]


def _need(fixture):
    header = {**fixture.get('header', {}), **fixture.get('profile', {})}
    value = header.get('half_listen_seconds')
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else HALF_LISTEN_S


def repeats(fixture):
    """One row for each repeat of the journal: ``t``, ``got_s`` (sound since the cue before began), ``need`` / ``need_offline``, ``state`` of the meter, ``ok`` (True / False / None) and ``why``."""
    cues, mic = fixture.get('cues', ()), fixture.get('mic', ())
    heard = sorted(packets(mic))
    end = max((row[1] for row in mic), default=None)
    need = _need(fixture)
    out = []
    for i in repeated(cues):
        since, at = float(cues[i - 1][0]), float(cues[i][0])
        meter = InputMeter(since)
        for when, size in heard:
            if since < when <= at:
                meter.packet(when, size)
        covered = end is not None and at <= end + COVER_S
        row = {'name': 'A3_repeat', 't': at, 'got_s': round(meter.got_s, 2), 'need': need, 'need_offline': need - PRECISION_S, 'state': meter.state(at),
               'ok': (meter.got_s >= need - PRECISION_S) if covered else None, 'why': 'got_s' if covered else 'no_mic'}
        out.append(row)
    return out


def metrics(fixture, from_s=None):
    cues = fixture.get('cues', ())
    rows = repeats(fixture)
    rows += [{'name': 'A4_state', 't': r['t'], 'state': r['state']} for r in rows]
    start = float(cues[0][0]) if from_s is None and cues else float(from_s or 0)
    rows.append({'name': 'A2_shows', 't': start, 'shows': sum(1 for c in cues if float(c[0]) >= start), 'total': len(cues)})
    return rows


def run(fixture, replay_cues=None, from_s=None):
    """The call's metrics through the replay contract; ``replay_cues`` are the cues of a controller replay (default: the journal's own, a closed replay)."""
    cues = fixture.get('cues', ()) if replay_cues is None else replay_cues
    return contract.run(fixture, cues, metrics(fixture, from_s))


def report(fixture):
    """Numbers only, for the passport: the replay's counts and the offline precision."""
    got = repeats(fixture)
    return {'repeats': len(got), 'a3_ok': sum(r['ok'] is True for r in got), 'a3_failed': sum(r['ok'] is False for r in got), 'a3_unknown': sum(r['ok'] is None for r in got),
            'mic_seconds': len(fixture.get('mic', ())), 'precision_s': PRECISION_S}


# =====================================================================================================================================
# I1 (U83): a recorded call by packets
# =====================================================================================================================================

def rows_of(packets, rate=24000):
    """The ``mic`` rows (``[first, last, packets, bytes]`` per second of the conversation) of the packets a stand fed (``real_sound.Packet``: ``t`` its arrival, ``data``): the shape the harvest keeps, so the meter
    and the contract see the stand's call as they see a journal's. A stall shows as a second with no row and a burst in the next."""
    seconds = {}
    for p in packets:
        seconds.setdefault(int(p.t), []).append((p.t, len(p.data)))
    return [[min(t for t, _ in row), max(t for t, _ in row), len(row), sum(n for _, n in row)] for _, row in sorted(seconds.items())]


def fixture_of_sound(out, packets, header=None):
    """The fixture of a ``stand.SoundStand`` call: the controller's cues (each ``[t, text, 'completed']``) and the packets' rows. ``run(fixture, replay_cues=...)`` then gives A3 and A4 for a composed or recorded call
    with the packet gaps it was fed (A3 on the stand's own clock: the rows are seconds wide, ``PRECISION_S`` is kept)."""
    cues = [[c[0], c[1], 'completed'] for c in out.cues if not c[6]]
    return {'cues': cues, 'mic': rows_of(packets), 'header': dict(header or {}), 'profile': {}}


def run_sound(out, packets, header=None):
    """The call's metrics (A3 repeats, A4 meter state, A2 shows) of a stand's conversation through the replay contract; the cues are the controller's own, so the contract marks them as its replay."""
    fixture = fixture_of_sound(out, packets, header)
    return run(fixture, replay_cues=fixture['cues'])

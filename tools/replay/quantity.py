"""h28: the class test of «more of it must not break it» (the calls of 7 Nov: long garbage talk, made-up things, friends interfering): the same scene with the quantity K of garbage and silence
growing, through the real chain of the h3 rig. What must not depend on K: the next bank question gets its answer, as fast, with or without the cloud's final; the cue of a question stays
open and is repeated by silence with no mode; talk around it holds it, not ends it. ``python -m tools.replay.quantity`` prints the table. Seconds are the rig's clock.
"""
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT / 'tests'), str(ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools.replay import repeat_scenes as R      # noqa: E402
from echo_sync import instant                    # noqa: E402

LIVE = dict(ear_job='on', ear_lookup='on', cloud_form='on', stumble_place='on')
BANK = [
    ('Что такое инфляция?', 'Устойчивый рост общего уровня цен. Деньги при этом обесцениваются.', []),
    ('Какие бывают виды финансовых отношений?', 'Шесть видов: между государством и населением, хозяйствующими субъектами, банками.', ['виды финансовых отношений', 'перечисли виды финансовых отношений']),
    ('Что такое денежная масса?', 'Все наличные и безналичные деньги в обращении, агрегат М2.', ['денежная масса']),
    ('В чём контрольная функция финансов?', 'Контроль за распределением и использованием денег по их цели.', ['контрольная функция', 'контрольная функция финансов']),
    ('Когда была Куликовская битва?', 'В 1380 году. Дмитрий Донской разбил войско Мамая.', []),
]
GARBAGE = ['ну вот вроде заработал ещё давай', 'слушай а ты пиццу заказал вчера вечером', 'зелёный слон летит над городом и поёт песню', 'да подожди не мешай мне тут',
           'а вот этот сосед опять шумит за стеной', 'кто-то там стучит в дверь наверное курьер', 'я вообще не знаю что мы тут делаем сегодня', 'второй вопрос', 'пока два', 'к два', 'деньги для',
           'организации', 'ха-ха смешно ты сказал про кота', 'марсианский налог на драконов равен семи', 'ну и чего ты молчишь давай говори уже', 'это всё какая-то ерунда полная']


def rig_of(flags=None):
    rig = R.make_rig({**LIVE, **(flags or {})})
    rows = [instant.clean_entry({'q': q, 'alt': alt, 'answer': a, 'source': 'scene', 'subject': 'scene'}) for q, a, alt in BANK]
    rig.c.instant = instant.Instant(rows, adapters=(), rank=True, rank2=True).for_call()
    return rig


def ear_only(rig, text, seconds=None):
    """One utterance the ear hears and the cloud never writes down (the call of 14:45: 110 ear finals, 0 user finals). -> the moment it ended."""
    from test_h3_tempo import TICK
    speech = seconds if seconds is not None else max(0.4, 0.38 * len(R.words_of(text)))
    ear = rig.onset()
    rig.pump(speech)
    ended = rig.offset()
    rig.pump(0.15)
    rig.worker.heard(ear, text)
    rig.pump(TICK)
    return ended


def garbage(rig, k, seed, finals):
    rng = random.Random(seed)
    for _ in range(k):
        text = rng.choice(GARBAGE)
        if finals:
            R.utter(rig, text)
        else:
            ear_only(rig, text)
        R.pump_dashing(rig, rng.choice((0.3, 1.0, 3.0, 8.0)))


def after(rig, mark, wait=8.0, step=0.1):
    """The first cue after ``mark``, pumped up to ``wait`` s: its text and when."""
    t0 = rig.w.clock.t
    while rig.w.clock.t - t0 < wait:
        got = rig.cues()[mark:]
        if got:
            return got[0].text, got[0].t
        rig.pump(step)
    return None, None


def question_after_garbage(k, *, finals=True, seed=1, ask='Что такое инфляция?'):
    rig = rig_of()
    try:
        garbage(rig, k, seed, finals)
        false_cues = len(rig.cues())
        mark = len(rig.cues())
        ended = ear_only(rig, ask)
        text, at = after(rig, mark)
        return dict(k=k, finals=finals, false_cues=false_cues, cue=text, s=None if at is None else round(at - ended, 2), jobs=len(rig.fake.runs))
    finally:
        rig.close()
        rig._mp.undo()


def silence_repeats(seconds=60.0):
    rig = rig_of()
    try:
        ear_only(rig, 'Что такое инфляция?')
        rig.pump(1.0)
        first = len(rig.cues())
        rig.pump(seconds)
        return dict(first=first, repeats=len(rig.cues()) - first, gaps=[round(b.t - a.t, 1) for a, b in zip(rig.cues(), rig.cues()[1:])])
    finally:
        rig.close()
        rig._mp.undo()


def talk_holds(k=30):
    """The cue is open, friends talk K turns; then a new bank question: it is answered; before it the old portion may be repeated, never lost to an error."""
    rig = rig_of()
    try:
        ear_only(rig, 'Что такое инфляция?')
        rig.pump(1.0)
        garbage(rig, k, 3, True)
        state = rig.c.state() or {}
        kept = state.get('chunks') is not None and rig.c.engine.current(state) is not None
        mark = len(rig.cues())
        ended = ear_only(rig, 'Перечисли виды финансовых отношений')
        text, at = after(rig, mark)
        return dict(k=k, kept=kept, cue=text, s=None if at is None else round(at - ended, 2))
    finally:
        rig.close()
        rig._mp.undo()


def main():
    for finals in (True, False):
        for k in (0, 5, 30, 120):
            print(question_after_garbage(k, finals=finals))
    print(silence_repeats())
    print(talk_holds())


if __name__ == '__main__':
    main()

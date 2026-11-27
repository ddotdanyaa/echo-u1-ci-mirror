"""G20-when-silent: the owner talks on his own and does not stumble: no cue. A 3-minute story with pauses up to 2 s, other people's chatter, laughter, a TV: not one cue. A cue only for a question, a stumble, a request.
Real controller, ear and fast_text on the stand (injected clock, scripted job that declines with «—»: no model, no phone)."""
import random

import pytest

from test_h3_tempo import TICK, call       # noqa: F401 - call is the fixture
from test_h5_live import LIVE, asked, spoken_failures

STORY = ['Значит, в прошлом году мы с женой решили поехать на озеро', 'Выехали рано утром, часов в шесть', 'Дорога была пустая, и мы быстро доехали до развилки',
         'Потом свернули налево, там такой старый мост', 'Мост оказался закрыт на ремонт, пришлось объезжать', 'Объезжали минут сорок, жена немного нервничала',
         'Но в итоге приехали, поставили палатку у самой воды', 'Вечером разожгли костёр и сварили уху', 'Рыбу нам отдал сосед по стоянке, он рыбак со стажем',
         'Ночью был дождь, но палатка не промокла', 'Утром туман стоял над озером, красиво невозможно', 'Мы погуляли по берегу, нашли грибы', 'Грибы потом пожарили с картошкой',
         'Обратно ехали уже через другой мост, он как раз открылся', 'Дома сразу легли спать, устали очень сильно', 'А на следующий день сын спросил, когда поедем снова',
         'Я сказал, что в августе, если будет отпуск', 'Вот такая история, ничего особенного, но запомнилась', 'Хочу в этом году повторить, только взять лодку',
         'Лодку можно взять у того же соседа, он вроде сдаёт']
CHATTER = ['Ха-ха-ха', 'Ну ты даёшь', 'А-а-а', 'Слушай, а Серёга-то вчера приходил', 'Да не, он занят был', 'Хе-хе', 'Угу', 'Ага, понятно', 'Ой, не могу',
           'Сегодня в Москве облачно, температура плюс пять, ветер юго-западный', 'В студии у нас сегодня гости', 'Добрый вечер, дорогие телезрители', 'Реклама', 'Ладно, потом договорим']


def decline_new(rig, seen):
    """Every job started since the last look is declined by the model; returns the count seen."""
    for n in range(seen, len(rig.fake.runs)):
        if rig.fake.run(n).cancelled.is_set() or rig.fake.run(n).ended.is_set():       # superseded by the next words: the product cancelled it, nothing to decline
            continue
        rig.job_says(n, '—')
        rig.job_ends(n)
    return len(rig.fake.runs)


def monologue(rig, lines, rng, pause=(0.4, 2.0), speech=(1.5, 5.0)):
    seen = len(rig.fake.runs)
    for line in lines:
        rig.says(line, speech=rng.uniform(*speech), lag=0.15)
        seen = decline_new(rig, seen)
        rig.pump(rng.uniform(*pause))
        seen = decline_new(rig, seen)
    return seen


def silent(rig):
    assert rig.said() == [], rig.said()
    assert not spoken_failures(rig)


@pytest.mark.parametrize('seed', range(5))
def test_a_three_minute_story_with_pauses_up_to_two_seconds_gets_no_cue(call, seed):
    rig = call(**LIVE, local_ear='act', prompt_tempo='ear')
    rng = random.Random(seed)
    lines = list(STORY)
    rng.shuffle(lines)
    t0 = rig.w.clock.t
    monologue(rig, lines, rng)
    assert rig.w.clock.t - t0 >= 60.0
    silent(rig)


def test_the_story_lasts_three_minutes_of_stand_time(call):
    rig = call(**LIVE, local_ear='act', prompt_tempo='ear')
    t0 = rig.w.clock.t
    monologue(rig, STORY * 2, random.Random(1), pause=(1.5, 2.0), speech=(3.0, 5.0))
    assert rig.w.clock.t - t0 >= 180.0
    silent(rig)


@pytest.mark.parametrize('seed', range(5))
def test_other_peoples_chatter_laughter_and_tv_get_no_cue(call, seed):
    rig = call(**LIVE, local_ear='act', prompt_tempo='ear')
    rng = random.Random(seed)
    lines = CHATTER * 4
    rng.shuffle(lines)
    monologue(rig, lines, rng, pause=(0.3, 6.0), speech=(0.3, 4.0))
    silent(rig)


def test_the_story_does_not_spoil_a_question_after_it(call):
    rig = call(**LIVE, local_ear='act', prompt_tempo='ear')
    seen = monologue(rig, STORY[:8], random.Random(3))
    silent(rig)
    asked(rig, 'Слушай, а какая столица Австралии?', uid='uq')
    n = len(rig.fake.runs) - 1
    rig.job_says(n, 'Канберра.')
    rig.job_ends(n)
    assert rig.said() == ['Канберра.'] and not spoken_failures(rig)


@pytest.mark.parametrize('seed', range(5))
def test_a_story_the_server_transcribes_gets_no_cue_and_no_failure_said(call, seed):
    """The same story through the cloud transcript (turn.done), every job declined: the product says nothing."""
    from test_h5_live import said_to_the_room
    rig = call(**LIVE)
    rng = random.Random(seed)
    lines = STORY * 2
    rng.shuffle(lines)
    t0, seen = rig.w.clock.t, 0
    for n, line in enumerate(lines):
        said_to_the_room(rig, f's{n}', line)
        seen = decline_new(rig, seen)
        rig.pump(rng.uniform(0.4, 2.0))
        seen = decline_new(rig, seen)
    assert rig.w.clock.t - t0 >= 60.0
    silent(rig)


def test_a_story_after_an_answer_adds_no_cue_beyond_the_bounded_repeats(call):
    from test_h5_live import ACCOUNT, MATERIALS, plan, said_to_the_room
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    base = len(rig.said())
    seen = len(rig.fake.runs)
    for n, line in enumerate(STORY):
        said_to_the_room(rig, f's{n}', line)
        seen = decline_new(rig, seen)
        rig.pump(1.5)
    assert len(rig.said()) <= base + LIVE['max_auto_repeats'] and not spoken_failures(rig)
    assert rig.said().count(MATERIALS.split(':')[0] + ':') <= 1 + LIVE['max_auto_repeats']


def test_control_a_request_and_a_question_do_cue(call):
    """Not vacuous: the same rig does cue on a request («повтори») and on a question."""
    from test_h5_live import ACCOUNT, BOUGHT, MATERIALS, job_mark, plan, said_to_the_room
    rig = call(**LIVE)
    plan(rig, asked=ACCOUNT, answer=MATERIALS)
    rig.pump(1.0)
    said_to_the_room(rig, 'r1', 'Как ты сказала?')
    job_mark(rig, 1, '[повтори]')
    assert rig.said() == [BOUGHT, BOUGHT]

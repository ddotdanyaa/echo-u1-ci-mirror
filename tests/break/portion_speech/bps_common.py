"""U237 break tests of the families portion / timers / speech / memory: the shared pieces.

Test code only. Nothing re-implements the product: every scenario drives the real ``ControlledMedia`` built as the host builds it
(``helpers_s6_ack.Dictation``: real EchoEngine, real portioner, real classifier; fakes only at the boundary: the clock and the provider events).
A red test here is a found defect: do not loosen an assertion, fix the product (or write down why the assertion is wrong).
"""
import re

import helpers_s6_ack as H

# Four sentences, 10-13 words each: at least three portions whatever the cutter does.
STORY = ('Инерция — это свойство тела сохранять скорость, пока на него не действует сила. '
         'Чем больше масса у тела, тем сильнее проявляется его инерция при разгоне. '
         'Именно поэтому тяжёлый грузовик останавливается дольше лёгкого автомобиля. '
         'Первый закон Ньютона описывает это свойство для всех тел во Вселенной.')

SIDE_ANSWER = 'Трение — это сила, которая мешает скольжению тел друг по другу. Оно возникает на любой шероховатой поверхности.'


def words_of(text):
    """The words of a portion as the owner would say them (no dashes or bare punctuation)."""
    return [w for w in text.split() if re.search(r'\w', w)]


def speaks(actions):
    return [a['text'] for a in actions if a['type'] == 'speak']


def dictation(tmp_path, answer=STORY, name='d', **kwargs):
    d = H.Dictation(tmp_path / name, answer, **kwargs)
    return d


def silence(d, seconds, step=1.0):
    """The transport in a silent room: a tick every ``step`` seconds, every cue the controller issues is played out. Returns the texts spoken by themselves."""
    heard, spent = [], 0.0
    while spent < seconds:
        d.clock.advance(step)
        spent += step
        actions = d.controller.tick(now=d.clock())
        heard += speaks(actions)
        d.play(actions)
    return heard


def finish(d, limit=40):
    """The owner reads every waiting portion back until the answer is complete."""
    for _ in range(limit):
        if d.completed:
            return
        d.say(d.current)
    raise AssertionError('the answer never completed: ' + repr(d.state))

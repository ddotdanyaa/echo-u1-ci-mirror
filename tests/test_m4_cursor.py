"""M4 (portion, the engine cursor): the length of the portions NOT YET SAID follows the listener, through the real ControlledMedia on the h3 stand.

U94.3 / harvest11 #4: ``PortionAdapter`` is fed by the controller once per CONFIRMED portion; 2 bad portions (asked again) of the last 4 lower the level
(a shorter cut), and ``EchoEngine.adapt_rest`` cuts the rest of the answer (here a WHOLE answer, not a stream) again: same words, more portions, the
cursor and the revision stay. A smooth listener changes nothing."""
import pytest

import helpers_s6_state as S
from echo_sync.portioner import ADAPT_LEVELS
from test_h3_tempo import TICK, call  # noqa: F401 - the fixture

ANSWER = ('Вода закипает в обычной кастрюле на плите при ста градусах Цельсия. В горах она закипает раньше, потому что давление воздуха ниже. '
          'Поэтому в горах еду готовят дольше обычного, и кастрюли с плотной крышкой там очень удобны. '
          'Скороварка поднимает давление внутри и возвращает кипение к привычной температуре, поэтому блюда в ней готовятся заметно быстрее.')


def profile():
    return dict(fast_text='on', preset='meaning', max_words=9)


def words(chunks):
    return ' '.join(chunks).lower().replace('.', '').replace(',', '').split()


def listen(rig, stumbled_portions):
    """The listener goes through the portions one by one; on the first ``stumbled_portions`` of them he asks «повтори» twice before he repeats the portion."""
    rig.asks('u1', 'Расскажи про кипение воды', 0, ANSWER)
    before = list(rig.c.state()['chunks'])
    for i in range(5):
        if rig.c.state().get('completed'):
            break
        for k in range(2 if i < stumbled_portions else 0):
            rig.w.feed(S.turn_created(f's{i}{k}', 'user', 'повтори'))
            rig.w.feed(S.turn_done(f's{i}{k}', 'user', 'повтори ещё раз'))
            rig.pump(1.0)
        said = rig.said()[-1]
        rig.w.feed(S.turn_created(f'r{i}', 'user', said.split()[0].lower()))
        rig.w.feed(S.turn_done(f'r{i}', 'user', said))
        rig.pump(1.5)
    return before, list(rig.c.state()['chunks'])


def test_two_bad_portions_of_the_last_four_lower_the_level_and_the_rest_is_cut_shorter(call):
    rig = call(**profile())
    before, after = listen(rig, 2)
    assert rig.c.adapter.trace, 'two portions asked again in a row: the level changed'
    change = rig.c.adapter.trace[0]
    assert change['level'] == 1 and ADAPT_LEVELS[change['level']] == 'semantic_short'
    assert words(after) == words(before), 'the words and the numbers of the answer stand'
    assert len(after) > len(before), 'the rest is cut shorter: more portions'
    assert after[:2] == before[:2], 'the portions already said are not touched'


def test_a_smooth_listener_changes_nothing(call):
    rig = call(**profile())
    before, after = listen(rig, 0)
    assert rig.c.adapter.trace == [] and after == before


def test_adapt_rest_cuts_a_whole_answer_and_refuses_a_stale_revision(call):
    rig = call(**profile())
    rig.asks('u1', 'Расскажи про кипение воды', 0, ANSWER)
    state = rig.c.state()
    assert not state.get('streaming'), 'precondition: a whole answer, nothing streams'
    assert rig.c.engine.adapt_rest(session_id=rig.c.session_id, revision=state['revision'] + 3, level=2) is None
    got = rig.c.engine.adapt_rest(session_id=rig.c.session_id, revision=state['revision'], level=2)
    after = rig.c.state()
    assert got is not None and after['revision'] == state['revision'] and after['chunk_index'] == state['chunk_index']
    assert words(after['chunks']) == words(state['chunks']) and len(after['chunks']) > len(state['chunks'])


STORY = ('Вода закипает в обычной кастрюле на плите при ста градусах Цельсия. В горах она закипает раньше, потому что давление воздуха ниже. '
         'Поэтому в горах еду готовят дольше обычного, и кастрюли с плотной крышкой там очень удобны. '
         'Скороварка поднимает давление внутри и возвращает кипение к привычной температуре, поэтому блюда в ней готовятся заметно быстрее.')
HALL = 'Сколько будет пять умножить на пять'


def confirm(rig, tid):
    said = rig.said()[-1]
    rig.w.feed(S.turn_created(tid, 'user', said.split()[0].lower()))
    rig.w.feed(S.turn_done(tid, 'user', said))
    rig.pump(1.5)


@pytest.mark.parametrize('go_on', ['Дальше', 'Давай дальше', 'Ну дальше', 'Хорошо, дальше'])
@pytest.mark.parametrize('confirmed', [1, 2, 3])
def test_u140_after_a_question_from_the_hall_the_story_goes_on_from_the_place(call, confirmed, go_on):
    """U140: the story is told, a question from the hall is answered, a go-on goes back to the story at the portion it stood on, said again because it was never confirmed (not from the start, not past it); the forms are a class."""
    rig = call(**profile())
    rig.asks('u1', 'Расскажи про кипение воды', 0, STORY)
    chunks = list(rig.c.state()['chunks'])
    for i in range(confirmed):
        confirm(rig, f'c{i}')
    told = rig.said()[-1]
    assert told in chunks, 'precondition: the last cue is a portion of the story'
    place = chunks.index(told)
    rig.asks('u2', HALL, 1, 'Двадцать пять.')
    assert rig.said()[-1].startswith('Двадцать пять'), rig.said()
    rig.w.feed(S.turn_created('n1', 'user', go_on.split()[0].lower()))
    rig.w.feed(S.turn_done('n1', 'user', go_on))
    rig.pump(2.0)
    after = rig.said()[-1]
    assert after in chunks and chunks.index(after) == place, f'after the hall: {after!r}; the story stood at {place}: {chunks}'

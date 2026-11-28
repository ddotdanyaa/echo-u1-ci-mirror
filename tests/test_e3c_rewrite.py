"""Task E3c, item 3 (T-B DEF-T-B01, audit M04): the cloud's final text rewrites the head it had already given and the controller
published. Before: the rewrite was dropped without a word (``_source``: «blocked»), the stream stayed open for good and the listener
waited at its frontier in silence (``streaming=True``, the answer watchdog off once anything was published).

Required: never silence with the stream open. A rewrite the listener has heard (confirmed or being repeated) is an explicit correction
(«Поправка: …») that takes the place of everything not yet confirmed; a rewrite of words nobody has heard replaces them silently; a
rewrite that only changes the surface (punctuation, case, spacing) is no rewrite at all; and a published answer whose stream stalls is
ended with the text that did arrive.

The real ControlledMedia with the production keywords of controlled_host.serve, on an injected clock (tests/test_e3c_restarts.Call).
F1 (wave F): a call publishes a meaning portion - a sentence or a clause - where it published a 2-word head before, so the early texts
below end their head with a full stop or a comma: the head is published at once, as the scenarios require.
"""
from test_e3c_restarts import Call, stream
from test_first_cue_never_silent import created, done


FLIP_EARLY = 'Да, трение всегда тормозит движение.'          # F1: a whole sentence, published at once (was the head «Да, трение»)
FLIP_FINAL = 'Нет, трение иногда ускоряет движение, например при ходьбе.'


def flip(tmp_path, confirmed):
    """T-B's N01 shape: the assistant turn is created with the early claim (its head is published at once), then the SAME turn is done
    with a text that does not continue that head but flips it. ``confirmed``: the listener repeated the head before the rewrite came."""
    s = Call(tmp_path, mute=(1,))
    s.ask('Всегда ли трение тормозит движение', tid='u1')
    s.at(0.5, created('a1', 'assistant', FLIP_EARLY))
    if confirmed:
        s.at(1.0, lambda s: s.c.provider(created('u2', 'user', s.texts[0].split()[0])))
        s.at(2.0, lambda s: s.c.provider(done('u2', 'user', s.texts[0])))
    s.at(2.5, done('a1', 'assistant', FLIP_FINAL))
    return s


def test_a_rewrite_of_the_head_nobody_has_confirmed_is_an_explicit_correction(tmp_path):
    s = flip(tmp_path, confirmed=False)
    s.until(3.0)
    assert s.texts[0] == 'Да, трение всегда тормозит движение.', s.texts
    after = [text for at, text in s.cues if at >= 2.5]
    assert after and after[0].startswith('Поправка:'), s.cues        # said at once, in place of the head that is withdrawn
    s.at(3.0, lambda s: s.c.provider(created('u2', 'user', 'Поправка')))
    s.at(4.2, lambda s: s.c.provider(done('u2', 'user', s.texts[-1])))
    s.until(40)
    assert s.dictated == ('Да, трение всегда тормозит движение. Поправка: Нет, трение иногда ускоряет движение, например при '
                          'ходьбе.'), s.distinct
    state = s.state()
    assert state['completed'] and not state.get('streaming'), state


def test_a_rewrite_of_a_head_the_listener_confirmed_keeps_it_and_corrects_it_explicitly(tmp_path):
    s = flip(tmp_path, confirmed=True)
    s.until(40)
    assert s.dictated == ('Да, трение всегда тормозит движение. Поправка: Нет, трение иногда ускоряет движение, например при '
                          'ходьбе.'), s.distinct
    state = s.state()
    assert state['chunks'][0] == 'Да, трение всегда тормозит движение.' and state['completed'] and not state.get('streaming'), state


def test_a_rewrite_that_only_changes_the_surface_goes_on_without_a_correction(tmp_path):
    """The same words with another punctuation (a refined transcript): nothing was withdrawn, so nothing is announced; the answer goes
    on after what was published."""
    s = Call(tmp_path)
    s.ask('Всегда ли трение тормозит движение', tid='u1')
    s.at(0.5, created('a1', 'assistant', 'Да, трение тормозит движение почти всегда,'))   # F1: the head ends at a comma
    s.at(2.5, done('a1', 'assistant', 'Да трение тормозит движение почти всегда, кроме ходьбы.'))
    s.until(40)
    # c23: since c22-merge the first cue waits for the next clause while it fits the cap (9 words), so the head is not published before the
    # refined transcript arrives and the text spoken is the refined one; either way nothing is withdrawn and nothing is announced.
    assert s.dictated in ('Да, трение тормозит движение почти всегда, кроме ходьбы.', 'Да трение тормозит движение почти всегда, кроме ходьбы.'), s.distinct
    assert not any('Поправка' in text for text in s.texts), s.texts
    assert s.state()['completed'], s.state()


def test_a_rewrite_of_words_nobody_has_heard_replaces_them_without_a_word(tmp_path):
    """The words that changed are in portions that were planned but never spoken: the listener has heard nothing that was withdrawn.
    They are replaced silently; what the listener heard stays."""
    # F1: the changed word stands in a whole sentence of its own, planned (published) while the listener is still on the first
    early = ('Трение — это сила, которая мешает телам скользить друг по другу. Оно нагревает их поверхности. Поэтому шины '
             'изнашиваются и тормоза греются при каждой остановке')
    final = ('Трение — это сила, которая мешает телам скользить друг по другу. Оно разогревает их поверхности. Поэтому шины '
             'изнашиваются и тормоза греются при каждой остановке.')
    s = Call(tmp_path, mute=(1,))
    s.ask('Что такое трение', tid='u1')
    ends = stream(s, 'a1', early, 0.3)
    s.at(ends + 0.5, lambda s: assert_published(s, 'нагревает'))
    s.at(ends + 0.6, done('a1', 'assistant', final))
    s.at(ends + 1.0, lambda s: s.c.provider(created('u2', 'user', s.texts[0].split()[0])))
    s.at(ends + 2.2, lambda s: s.c.provider(done('u2', 'user', s.texts[0])))
    s.until(80)
    assert s.dictated == ('сила, которая мешает телам скользить друг по другу. Оно разогревает их поверхности. Поэтому шины '
                          'изнашиваются и тормоза греются при каждой остановке.'), s.distinct
    assert not any('Поправка' in text or 'нагревает' in text for text in s.texts), s.texts


def assert_published(s, word):
    """Precondition of the scenario: the word that the rewrite changes is in a portion already planned (published, not yet spoken)."""
    state = s.state()
    assert any(word in chunk for chunk in state['chunks'][state['chunk_index'] + 1:]), state['chunks']
    return []


def test_a_published_answer_whose_stream_stalls_is_ended_with_the_text_that_arrived(tmp_path):
    """The cloud's turn never grows again and never closes: the listener confirms what was published and waits at the frontier. After
    ANSWER_CAP_SECONDS of that wait the text that did arrive is the end of the answer: its rest is dictated and the stream is closed,
    never left open for good."""
    s = Call(tmp_path)
    s.ask('Что такое инерция', tid='u1')
    # F1: the head ends at a comma, so a meaning portion is published at once (was «свойство тела» of «… сохранять своё состояние»)
    s.at(0.5, created('a1', 'assistant', 'Инерция — это свойство тела сохранять своё состояние, пока на него не действуют'))   # no more
    s.until(25)
    assert s.state().get('streaming') and s.dictated == 'свойство тела сохранять своё состояние,', s.distinct   # still waited for
    s.until(45)
    assert s.dictated == 'свойство тела сохранять своё состояние, пока на него не действуют', s.distinct
    state = s.state()
    assert not state.get('streaming') and state['completed'], state

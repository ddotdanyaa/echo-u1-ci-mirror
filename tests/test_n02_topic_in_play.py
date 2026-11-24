"""N02 (regression of g31, 15.11): a follow-up hangs on the topic IN PLAY (``lookup_topic``, set when a question opens), not on the last ANSWERED question of the history.
Through the real ControlledMedia: the new subject was asked (its lookup has not come back, so the engine's history still ends with the old answered question), then «Почему так?»."""
from test_controlled_media import question, setup, start


def test_a_follow_up_after_a_new_subject_is_looked_up_with_the_new_subject_not_the_old_answered_question(tmp_path):
    c = setup(tmp_path)
    start(c)                                                   # answered: «Почему меняются времена года?»
    question(c, 'new', 'Что такое инерция?')                   # the new subject; no answer to it yet
    actions = question(c, 'followup', 'Почему так?')
    lookup = [a['lookup_question'] for a in actions if a.get('type') == 'lookup'][-1]
    assert 'инерци' in lookup.casefold() and 'времена' not in lookup, lookup


def test_a_follow_up_with_no_new_subject_still_hangs_on_the_answered_question(tmp_path):
    c = setup(tmp_path)
    start(c)
    actions = question(c, 'followup', 'Почему?')
    assert actions[-1]['lookup_question'] == 'Почему? К вопросу: Почему меняются времена года?'


def _answered(c, text):
    from test_controlled_media import grounded, source
    epoch = question(c, 'u1', text)[-1]['epoch']
    grounded(c, epoch)
    source(c)


def test_a_swap_that_fits_only_the_old_answered_question_is_not_built_on_it_when_a_topic_is_in_play(tmp_path):
    c = setup(tmp_path)
    _answered(c, 'Что учитывает активный счёт?')
    question(c, 'new', 'Что такое инерция?')                   # the topic in play; the old question is still the last ANSWERED one
    actions = question(c, 'swap', 'а пассивный')
    lookups = [a['lookup_question'] for a in actions if a.get('type') == 'lookup']
    assert not any('счёт' in text.casefold() for text in lookups), lookups


def test_the_topic_in_play_is_the_whole_compound_question_not_the_part_the_search_reads(tmp_path, monkeypatch):
    from echo_sync import cm_question
    real = cm_question.probe
    whole = 'Что такое инерция и чем она отличается от массы?'

    def probe(name, *args, **kwargs):
        if name == 'question_part':
            return type('Feature', (), {'value': 'Что такое инерция?'})()      # the search reads the first part only
        return real(name, *args, **kwargs)
    monkeypatch.setattr(cm_question, 'probe', probe)
    c = setup(tmp_path)
    c.fast_call = True
    question(c, 'u1', whole)
    assert c.lookup_topic == whole, c.lookup_topic

"""night-bench, the finding «каждый новый ответ гасит прежний» (671d2fe): ``ControlledMedia._ledger_answer`` writes the answer row of a revision with
``supersedes=`` the row before it, whatever question that row answered (a new question is a new revision too). Through the real controller every answer row
of a call but the last one is ``superseded``: ``ConversationLedger.recap`` (topic_recap) has at most one pair and is always empty, and the projection of
v6_memory, whose signature holds ``superseded``, is rebuilt whole at every answered question instead of being appended to. The real controller, no stand, no network.
Red on 671d2fe. The owner of the files decides the fix (supersede only a row of the SAME question, or let the readers ignore the mark for another question)."""
from echo_sync import v6_memory as V
from echo_sync.controlled_media import ControlledMedia

SET = {'conversation_ledger': 'memory', 'topic_recap': 'on'}
TALK = (('Сколько будет шесть умножить на семь?', 'Сорок два.'), ('В каком году было крещение Руси?', 'Крещение Руси в 988 году.'), ('Когда основали Петербург?', 'В 1703 году.'),
        ('Когда была Куликовская битва?', 'В 1380 году.'), ('Почему небо голубое?', 'Воздух рассеивает синий свет сильнее.'), ('Почему трава зелёная?', 'Хлорофилл отражает зелёный свет.'),
        ('Зачем нужен налог на прибыль?', 'Он пополняет бюджет.'), ('Почему идёт дождь?', 'Пар остывает и падает каплями.'), ('Почему дует ветер?', 'Воздух идёт от высокого давления к низкому.'),
        ('Почему море солёное?', 'Реки приносят соли, вода испаряется.'))


def turn(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def a_call(tmp_path):
    """Ten questions, each answered and its first portion begun and said (the X-CUE source writes the answer row at the first cue of a revision)."""
    c = ControlledMedia(tmp_path / 's.db', session_id='s', settings=SET)
    c.begin_call()
    for n, (question, answer) in enumerate(TALK, 1):
        c.provider(turn(f'u{n}', 'user', question))
        c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'source'}])
        acts = c.provider(turn(f'a{n}', 'assistant', getattr(c, 'answer_marker', '') + answer))
        cue = next(x for x in acts if isinstance(x, dict) and x.get('text'))
        c._cue_event('began', cue, c.clock())
        c._cue_event('done', cue, c.clock() + 1.0)
    return c


def test_the_answer_of_another_question_is_not_superseded_by_the_next_answer(tmp_path):
    answers = [r for r in a_call(tmp_path).convo.records() if r.kind == 'answer']
    assert len(answers) == len(TALK), 'precondition: one answer row per answered question'
    assert [r.tid for r in answers] == [f'u{n}' for n in range(1, len(TALK) + 1)], 'precondition: each row names its own question'
    gone = [r.tid for r in answers if r.superseded]
    assert not gone, 'answer rows of %d other questions are marked superseded: %s' % (len(gone), gone)


def test_one_more_answered_question_is_appended_to_the_projection_not_a_rebuild_of_it(tmp_path, monkeypatch):
    c = a_call(tmp_path)
    proj = V.Projection(c.convo)
    V.build_card(c.convo, 'какая скидка', since=None, projection=proj)
    rebuilt = []
    real = V.Projection._rebuild
    monkeypatch.setattr(V.Projection, '_rebuild', lambda self, records, since: (rebuilt.append(len(records)), real(self, records, since))[1])
    c.provider(turn('u99', 'user', 'Почему лёд скользкий?'))
    c.grounding(c.epoch, [{'url': 'https://example.org', 'text': 'source'}])
    acts = c.provider(turn('a99', 'assistant', getattr(c, 'answer_marker', '') + 'На нём тонкий слой воды.'))
    cue = next(x for x in acts if isinstance(x, dict) and x.get('text'))
    c._cue_event('began', cue, c.clock())
    V.build_card(c.convo, 'какая скидка', since=None, projection=proj)
    assert not rebuilt, 'a new answered question rebuilt the whole projection (%s records): the row before it changed its superseded mark' % rebuilt

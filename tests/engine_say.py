"""Lane B: the engine carries out a verdict it is given (``EchoEngine.reply(decided=...)``); a test of the engine alone has no controller, so its verdict is the plugin's: ``plain_ruling``
(the classifier and going on, as the engine used to read them itself). ``engine_reply(engine, session_id=..., turn_id=..., text=..., ...)`` is ``engine.reply`` for such a test."""
from echo_sync.classifier import CORRECTION, QUESTION
from echo_sync.prepared_answers import from_pairs
from echo_sync.utterance_judge import plain_ruling


def engine_reply(engine, **kw):
    qa = kw.pop('qa', None)
    asked = kw.pop('asked', None)       # as the controller does (``_asked_ruling(whole=)``): the whole utterance is the question of a question or a correction the bank did not prepare
    if 'decided' not in kw:
        kw.update(plain_ruling(engine, kw['session_id'], kw.get('text'), bank=from_pairs(qa), settings=kw.get('settings')))
    if asked and kw['decided'].kind in (QUESTION, CORRECTION) and kw['decided'].prepared is None:
        kw['decided'] = kw['decided']._replace(question=asked)
    return engine.reply(**kw)

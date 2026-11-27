"""Lane B: the engine carries out a verdict it is given (``EchoEngine.reply(decided=...)``); a test of the engine alone has no controller, so its verdict is the plugin's: ``plain_ruling``
(the classifier and going on, as the engine used to read them itself). ``engine_reply(engine, session_id=..., turn_id=..., text=..., ...)`` is ``engine.reply`` for such a test."""
from echo_sync.utterance_judge import plain_ruling


def engine_reply(engine, **kw):
    qa = kw.pop('qa', None)
    if 'decided' not in kw:
        kw.update(plain_ruling(engine, kw['session_id'], kw.get('text'), qa=qa, settings=kw.get('settings')))
    return engine.reply(**kw)

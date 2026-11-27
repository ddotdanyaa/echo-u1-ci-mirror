"""N135 (E72.1, E16): a PERSONAL question about data that changes («сколько у меня сейчас на счету», «какая у меня погода») has no answer here: the system knows neither the account, nor the sky over this person.

Pure, no model, no search, no I/O. ``personal_volatile(text)`` is the class of the ear's text («account», «weather», ...) or None, decided in microseconds; ``honest_reply`` is the short template said at once instead of
8 s of silence and «Нет ответа». Strict on purpose: it fires only on a question that is about «me» AND a thing of this list, the two near each other (``NEAR_WORDS``), and never on a task («если у меня на счету 5000,
сколько ...»), a number given (in digits or words, in the question or just before it), or a stable fact.
D-1 (the caveat «по памяти») is two variants of the reply, ``plain`` (default, the coordinator's standing choice) and ``hedged``: both are pinned by the tests, the owner picks. Inert: nobody imports it until a flag does.
"""
from __future__ import annotations

import re

from .textutil import NUMBER_WORDS, norm_words

NEAR_WORDS = 4      # w3 n2_h06 step 3: the «me» of the question stands at most this many words from the thing it owns («сколько у меня сейчас на счету»: 3); «сколько часов сна нужно взрослому
                    # человеку, ну, в среднем, я не совсем расслышал» has its «я» 7 words off, in another clause, and asks about people in general
_MINE = frozenset('мой моя мое мои моего моей моим моих мою мне меня я'.split())
_HYPOTHESIS = frozenset('если допустим представим представь пусть предположим предположим допустим например'.split())
_DIGITS = re.compile(r'\d')
_HOWTO = frozenset('как такое объясни объясните расскажи расскажите почему зачем'.split())      # a how-to or a definition is a question of the world, not of the listener's data
_ASKING = frozenset('сколько какая какой какое какие каков где что когда скажи подскажи посмотри проверь есть ли'.split())

# kind -> (phrases as word tuples that must all be present as a sequence-free set, words that name the thing)
_KINDS = (
    ('account', frozenset('счету счете баланс балансе остаток остатке карте кошельке зарплата зарплату'.split())),
    ('weather', frozenset('погода погоду погоде градусов температура температуре дождь дождь снег'.split())),
    ('calendar', frozenset('календаре календарь расписании расписание встреча встречи встреч планы задачи'.split())),
    ('mail', frozenset('письма писем сообщений сообщения почте уведомлений'.split())),
    ('place', frozenset('нахожусь местоположение геолокация'.split())),
    ('body', frozenset('пульс давление шагов шаги сон сна калорий'.split())),
    ('parcel', frozenset('посылка посылку заказ заказа доставка курьер'.split())),
)
_HERE = frozenset('у меня мне мой моя мои мое моя моего моей моих мою тут здесь за окном'.split())
_ASKS_THING = {'weather': frozenset('у меня за окном здесь тут'.split())}


def _given(text):
    """A number is given in ``text``: in digits or in words («в одиннадцать вечера»: the transcript writes numbers as words as often as in digits)."""
    return bool(_DIGITS.search(str(text))) or any(word in NUMBER_WORDS for word in norm_words(text))


def personal_volatile(text, before=()):
    """The kind of a personal question about changing data, or None (a task, a number given, another person, a stable fact).
    ``before``: what the listener said just before ``text`` in the same breath of talk (a question said in parts: «я ложусь в одиннадцать» | «вставать в шесть» | «сколько часов сна у меня
    получится»): a number given there makes the question a task as much as one given in ``text``."""
    words = norm_words(text)
    if not words or len(words) > 14:
        return None
    if _given(text) or any(_given(said) for said in before) or any(word in _HYPOTHESIS for word in words):
        return None
    spoken = set(words)
    if spoken & _HOWTO:
        return None
    owners = [k for k, word in enumerate(words) if word in (_MINE - {'мне'}) or word in {'здесь', 'тут', 'окном'}]      # «мне» alone is a dative of a request («где мне найти...»), not a thing of mine
    if not owners:
        return None
    if not (spoken & _ASKING or '?' in str(text)):
        return None
    if 'где' in spoken and 'я' in spoken and spoken & {'сейчас', 'нахожусь', 'сегодня'} and len(words) <= 5:
        return 'place'                       # «где я сейчас», «где я нахожусь»
    for kind, names in _KINDS:
        if spoken & names:
            if kind == 'weather' and not (spoken & _ASKS_THING['weather']):
                return None                  # «какая погода в Казани» has a place and a search, not this
            if kind == 'place':
                continue
            if kind in ('account', 'calendar', 'mail', 'body', 'parcel') and not spoken & ((_MINE - {'мне'}) | {'тут', 'здесь'}):
                return None
            things = [k for k, word in enumerate(words) if word in names]
            if min(abs(k - j) for k in things for j in owners) > NEAR_WORDS:
                return None                  # the «me» is of another clause: the thing is asked of the world
            return kind
    return None


_REPLY = {
    'account': 'У меня нет доступа к вашему счёту. Остаток посмотрите в приложении банка.',
    'weather': 'Я не вижу, какая погода у вас. Посмотрите в приложении или за окном.',
    'calendar': 'Я не вижу ваш календарь. Откройте его в телефоне.',
    'mail': 'Я не вижу вашу почту. Откройте её на телефоне.',
    'place': 'Я не знаю, где вы сейчас. Это видно на карте в телефоне.',
    'body': 'У меня нет ваших показаний. Посмотрите их в приложении часов.',
    'parcel': 'Я не вижу ваш заказ. Статус смотрите в приложении магазина.',
}
_HEDGE = ' Это меняется, по памяти я не скажу.'
VARIANTS = ('plain', 'hedged')


def honest_reply(kind, variant='plain'):
    """The short truthful sentence for ``kind`` (None for an unknown kind). Phrases of up to 12 words, no digits, no abbreviations: it is spoken. ``hedged`` adds that memory will not do for this."""
    if variant not in VARIANTS:
        raise ValueError(variant)
    text = _REPLY.get(kind)
    return None if text is None else text + (_HEDGE if variant == 'hedged' else '')

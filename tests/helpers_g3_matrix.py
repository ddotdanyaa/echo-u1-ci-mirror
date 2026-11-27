"""G3 Part 1: the decision matrix of the turn arbiter, offline, at machine speed.

Every cell is one short scripted exchange through the REAL ControlledMedia, EchoEngine, classifier, portioner and reference base; the wire and the
cloud are emulated (helpers_w1f.Wire: fake clock). STATE x UTTERANCE x CLOUD x wording. A wording belongs to a scene (a topic with its own old answer):
the last scene is the holdout (20 %), never tuned on. After the exchange the listener repeats the portion that should be waiting (the probe): that is
what tells whether the position survived.

``expected`` is the table of the brief, Part 2, written from the rules and not from what the code does; ``score`` compares a run with it. Run as a
script for the table:  python tests/helpers_g3_matrix.py [dev|holdout|all] [--cells family/state/cloud/scene ...] [--json path]
"""
import json
import logging
import os
import statistics
import sys
import tempfile
from collections import Counter, namedtuple
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, os.environ.get('G3_ENGINE_ROOT') or str(Path(__file__).resolve().parents[1]))

from echo_sync.classifier import CORRECTION, QUESTION, analyze                # noqa: E402
from echo_sync import controlled_media as _controlled_media                  # noqa: E402
from echo_sync.controlled_media import ControlledMedia                        # noqa: E402
from echo_sync.engine import EchoEngine                                       # noqa: E402
from echo_sync.textutil import norm_words                                     # noqa: E402
from helpers_w1f import Wire, created, delta, done, pieces                    # noqa: E402

STATES = ('idle', 'more', 'last', 'streaming', 'cut', 'paused')
FAMILIES = ('full', 'in_words', 'paraphrase', 'partial', 'stuck', 'wrong', 'repeat_why', 'repeat_new', 'clear', 'lower', 'bare', 'correction', 'followup',
            'remark', 'by_statement', 'by_question', 'chatter', 'command')
# ``goes_on``: a substantive reply, and somebody goes on talking right after it (a bystander's exchange goes on; a real question leaves silence)
CLOUDS = ('substantive', 'filler_answer', 'filler_only', 'ugu', 'chitchat', 'delegation', 'nothing', 'late', 'first_person', 'goes_on')
METRICS = ('missed_q', 'false_int', 'false_ack', 'double_adv', 'lost_pos', 'stale_cue', 'spoken_fail', 'extra_gen', 'missed_ack', 'wrong_cue')

ANSWERS = ('substantive', 'filler_answer', 'delegation', 'first_person')    # the cloud answers what it was told
LOCAL = ('full', 'in_words', 'paraphrase', 'partial', 'stuck', 'wrong')
ACKS = ('full', 'in_words', 'paraphrase')
HOLDS = ('partial', 'stuck', 'wrong')
BREATH = ('repeat_why', 'repeat_new')
ASKS = ('clear', 'lower', 'bare', 'correction', 'followup')
FOREIGN = ('by_statement', 'by_question', 'chatter')
NO_EVIDENCE_ROWS = ('bare', 'by_statement', 'chatter')     # the classifier has nothing for these: a paused answer takes no candidate (G1, pinned)

FILLER = 'Сейчас посмотрю.'
GOES_ON = 'Ну да, я тоже так подумал тогда'
GOES_ON_AFTER = 0.35       # seconds after the reply was ready


class Scene:
    def __init__(self, name, **fields):
        self.name = name
        self.__dict__.update(fields)
        self.holdout = fields.get('holdout', False)


SCENES = (
    Scene('amort',
          q='Как считают амортизацию станка?',
          a='Обычно станок списывают за 10 лет. Линейный способ не меняет ежегодную сумму начисления. Первый учёт амортизации ввели в 1885 году.',
          cut='Обычно станок списывают за 10 лет. Линейный способ не меняет',
          retell='Обычно станок списывают за 10 лет, линейный способ не меняет сумму.',
          para=('Традиционно станок списывают за 10 лет', 'Первый учёт амортизации ввели именно в 1885 году'),
          wrong=('Обычно станок списывают за 12 лет', 'Первый учёт амортизации ввели в 1895 году'),
          words=('Обычно станок списывают за десять лет', 'Первый учёт амортизации ввели в тысяча восемьсот восемьдесят пятом году'),
          why='А почему?', new='А что такое дебиторская задолженность?', twice=False,
          clear='Что такое дебиторская задолженность?', bare='сорок две тысячи рублей умножить на двенадцать', correction='Не 10 лет, а 15',
          followup='А почему так?', remark='Ты опять завис, суфлёр совсем плохо работает', by_statement='Вася уже подъехал к заправке на углу',
          by_question='Маш, ты не видела мои ключи от машины?', chatter='Ну и жара сегодня на улице, да', command='Стоп',
          replies=dict(clear='Дебиторская задолженность — это долги покупателей перед компанией.', bare='Пятьсот четыре тысячи.',
                       correction='Тогда станок списывают за 15 лет.', followup='Равные доли упрощают планирование расходов.',
                       repeat_why='Равные доли упрощают планирование расходов.', repeat_new='Дебиторская задолженность — это долги покупателей перед компанией.',
                       remark='Постараюсь отвечать быстрее и короче.', by_statement='Заправка на углу работает круглосуточно.',
                       by_question='Ключи обычно лежат в прихожей на полке.', chatter='Сегодня действительно жарко, около тридцати градусов.',
                       other='Такой порядок заметно упрощает налоговый учёт.'),
          first='Я пять лет работал главным бухгалтером в строительной компании.', chit='Хорошо, рад помочь!',
          lower='Когда появился налог на прибыль?', lower_a='в 1992 году, вместе с новым кодексом.'),
    Scene('liquid',      # w3-integ: «до 2,5» became «до 2»: since r21-core (R21-03) the range is one portion, and «от 1,5 до 2,5» weighs more syllables than the first portion's window (R21-10, digits weigh as said)
          q='Что показывает коэффициент текущей ликвидности?',
          a='Нормой считают значение от 1,5 до 2. Показатель ниже единицы не означает банкротства. Банкиры обычно называют 1919 год.',
          cut='Нормой считают значение от 1,5 до 2. Показатель ниже единицы не',
          retell='Нормой считают значение от 1,5 до 2, показатель ниже единицы не означает банкротства.',
          para=('Нормой просто считают значение от 1,5 до 2', 'Банкиры традиционно называют 1919 год'),
          wrong=('Нормой считают значение от 1,5 до 3', 'Банкиры обычно называют 1991 год'),
          words=('Нормой считают значение от полутора до двух', 'Банкиры обычно называют тысяча девятьсот девятнадцать год'),
          why='А почему именно столько?', new='Как рассчитать рентабельность продаж?', twice=False,
          clear='Как рассчитать рентабельность продаж?', bare='оборотный капитал', correction='Нет, не единицы, а двух',
          followup='Приведи пример', remark='Слушай, суфлёр, говори помедленнее, я не успеваю', by_statement='Лена сказала, что заказ привезут к пяти',
          by_question='Серёж, во сколько у тебя поезд завтра?', chatter='Кстати, вчера наши опять проиграли в хоккей', command='Повтори',
          replies=dict(clear='Рентабельность продаж равна прибыли, делённой на выручку.', bare='Оборотный капитал — это разница оборотных активов и короткого долга.',
                       correction='Показатель ниже двух тоже не означает банкротства.', followup='Например, активы 300 рублей при долгах 200 рублей дают полтора.',
                       repeat_why='Кредиторы считают такой запас достаточным.', repeat_new='Рентабельность продаж равна прибыли, делённой на выручку.',
                       remark='Постараюсь говорить заметно медленнее.', by_statement='Заказ к пяти часам вполне успеют доставить.',
                       by_question='Поезд завтра отправляется в девять утра.', chatter='Вчерашний хоккейный матч закончился со счётом три один.',
                       other='Банки смотрят на этот показатель при выдаче кредита.'),
          first='Я считаю этот показатель главным при анализе кредитора.', chit='Отлично, спасибо за вопрос!',
          lower='Где хранят резервный капитал?', lower_a='на отдельном счёте восемьдесят два.'),
    Scene('double',
          q='Кто описал двойную запись в бухгалтерском учёте?',
          a='Историки обычно называют 1494 год — тогда Лука Пачоли издал свой трактат. Двойная запись отражает операцию на двух счетах. С тех пор прошло 530 лет.',
          cut='Историки обычно называют 1494 год — тогда Лука Пачоли издал свой трактат. Двойная запись отражает',
          retell='Историки обычно называют 1494 год, тогда Лука Пачоли издал трактат о двойной записи.',
          para=('Историки традиционно называют 1494 год', 'С тех пор вот прошло 530 лет'),
          wrong=('Историки обычно называют 1484 год', 'С тех пор прошло 530 дней'),
          words=('Историки обычно называют тысяча четыреста девяносто четыре год', 'С тех пор прошло пятьсот тридцать лет'),
          why='А почему именно он?', new='Чем отличается дебет от кредита?', twice=True,
          clear='Чем отличается дебет от кредита?', bare='статья 143 налогового кодекса', correction='Нет, не 1494, а 1458',
          followup='Это неправильно', remark='Опять ты повторяешь одно и то же, суфлёр', by_statement='Дима оставил машину возле второго подъезда',
          by_question='Оль, а где ты купила этот кофе?', chatter='Интересно, кто сейчас лучший футболист в мире', command='Дальше',
          replies=dict(clear='Дебет показывает левую сторону счёта, кредит показывает правую сторону.', bare='Статья 143 определяет налогоплательщиков налога.',
                       correction='В 1458 году трактат написал Бенедетто Котрульи.', followup='Трактат Пачоли действительно вышел в Венеции.',
                       repeat_why='Его книга разошлась по всей Европе.', repeat_new='Дебет показывает левую сторону счёта, кредит показывает правую сторону.',
                       remark='Постараюсь не говорить одинаково.', by_statement='Парковка возле подъезда обычно бесплатная.',
                       by_question='Такой кофе продаётся в магазине за углом.', chatter='Лучшим футболистом многие считают Холанда.',
                       other='Венецианские купцы применяли этот приём раньше.'),
          first='Я преподаю бухгалтерский учёт двенадцать лет и начинаю именно с этого трактата.', chit='Понял, спасибо!',
          lower='Почему кредит пишут справа?', lower_a='потому что так принято со времён венецианских купцов.'),
    Scene('bond',
          q='Чем отличается акция от облигации?',
          a='Облигация приносит купон 8 процентов годовых. Владелец облигации не становится совладельцем бизнеса. '
            'Выпуск разместили в 2021 году.',
          cut='Облигация приносит купон 8 процентов годовых. Владелец облигации не становится',
          retell='Облигация приносит купон 8 процентов годовых, владелец облигации не становится совладельцем.',
          para=('Облигация просто приносит купон 8 процентов годовых', 'Выпуск вот разместили в 2021 году'),
          wrong=('Облигация не приносит купон 8 процентов годовых', 'Выпуск разместили в 2012 году'),
          words=('Облигация приносит купон восемь процентов годовых', 'Выпуск разместили в две тысячи двадцать первом году'),
          why='А почему так мало?', new='Какая сейчас ключевая ставка Банка России?', twice=True,
          clear='Какая сейчас ключевая ставка Банка России?', bare='17 рублей плюс 26', correction='Не 8, а 9 процентов',
          followup='А если наоборот?', remark='Хватит умничать, суфлёр, ты мне мешаешь', by_statement='Шлагбаум опять сломался, надо звонить охраннику',
          by_question='Тань, ты закрыла входную дверь?', chatter='Как думаешь, пойдёт сегодня дождь?', command='Продолжай',
          replies=dict(clear='Ключевая ставка составляет шестнадцать процентов годовых.', bare='Сорок три.',
                       correction='Девять процентов годовых дают владельцу больший купон.', followup='Тогда акционер получает дивиденды вместо купона.',
                       repeat_why='Низкий риск снижает доходность такой бумаги.', repeat_new='Ключевая ставка составляет шестнадцать процентов годовых.',
                       remark='Постараюсь больше не мешать вашей беседе.', by_statement='Охрана обычно отвечает по номеру на будке.',
                       by_question='Дверь обычно закрывают на два оборота.', chatter='Завтра обещают кратковременный дождь и прохладу.',
                       other='Купон выплачивают дважды в год.'),
          first='Я держу облигации федерального займа в своём портфеле уже семь лет.', chit='Ладно, хорошо, договорились!',
          lower='Сколько стоит одна штука на бирже?', lower_a='примерно тысячу рублей при размещении.'),
    Scene('breakeven', holdout=True,
          q='Что такое точка безубыточности?',
          a='Порог равен 2 миллионам рублей выручки. Рост цены не всегда снижает этот порог. Метод применяют с 1903 года.',
          cut='Порог равен 2 миллионам рублей выручки. Рост цены не всегда',
          retell='Порог равен 2 миллионам рублей выручки, рост цены не всегда снижает порог.',
          para=('Порог просто равен 2 миллионам рублей выручки', 'Метод ведь применяют с 1903 года'),
          wrong=('Порог равен 2 миллионам рублей прибыли', 'Метод применяют с 1930 года'),
          words=('Порог равен двум миллионам рублей выручки', 'Метод применяют с тысяча девятьсот три года'),
          why='А почему не меньше?', new='Что значит маржинальный доход?', twice=True,
          clear='Что значит маржинальный доход?', bare='дисконтирование денежных потоков', correction='Не 2 миллиона, а 3',
          followup='Объясни на примере', remark='Суфлёр, ты отвечаешь слишком медленно', by_statement='Коля забрал документы из бухгалтерии ещё утром',
          by_question='Паш, ты позвонил сантехнику?', chatter='Вот бы сейчас в отпуск к морю', command='Ещё раз',
          replies=dict(clear='Маржинальный доход равен выручке минус переменные расходы.', bare='Дисконтирование приводит будущие платежи к текущей стоимости.',
                       correction='Три миллиона рублей требуют большего объёма продаж.', followup='Например, пекарня покрывает аренду после тысячи булок.',
                       repeat_why='Постоянные расходы задают нижнюю границу.', repeat_new='Маржинальный доход равен выручке минус переменные расходы.',
                       remark='Постараюсь отвечать заметно быстрее.', by_statement='Бухгалтерия работает до шести вечера.',
                       by_question='Сантехника обычно вызывают через диспетчера.', chatter='На море сейчас тепло и немного ветрено.',
                       other='Переменные расходы растут вместе с продажами.'),
          first='Я считаю порог каждый квартал для своей небольшой пекарни.', chit='Угу, понятно, договорились!',
          lower='Зачем считать запас прочности?', lower_a='чтобы вовремя сократить закупки.'),
)

Cell = namedtuple('Cell', 'family state cloud scene')


def delegation(uid, did='d1'):
    return {'type': 'delegation.created', 'item': {'id': did, 'target': 'client', 'user_bidi_turn_id': uid}}


@contextmanager
def memory_db():
    """The engine's own SQL on one in-memory connection per engine: a cell costs no disk."""
    import sqlite3
    original = EchoEngine._db

    @contextmanager
    def _db(self):
        db = self.__dict__.get('_memory_db')
        if db is None:
            db = self.__dict__['_memory_db'] = sqlite3.connect(':memory:')
        with db:
            yield db
    EchoEngine._db = _db
    try:
        yield
    finally:
        EchoEngine._db = original


class MatrixWire(Wire):
    """The wire, the lookup of the transport and the delegation path of the cloud; every action of the controller is kept (``seen``)."""
    mic_stream = False      # the cells set the provider's events alone; the cells over a live line are the matter of E870

    def __init__(self, *args, **kwargs):
        if os.environ.get('G3_CONFIRM') and not os.environ.get('G3_ENGINE_ROOT'):
            kwargs['confirm_seconds'] = float(os.environ['G3_CONFIRM'])         # the effect of the confirm window: 0 switches it off
        _controlled_media._LEDGERS.clear()      # U91: every cell is its own call; the same session, turn id and words in one temp dir would read as a reconnect (the ledger holds the last final)
        super().__init__(*args, **kwargs)
        self.seen, self.after_result = [], None
        self.generations = self.lookups_sent = 0
        made = self.c.engine.generate

        def counted(*args, **kwargs):
            self.generations += 1
            return made(*args, **kwargs)
        self.c.engine.generate = counted

    def _act(self, actions):
        self.seen.extend(actions or [])
        for action in actions or []:
            if action['type'] == 'lookup':
                self.at(self.now + 0.4, self._lookup_done(action))
            elif action['type'] == 'context':
                self.c.delivery_sent(action['epoch'], action.get('delegation_id'))
                if self.after_result:
                    reply, self.after_result = self.after_result, None
                    self.at(self.now + 0.5, reply)
        super()._act(actions)

    @staticmethod
    def _lookup_done(action):
        def go(wire):
            if not ControlledMedia.public_lookup_allowed(action.get('lookup_question') or action.get('question') or ''):
                return (wire.c.without_source(action['epoch'],'refused') or [])        # the transport never sends a personal question out
            wire.lookups_sent += 1
            rows = [{'url': 'https://example.org/a', 'title': action.get('question') or '',
                     'text': (action.get('question') or '') + ' подробная справка из открытого источника о предмете вопроса.'}]
            return wire.c.grounding(action['epoch'], rows)
        return go


def first_person(scene):
    return scene.first


def wording(scene, family, portion, index):
    """The finals of this utterance (several for a stuck listener who says the same words twice). ``index``: 0 the first portion, 1 the last."""
    words = str(portion or scene.para[index]).rstrip(' .,;:—–-!?…').split()
    head = ' '.join(words[:max(1, (len(words) + 1) // 2)])
    bare = ' '.join(words)
    return {'full': [bare], 'in_words': [scene.words[index]], 'paraphrase': [scene.para[index]], 'partial': [head],
            'stuck': [head, head] if scene.twice else [head + ' ' + head.split()[-1]], 'wrong': [scene.wrong[index]],
            'repeat_why': [bare + ', ' + scene.why[0].lower() + scene.why[1:]], 'repeat_new': [bare + '. ' + scene.new]}.get(family) or [getattr(scene, family)]


def reply_text(scene, family):
    return scene.lower_a if family == 'lower' else scene.replies.get(family) or scene.replies['other']


def _base_state(wire, scene, state):
    """Bring the call to ``state``; returns the moment the exchange may start."""
    wire.user('q0', scene.q, 0.0, 1.0)
    if state in ('streaming', 'cut'):
        cuts, total = [], 0
        for piece in pieces(scene.cut):
            total += len(piece)
            cuts.append(total)
        times = [1.05 + n * 0.08 for n in range(len(cuts))]
        wire.assistant('a0', ' ' + scene.cut, 1.05, times[-1], final=False, grow=[c + 1 for c in cuts], times=times)
        wire.until(4.0)
        return 4.2
    wire.assistant('a0', ' ' + scene.a, 1.05, 2.0)
    wire.until(4.0)
    t = 4.2
    if state in ('idle', 'last'):
        for _ in range(6):
            s = wire.state()
            remaining = len(s.get('chunks') or []) - s.get('chunk_index', 0)
            if s.get('completed') or (state == 'last' and remaining <= 1):
                break
            wire.confirm(t)
            t += 3.4
            wire.until(t)
    if state == 'paused':
        wire.user('s0', 'Стоп', t, t + 0.4)
        wire.until(t + 1.0)
        t += 1.2
    return t


Obs = namedtuple('Obs', 'cues classes adv failures lookups contexts gens probe waiting plan_after stale latency replay_after')


def _words(text):
    return norm_words(text)


def _inside(cue, text):
    cue, text = _words(cue), _words(text)
    return bool(cue) and any(text[i:i + len(cue)] == cue for i in range(len(text) - len(cue) + 1))


def _sync(wire):
    s = wire.state()
    return s, s.get('entry'), (s.get('history') or [{}])[s['entry']] if type(s.get('entry')) is int and s.get('history') else {}


def _cue_class(cue, cell, base_chunks, index, reply):
    scene = cell.scene
    portion = base_chunks[index] if index is not None and index < len(base_chunks) else None
    if references(cell) and not _inside(cue, scene.a):
        return 'answer'
    if _inside(cue, FILLER):
        return 'filler'
    if _inside(cue, reply):
        return 'answer'
    if portion is not None and _words(cue) == _words(portion):
        return 'replay'
    if portion is not None and _inside(cue, portion):
        return 'tail'
    if _inside(cue, scene.a) or _inside(cue, scene.cut):
        return 'plan'
    if _inside(cue, scene.first) or _inside(cue, scene.chit):
        return 'answer'
    return 'other'


def run_cell(cell, tmp):
    scene = cell.scene
    wire = MatrixWire(Path(tmp))
    begin = _base_state(wire, scene, cell.state)
    state, entry, record = _sync(wire)
    base_chunks = list(state.get('chunks') or record.get('chunks') or [])
    spoken = record.get('spoken', 0)
    waiting = None if state.get('completed') else state.get('chunk_index', 0)
    last = bool(cell.state in ('idle', 'last'))
    portion = base_chunks[-1] if cell.state == 'idle' else base_chunks[waiting] if waiting is not None and waiting < len(base_chunks) else None
    finals = wording(scene, cell.family, portion, 1 if last else 0)
    want = expected(cell, analyze(finals[-1], state, [], wire.c.settings).kind in (QUESTION, CORRECTION))
    played_from, seen_from = len(wire.played), len(wire.seen)
    wire.generations = wire.lookups_sent = 0
    t = begin
    if cell.state == 'cut':
        wire.at(t, done('a0', 'assistant', ' ' + scene.cut))
    uid = None
    for n, text in enumerate(finals):
        uid = f'u{n}'
        length = 0.3 + 0.12 * len(text.split())
        wire.user(uid, text, t + 0.05, t + 0.05 + length)
        t += 0.05 + length + 0.25
    final = t - 0.25
    reply = reply_text(scene, cell.family)
    start = final + 0.05
    if cell.cloud in ANSWERS or cell.cloud == 'goes_on':
        # what the model says once a result reached it: the sourced answer of a lookup, the answer after the end of its own delegation's wait
        def answer(w, text=scene.first if cell.cloud == 'first_person' else reply):
            w.assistant('r2', ' ' + text, w.now + 0.05, w.now + 0.8)
        wire.after_result = answer
    if cell.cloud in ('substantive', 'goes_on'):
        wire.assistant('r1', ' ' + reply, start, start + 0.8)
        if cell.cloud == 'goes_on':
            count = len(pieces(' ' + reply))
            ready = start + 0.8 * (count - 1) / max(1, count)           # the last word of the reply has arrived
            wire.user('more', GOES_ON, ready + GOES_ON_AFTER, ready + GOES_ON_AFTER + 1.0)
    elif cell.cloud == 'filler_answer':
        wire.assistant('r1', ' ' + FILLER + ' ' + reply, start, start + 1.2)
    elif cell.cloud == 'filler_only':
        wire.assistant('r1', ' ' + FILLER, start, start + 0.6)
    elif cell.cloud == 'ugu':
        wire.assistant('r1', ' Угу.', start, start + 0.3)
    elif cell.cloud == 'chitchat':
        wire.assistant('r1', ' ' + scene.chit, start, start + 0.5)
    elif cell.cloud == 'delegation':
        wire.at(final + 0.1, delegation(uid))
    elif cell.cloud == 'first_person':
        wire.assistant('r1', ' ' + scene.first, start, start + 0.8)
    elif cell.cloud == 'late':
        if cell.state in ('streaming', 'cut'):
            rest = scene.a[len(scene.cut):]
            if cell.state == 'streaming':
                for n, piece in enumerate(pieces(rest)):
                    wire.at(start + 0.05 * n, delta('a0', piece))
                wire.at(start + 0.05 * len(pieces(rest)), done('a0', 'assistant', ' ' + scene.a))
            else:
                wire.assistant('r1', rest, start, start + 0.8)
        else:
            wire.assistant('r1', ' ' + scene.retell, start, start + 0.8)
    end = final + 10.5
    wire.until(end)
    # lookup answers: a sourced answer of the model after the context (only when the question went that way)
    state_after = wire.state()
    actions = wire.seen[seen_from:]
    sent, made = wire.lookups_sent, wire.generations        # the probe's own steps are not the exchange's
    # rule 6: text of the old answer that nobody had published, cued while another question holds the call: late text of a retired question
    held = wire.state().get('question') != scene.q
    stale = held and any(_inside(text, scene.a[len(scene.cut):]) for _, text in wire.played[played_from:])
    answered_at = [at for at, text in wire.played[played_from:] if _cue_class(text, cell, base_chunks, waiting, reply) == 'answer']
    latency = answered_at[0] - final if answered_at else None
    replayed = [at for at, text in wire.played[played_from:] if _cue_class(text, cell, base_chunks, waiting, reply) == 'replay']
    replay_after = replayed[0] - final if replayed else None
    cues = [text for _, text in wire.played[played_from:]]
    after = (state_after.get('history') or [])
    old = after[entry] if type(entry) is int and entry < len(after) else {}
    advanced = old.get('spoken', spoken) - spoken
    chunks_now = list(old.get('chunks') or base_chunks)
    # the probe: the listener repeats the portion that should wait
    expected_row = want
    probe = None
    next_portion = spoken + expected_row.adv
    if cell.state != 'idle' and old and next_portion < len(chunks_now):
        wording_now = chunks_now[next_portion].rstrip(' .,;:—–-')
        ahead = wire.now + 0.4
        wire.user('probe', wording_now, ahead, ahead + 0.6)
        wire.until(ahead + 2.0)
        s2 = wire.state()
        hist = s2.get('history') or []
        again = hist[entry] if type(entry) is int and entry < len(hist) else {}
        probe = again.get('spoken', 0) == next_portion + 1 and s2.get('entry') == entry
    classes = [_cue_class(cue, cell, base_chunks, waiting, reply) for cue in cues]
    return Obs(cues, classes, advanced, sum(1 for a in actions if a['type'] == 'unanswered'), sent, sum(1 for a in actions if a['type'] == 'context'), made,
               probe, portion, wire.plan(), stale, latency, replay_after), expected_row


# ---- the table of the brief -----------------------------------------------------------------------------------------------------------------------
# adv: portions of the old plan confirmed by this utterance. answer: its reply is cued. cue: what else must be heard (None: nothing is asked for).
# failure: the spoken failure is a correct outcome here. gens: how many publications + lookups + contexts are right at most. undecidable: a tag when the
# available signals cannot tell this cell (the outcome that protects the position is then the expected one, and a whisper is allowed).
Expect = namedtuple('Expect', 'adv answer cue failure gens undecidable')


def references(cell):
    return cell.scene.name == 'double' and cell.family == 'bare'


def expected(cell, asks=False):
    """``asks``: the words look like a question to the classifier in this state (nothing but the words: who they were said to it cannot know)."""
    f, s, c = cell.family, cell.state, cell.cloud
    # a question form opens at once and its reply goes out; a turn with no form waits for the silence after its reply, and the talk goes on
    answers = c in ANSWERS or (c == 'goes_on' and (asks or f in BREATH))
    new_sentence = c in ('substantive', 'filler_answer', 'first_person', 'goes_on')     # right after a cut: the answer going on, or a reply to the turn?
    plan = s != 'idle'
    cut = s == 'cut'
    gen = 3                                                     # a question: its publication, its lookup, its context
    # DEF-FAULT-03: the listener is told, once, when nothing comes of a question (a stream that just goes on says nothing to the question either)
    promised = c in ('filler_only', 'nothing') or (c == 'late' and s == 'streaming')
    if f in ACKS:
        undecided = 'cut_then_new_sentence' if cut and new_sentence else None
        return Expect(1 if plan else 0, False, 'next' if s == 'more' else None, False, 0, undecided)
    if f in HOLDS:
        undecided = 'cut_then_new_sentence' if cut and new_sentence else None
        # other speech after the try: nothing is said over it (W1F-B C4, the silence timer does not run again for speech it cannot place)
        cue = None if s in ('idle', 'paused') or c == 'goes_on' else 'replay' if f == 'wrong' else 'tail'
        return Expect(0, False, cue, False, 0, undecided)
    if f in BREATH:
        return Expect(1 if plan else 0, answers, None, promised, gen, 'elliptic_after_cut' if f == 'repeat_why' and cut and c == 'late' else None)
    if f in ASKS:
        if references(cell):
            return Expect(0, True, None, False, gen, None)
        if f in NO_EVIDENCE_ROWS and s == 'paused' and not asks:
            return Expect(0, False, None, False, 0, None)       # pinned by test_g1_admit: a paused answer is not replaced by a candidate
        return Expect(0, answers, None, promised, gen if answers or not plan else 0, 'elliptic_after_cut' if f == 'followup' and cut and c == 'late' else None)
    if f == 'remark':
        return Expect(0, False, None, False, 0, None)
    if f in FOREIGN:
        if f in NO_EVIDENCE_ROWS and s == 'paused' and not asks:
            return Expect(0, False, None, False, 0, None)
        if answers:
            return Expect(0, False, None, False, gen, 'addressee')
        if promised:
            return Expect(0, False, None, True, gen, 'addressee_no_reply')
        return Expect(0, False, None, False, 0, None)
    # commands
    word = norm_words(cell.scene.command)
    if word in (['дальше'], ['продолжай']) and not plan:
        return Expect(0, c in ANSWERS or c == 'goes_on', None, c in ('filler_only', 'nothing'), gen, None)     # ruling 4d: nothing to go on with, the words are a question
    adv = 1 if word == ['дальше'] and s in ('more', 'last', 'streaming', 'cut') else 0
    return Expect(adv, False, None, False, 0, 'cut_then_new_sentence' if cut and new_sentence else None)


def score(cell, obs, want):
    """The defects of one run: ``{metric: count}``."""
    out = Counter()
    answered = 'answer' in obs.classes
    if want.answer and not answered:
        out['missed_q'] += 1
    if not want.answer and (answered or 'filler' in obs.classes or 'other' in obs.classes):
        out['false_int'] += 1
    if want.adv == 0 and obs.adv > 0:
        out['false_ack'] += 1
    if want.adv >= 1 and obs.adv > want.adv:
        out['double_adv'] += 1
    if obs.adv < want.adv:
        out['missed_ack'] += 1
    if obs.probe is False:
        out['lost_pos'] += 1
    if obs.stale or (answered and any(k in ('replay', 'tail', 'plan') for k in obs.classes[obs.classes.index('answer') + 1:])):
        out['stale_cue'] += 1
    if want.cue == 'tail' and ('tail' not in obs.classes or 'replay' in obs.classes):
        out['wrong_cue'] += 1
    if want.cue == 'replay' and 'replay' not in obs.classes:
        out['wrong_cue'] += 1
    if want.cue == 'next' and 'plan' not in obs.classes:
        out['wrong_cue'] += 1
    if obs.failures and not want.failure:
        out['spoken_fail'] += 1
    made = obs.gens + obs.lookups + obs.contexts            # what the cloud or the public lookup was really asked
    if made > want.gens:
        out['extra_gen'] += 1
        if obs.gens <= want.gens:
            out['lookup_first'] += 1                        # only the public lookup and its context ran, nothing was published: see ``blocking``
    return out


def blocking(defects, want):
    """What still counts against a cell after the named undecidable outcome is allowed."""
    allowed = {'addressee': {'false_int', 'extra_gen'}, 'addressee_no_reply': {'spoken_fail', 'extra_gen'},
               'cut_then_new_sentence': {'false_int', 'wrong_cue', 'extra_gen'}, 'elliptic_after_cut': {'stale_cue', 'extra_gen'}}.get(want.undecidable, set())
    if 'lookup_first' in defects:
        # Not undecidable, a choice the report names: S6 pins the lookup of a question at its final, so a question-looking line runs it before the cloud can
        # say that the line was not for it (a cloud that said so is not asked with the sources). Nothing is spoken, the position stays.
        # ``test_the_named_lookups_do_not_grow`` bounds it.
        allowed = allowed | {'extra_gen', 'lookup_first'}
    return {key: value for key, value in defects.items() if key not in allowed}


def cells(which='dev', families=FAMILIES):
    for scene in SCENES:
        if (which == 'dev' and scene.holdout) or (which == 'holdout' and not scene.holdout):
            continue
        for family in families:
            for state in STATES:
                for cloud in CLOUDS:
                    yield Cell(family, state, cloud, scene)


def run(which='dev', families=FAMILIES, selected=None):
    """``[(cell, obs, expect, defects)]``."""
    out = []
    with memory_db(), quiet_log(), tempfile.TemporaryDirectory() as tmp:
        for cell in selected or cells(which, families):
            obs, want = run_cell(cell, tmp)
            out.append((cell, obs, want, score(cell, obs, want)))
    return out


@contextmanager
def quiet_log():
    """No log of thousands of cells; the logger is left as it was found (other test modules read it)."""
    logger = logging.getLogger('echo-sync')
    level = logger.level
    logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        logger.setLevel(level)


def table(results):
    """The metrics per family, as text."""
    head = f'{"family":14}{"cells":>6}' + ''.join(f'{m:>12}' for m in METRICS) + f'{"unnamed":>9}'
    rows = [head]
    total, cells_n, unnamed_n = Counter(), 0, 0
    for family in FAMILIES:
        mine = [r for r in results if r[0].family == family]
        if not mine:
            continue
        sums, unnamed = Counter(), 0
        for _, _, want, defects in mine:
            sums.update(defects)
            unnamed += bool(blocking(defects, want))
        total.update(sums)
        cells_n += len(mine)
        unnamed_n += unnamed
        rows.append(f'{family:14}{len(mine):>6}' + ''.join(f'{sums[m]:>12}' for m in METRICS) + f'{unnamed:>9}')
    rows.append(f'{"TOTAL":14}{cells_n:>6}' + ''.join(f'{total[m]:>12}' for m in METRICS) + f'{unnamed_n:>9}')
    named = Counter(want.undecidable for _, _, want, defects in results if want.undecidable and defects)
    named['lookup_first'] = sum(1 for _, _, _, defects in results if 'lookup_first' in defects)
    rows.append('named: ' + ', '.join(f'{key} {value}' for key, value in sorted(named.items())))
    rows.append('goes_on column, false interventions: ' + str(sum(1 for c, _, _, d in results if c.cloud == 'goes_on' and 'false_int' in d)) + ' of '
                + str(sum(1 for c, _, _, _ in results if c.cloud == 'goes_on')) + ', by family '
                + str({f: sum(1 for c, _, _, d in results if c.cloud == 'goes_on' and 'false_int' in d and c.family == f) for f in FOREIGN}))
    bare = [o.latency for c, o, _, _ in results if c.family == 'bare' and c.cloud == 'substantive' and o.latency is not None and not references(c)]
    if bare:
        rows.append(f'bare questions, substantive: final -> first cue, n={len(bare)}, median {statistics.median(bare):.2f} s, max {max(bare):.2f} s')
    wrong = [o.replay_after for c, o, _, _ in results if c.family == 'wrong' and o.replay_after is not None]
    if wrong:
        rows.append(f'wrong repeat: final -> replay, n={len(wrong)}, median {statistics.median(wrong):.2f} s')
    return '\n'.join(rows)


def as_json(results):
    return {'/'.join((c.family, c.state, c.cloud, c.scene.name)): blocking(d, w) for c, _, w, d in results if blocking(d, w)}


if __name__ == '__main__':
    args = sys.argv[1:]
    which = args[0] if args and args[0] in ('dev', 'holdout', 'all') else 'dev'
    picked = None
    if '--cells' in args:
        by_name = {s.name: s for s in SCENES}
        picked = []
        for name in args[args.index('--cells') + 1:]:
            if name.startswith('--'):
                break
            family, state, cloud, scene = name.split('/')
            picked.append(Cell(family, state, cloud, by_name[scene]))
    results = run(which, selected=picked)
    if '--json' in args:
        Path(args[args.index('--json') + 1]).write_text(json.dumps(as_json(results), ensure_ascii=False, indent=0), encoding='utf-8')
    if picked:
        for cell, obs, want, defects in results:
            print('/'.join((cell.family, cell.state, cell.cloud, cell.scene.name)), dict(defects), want)
            print('   ', obs)
    else:
        print(table(results))

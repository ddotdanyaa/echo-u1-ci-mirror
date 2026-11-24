"""Helpers of tests/test_t_classes.py (WAVE 2 / Task T-A: the V2 failure classes F01-F70 and causal chains C01-C24).

Test code only. Nothing here re-implements the product:

REAL (the same code as production)
  ControlledMedia built with the keywords read from ``controlled_host.py`` by ``ast`` (``helpers_s6_state.host_kwargs``),
  EchoEngine and its SQLite file, FramelessTurns, portioner, first_useful, ru_alignment, NativeMediaSocket.
FAKE, only at the external boundary
  the GPT-Live helper pipe (``FakeSource``: what the product sends upstream), SAPI synthesis (silent PCM of the length a
  scenario asks for), the public lookup (rows chosen by the scenario), the websocket send (a recorder) and time (one injected
  clock) - all of it the ``World`` of the S6 state axis, reused as it is.

What is NEW here
  * ``Subject``: invented-but-plausible unfamiliar subjects (no scenario is tied to one phrase or one subject; the generators
    combine subject x situation x perturbation, and a split of whole subjects is held out);
  * ``Ledger``: every executed scenario is registered with its factor tuple, so the count is of DISTINCT tuples, never of
    retries (see ``Ledger``);
  * ``Rig``: a user/cloud/phone driver over the production wire with observations that are read from the wire (frames, the
    stored cursor), not from the matchers it judges;
  * the oracles: they work on the text a scenario was BUILT from (the perturbation it applied), never by calling the
    production matcher. ``test_t_classes.py::test_the_oracles_do_not_import_the_code_they_judge`` pins that by ``ast``.
"""
from __future__ import annotations

import atexit
import contextlib
import json
import os
import re
import shutil
import unicodedata
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import helpers_s6_state as s6
from helpers_s6_state import FRAME, PLAYOUT_FRAMES, SOURCE_ROWS, World, host_kwargs, turn_created, turn_delta, turn_done

__all__ = ['LEDGER', 'ScenarioFailure', 'NotApplicable', 'scenario', 'sweep', 'pick', 'require', 'HOLDOUT', 'SPLITS', 'Subject', 'DEV',
           'HELD_OUT', 'Rig', 'TWorld', 'nt', 'words', 'host_kwargs', 'replace_token', 'number_slips', 'add_negation',
           'drop_negation', 'drop_word', 'ROLE_SWAPS', 'contains_sequence', 'inject_db_fault', 'corrupt_saved_state', 'holdout_requested',
           'ECHO_EARLIEST', 'ECHO_MIDDLE', 'ECHO_LATEST', 'cue_pcm', 'captured_log']


# =====================================================================================================================
# 1. Failures, the ledger of executed scenarios, the holdout marker
# =====================================================================================================================

class NotApplicable(Exception):
    """The scenario cannot be built from this subject (its portion plan has no such atom): not counted, not a failure."""


class ScenarioFailure(AssertionError):
    """The production code did not do what the requirement says. The message names the observed and the required.

    An ``AssertionError`` (also the ones of the S6 invariants) is a finding about the product; any other exception is a
    bug of the test and is never covered by an ``xfail``.
    """


def require(condition, scenario_name, observed, required):
    if not condition:
        raise ScenarioFailure(f'[{scenario_name}] observed: {observed} | required: {required}')


class Ledger:
    """Distinct executed scenarios. A scenario is a class id plus the tuple of the factors that make it what it is
    (subject, situation, perturbation, position ...). Executing the same tuple twice (a retry, a repeated parametrisation)
    adds to ``runs`` and never to the count. ``outcome`` is PASS, DEFECT (an ``AssertionError``: a finding about the product)
    or ERROR (any other exception: a bug of the test, counted as executed but reported apart)."""

    def __init__(self):
        self.rows = {}

    def open(self, cls, factors, split):
        key = (cls, tuple(str(x) for x in factors))
        row = self.rows.setdefault(key, {'cls': cls, 'factors': list(key[1]), 'split': split, 'runs': 0, 'outcome': None})
        row['runs'] += 1
        return row

    def distinct(self, cls=None, split=None, outcome=None):
        return sum(1 for row in self.rows.values()
                   if (cls is None or row['cls'] == cls) and (split is None or row['split'] == split)
                   and (outcome is None or row['outcome'] == outcome))

    def by_class(self):
        counts = {}
        for row in self.rows.values():
            entry = counts.setdefault(row['cls'], {'dev': 0, 'holdout': 0, 'PASS': 0, 'DEFECT': 0, 'ERROR': 0})
            entry[row['split']] += 1
            entry[row['outcome'] or 'ERROR'] += 1
        return counts

    def dump(self, path):
        data = {'distinct': len(self.rows), 'by_class': self.by_class(),
                'rows': [{**row, 'factors': row['factors']} for row in self.rows.values()]}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')


LEDGER = Ledger()


@contextlib.contextmanager
def scenario(cls, *factors, split='dev'):
    """Register one scenario and record how it ended."""
    row = LEDGER.open(cls, factors, split)
    try:
        yield row
    except NotApplicable:
        row['runs'] -= 1
        if row['runs'] == 0:
            LEDGER.rows.pop((cls, tuple(str(x) for x in factors)), None)
        raise
    except AssertionError:
        row['outcome'] = 'DEFECT'
        raise
    except BaseException:
        row['outcome'] = 'ERROR'
        raise
    else:
        row['outcome'] = row['outcome'] if row['outcome'] == 'DEFECT' else 'PASS'


def _dump_ledger():                                           # pragma: no cover - at interpreter exit
    target = os.environ.get('T_CLASSES_LEDGER')
    if target and LEDGER.rows:
        with contextlib.suppress(OSError):
            LEDGER.dump(target)


atexit.register(_dump_ledger)


def _quiet_mark(name):
    """``pytest.mark.<name>`` without the unknown-marker warning: the marker is declared by this module alone (the repository
    has no conftest.py or pytest.ini, and a second author must not collide with this one on a shared config file)."""
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return getattr(pytest.mark, name)


HOLDOUT = _quiet_mark('holdout')
SPLITS = [pytest.param('dev', id='dev'), pytest.param('holdout', id='holdout', marks=HOLDOUT)]


def holdout_requested(config):
    """True when ``-m`` selects the holdout (``-m holdout``, ``-m "holdout or ..."``); never for ``-m "not holdout"``."""
    expression = config.getoption('markexpr', default='') or ''
    return bool(re.search(r'(?<!not )(?<!not\s)\bholdout\b', expression))


# =====================================================================================================================
# 2. Text oracles (independent: standard library only)
# =====================================================================================================================

_PUNCT = re.compile(r'[^\w\s%]|_', re.UNICODE)


def nt(text):
    """Normal form used by the oracles: lower case, ё = е, no punctuation (the % sign is kept), single spaces."""
    text = unicodedata.normalize('NFC', str(text)).casefold().replace('ё', 'е').replace('—', ' ').replace('–', ' ')
    return ' '.join(_PUNCT.sub(' ', text).split())


def words(text):
    return nt(text).split()


def contains_sequence(haystack, needle):
    """Is ``needle`` (a list of words) a contiguous part of ``haystack`` (a list of words)?"""
    n = len(needle)
    return n > 0 and any(haystack[i:i + n] == needle for i in range(len(haystack) - n + 1))


# =====================================================================================================================
# 3. Subjects
# =====================================================================================================================

@dataclass(frozen=True)
class Subject:
    """An unfamiliar subject. Every field is hand-written (case forms included) so the generators never inflect by rule."""
    key: str
    domain: str
    nom: str
    gen: str
    acc: str
    prep: str
    ins: str
    definition: str          # «<Nom> — это ...»
    cause: str               # a sentence with «потому что»
    example: str
    numeric: str             # a sentence with NUMBER and UNIT
    number: str
    unit: str                # the unit exactly as it is written in ``numeric``
    unit_alt: str            # a unit a listener might say instead (a different measure)
    exception: str           # a sentence with «не»
    number_words: str = ''   # how a listener says NUMBER in ``numeric`` (the case the sentence needs)

    def answer(self, style='plain'):
        """The cloud's answer text of this subject. Styles differ in what they carry, not in wording."""
        if style == 'definition':
            return self.definition
        if style == 'number':                         # the sentence with the number first: its portions are the first ones
            return self.numeric
        if style == 'negation':
            return self.exception
        if style == 'numeric':
            return f'{self.definition} {self.numeric}'
        if style == 'exception':
            return f'{self.definition} {self.exception}'
        if style == 'compound':                       # definition, cause, example: the three obligations of F03/C01
            return f'{self.definition} {self.cause} {self.example}'
        if style == 'full':
            return f'{self.definition} {self.cause} {self.numeric} {self.exception}'
        return f'{self.definition} {self.numeric} {self.exception}'

    def question(self, form='what'):
        return QUESTION_FORMS[form].format(nom=self.nom, gen=self.gen, acc=self.acc, prep=self.prep, ins=self.ins,
                                           Nom=self.nom[:1].upper() + self.nom[1:])


QUESTION_FORMS = {
    'what': 'Что такое {nom}?',
    'explain': 'Объясни, пожалуйста, что такое {nom}.',
    'why': 'Почему важен {nom}?',
    'tell': 'Расскажи про {acc}.',
    'which': 'Какое значение имеет {nom}?',
}


def _s(key, domain, forms, definition, cause, example, numeric, number, unit, unit_alt, exception, number_words=''):
    nom, gen, acc, prep, ins = forms
    return Subject(key, domain, nom, gen, acc, prep, ins, definition, cause, example, numeric, number, unit, unit_alt,
                   exception, number_words)


DEV = (
    _s('hydraulic', 'гидравлика',
       ('гидравлический удар', 'гидравлического удара', 'гидравлический удар', 'гидравлическом ударе', 'гидравлическим ударом'),
       'Гидравлический удар — это резкий скачок давления в трубе.',
       'Он возникает, потому что поток жидкости внезапно останавливается.',
       'Например, так бывает при быстром закрытии задвижки.',
       'Давление при этом может вырасти на 15 процентов.', '15', 'процентов', 'процентных пунктов',
       'В гибких шлангах этот эффект не возникает.', 'пятнадцать'),
    _s('sequence', 'теория музыки',
       ('секвенция', 'секвенции', 'секвенцию', 'секвенции', 'секвенцией'),
       'Секвенция — это повтор музыкальной фразы на другой высоте.',
       'Её используют, потому что слушателю легче запомнить знакомый оборот.',
       'Например, мелодия каждый раз поднимается на одну ступень.',
       'Обычно фраза сдвигается на 3 тона.', '3', 'тона', 'полутона',
       'В строгой фуге секвенция не нарушает тональность.', 'три'),
    _s('podzol', 'почвоведение',
       ('подзолистая почва', 'подзолистой почвы', 'подзолистую почву', 'подзолистой почве', 'подзолистой почвой'),
       'Подзолистая почва — это бедная перегноем почва таёжной зоны.',
       'Она образуется, потому что осадки вымывают питательные вещества вниз.',
       'Например, такие почвы часто встречаются под хвойным лесом.',
       'Слой перегноя там редко превышает 12 сантиметров.', '12', 'сантиметров', 'миллиметров',
       'Для картофеля такая почва без удобрений не подходит.', 'двенадцать'),
    _s('annuity', 'финансы',
       ('аннуитетный платёж', 'аннуитетного платежа', 'аннуитетный платёж', 'аннуитетном платеже', 'аннуитетным платежом'),
       'Аннуитетный платёж — это равный ежемесячный взнос по кредиту.',
       'Он удобен, потому что сумма заранее известна заёмщику.',
       'Например, кредит гасится одинаковыми частями каждый месяц.',
       'Банк может взять комиссию 5 тысяч рублей.', '5', 'тысяч рублей', 'рублей',
       'Досрочное погашение этот платёж не отменяет.', 'пять'),
    _s('perigee', 'орбитальная механика',
       ('перигей', 'перигея', 'перигей', 'перигее', 'перигеем'),
       'Перигей — это ближайшая к Земле точка орбиты спутника.',
       'Там скорость выше, потому что притяжение сильнее.',
       'Например, у многих спутников связи он лежит над экватором.',
       'У некоторых спутников перигей лежит на высоте 400 километров.', '400', 'километров', 'метров',
       'У круговой орбиты перигей не выделяется.', 'четыреста'),
    _s('heliotropism', 'ботаника',
       ('гелиотропизм', 'гелиотропизма', 'гелиотропизм', 'гелиотропизме', 'гелиотропизмом'),
       'Гелиотропизм — это поворот растения вслед за Солнцем.',
       'Он нужен, потому что листьям требуется больше света.',
       'Например, подсолнух днём поворачивает соцветие к западу.',
       'За сутки растение сдвигается примерно на 90 градусов.', '90', 'градусов', 'минут',
       'Ночью такой поворот не происходит.', 'девяносто'),
    _s('quench', 'металловедение',
       ('закалка стали', 'закалки стали', 'закалку стали', 'закалке стали', 'закалкой стали'),
       'Закалка стали — это быстрое охлаждение раскалённого металла.',
       'Металл становится твёрже, потому что меняется его структура.',
       'Например, ножи часто опускают в масло.',
       'Перед этим металл нагревают до 800 градусов Цельсия.', '800', 'градусов Цельсия', 'градусов Кельвина',
       'После закалки сталь не становится пластичнее.', 'восемьсот'),
    _s('agglutination', 'лингвистика',
       ('агглютинация', 'агглютинации', 'агглютинацию', 'агглютинации', 'агглютинацией'),
       'Агглютинация — это присоединение к корню цепочки суффиксов.',
       'Так образуются слова, потому что каждый суффикс несёт своё значение.',
       'Например, в турецком языке слово бывает очень длинным.',
       'Одно слово иногда содержит 9 суффиксов.', '9', 'суффиксов', 'корней',
       'В русском языке такая цепочка не бывает длинной.', 'девять'),
    _s('twinning', 'кристаллография',
       ('двойникование', 'двойникования', 'двойникование', 'двойниковании', 'двойникованием'),
       'Двойникование — это срастание двух кристаллов по общей плоскости.',
       'Оно возникает, потому что решётка сдвигается при росте.',
       'Например, так образуется ласточкин хвост у гипса.',
       'Угол между половинками составляет 60 градусов.', '60', 'градусов', 'минут',
       'У аморфных веществ двойникование не встречается.', 'шестьдесят'),
    _s('hypoxia', 'медицина',
       ('гипоксия', 'гипоксии', 'гипоксию', 'гипоксии', 'гипоксией'),
       'Гипоксия — это нехватка кислорода в тканях организма.',
       'Она развивается, потому что в крови мало кислорода.',
       'Например, на большой высоте дышать труднее.',
       'Опасным считают насыщение крови ниже 90 процентов.', '90', 'процентов', 'промилле',
       'При лёгкой степени симптомы могут не проявляться.', 'девяносто'),
    _s('hansa', 'история',
       ('Ганзейский союз', 'Ганзейского союза', 'Ганзейский союз', 'Ганзейском союзе', 'Ганзейским союзом'),
       'Ганзейский союз — это объединение торговых городов северной Европы.',
       'Города объединились, потому что купцам нужна была защита на море.',
       'Например, в союз входили Любек и Гамбург.',
       'Союз просуществовал около 300 лет.', '300', 'лет', 'месяцев',
       'Единого государства он не создал.', 'триста'),
    _s('maillard', 'кулинарная химия',
       ('реакция Майяра', 'реакции Майяра', 'реакцию Майяра', 'реакции Майяра', 'реакцией Майяра'),
       'Реакция Майяра — это взаимодействие сахаров и аминокислот при нагреве.',
       'Корочка темнеет, потому что образуются новые ароматные вещества.',
       'Например, так румянится жареное мясо.',
       'Хлебу для румяной корочки нужно 25 минут.', '25', 'минут', 'секунд',
       'При варке в воде реакция не идёт.', 'двадцать пять'),
    _s('coupling', 'электроника',
       ('ёмкостная связь', 'ёмкостной связи', 'ёмкостную связь', 'ёмкостной связи', 'ёмкостной связью'),
       'Ёмкостная связь — это передача сигнала через конденсатор.',
       'Постоянный ток блокируется, потому что конденсатор его не пропускает.',
       'Например, так соединяют каскады усилителя.',
       'Типичная ёмкость такого конденсатора равна 100 нанофарад.', '100', 'нанофарад', 'микрофарад',
       'Постоянное напряжение через неё не проходит.', 'сто'),
    _s('tuff', 'геология',
       ('вулканический туф', 'вулканического туфа', 'вулканический туф', 'вулканическом туфе', 'вулканическим туфом'),
       'Вулканический туф — это пористая порода из спрессованного пепла.',
       'Он лёгкий, потому что внутри много пустот.',
       'Например, из него строили древние храмы.',
       'Плотность этой породы около 2 тонн на кубометр.', '2', 'тонн на кубометр', 'килограммов на кубометр',
       'В воде такой камень не тонет сразу.', 'двух'),
)

# Whole subjects kept out of every development test: their own domains, their own terms, their own numbers and units.
HELD_OUT = (
    _s('moraine', 'гляциология',
       ('ледниковая морена', 'ледниковой морены', 'ледниковую морену', 'ледниковой морене', 'ледниковой мореной'),
       'Ледниковая морена — это груда камней и глины, оставленная ледником.',
       'Она остаётся на месте, потому что лёд тает и отступает.',
       'Например, холмы морены видны на равнинах севера.',
       'Некоторые валы морены поднимаются на 35 метров.', '35', 'метров', 'километров',
       'Внутри морены слоёв почти не бывает.', 'тридцать пять'),
    _s('metronome', 'акустика',
       ('метроном', 'метронома', 'метроном', 'метрономе', 'метрономом'),
       'Метроном — это прибор, который отсчитывает ровный ритм.',
       'Музыканты берут его, потому что так проще держать темп.',
       'Например, ученик играет гамму под его щелчки.',
       'Обычный темп ограничен 208 ударами в минуту.', '208', 'ударами в минуту', 'ударами в секунду',
       'Электронный метроном маятник не использует.', 'двести восемь'),
    _s('ceramic', 'гончарное дело',
       ('обжиг керамики', 'обжига керамики', 'обжиг керамики', 'обжиге керамики', 'обжигом керамики'),
       'Обжиг керамики — это нагрев глиняных изделий в печи.',
       'Глина твердеет, потому что из неё уходит связанная вода.',
       'Например, кувшин после обжига звенит при ударе.',
       'Печь для этого разогревают до 950 градусов Цельсия.', '950', 'градусов Цельсия', 'градусов Фаренгейта',
       'Сырую глину сразу обжигать не нужно.', 'девятьсот пятьдесят'),
    _s('xray', 'физика кристаллов',
       ('рентгеновская дифракция', 'рентгеновской дифракции', 'рентгеновскую дифракцию', 'рентгеновской дифракции',
        'рентгеновской дифракцией'),
       'Рентгеновская дифракция — это рассеяние лучей на атомной решётке.',
       'Картина получается, потому что лучи складываются в определённых направлениях.',
       'Например, так определяют структуру белков.',
       'Расстояние между слоями порядка 5 ангстрем.', '5', 'ангстрем', 'нанометров',
       'Аморфное стекло чётких пятен не даёт.', 'пять'),
    _s('critpath', 'управление проектами',
       ('критический путь', 'критического пути', 'критический путь', 'критическом пути', 'критическим путём'),
       'Критический путь — это самая длинная цепочка зависимых задач проекта.',
       'Она важна, потому что любая её задержка сдвигает срок проекта.',
       'Например, строительство нельзя закончить раньше фундамента.',
       'Запас времени на такой цепочке равен 0 дней.', '0', 'дней', 'часов',
       'Задачи вне критического пути срок не меняют.', 'ноль'),
    _s('eclipse', 'астрономия',
       ('лунное затмение', 'лунного затмения', 'лунное затмение', 'лунном затмении', 'лунным затмением'),
       'Лунное затмение — это прохождение Луны через тень Земли.',
       'Оно случается, потому что Земля оказывается между Луной и Солнцем.',
       'Например, диск Луны при этом становится красноватым.',
       'Полная фаза порой длится 100 минут.', '100', 'минут', 'секунд',
       'При новолунии оно не наступает.', 'сто'),
)


def split_subjects(split):
    return DEV if split == 'dev' else HELD_OUT


def pick(split, count, offset=0):
    """``count`` subjects of the split, rotating from ``offset`` (so that every subject is used by some variant)."""
    pool = split_subjects(split)
    return [pool[(offset + i) % len(pool)] for i in range(min(count, len(pool)))]


def sweep(cls, kind, split, body, *, count=2, offset=0, subjects=None):
    """Run ``body(subject)`` as one registered scenario per subject, all of them even when some fail, and raise ONE
    ``ScenarioFailure`` that names how many failed and the first reason. ``NotApplicable`` skips a subject."""
    failures, ran = [], 0
    for subject in (subjects or pick(split, count, offset)):
        try:
            with scenario(cls, kind, subject.key, split=split):
                body(subject)
            ran += 1
        except NotApplicable:
            continue
        except AssertionError as error:
            ran += 1
            failures.append(f'{subject.key}: {error}')
    if not ran:
        pytest.skip(f'{cls}/{kind}: no subject can build this scenario')
    if failures:
        raise ScenarioFailure(f'{cls}/{kind}: {len(failures)} of {ran} scenarios failed; first: {failures[0]}')


# =====================================================================================================================
# 3b. Perturbations: what a listener (or an ASR) can do to a portion that is being repeated
# =====================================================================================================================

def replace_token(text, old, new):
    """``text`` with the first whole-token occurrence of ``old`` replaced by ``new`` (None when ``old`` is not a token of it)."""
    match = re.search(r'(?<![\w,])' + re.escape(old) + r'(?![\w])', text)
    if not match:
        return None
    return text[:match.start()] + new + text[match.end():]


def number_slips(number):
    """Ways a number goes wrong when it is repeated: {kind: wrong number}. Each differs in value from ``number``."""
    if not number.isdigit():
        return {}
    value = int(number)
    slips = {'plus_seven': str(value + 7), 'times_ten': str(value * 10) if value else '10'}
    if len(number) > 1 and len(set(number)) > 1:
        slips['digits_swapped'] = number[1] + number[0] + number[2:]
    if len(number) > 2 and number.endswith('0'):
        slips['zero_dropped'] = number[:-1]
    return slips


def drop_word(text, index):
    parts = text.split()
    return ' '.join(parts[:index] + parts[index + 1:])


def drop_negation(text):
    """``text`` without its «не» (None when it has none)."""
    parts = text.split()
    for i, part in enumerate(parts):
        if nt(part) == 'не':
            return ' '.join(parts[:i] + parts[i + 1:])
    return None


def add_negation(text):
    """«не» in front of the second word (or the first of a one-word portion): changes the meaning of the portion."""
    parts = text.split()
    if any(nt(part) == 'не' for part in parts):
        return None
    i = 1 if len(parts) > 1 else 0
    return ' '.join(parts[:i] + ['не'] + parts[i:])


# Pairs whose roles are marked by unambiguous case endings, so that the second member says the OPPOSITE of the first.
ROLE_SWAPS = (
    ('Инфляция снижает ставку.', 'Ставка снижает инфляцию.'),
    ('Банк кредитует заёмщика.', 'Заёмщик кредитует банк.'),
    ('Врач лечит пациента.', 'Пациент лечит врача.'),
    ('Учитель проверяет ученика.', 'Ученик проверяет учителя.'),
    ('Нагрев ускоряет реакцию.', 'Реакция ускоряет нагрев.'),
    ('Свет нагревает воду.', 'Вода нагревает свет.'),
    ('Ветер двигает лодку.', 'Лодка двигает ветер.'),
    ('Налог повышает цену.', 'Цена повышает налог.'),
    ('Вирус заражает клетку.', 'Клетка заражает вирус.'),
    ('Бактерия разлагает глюкозу.', 'Глюкоза разлагает бактерию.'),
    ('Продавец обманул покупателя.', 'Покупатель обманул продавца.'),
    ('Иванов уплатил Петрову.', 'Петров уплатил Иванову.'),
)


# =====================================================================================================================
# 4. The world: the S6 World with a lookup the scenario controls
# =====================================================================================================================

class _PooledConnection:
    """A sqlite3 connection that ``close()`` does not close: the engine opens (and closes) one per read, ~120 times a turn; reusing the
    open connection of the same file keeps every statement, transaction and rollback of the engine exactly as they are and only saves
    the cost of opening the file again. The scenario's world closes the real connection."""

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __enter__(self):
        return self._real.__enter__()

    def __exit__(self, *exc):
        return self._real.__exit__(*exc)

    def close(self):
        return None


class TWorld(World):
    """``World`` of the S6 state axis (production controller + wire, fakes at the boundary) with a lookup whose rows and
    failures a scenario chooses, and whose synthesis can be told how long a cue is."""

    def __init__(self, *args, rows=None, controller_settings=None, controller_kwargs=None, **kwargs):
        self.controller_settings = controller_settings
        self.controller_kwargs = controller_kwargs            # keywords of ControlledMedia on top of the ones the host passes (the profile stays as it is)
        self.call_gates = {}
        self.rows_for = rows or (lambda question: list(SOURCE_ROWS))
        self.lookup_mode = 'ok'            # ok | raise | empty
        self.lookup_gate = None
        self.lookup_hold = False
        self.synth_frames = PLAYOUT_FRAMES
        self.synth_pcm = None              # a function text -> PCM bytes, when a scenario wants real-looking audio
        self._pool = {}
        self._install_pool()
        super().__init__(*args, **kwargs)

    async def _lookup(self, question):
        self.lookup_calls.append(question)
        gate = self.call_gates.get(('lookup', len(self.lookup_calls) - 1))
        if gate is not None:
            await gate.wait()
        if self.lookup_hold and self.lookup_gate is not None:
            await self.lookup_gate.wait()
        if self.lookup_mode == 'raise':
            raise RuntimeError('injected lookup failure')
        if self.lookup_mode == 'empty':
            return []
        return list(self.rows_for(question))

    async def _synthesize(self, text, end=None):
        self.synth_calls.append(text)
        gate = self.call_gates.get(('synth', len(self.synth_calls) - 1))
        if gate is not None:
            await gate.wait()
        if self.hold:
            await self.gate.wait()
        if self.synth_pcm is not None:
            return self.synth_pcm(text)
        return FRAME * self.synth_frames

    def _install_pool(self):
        import sqlite3
        import types
        from echo_sync import engine as engine_module
        real_connect = sqlite3.connect
        pool = self._pool

        def connect(path, *args, **kwargs):
            key = str(path)
            if key not in pool:
                pool[key] = real_connect(path, *args, **kwargs)
            return _PooledConnection(pool[key])
        proxy = types.SimpleNamespace(**{name: getattr(sqlite3, name) for name in dir(sqlite3) if not name.startswith('__')})
        proxy.connect = connect
        self._engine_module, self._engine_sqlite = engine_module, engine_module.sqlite3
        engine_module.sqlite3 = proxy

    def close(self):
        try:
            super().close()
        finally:
            if getattr(self, '_engine_module', None) is not None:
                self._engine_module.sqlite3 = self._engine_sqlite
                self._engine_module = None
            for connection in self._pool.values():
                with contextlib.suppress(Exception):
                    connection.close()
            self._pool.clear()
            if self._own_root:
                shutil.rmtree(self.root, ignore_errors=True)

    def hold_call(self, kind, index):
        """Hold the ``index``-th call of ``kind`` ('lookup' or 'synth') until ``release_call``: one late descendant, the rest run."""
        async def make():
            import asyncio
            return asyncio.Event()
        self.call_gates[(kind, index)] = self.run(make())

    def release_call(self, kind, index):
        self.version += 1
        self.call_gates[(kind, index)].set()
        self.settle()

    def connect_peer(self):
        """As ``World.connect_peer`` (a new controller over the same SQLite file, a new wire) with an optional explicit profile."""
        from echo_sync.controlled_media import ControlledMedia
        from echo_sync.native_media_socket import NativeMediaSocket
        self.connections += 1
        self.open = None
        self.source = s6.FakeSource()
        kwargs = host_kwargs()
        if self.controller_settings:
            kwargs['settings'] = dict(self.controller_settings)
        kwargs.update(self.controller_kwargs or {})
        self.controller = ControlledMedia(self.db, session_id=self.session_id, clock=self.clock.now, **kwargs)
        self.wire = NativeMediaSocket(self.controller, self._emit, self._connect, self._lookup, self._synthesize, clock=self.clock.now)
        self.run(self._handshake())
        self.note(f'-- call #{self.connections} ready (quiet_reopen={self.controller.quiet_reopen})')

    def hold_lookup(self):
        async def make():
            import asyncio
            return asyncio.Event()
        self.lookup_gate = self.run(make())
        self.lookup_hold = True

    def release_lookup(self):
        self.version += 1
        self.lookup_hold = False
        if self.lookup_gate is not None:
            self.lookup_gate.set()
        self.settle()


# =====================================================================================================================
# 5. The rig: a user, a cloud and a phone on the production wire
# =====================================================================================================================

@dataclass
class Obs:
    """What one step did, read from the wire."""
    cues: list = field(default_factory=list)          # portions that began (not diagnostics)
    diagnostics: list = field(default_factory=list)
    frames: list = field(default_factory=list)
    before: dict = field(default_factory=dict)
    after: dict = field(default_factory=dict)
    model_frames: int = 0                             # frames written to the helper pipe during the step
    lookups: int = 0
    tid: object = None

    @property
    def spoken(self):
        return [cue.text for cue in self.cues]

    @property
    def moved(self):
        return (self.before.get('revision'), self.before.get('index')) != (self.after.get('revision'), self.after.get('index'))

    @property
    def advanced(self):
        """The cursor went exactly one portion forward inside one revision."""
        return (self.before.get('revision') is not None and self.before['revision'] == self.after.get('revision')
                and self.after.get('index') == (self.before.get('index') or 0) + 1)


class Rig:
    """Drives one ``TWorld``. Every step returns an ``Obs``; ``check`` applies the invariants that hold in every scenario:
    one response in flight, no stale audio, no error frame (unless the scenario expects one), the stored state is sane and
    the portion index never goes back inside a revision."""

    HUMAN = 0.5            # seconds a listener needs after a cue is over before they start repeating it

    def __init__(self, world=None, **world_kwargs):
        self.w = world or TWorld(**world_kwargs)
        self.n_user = 0
        self.n_assistant = 0
        self.errors_seen = 0
        self.last = self.snap()
        self.expect_errors = False

    # -- life cycle ------------------------------------------------------------------------------------------------
    def close(self):
        self.w.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- observation -------------------------------------------------------------------------------------------------
    def snap(self):
        """The stored cursor and the controller's flags, read afresh (``World.snapshot`` caches by event count, and a cue that is
        being sent on the loop between two events can fill that cache with a state that is one event old)."""
        return self.w._snapshot()

    def state(self):
        return self.w.state() or {}

    def portion(self):
        """The text of the portion that waits for its confirmation, or None."""
        state = self.state()
        chunks, index = state.get('chunks') or [], state.get('chunk_index', 0)
        if not state or state.get('completed') or state.get('pending_turn') or state.get('stream_waiting_next'):
            return None
        return chunks[index] if 0 <= index < len(chunks) else None

    def all_chunks(self):
        return list(self.state().get('chunks') or [])

    def cue_texts(self, since=0, diagnostics=False):
        return [c.text for c in self.w.cues[since:] if c.diagnostic == diagnostics]

    def mark(self):
        return len(self.w.cues), self.w.seq, len(self.w.source.frames), len(self.w.lookup_calls)

    def _obs(self, mark, before):
        cues_mark, seq_mark, model_mark, lookup_mark = mark
        fresh = self.w.cues[cues_mark:]
        return Obs(cues=[c for c in fresh if not c.diagnostic], diagnostics=[c for c in fresh if c.diagnostic],
                   frames=[f for s, _, f in self.w.frames if s > seq_mark], before=before, after=self.snap(),
                   model_frames=len(self.w.source.frames) - model_mark, lookups=len(self.w.lookup_calls) - lookup_mark)

    def upstream_events(self):
        """The JSON frames the product has written to the cloud helper (context appends)."""
        events = []
        for kind, payload in self.w.source.frames:
            if kind == 'E':
                with contextlib.suppress(ValueError):
                    events.append(json.loads(payload.decode('utf-8')))
        return events

    def upstream_joined(self):
        """The context the product sent upstream, chunks glued back together exactly as the cloud receives them."""
        return ''.join(part.get('text', '') for event in self.upstream_events() for part in event.get('content', []))

    def upstream_text(self):
        return '\n'.join(part.get('text', '') for event in self.upstream_events() for part in event.get('content', []))

    # -- invariants of every scenario ---------------------------------------------------------------------------------
    def check(self, name='wire'):
        w = self.w
        if w.violations:
            raise ScenarioFailure(f'[{name}] wire invariant: {w.violations[0]}')
        if w.loop_errors:
            raise ScenarioFailure(f'[{name}] unhandled exception in a wire task: {w.loop_errors[-1]}')
        while self.errors_seen < len(w.errors):
            frame = w.errors[self.errors_seen]
            self.errors_seen += 1
            if not self.expect_errors:
                raise ScenarioFailure(f'[{name}] error frame in a fault-free scenario: {frame}')
        now = self.snap()
        if now['revision'] is not None:
            n = len(now['chunks'])
            if not 0 <= now['index'] <= n:
                raise ScenarioFailure(f"[{name}] stored index {now['index']} outside 0..{n}")
            if self.last['revision'] == now['revision'] and self.last['index'] is not None and now['index'] < self.last['index']:
                raise ScenarioFailure(f"[{name}] the portion index went back {self.last['index']} -> {now['index']}")
            if self.last['revision'] is not None and now['revision'] < self.last['revision']:
                raise ScenarioFailure(f"[{name}] the revision went back {self.last['revision']} -> {now['revision']}")
        self.last = now

    # -- the user ---------------------------------------------------------------------------------------------------
    def _uid(self):
        self.n_user += 1
        return f'u{self.n_user}'

    def _aid(self):
        self.n_assistant += 1
        return f'a{self.n_assistant}'

    def feed(self, event, name='feed', settle=True):
        before = self.snap()
        mark = self.mark()
        self.w.feed(event, settle=settle)
        self.check(name)
        return self._obs(mark, before)

    def pump(self, frames):
        """Let the sender run until ``frames`` frames of the portion in the ear reached the phone."""
        self.w.pump_until(frames)

    def pump_frames(self, frames, limit=600):
        """As ``pump`` for any number of frames (``pump`` gives up after 60 loop turns, fewer than a cue of a real portion needs). Returns the
        cue in the ear once ``frames`` of its frames were sent, or None when no cue ever got that far."""
        import asyncio

        async def one_turn():
            await asyncio.sleep(0)
        for _ in range(limit):
            cue = self.w.open
            if cue is not None and cue.audio_frames >= frames:
                return cue
            self.w.run(one_turn())
        return None

    def long_cues(self, voice=None):
        """From now on every cue the synthesizer returns lasts ``voice`` seconds (CUE_VOICE_SECONDS) and then the SAPI tail of silence: as long
        as a real portion, so that there is a window in which it can be heard back."""
        seconds = CUE_VOICE_SECONDS if voice is None else voice
        self.w.synth_pcm = lambda text: cue_pcm(seconds)

    def settle(self):
        self.w.settle()
        self.check('settle')

    def user_partials(self, tid, partials, *, name='user'):
        """The growing transcript of an unfinished user turn, the way the provider sends it: ``turn.created`` with the first
        words, then ``turn.delta`` with what was added. Each partial must extend the one before."""
        previous = None
        for n, partial in enumerate(partials):
            if previous is None:
                self.w.feed(turn_created(tid, 'user', partial))
            else:
                require(partial.startswith(previous), name, f'partial {partial!r} does not extend {previous!r}',
                        'transcripts that grow by deltas')
                self.w.feed(turn_delta(tid, partial[len(previous):], n))
            previous = partial
            self.check(name + ':partial')

    def user(self, text, tid=None, *, partials=(), name='user', settle=True):
        """A user turn: the optional ``partials`` and then the final ``turn.done`` (whose text replaces the partials: that is
        where an ASR correction happens). Returns the ``Obs`` of the whole turn, with ``.tid``."""
        tid = tid or self._uid()
        before = self.snap()
        mark = self.mark()
        if partials:
            self.user_partials(tid, partials, name=name)
        self.w.feed(turn_done(tid, 'user', text), settle=settle)
        self.check(name)
        obs = self._obs(mark, before)
        obs.tid = tid
        return obs

    def ask(self, text, tid=None, **kwargs):
        return self.user(text, tid, name='ask', **kwargs)

    def cloud(self, text, tid=None, *, mode='whole', group=2, name='cloud', settle=True):
        """The cloud's answer. ``whole``: one turn.done; ``stream``: created + word-group deltas + done;
        ``open``: created + deltas, never done (a producer that goes quiet)."""
        tid = tid or self._aid()
        before = self.snap()
        mark = self.mark()
        if mode == 'whole':
            self.w.feed(turn_done(tid, 'assistant', text), settle=settle)
        else:
            groups = s6.word_groups(text, group)
            self.w.feed(turn_created(tid, 'assistant', groups[0]))
            self.check(name + ':created')
            for n, piece in enumerate(groups[1:], 1):
                self.w.feed(turn_delta(tid, piece, n))
                self.check(name + ':delta')
            if mode == 'stream':
                self.w.feed(turn_done(tid, 'assistant', text), settle=settle)
        self.check(name)
        obs = self._obs(mark, before)
        obs.tid = tid
        return obs

    def advance(self, seconds, step=0.5):
        before = self.snap()
        mark = self.mark()
        self.w.advance(seconds, step=step)
        self.check('silence')
        return self._obs(mark, before)

    def human_pause(self):
        """The listener lets the cue finish and takes a breath."""
        self.w.settle()
        return self.advance(self.HUMAN)

    def confirm(self, text=None, tid=None, *, name='confirm'):
        """The listener repeats the waiting portion (or ``text``) after the cue is over."""
        portion = text if text is not None else self.portion()
        require(portion is not None, name, 'no portion is waiting', 'a portion that can be confirmed')
        self.human_pause()
        return self.user(portion, tid, name=name)

    def reconnect(self):
        before = self.snap()
        mark = self.mark()
        self.w.reconnect()
        self.check('reconnect')
        return self._obs(mark, before)

    def barge_in(self, how='provider_speech_started'):
        before = self.snap()
        mark = self.mark()
        if how == 'client_cancel':
            self.w.client({'type': 'response.cancel'})
        elif how == 'client_clear':
            self.w.client({'type': 'input_audio_buffer.clear'})
        else:
            self.w.feed({'type': 'input_audio_buffer.speech_started'})
        self.check('barge_in')
        return self._obs(mark, before)

    # -- compound helpers -------------------------------------------------------------------------------------------
    def dictation(self, subject, style='plain', *, form='what', mode='whole', group=2, confirm=0):
        """Ask ``subject`` and let the cloud answer; optionally confirm the first ``confirm`` portions. Returns the
        question's tid."""
        obs = self.ask(subject.question(form))
        require(self.w.controller.question_id == obs.tid, 'dictation', f'the question {subject.question(form)!r} was not accepted',
                'a plain question is accepted')
        self.cloud(subject.answer(style), mode=mode, group=group)
        for _ in range(confirm):
            self.confirm()
        return obs.tid

    def confirm_until(self, predicate, limit=40):
        """Confirm portions one by one until the waiting portion satisfies ``predicate``; returns that portion."""
        for _ in range(limit):
            portion = self.portion()
            if portion is None:
                return None
            if predicate(portion):
                return portion
            self.confirm()
        return None


# =====================================================================================================================
# 6. Fault injection at the storage boundary
# =====================================================================================================================

class _FaultConnection:
    """A sqlite3 connection whose ``execute`` raises when the scenario says so (a power cut, a full disk, a locked file)."""

    def __init__(self, connection, when):
        self._connection = connection
        self._when = when
        self.statements = 0

    def execute(self, sql, *args):
        self.statements += 1
        error = self._when(' '.join(str(sql).split()), self.statements)
        if error is not None:
            raise error
        return self._connection.execute(sql, *args)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def inject_db_fault(monkeypatch, when):
    """Make ``EchoEngine._db`` hand out connections that fail where ``when(sql, n)`` returns an exception. The real transaction
    handling (``with db``: commit or roll back) is the engine's own."""
    from echo_sync.engine import EchoEngine
    real = EchoEngine._db

    @contextlib.contextmanager
    def faulty(self):
        with real(self) as db:
            yield _FaultConnection(db, when)
    monkeypatch.setattr(EchoEngine, '_db', faulty)


def corrupt_saved_state(world, how):
    """Damage the stored session row of ``world`` the way a crash, a foreign writer or a disk fault could."""
    import json
    import sqlite3
    connection = sqlite3.connect(str(world.db))
    try:
        raw = connection.execute('SELECT state FROM sessions WHERE session_id=?', (world.session_id,)).fetchone()[0]
        state = json.loads(raw)
        damaged = {
            'truncated_json': raw[:len(raw) // 2], 'empty': '', 'binary': '\x00\x01\x02', 'not_object': '[1, 2, 3]',
            'no_revision': json.dumps({k: v for k, v in state.items() if k != 'revision'}),
            'no_chunks': json.dumps({k: v for k, v in state.items() if k != 'chunks'}),
            'index_past_end': json.dumps({**state, 'chunk_index': 99}), 'index_negative': json.dumps({**state, 'chunk_index': -3}),
            'index_text': json.dumps({**state, 'chunk_index': 'x'}), 'revision_text': json.dumps({**state, 'revision': 'abc'}),
            'history_null': json.dumps({**state, 'history': None}),
        }[how]
        connection.execute('UPDATE sessions SET state=? WHERE session_id=?', (damaged, world.session_id))
        connection.commit()
    finally:
        connection.close()


# =====================================================================================================================
# 7. Audio built from the production synthesis path (F22)
# =====================================================================================================================

def voiced_wav(path, *, lead_ms=0, voice_ms=250, tail_ms=780, amplitude=6000):
    """A 24 kHz mono 16-bit WAV: ``lead_ms`` of silence, ``voice_ms`` of a tone, ``tail_ms`` of silence (what SAPI writes)."""
    import math
    import struct
    import wave
    rate = 24000
    samples = [0] * (rate * lead_ms // 1000)
    samples += [int(amplitude * math.sin(2 * math.pi * 220 * i / rate)) for i in range(rate * voice_ms // 1000)]
    samples += [0] * (rate * tail_ms // 1000)
    with wave.open(str(path), 'wb') as target:
        target.setframerate(rate)
        target.setnchannels(1)
        target.setsampwidth(2)
        target.writeframes(struct.pack('<%dh' % len(samples), *samples))


class WavWorker:
    """The SAPI worker as ``render_cue_pcm`` sees it: ``synthesize(text, path)`` writes a WAV; the scenario picks its lead silence."""

    def __init__(self, **shape):
        self.shape = shape

    def synthesize(self, text, path, end=None):
        voiced_wav(path, **self.shape)
        return str(path)


def rendered_cue(directory, **shape):
    """The PCM the host would send for a cue whose synthesis has the given ``shape``: the PRODUCTION ``render_cue_pcm``."""
    from echo_sync.controlled_host import render_cue_pcm
    Path(directory).mkdir(parents=True, exist_ok=True)
    return render_cue_pcm(WavWorker(**shape), 'проба', directory)


def audible_onset_ms(frames, threshold=500):
    """Milliseconds from the first PCM frame of the first response to the first sample louder than ``threshold`` (None if never)."""
    import base64
    import struct
    index = 0
    for _, _, frame in frames:
        if frame.get('type') != 'response.audio.delta':
            continue
        pcm = base64.b64decode(frame['delta'])
        samples = struct.unpack('<%dh' % (len(pcm) // 2), pcm)
        for n, value in enumerate(samples):
            if abs(value) > threshold:
                return (index * 480 + n) / 24.0
        index += 1
    return None


def voiced_frame_count(frames, threshold=500):
    """How many 20 ms frames on the wire carry a sample louder than ``threshold``."""
    import base64
    import struct
    count = 0
    for _, _, frame in frames:
        if frame.get('type') != 'response.audio.delta':
            continue
        pcm = base64.b64decode(frame['delta'])
        if any(abs(v) > threshold for v in struct.unpack('<%dh' % (len(pcm) // 2), pcm)):
            count += 1
    return count


# =====================================================================================================================
# 8. The system's own voice heard back (F16, C07): cues as long as real portions, an echo that arrives when a real echo does
# =====================================================================================================================

# There is no drop of an echo (ledger ruling of 2 Nov): the iPhone cancels our playback with its voice processing and a
# fast listener begins to repeat INSIDE the cue, so a drop rejected genuine repeats; the overlap is decided and logged (``own_voice_suspect``)
# and the repeat is accepted. The physics is written down here, not imported from the controller's own constants.
CUE_VOICE_SECONDS = 2.0                  # the voice of a 4-word portion
CUE_TAIL_SECONDS = 0.78                  # the silence SAPI leaves after the voice (the PCM is longer than the voice)
FRAME_SECONDS = 0.02                     # the sender paces 20 ms frames
# A cue heard back is announced by the provider no sooner than about a second after the cue's first audio: the microphone has to pick it up, the
# provider's VAD and ASR have to transcribe it (candidate review of 2 Nov: 0.9-2.3 s from the start of its probe audio, never under 1.26 s).
# The echo is announced after this many frames of the cue were sent - 1.02 s, 1.38 s and 1.74 s after its first audio - all inside the window
# in which the cue can be heard back (voice 2.0 s + the controller's margin).
ECHO_EARLIEST, ECHO_MIDDLE, ECHO_LATEST = 52, 70, 88


def cue_pcm(voice=CUE_VOICE_SECONDS, tail=CUE_TAIL_SECONDS, amplitude=3000):
    """24 kHz 16-bit mono PCM of one cue as the SAPI path delivers it: ``voice`` seconds of sound, then ``tail`` seconds of silence, in whole
    20 ms frames so that the sender paces it exactly."""
    from array import array
    loud = int(voice * 24000) // 480 * 480
    quiet = int(tail * 24000) // 480 * 480
    return array('h', [amplitude] * loud + [0] * quiet).tobytes()


@contextlib.contextmanager
def captured_log(name='echo-sync'):
    """The decision lines the controller logs (``echo-sync decision kind=... reason=...``) while the block runs, as a list of strings.
    Needs no pytest fixture, so that a scenario can be called directly (the negative controls do)."""
    import logging
    lines = []

    class Collect(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    logger = logging.getLogger(name)
    handler, level = Collect(level=logging.INFO), logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield lines
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)

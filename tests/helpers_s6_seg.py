"""Helpers of tests/test_s6_segmentation.py (S6 / axis "seg"): harness, corpus, alignment oracles, quality statistics.

Nothing here re-implements the engine. The harness drives the REAL ``ControlledMedia`` (built exactly like
``controlled_host.serve`` builds it) with provider wire events, and calls the real ``portions`` /
``stable_prefix`` / ``first_cue``. The only fakes are the provider events themselves.

Run as a script (``python -m tests.helpers_s6_seg`` from the repository root) it prints the quality section of
the report: portion-length histogram, share of boundaries at punctuation, the worst portions with reasons.
"""
from __future__ import annotations

import functools
import random
import re
import tempfile
from collections import Counter
from pathlib import Path

from echo_sync.controlled_media import ControlledMedia
from echo_sync.portioner import portions, syllables
from echo_sync.settings import resolve
from echo_sync.textutil import WORDS, norm_words, normalize

# Same keywords as the ControlledMedia(...) call in echo_sync/controlled_host.py (guarded by an AST test).
HOST_KWARGS = dict(source_delivery='delegation', session_context_fallback=True, lookup_policy='required',
                   first_useful_gate=True, coalesce_seconds=3.2, quiet_reopen=True)
# controlled_host passes no ``settings``: ControlledMedia then uses its own default profile.
CONTROLLED_SETTINGS = {'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2,
                       'ack_match': 'ru_aligned', 'on_mismatch': 'silent'}

# Every profile the product can run with. ``range_2_8`` is the owner's wording ("portions of 2-8 words")
# written in the engine's own settings.
PROFILES = {
    'controlled': CONTROLLED_SETTINGS,                      # what the iPhone call really uses
    'adaptive': {'preset': 'adaptive'},
    'slow': {'preset': 'slow'},
    'semantic_short': {'preset': 'semantic_short'},
    'pronunciation_short': {'preset': 'pronunciation_short'},
    'range_2_8': {'portion_mode': 'syllables', 'min_words': 2, 'max_words': 8, 'target_syllables': 12,
                  'max_syllables': 20},
    'words3': {},                                           # the engine default: three words
    'words2': {'words_per_portion': 2},
    'words4': {'words_per_portion': 4},
}
SYLLABLE_PROFILES = tuple(name for name, s in PROFILES.items() if resolve(s)['portion_mode'] == 'syllables')
WORD_PROFILES = tuple(name for name in PROFILES if name not in SYLLABLE_PROFILES)


# F3 round 1: three questions about percentages were reworded (the segmentation is what these items test): «Сколько процентов …» / «Какой процент …» now
# need verification (generator.needs_verification: amounts and rates are looked up), and this harness has no sources to give.

# --- whitespace-free coordinates -----------------------------------------------------------------------

def nospace(text):
    """The characters of ``text`` without any whitespace: portions only ever add or drop whitespace."""
    return ''.join(str(text).split())


def squeeze(text):
    return ' '.join(str(text).split())


def boundaries(portion_list):
    """Cut positions between portions, counted in non-whitespace characters from the start of the text."""
    cuts, total = [], 0
    for portion in portion_list[:-1]:
        total += len(nospace(portion))
        cuts.append(total)
    return cuts


@functools.lru_cache(maxsize=None)
def atom_spans(answer, atom):
    """Every whole-word occurrence of ``atom`` in ``answer`` as a (start, end) span in non-space characters."""
    flat = squeeze(answer)
    wanted = squeeze(atom)
    spans = []
    for match in re.finditer(r'(?<!\w)' + re.escape(wanted) + r'(?!\w)', flat):
        before = len(nospace(flat[:match.start()]))
        spans.append((before, before + len(nospace(wanted))))
    return tuple(spans)


def cut_atoms(answer, atoms, portion_list, *, shift=0):
    """Atoms (text) that a portion boundary falls into. ``shift``: non-space characters elided in front."""
    cuts = [c + shift for c in boundaries(portion_list)]
    hit = []
    for atom in atoms:
        for start, end in atom_spans(answer, atom):
            if start >= shift and any(start < c < end for c in cuts):
                hit.append(atom)
                break
    return hit


@functools.lru_cache(maxsize=None)
def _word_spans(answer):
    """``(start, end, word)`` of every word of ``answer`` in non-space characters."""
    flat = squeeze(answer)
    spans, count, last = [], 0, 0
    for match in WORDS.finditer(flat):
        count += len(nospace(flat[last:match.start()]))
        start = count
        count += len(nospace(match.group()))
        spans.append((start, count, match.group()))
        last = match.end()
    return tuple(spans)


def cut_words(answer, portion_list, *, shift=0):
    """Words of ``answer`` that a portion boundary falls INTO (a word is never to be cut)."""
    cuts = [c + shift for c in boundaries(portion_list)]
    return [word for start, end, word in _word_spans(answer)
            if start >= shift and any(start < c < end for c in cuts)]


def product_words(text):
    """Words as ``max_words`` / ``min_words`` count them: the engine's own ``WORDS`` (6,5 is two words)."""
    return len(WORDS.findall(str(text)))


def lossless_problem(expected, portion_list):
    """``None`` when the portions are the text in order, else a one-line description of the first difference."""
    want, got = nospace(expected), nospace(''.join(portion_list))
    if want == got:
        return None
    n = next((i for i, (a, b) in enumerate(zip(want, got)) if a != b), min(len(want), len(got)))
    return (f'differs at char {n}: expected …{want[max(0, n - 12):n + 12]!r} got …{got[max(0, n - 12):n + 12]!r} '
            f'(expected {len(want)} chars, got {len(got)})')


# --- the question is not the answer -----------------------------------------------------------------------

_NOISE = frozenset('это является представляет собой такое так вот что как для при без который которая которое которые '
                   'все весь вся всех или его её они оно она был была были было будет есть быть из за на по от до '
                   'под над про между через после перед около более менее очень также тоже уже еще ещё'.split())


try:                                   # a stemmer is only a tool of the oracle; without it the first five letters do
    from snowballstemmer import stemmer as _snowball
    _STEMMER = _snowball('russian')
except Exception:                       # pragma: no cover
    _STEMMER = None


def _crude(word):
    return _STEMMER.stemWord(word) if _STEMMER else word[:5]


def echoes_question(portion, question):
    """True when the portion only repeats the question: every content word has a question word with the
    same stem (an inflection). Numbers, ``да``/``нет``, negations, ALL-CAPS abbreviations (УК РФ, IV) and
    Latin words (pH) are content."""
    asked = {_crude(w) for w in norm_words(question)}
    content = []
    for match in WORDS.finditer(str(portion)):
        raw, word = match.group(), normalize(match.group())
        if word and word not in _NOISE and (len(word) > 2 or word.isdigit() or word in ('не', 'ни', 'да')
                                            or (len(raw) >= 2 and raw.isupper()) or re.search('[a-z]', word)):
            content.append(word)
    return bool(content) and all(_crude(w) in asked for w in content)


# --- the host-like controller and a streamed answer -----------------------------------------------------

def host_controller(directory, *, settings=None, name='controlled-state.sqlite3'):
    return ControlledMedia(Path(directory) / name, session_id='native-probe-' + '0' * 32,
                           settings=settings, **HOST_KWARGS)


def created(tid, role, text):
    return {'type': 'turn.created', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def delta(tid, text, n):
    return {'type': 'turn.delta', 'turn_id': tid, 'delta': text, 'start_ms': n * 40, 'end_ms': n * 40 + 39}


def done(tid, role, text):
    return {'type': 'turn.done', 'turn': {'id': tid, 'role': role, 'transcript': text}}


def slices(text, how, rng=None):
    """Deltas the provider could have sent: the wire only promises that they concatenate to the text."""
    if how == 'words':
        return re.findall(r'\s*\S+', text) or [text]
    if how == 'chars5':
        return [text[i:i + 5] for i in range(0, len(text), 5)]
    if how == 'chars1':
        return list(text)
    pieces, i = [], 0
    while i < len(text):
        size = rng.randint(1, 9)
        pieces.append(text[i:i + size])
        i += size
    return pieces


class Stream:
    """One question and one assistant turn fed to the host-like controller event by event."""

    def __init__(self, directory, question, answer, how='words', seed=0, settings=None, ask=True):
        self.controller = c = host_controller(directory, settings=settings)
        self.question, self.answer, self.how = question, answer, how
        self.cues = []        # (index of the assistant event that produced it, text)
        self.events = 0
        self.user_actions = []
        if ask:
            words = slices(question, 'words')
            c.provider(created('u1', 'user', words[0]))
            for n, piece in enumerate(words[1:], 1):
                c.provider(delta('u1', piece, n))
            self.user_actions = c.provider(done('u1', 'user', question))
        self.pieces = pieces = slices(answer, how, random.Random(seed))
        self._feed(created('a1', 'assistant', pieces[0]))
        for n, piece in enumerate(pieces[1:], 1):
            self._feed(delta('a1', piece, n))
        self._feed(done('a1', 'assistant', answer))

    def _feed(self, event):
        for action in self.controller.provider(event):
            if action['type'] == 'speak':
                self.cues.append((self.events, action['text']))
        self.events += 1

    @property
    def state(self):
        return self.controller.state() or {}

    @property
    def chunks(self):
        return list(self.state.get('chunks', []))

    def walk(self, limit=200):
        """The user repeats every cue aloud; collect what the phone speaks next until nothing follows."""
        if not self.cues:
            return []
        spoken = [self.cues[0][1]]
        for n in range(limit):
            actions = self.controller.provider(done(f'ack{n}', 'user', spoken[-1]))
            speak = [a['text'] for a in actions if a['type'] == 'speak']
            if not speak:
                break
            spoken.append(speak[0])
        return spoken


class Streamed:
    """Plain data of one finished ``Stream`` (the SQLite file is gone when this exists)."""
    __slots__ = ('question', 'answer', 'how', 'chunks', 'cues', 'walk', 'completed', 'streaming', 'index',
                 'user_actions', 'answer_state')

    def __repr__(self):
        return f'Streamed({self.how}, cues={self.cues}, chunks={self.chunks})'


def stream(question, answer, how='words', *, seed=0, settings=None, walk=True, ask=True):
    """Feed one question and one answer to a fresh host-like controller and keep the outcome as plain data."""
    with tempfile.TemporaryDirectory(prefix='s6seg-') as directory:
        run = Stream(directory, question, answer, how, seed=seed, settings=settings, ask=ask)
        out = Streamed()
        out.question, out.answer, out.how = question, answer, how
        out.chunks, out.cues = run.chunks, [text for _, text in run.cues]
        out.completed, out.streaming = run.state.get('completed'), run.state.get('streaming')
        out.index, out.user_actions = run.state.get('chunk_index'), run.user_actions
        out.answer_state = run.state.get('answer')
        out.walk = run.walk() if walk else None
        return out


# =====================================================================================================
# The corpus: realistic Russian answers of a voice prompter, with the pieces that must never be cut
# =====================================================================================================
#
# Every answer is written with markup ``[[kind:text]]`` around a piece that is declared to be INDIVISIBLE
# (a number, a number with its unit, a negation with its word, a name ...). Markup may nest. It is removed to
# give the answer; the declared pieces are the oracle, so the checks never ask the portioner what a unit is.
#
# kind        piece
# decimal     6,5          digit groups joined by a decimal comma/point
# grouped     384 400      thousands groups
# numdate     22.06.1941   a numeric date
# unit        15 %, 5 лет, 22 июня, 1941 года        number + a unit the portioner documents
# unit_ext    250 миллилитров, 220 В                  number + a unit it does not know
# spelled     двадцать пять процентов                  a number written in words + its unit
# time        12:30     range  1941–1945     ratio  1:100 000     fraction  3/4     expression  2 + 2 = 4
# degree      100 °C    slashunit  км/с, км/ч, г/см³    currency  1 500 ₽ (symbol after the number)
# century     XIX веке, 12 веке
# abbr        и т. д., т. е., УК РФ, и др.      abbr_era  н. э.      unit_abbr  70 тыс. человек
# initials    А. С. Пушкин, Иванов И. И.        name2 / name3   Исаак Ньютон / Лев Николаевич Толстой
# neg         не рыба, ни один

class Item:
    __slots__ = ('id', 'category', 'question', 'answer', 'atoms', 'elide', 'punctuated')

    def __init__(self, id, category, question, answer, atoms, elide='', punctuated=True):
        self.id, self.category, self.question, self.answer = id, category, question, answer
        self.atoms, self.elide, self.punctuated = tuple(atoms), elide, punctuated

    def __repr__(self):
        return f'Item({self.id}: {self.answer!r})'

    def atoms_of(self, *kinds):
        return [text for kind, text in self.atoms if kind in kinds]


def _flatten(marked):
    """Strip nested markup too: the plain text of ``[[unit:[[grouped:384 400]] километров]]``."""
    previous = None
    while previous != marked:
        previous = marked
        marked = re.sub(r'\[\[\w+:((?:(?!\[\[).)*?)\]\]', r'\1', marked)
    return marked


def _nested_atoms(marked):
    """Every ``(kind, plain piece)`` including pieces nested inside other pieces."""
    atoms = []
    for match in re.finditer(r'\[\[(\w+):', marked):
        depth, i = 1, match.end()
        while i < len(marked) and depth:
            if marked.startswith('[[', i):
                depth += 1
                i += 2
            elif marked.startswith(']]', i):
                depth -= 1
                i += 2
            else:
                i += 1
        atoms.append((match.group(1), squeeze(_flatten(marked[match.end():i - 2]))))
    return atoms


# (category, question, marked answer, head the system may drop) ---------------------------------------------
_HAND = [
    # --- definitions «X — это …» -------------------------------------------------------------------
    ('definition', 'Что такое инерция', 'Инерция — это свойство тела сохранять своё состояние движения или покоя, пока на него [[neg:не действует]] внешняя сила.', 'Инерция — это'),
    ('definition', 'Что такое фотосинтез', 'Фотосинтез — это процесс образования органических веществ из углекислого газа и воды на свету.', 'Фотосинтез — это'),
    ('definition', 'Что такое демократия', 'Демократия — это форма правления, при которой власть принадлежит народу.', 'Демократия — это'),
    ('definition', 'Что такое инфляция', 'Инфляция — это устойчивый рост общего уровня цен в экономике.', 'Инфляция — это'),
    ('definition', 'Что такое электроэнцефалография', 'Электроэнцефалография — это метод записи электрической активности головного мозга с помощью электродов.', 'Электроэнцефалография — это'),
    ('definition', 'Что такое диффузия', 'Диффузия — это самопроизвольное проникновение молекул одного вещества между молекулами другого.', 'Диффузия — это'),
    ('definition', 'Что такое алгоритм', 'Алгоритм — это конечная последовательность чётко определённых действий для решения задачи.', 'Алгоритм — это'),
    ('definition', 'Что такое гравитация', 'Гравитация — это сила взаимного притяжения всех тел, имеющих массу.', 'Гравитация — это'),
    ('definition', 'Что такое метафора', 'Метафора — это скрытое сравнение, когда одно явление называют словами, обозначающими другое.', 'Метафора — это'),
    ('definition', 'Что такое рентгеноструктурный анализ', 'Рентгеноструктурный анализ — это метод изучения строения кристаллов по дифракции рентгеновских лучей.', 'Рентгеноструктурный анализ — это'),
    ('definition', 'Что такое конституция', 'Конституция — это основной закон государства, который имеет высшую юридическую силу.', 'Конституция — это'),
    ('definition', 'Что такое вакуум', 'Вакуум — это пространство, в котором практически нет вещества.', 'Вакуум — это'),
    ('definition', 'Что такое энтропия', 'Энтропия — это мера беспорядка в системе, а в термодинамике — функция её состояния.', 'Энтропия — это'),
    ('definition', 'Что такое квант', 'Квант — это минимальная порция, на которую может изменяться физическая величина.', 'Квант — это'),
    ('definition', 'Что такое скорость', 'Скорость показывает, какой путь проходит тело за единицу времени.', ''),
    ('definition', 'Что такое кислота', 'Кислота — вещество, которое отдаёт протоны и окрашивает лакмус в красный цвет.', 'Кислота —'),
    ('definition', 'Что такое ток', 'Ток — упорядоченное движение заряженных частиц.', 'Ток —'),
    ('definition', 'Что такое налог', 'Налог — это обязательный платёж, который государство взимает с граждан и организаций.', 'Налог — это'),
    ('definition', 'Что такое орбита', 'Орбита — траектория, по которой небесное тело движется вокруг другого тела.', 'Орбита —'),
    ('definition', 'Что такое антоним', 'Антоним — слово с противоположным значением, например «горячий» и «холодный».', 'Антоним —'),

    # --- numbers with units ------------------------------------------------------------------------
    ('number_unit', 'Сколько километров от Земли до Луны', 'Расстояние от Земли до Луны составляет около [[unit:[[grouped:384 400]] километров]].', ''),
    ('number_unit', 'Какая высота Эвереста', 'Высота Эвереста — [[unit:[[grouped:8 848]] метров]] над уровнем моря.', ''),
    ('number_unit', 'Какова скорость света', 'Скорость света в вакууме составляет примерно [[slashunit:[[grouped:300 000]] км/с]].', ''),
    ('number_unit', 'Сколько весит литр воды', 'Литр воды при комнатной температуре весит примерно [[unit:1 кг]].', ''),
    ('number_unit', 'При какой температуре кипит вода', 'Вода кипит при [[degree:100 °C]] на уровне моря.', ''),
    ('number_unit', 'Какая нормальная температура тела', 'Нормальная температура тела человека — около [[degree:[[decimal:36,6]] °C]].', ''),
    ('number_unit', 'Сколько длится школьный урок', 'Школьный урок длится [[unit:45 минут]].', ''),
    ('number_unit', 'Какая площадь России', 'Площадь России составляет около [[unit:[[decimal:17,1]] млн]] квадратных километров.', ''),
    ('number_unit', 'Сколько человек играет в футбольной команде', 'В футбольной команде на поле одновременно играют [[unit:11 человек]].', ''),
    ('number_unit', 'Какова длина экватора', 'Длина экватора Земли составляет примерно [[unit:[[grouped:40 075]] километров]].', ''),
    ('number_unit', 'Сколько воды нужно человеку', 'Взрослому человеку нужно около [[unit:2 литров]] воды в сутки.', ''),
    ('number_unit', 'Сколько дней в високосном году', 'В високосном году [[unit:366 дней]].', ''),
    ('number_unit', 'Сколько секунд в часе', 'В одном часе [[unit:[[grouped:3 600]] секунд]].', ''),
    ('number_unit', 'Сколько весит африканский слон', 'Взрослый африканский слон весит от 4 до [[unit:6 тонн]].', ''),
    ('number_unit', 'Какая глубина Марианской впадины', 'Глубина Марианской впадины — почти [[unit:11 километров]].', ''),
    ('number_unit', 'Сколько людей живёт в Москве', 'В Москве живёт около [[unit:13 миллионов человек]].', ''),
    ('number_unit', 'Сколько длится беременность', 'Беременность у человека длится около [[unit:40 недель]].', ''),
    ('number_unit', 'Как быстро летит самолёт', 'Пассажирский самолёт летит со скоростью около [[slashunit:900 км/ч]].', ''),
    ('number_unit', 'Какой объём у стакана', 'Обычный гранёный стакан вмещает [[unit_ext:250 миллилитров]].', ''),
    ('number_unit', 'Какая длина у футбольного поля', 'Длина футбольного поля — от 90 до [[unit_ext:120 метров]].', ''),
    # W1F-A (b), brief task-w1fix-briefs.md: «head elision instead of the restatement fallback when the first new-content unit of the
    # same sentence is already ready» - the restated head before the number is elided (first_useful.elide_restated_head)
    ('number_unit', 'Какой размер у файла', 'Размер файла — около [[unit_ext:[[decimal:2,5]] гигабайта]].', 'Размер файла —'),
    ('number_unit', 'Какая мощность у чайника', 'Мощность чайника — [[unit:2 кВт]], а напряжение в сети — [[unit_ext:220 В]].', ''),

    # --- dates and years --------------------------------------------------------------------------
    ('date_year', 'Когда началась Великая Отечественная война', 'Великая Отечественная война началась [[unit:22 июня]] [[unit:1941 года]].', ''),
    ('date_year', 'Когда закончилась Вторая мировая война', 'Вторая мировая война закончилась [[unit:2 сентября]] [[unit:1945 года]].', ''),
    ('date_year', 'В каком году основали Санкт-Петербург', 'Санкт-Петербург основан в [[unit:1703 году]] Петром Первым.', ''),
    ('date_year', 'Когда отменили крепостное право в России', 'Крепостное право в России отменили [[unit:19 февраля]] [[unit:1861 года]].', ''),
    ('date_year', 'Когда человек впервые полетел в космос', '[[name2:Юрий Гагарин]] полетел в космос [[unit:12 апреля]] [[unit:1961 года]].', ''),
    ('date_year', 'В каком году распался Советский Союз', 'Советский Союз распался в декабре [[unit:1991 года]].', ''),
    ('date_year', 'Когда родился Пушкин', '[[name3:Александр Сергеевич Пушкин]] родился [[unit:6 июня]] [[unit:1799 года]] в Москве.', ''),
    ('date_year', 'Когда была Бородинская битва', 'Бородинское сражение произошло [[unit:7 сентября]] [[unit:1812 года]].', ''),
    ('date_year', 'Когда приняли Конституцию России', 'Действующую Конституцию России приняли на референдуме [[unit:12 декабря]] [[unit:1993 года]].', ''),
    ('date_year', 'Когда началась Первая мировая война', 'Первая мировая война началась в [[unit:1914 году]] и закончилась в [[unit:1918 году]].', ''),
    ('date_year', 'Когда крестили Русь', 'Русь крестили в [[unit:988 году]] при князе Владимире.', ''),
    ('date_year', 'Сколько длилась Столетняя война', 'Столетняя война длилась с 1337 по [[unit:1453 год]], то есть [[unit:116 лет]].', ''),
    ('date_year', 'Кто изобрёл телефон', 'Телефон изобрёл [[name2:Александр Белл]], и патент он получил в [[unit:1876 году]].', ''),
    ('date_year', 'В каком веке жил Ломоносов', '[[name3:Михаил Васильевич Ломоносов]] жил в восемнадцатом веке, с 1711 по [[unit:1765 год]].', ''),
    ('date_year', 'Когда произошла Куликовская битва', 'Куликовская битва произошла [[unit:8 сентября]] [[unit:1380 года]] на Дону.', ''),

    # --- percentages -------------------------------------------------------------------------------
    ('percent', 'Сколько кислорода в воздухе', 'Кислорода в воздухе около [[unit:21 %]], а азота — около [[unit:78 %]].', ''),
    ('percent', 'Сколько воды в теле человека', 'Вода составляет примерно [[unit:60%]] массы тела взрослого человека.', ''),
    ('percent', 'Какая доля суши на Земле', 'Суша занимает около [[unit:29 %]] поверхности Земли, остальное — океаны.', ''),
    ('percent', 'Насколько вырос ВВП', 'ВВП вырос на [[unit:[[decimal:3,5]] %]] по сравнению с прошлым годом.', ''),
    ('percent', 'Какая часть населения планеты живёт в городах', 'В городах живёт более [[unit:55 процентов]] населения планеты.', ''),
    ('percent', 'Какова вероятность выпадения орла', 'Вероятность выпадения орла равна [[unit:50 %]], то есть одной второй.', ''),
    ('percent', 'Сколько меди в бронзе', 'В бронзе обычно [[unit:88 %]] меди и [[unit:12 %]] олова.', ''),
    ('percent', 'Какая у измерения точность', 'Погрешность измерения [[neg:не превышает]] [[unit:[[decimal:0,5]] %]].', ''),
    ('percent', 'Сколько воды в арбузе', 'Арбуз на [[unit:92 процента]] состоит из воды.', ''),
    ('percent', 'Какая влажность считается комфортной', 'Комфортная влажность воздуха в помещении — от 40 до [[unit:60 %]].', ''),

    # --- negations «не / ни» -----------------------------------------------------------------------
    ('negation', 'Правда ли что кит рыба', 'Нет, кит [[neg:не рыба]], а млекопитающее, которое дышит лёгкими.', ''),
    ('negation', 'Что происходит со звуком в вакууме', 'В вакууме звук [[neg:не распространяется]], потому что там нет среды.', ''),
    ('negation', 'Можно ли делить на ноль', 'Нет, на ноль делить нельзя, потому что результат [[neg:не определён]].', ''),
    ('negation', 'Всегда ли вода кипит при ста градусах', '[[neg:Не всегда]]: температура кипения зависит от давления.', ''),
    ('negation', 'Что такое нейтральный раствор', 'Это раствор, который [[neg:не является]] ни кислым, ни щелочным.', ''),
    ('negation', 'Почему Луна не падает на Землю', 'Луна [[neg:не падает]], потому что движется вокруг Земли с большой скоростью.', ''),
    ('negation', 'Кто победил в споре', '[[neg:Ни одна]] из сторон [[neg:не добилась]] полной победы.', ''),
    ('negation', 'Правда ли что человек использует лишь десять процентов мозга', 'Нет, это миф: учёные [[neg:не нашли]] неиспользуемых областей мозга.', ''),
    ('negation', 'Бывают ли чёрные лебеди', 'Да, чёрные лебеди существуют, это [[neg:не выдумка]].', ''),
    ('negation', 'Проводит ли дерево ток', 'Сухое дерево почти [[neg:не проводит]] электрический ток.', ''),
    ('negation', 'Почему рыбы не тонут', 'Рыбы [[neg:не тонут]], потому что у них есть плавательный пузырь.', ''),
    ('negation', 'Нужно ли ждать ответа', 'Ждать [[neg:не нужно]], ответ готов сразу.', ''),
    ('negation', 'Что будет, если не пить воду', 'Без воды человек [[neg:не проживёт]] больше нескольких суток.', ''),
    ('negation', 'Верно ли что Земля плоская', 'Нет, Земля [[neg:не плоская]], а имеет форму геоида.', ''),
    ('negation', 'Можно ли обогнать свет', 'Нет, ничто с массой [[neg:не может]] двигаться быстрее света.', ''),
    ('negation', 'Что не относится к металлам', 'К металлам [[neg:не относятся]] [[neg:ни кислород]], [[neg:ни азот]], [[neg:ни водород]].', ''),

    # --- abbreviations -----------------------------------------------------------------------------
    ('abbreviation', 'Что такое ВВП', 'ВВП — это валовой внутренний продукт, то есть стоимость всех товаров и услуг, произведённых в стране за год.', 'ВВП — это'),
    ('abbreviation', 'Какие бывают фрукты', 'Яблоки, груши, сливы [[abbr:и т. д.]] относятся к семечковым и косточковым плодам.', ''),
    ('abbreviation', 'Что относится к хвойным', 'К хвойным относятся ель, сосна, пихта [[abbr:и др.]]', ''),
    ('abbreviation', 'По какому кодексу судят за кражу', 'За кражу судят по [[abbr:УК РФ]], а споры о собственности решают по [[abbr:ГК РФ]].', ''),
    ('abbreviation', 'Что значит н. э.', 'Сокращение «[[abbr_era:н. э.]]» означает «нашей эры»: например, 476 год [[abbr_era:н. э.]] — это падение Западной Римской империи.', ''),
    ('abbreviation', 'Когда построили пирамиды', 'Великие пирамиды в Гизе построили около [[unit:2560 года]] до [[abbr_era:н. э.]]', ''),
    ('abbreviation', 'Когда жил Аристотель', 'Аристотель жил в [[century:IV веке]] до [[abbr_era:н. э.]] и был учителем Александра Македонского.', ''),
    ('abbreviation', 'Что такое НАТО', 'НАТО — это Североатлантический альянс, военно-политический блок, основанный в [[unit:1949 году]].', 'НАТО — это'),
    ('abbreviation', 'Что такое ЕГЭ', 'ЕГЭ — это единый государственный экзамен, который сдают выпускники школ.', 'ЕГЭ — это'),
    # W1F-A (b), brief task-w1fix-briefs.md: «head elision instead of the restatement fallback when the first new-content unit of the
    # same sentence is already ready» - the restated head before the number is elided (first_useful.elide_restated_head)
    ('abbreviation', 'Каково население города', 'Население города — около [[unit_abbr:70 тыс. человек]], и оно медленно растёт.',
     'Население города —'),
    ('abbreviation', 'Что значит т. е.', 'Сокращение «[[abbr:т. е.]]» значит «то есть» и вводит уточнение.', ''),
    ('abbreviation', 'Кто такой А. С. Пушкин', '[[initials:А. С. Пушкин]] — великий русский поэт, автор «Евгения Онегина».', ''),
    ('abbreviation', 'Кто подписал этот приказ', 'Приказ подписал [[initials:Иванов И. И.]], а утвердил директор.', ''),
    ('abbreviation', 'Что такое ООН', 'ООН — Организация Объединённых Наций, международная организация, созданная в [[unit:1945 году]] для поддержания мира.', 'ООН —'),

    # --- enumerations ------------------------------------------------------------------------------
    ('enumeration', 'Какие бывают агрегатные состояния вещества', 'Твёрдое, жидкое, газообразное и плазма.', ''),
    ('enumeration', 'Назови цвета радуги', 'Красный, оранжевый, жёлтый, зелёный, голубой, синий и фиолетовый.', ''),
    ('enumeration', 'Какие бывают падежи в русском языке', 'В русском языке шесть падежей: именительный, родительный, дательный, винительный, творительный и предложный.', ''),
    ('enumeration', 'Перечисли планеты земной группы', 'К планетам земной группы относятся Меркурий, Венера, Земля и Марс.', ''),
    ('enumeration', 'Какие органы чувств есть у человека', 'Зрение, слух, обоняние, вкус и осязание.', ''),
    ('enumeration', 'Назови три закона Ньютона', 'Первый закон — инерции, второй — связь силы и ускорения, третий — равенство действия и противодействия.', ''),
    ('enumeration', 'Какие бывают формы правления', 'Монархия, республика и теократия — три основные формы правления.', ''),
    ('enumeration', 'Перечисли ветви власти', 'Законодательная, исполнительная и судебная.', ''),
    ('enumeration', 'Какие бывают виды передачи тепла', 'Теплопроводность, конвекция и излучение.', ''),
    ('enumeration', 'Назови основные цвета в RGB', 'Красный, зелёный и синий — отсюда и название RGB.', ''),
    ('enumeration', 'Какие есть океаны', 'Тихий, Атлантический, Индийский, Северный Ледовитый и Южный.', ''),
    ('enumeration', 'Назови части речи', 'Существительное, прилагательное, глагол, наречие, местоимение, числительное, предлог, союз, частица и междометие.', ''),

    # --- long compound terms -----------------------------------------------------------------------
    ('compound_term', 'Что изучает электроэнцефалография', 'Электроэнцефалография изучает электрическую активность головного мозга.', ''),
    ('compound_term', 'Что такое сверхпроводимость', 'Сверхпроводимость — это явление, при котором электрическое сопротивление материала падает до нуля.', 'Сверхпроводимость — это'),
    ('compound_term', 'Как называется этот метод', 'Этот метод называется рентгеноструктурным анализом.', ''),
    ('compound_term', 'Что такое научно-технический прогресс', 'Научно-технический прогресс — это непрерывное развитие науки, техники и технологий.', 'Научно-технический прогресс — это'),
    ('compound_term', 'Что такое фотоэлектрический эффект', 'Фотоэлектрический эффект — это выбивание электронов из вещества под действием света.', 'Фотоэлектрический эффект — это'),
    ('compound_term', 'Что такое межпозвоночная грыжа', 'Межпозвоночная грыжа — это выпячивание диска позвоночника, которое может сдавливать нервные корешки.', 'Межпозвоночная грыжа — это'),
    ('compound_term', 'Как называется наша страна', 'Полное название — Российская Федерация, а краткое — Россия.', ''),
    ('compound_term', 'Что показывает водородный показатель', 'Водородный показатель, или pH, показывает кислотность раствора.', ''),
    ('compound_term', 'Что такое электромагнитная индукция', 'Электромагнитная индукция — это возникновение тока в проводнике при изменении магнитного поля.', 'Электромагнитная индукция — это'),
    ('compound_term', 'Что такое самоуправление', 'Самоуправление — это право людей самостоятельно решать местные вопросы.', 'Самоуправление — это'),
    ('compound_term', 'Как называется протокол передачи страниц', 'Это гипертекстовый протокол передачи данных, известный как HTTP.', ''),
    ('compound_term', 'Что такое многофункциональный центр', 'Многофункциональный центр — это учреждение, где можно получить государственные услуги в одном месте.', 'Многофункциональный центр — это'),

    # --- personal names ----------------------------------------------------------------------------
    ('name', 'Кто открыл закон всемирного тяготения', 'Закон всемирного тяготения открыл [[name2:Исаак Ньютон]] в [[unit:1687 году]].', ''),
    ('name', 'Кто создал периодическую таблицу', 'Периодическую таблицу элементов создал [[name3:Дмитрий Иванович Менделеев]].', ''),
    ('name', 'Кто написал роман «Война и мир»', 'Роман «Война и мир» написал [[name3:Лев Николаевич Толстой]].', ''),
    ('name', 'Кто первым полетел в космос', 'Первым в космос полетел [[name3:Юрий Алексеевич Гагарин]].', ''),
    ('name', 'Кто автор теории относительности', 'Автор теории относительности — [[name2:Альберт Эйнштейн]].', ''),
    ('name', 'Кто был первым президентом США', 'Первым президентом США был [[name2:Джордж Вашингтон]].', ''),
    ('name', 'Кто написал «Евгения Онегина»', '«Евгения Онегина» написал [[name3:Александр Сергеевич Пушкин]].', ''),
    ('name', 'Кто открыл пенициллин', 'Пенициллин открыл шотландский учёный [[name2:Александр Флеминг]] в [[unit:1928 году]].', ''),
    ('name', 'Кто первым побывал на Луне', 'Первым на Луне побывал [[name2:Нил Армстронг]] в июле [[unit:1969 года]].', ''),
    ('name', 'Кто основал Москву', 'Москву основал князь [[name2:Юрий Долгорукий]] в [[unit:1147 году]].', ''),
    ('name', 'Кто изобрёл радио', 'Радио изобрёл [[name3:Александр Степанович Попов]] в [[unit:1895 году]].', ''),
    ('name', 'Кто создал теорию эволюции', 'Теорию эволюции путём естественного отбора предложил [[name2:Чарльз Дарвин]].', ''),
    ('name', 'Кто написал «Преступление и наказание»', 'Это роман [[name3:Фёдора Михайловича Достоевского]].', ''),
    ('name', 'Кто была первой женщиной в космосе', 'Первой женщиной в космосе стала [[name2:Валентина Терешкова]] в [[unit:1963 году]].', ''),

    # --- two-sentence answers ----------------------------------------------------------------------
    ('two_sentences', 'Почему небо голубое', 'Потому что воздух сильнее рассеивает синий свет. Поэтому днём мы видим небо голубым.', 'Потому что'),
    ('two_sentences', 'Как работает холодильник', 'Холодильник переносит тепло изнутри наружу с помощью хладагента. Поэтому внутри становится холодно, а сзади — тепло.', ''),
    ('two_sentences', 'Зачем нужен сон', 'Во сне организм восстанавливается и закрепляет воспоминания. Без сна человек быстро теряет внимание и память.', ''),
    ('two_sentences', 'Что такое налог', 'Налог — это обязательный платёж государству. Из налогов оплачивают школы, дороги и больницы.', 'Налог — это'),
    ('two_sentences', 'Почему зимой холодно', 'Зимой солнечные лучи падают на землю под меньшим углом. Поэтому поверхность получает меньше тепла.', ''),
    ('two_sentences', 'Как образуется радуга', 'Радуга появляется, когда солнечный свет преломляется в каплях дождя. Белый свет при этом раскладывается на семь цветов.', ''),
    ('two_sentences', 'Как работает вакцина', 'Вакцина показывает иммунной системе безопасную копию возбудителя. Организм запоминает её и быстро реагирует при настоящей встрече.', ''),
    ('two_sentences', 'Почему корабли не тонут', 'Корабль вытесняет столько воды, сколько весит сам. Поэтому сила Архимеда держит его на плаву.', ''),
    ('two_sentences', 'Что такое облигация', 'Облигация — это долговая бумага. Покупатель одалживает деньги и получает за это проценты.', 'Облигация — это'),
    ('two_sentences', 'Как действует магнит', 'Магнит создаёт вокруг себя магнитное поле. Оно притягивает железо, никель и кобальт.', ''),
    ('two_sentences', 'Почему при трении выделяется тепло', 'Трение превращает часть энергии движения в тепло. Поэтому ладони нагреваются, когда мы быстро трём их друг о друга.', ''),
    ('two_sentences', 'Что такое конкуренция', 'Конкуренция — это соперничество продавцов за покупателей. Она снижает цены и улучшает качество товаров.', 'Конкуренция — это'),
    ('two_sentences', 'Как найти площадь круга', 'Площадь круга равна числу пи, умноженному на квадрат радиуса. Например, при радиусе [[unit:2 метра]] она составит около [[decimal:12,6]] квадратных метров.', ''),
    ('two_sentences', 'Как питаются растения', 'Растения берут воду из почвы и углекислый газ из воздуха. На свету они превращают их в сахара и кислород.', ''),
    ('two_sentences', 'Для чего нужна банковская карта', 'Карта позволяет платить без наличных. Деньги при этом списываются с вашего счёта.', ''),
    ('two_sentences', 'Почему идёт дождь', 'Водяной пар поднимается вверх и остывает. Из мелких капель образуются облака, а затем дождь.', ''),

    # --- answers without terminal punctuation -------------------------------------------------------
    ('no_final_punct', 'Как называется столица Франции', 'Столица Франции — Париж', ''),
    ('no_final_punct', 'Что показывает скорость', 'Скорость показывает какой путь проходит тело за единицу времени', ''),
    ('no_final_punct', 'Какая планета самая большая', 'Самая большая планета Солнечной системы — Юпитер', ''),
    ('no_final_punct', 'Когда самый длинный день в году', 'Самый длинный день в году приходится на двадцать первое или двадцать второе июня', ''),
    ('no_final_punct', 'Что такое фотосинтез', 'Фотосинтез — это процесс образования органических веществ из углекислого газа и воды на свету', 'Фотосинтез — это'),
    ('no_final_punct', 'Почему небо голубое', 'Потому что воздух сильнее рассеивает синий свет', 'Потому что'),
    ('no_final_punct', 'Сколько часов в сутках', 'В сутках [[spelled:двадцать четыре часа]]', ''),
    ('no_final_punct', 'Что делает вода при нуле градусов', 'При нуле градусов вода начинает замерзать и превращается в лёд', ''),
    ('no_final_punct', 'Кто написал «Горе от ума»', 'Её написал [[name3:Александр Сергеевич Грибоедов]]', ''),
    ('no_final_punct', 'Что такое пословица', 'Пословица — это короткое народное изречение с поучительным смыслом', 'Пословица — это'),
    ('no_final_punct', 'Как работает светофор', 'Красный сигнал запрещает движение, жёлтый предупреждает о смене, а зелёный разрешает ехать', ''),
    ('no_final_punct', 'Сколько сторон у треугольника', 'У треугольника три стороны и три угла', ''),
    ('no_final_punct', 'Как правильно сказать: ложить или класть', 'Правильно говорить «класть», а слова «ложить» в литературном языке нет', ''),
    ('no_final_punct', 'Нужно ли пить воду', 'Да, нужно пить воду регулярно в течение дня', ''),

    # --- numbers written in words (a voice transcript often has them) --------------------------------
    ('spelled_numbers', 'Чему равна четверть в долях целого', 'Четверть — это [[spelled:двадцать пять процентов]].', ''),
    # W1F-A (b), brief task-w1fix-briefs.md: «head elision instead of the restatement fallback when the first new-content unit of the
    # same sentence is already ready» - the restated head before the number is elided (first_useful.elide_restated_head)
    ('spelled_numbers', 'Сколько градусов в развёрнутом угле', 'В развёрнутом угле [[spelled:сто восемьдесят градусов]].',
     'В развёрнутом угле'),
    ('spelled_numbers', 'Каково расстояние между городами', 'Между городами примерно [[spelled:три тысячи километров]].', ''),
    ('spelled_numbers', 'Сколько длится перерыв', 'Перерыв длится [[spelled:пятнадцать минут]].', ''),
    ('spelled_numbers', 'Сколько лет стране', 'Стране уже больше [[spelled:ста лет]].', ''),
    ('spelled_numbers', 'Как долго идти пешком до вокзала', 'До вокзала идти пешком около [[spelled:сорока минут]].', ''),
    ('spelled_numbers', 'Какая высота у горы', 'Высота горы — примерно [[spelled:две тысячи метров]] над уровнем моря.', ''),
    ('spelled_numbers', 'Сколько человек учится в классе', 'В классе учатся [[spelled:двадцать пять человек]].', ''),
    ('spelled_numbers', 'Сколько ему лет', 'Ему [[spelled:тридцать шесть лет]].', ''),
    ('spelled_numbers', 'Чему равна половина в долях целого', 'В половине ровно [[spelled:пятьдесят процентов]].', ''),

    # --- numeric forms: time, ratio, range, fraction, currency, century, numeric date ------------------
    ('numeric_forms', 'Во сколько отправляется поезд', 'Поезд отправляется в [[time:12:30]] с первого пути.', ''),
    ('numeric_forms', 'Когда начинается урок', 'Урок начинается в [[time:9:45]], а заканчивается в [[time:10:30]].', ''),
    ('numeric_forms', 'Каково соотношение сторон экрана', 'Соотношение сторон экрана — [[ratio:16:9]], то есть он вытянут по горизонтали.', ''),
    ('numeric_forms', 'В каком масштабе карта', 'Масштаб карты — [[ratio:1:[[grouped:100 000]]]], то есть в одном сантиметре один километр.', ''),
    ('numeric_forms', 'Сколько шла война', 'Война шла с [[range:1941–1945]] годов.', ''),
    ('numeric_forms', 'Сколько часов нужно спать', 'Взрослому нужно спать [[range:7–9]] часов в сутки.', ''),
    ('numeric_forms', 'Какая доля голосов нужна', 'Для принятия решения нужно [[neg:не менее]] [[fraction:3/4]] голосов.', ''),
    ('numeric_forms', 'Сколько муки нужно для теста', 'На тесто потребуется [[fraction:1/2]] стакана муки.', ''),
    ('numeric_forms', 'При какой температуре замерзает вода', 'Вода замерзает при [[degree:0 °C]], а кипит при [[degree:100 °C]].', ''),
    ('numeric_forms', 'Какая температура на Венере', 'Температура на поверхности Венеры достигает [[degree:465 °C]].', ''),
    ('numeric_forms', 'Когда температура считается повышенной', 'Температура выше [[degree:38 °C]] считается повышенной.', ''),
    ('numeric_forms', 'Сколько стоит билет', 'Билет на поезд обойдётся примерно в [[currency:[[grouped:1 500]] ₽]], а детский — в [[currency:800 ₽]].', ''),
    ('numeric_forms', 'Какая у компании выручка', 'Выручка компании составила [[currency:[[decimal:2,3]] млн ₽]] за квартал.', ''),
    ('numeric_forms', 'Насколько увеличился доход', 'Доход вырос на [[unit:5 млн долларов]] за год.', ''),
    ('numeric_forms', 'Какова скорость самолёта', 'Скорость самолёта — около [[slashunit:900 км/ч]], что примерно [[slashunit:250 м/с]].', ''),
    ('numeric_forms', 'Какая плотность у воды', 'Плотность воды равна [[slashunit:1 г/см³]] при температуре [[degree:4 °C]].', ''),
    ('numeric_forms', 'В каком веке была революция', 'Французская революция произошла в [[century:XVIII веке]], а Октябрьская — в [[century:XX веке]].', ''),
    ('numeric_forms', 'В каком веке основали город', 'Город основали в [[century:12 веке]], а расцвёл он в [[century:XV веке]].', ''),
    ('numeric_forms', 'Как записывается дата', 'Дату записывают так: [[numdate:22.06.1941]].', ''),
    ('numeric_forms', 'Сколько будет два плюс два', 'Два плюс два равно 4, то есть [[expression:2 + 2 = 4]].', ''),
    ('numeric_forms', 'Каков был счёт матча', 'Счёт матча был [[expression:3 : 1]] в пользу гостей.', ''),
    ('numeric_forms', 'Сколько будет пять умножить на шесть', 'Пять умножить на шесть будет 30, то есть [[expression:5 × 6 = 30]].', ''),
    ('numeric_forms', 'Чему равно десять минус четыре', 'Десять минус четыре равно 6, то есть [[expression:10 − 4 = 6]].', ''),

    # --- one long sentence --------------------------------------------------------------------------
    ('long_sentence', 'Расскажи о фотосинтезе', 'Фотосинтез — это процесс, в котором растения, водоросли и некоторые бактерии превращают световую энергию в химическую энергию органических веществ, при этом выделяя кислород, который необходим для дыхания почти всех живых существ на Земле.', ''),
    ('long_sentence', 'Что такое финансовая система', 'Финансовая система Российской Федерации представляет собой совокупность взаимосвязанных сфер финансовых отношений, в которых образуются, распределяются и используются денежные фонды государства, предприятий и населения.', ''),
    ('long_sentence', 'Что говорит закон об ответственности', 'Если человек причинил вред другому лицу, то он обязан возместить этот вред полностью, если [[neg:не докажет]], что вред возник не по его вине.', ''),
    ('long_sentence', 'Как устроена клетка', 'Клетка состоит из мембраны, цитоплазмы и ядра, а в ядре хранится наследственная информация, которая передаётся от родителей к детям и определяет признаки организма.', ''),
    ('long_sentence', 'Зачем нужна демократия', 'Демократия нужна для того, чтобы граждане могли влиять на решения власти, выбирать своих представителей, контролировать их работу и защищать свои права законным путём.', ''),
    ('long_sentence', 'Почему происходят землетрясения', 'Землетрясения происходят потому, что литосферные плиты медленно движутся, накапливают напряжение, а затем резко сдвигаются, и энергия высвобождается в виде сейсмических волн.', ''),
    ('long_sentence', 'Как работает интернет', 'Интернет состоит из множества связанных между собой сетей, по которым данные передаются небольшими пакетами, а специальные маршрутизаторы выбирают для каждого пакета подходящий путь.', ''),
    ('long_sentence', 'Что такое экосистема', 'Экосистема — это сообщество живых организмов вместе с неживой средой, в котором растения, животные, грибы и микроорганизмы связаны потоками энергии и веществ.', 'Экосистема — это'),

    # --- quotes, brackets, dashes ------------------------------------------------------------------
    ('quotes_parens', 'Что означает слово «альтруизм»', 'Слово «альтруизм» означает бескорыстную заботу о благе других людей.', ''),
    ('quotes_parens', 'Как называется поэма Пушкина о Руслане', 'Одна из самых известных поэм Пушкина называется «Руслан и Людмила».', ''),
    ('quotes_parens', 'Что значит выражение «ни пуха ни пера»', 'Это пожелание удачи, на которое принято отвечать «к чёрту», и [[neg:ни пуха]] [[neg:ни пера]] тут [[neg:не значит]] ничего дурного.', ''),
    ('quotes_parens', 'Что такое ДНК', 'ДНК (дезоксирибонуклеиновая кислота) хранит наследственную информацию организма.', ''),
    ('quotes_parens', 'Как правильно писать слово', 'Слово пишется слитно (например, «вообще»), а в других случаях — раздельно.', ''),
    ('quotes_parens', 'Что такое Рунет', 'Рунет — это русскоязычная часть интернета (сайты, форумы и соцсети).', 'Рунет — это'),
    ('quotes_parens', 'Кто сказал фразу «Я мыслю, следовательно, существую»', 'Эту фразу сказал философ [[name2:Рене Декарт]].', ''),
    ('quotes_parens', 'Как называется первый закон Ньютона', 'Первый закон Ньютона называют законом инерции — «всякое тело сохраняет состояние покоя, пока на него [[neg:не действуют]] другие тела».', ''),

    # --- yes / no and very short answers -----------------------------------------------------------
    ('short', 'Правда ли что кит рыба', 'Нет, кит [[neg:не рыба]].', ''),
    ('short', 'Правда ли что Земля круглая', 'Да, Земля круглая.', ''),
    ('short', 'Растёт ли трава зимой', 'Нет.', ''),
    ('short', 'Верно ли что вода мокрая', 'Да.', ''),
    ('short', 'Можно ли есть грибы сырыми', 'Лучше [[neg:не стоит]].', ''),
    ('short', 'Есть ли жизнь на Марсе', 'Пока неизвестно.', ''),
    ('short', 'Нужна ли виза', 'Нет, визу оформлять [[neg:не нужно]].', ''),
    ('short', 'Правда ли что молния бьёт в одно место дважды', 'Да, бывает: в высокие здания она ударяет много раз в год.', ''),
]

# Alignment sweep: the same fact behind prefaces of different length, so that every cut position of the
# fixed-size and of the syllable planner is tried against the declared pieces.
_PREFACES = ('', 'Итак, ', 'Если коротко, ', 'Можно сказать, что ', 'Как известно, ', 'Вкратце, ', 'Коротко говоря, ',
             'Насколько я знаю, ', 'По имеющимся данным, ', 'Для начала отмечу, что ')
_FRAMES = [
    ('Сколько километров до Луны', 'расстояние от Земли до Луны составляет около [[unit:[[grouped:384 400]] километров]]'),
    ('При какой температуре кипит вода', 'вода кипит при [[degree:100 °C]] на уровне моря'),
    ('Во сколько уходит поезд', 'поезд отправляется в [[time:12:30]] с первого пути'),
    ('Сколько продолжалась война', 'война шла с [[range:1941–1945]] годов'),
    ('Какова скорость света', 'скорость света в вакууме составляет примерно [[slashunit:[[grouped:300 000]] км/с]]'),
    ('Когда построили пирамиду Хеопса', 'эту пирамиду построили около [[unit:2560 года]] до [[abbr_era:н. э.]]'),
    ('Кто открыл закон тяготения', 'этот закон открыл [[name2:Исаак Ньютон]] в [[unit:1687 году]]'),
    ('Кто написал это стихотворение', 'стихотворение написал [[name3:Александр Сергеевич Пушкин]] в юности'),
    ('Когда произошла революция', 'эта революция произошла в [[century:XVIII веке]]'),
    ('Рыба ли кит', 'кит [[neg:не рыба]], а млекопитающее'),
    ('Сколько денег осталось', 'в бюджете осталось [[currency:[[grouped:1 500]] ₽]] до конца месяца'),
    ('Какая температура у здорового человека', 'нормальная температура тела — около [[degree:[[decimal:36,6]] °C]]'),
    ('Сколько кислорода в воздухе', 'в воздухе около [[unit:21 %]] кислорода'),
    ('Сколько градусов в развёрнутом угле', 'в развёрнутом угле [[spelled:сто восемьдесят градусов]]'),
    ('Сколько жителей в городе', 'население города — около [[unit_abbr:70 тыс. человек]]'),
    ('Кто отвечает за кражу', 'ответственность за кражу предусмотрена [[abbr:УК РФ]]'),
]


def ends_with_terminal_punctuation(text):
    """The product's own notion of a finished answer (controlled_media: a segment is final only then)."""
    return bool(re.search(r'[.!?…][»”"\)]*\s*$', text))


def _build():
    items, counters = [], {}
    for category, question, marked, elide in _HAND:
        counters[category] = counters.get(category, 0) + 1
        answer = squeeze(_flatten(marked))
        items.append(Item(f'{category}-{counters[category]:02d}', category, question.rstrip('?') + '?', answer,
                          _nested_atoms(marked), elide, ends_with_terminal_punctuation(answer)))
    for fi, (question, frame) in enumerate(_FRAMES, 1):
        for pi, preface in enumerate(_PREFACES):
            marked = ((preface + frame) if preface else (frame[:1].upper() + frame[1:])) + '.'
            items.append(Item(f'sweep-{fi:02d}-{pi:02d}', 'alignment_sweep', question + '?',
                              squeeze(_flatten(marked)), _nested_atoms(marked), '', True))
    return items


CORPUS = _build()
HAND_CORPUS = [item for item in CORPUS if item.category != 'alignment_sweep']


# =====================================================================================================
# Quality statistics for the report
# =====================================================================================================

PUNCT_END = ',;:.!?…—–)»”'
SENTENCE_END = '.!?…'
_ABBREVIATIONS = frozenset('т н г гг др пр см рис им ул тыс млн млрд руб коп проф акад стр д е п э'.split())
_SENTENCE_BREAK = re.compile(r'(\w+)([.!?…]+)[»”"\)]*\s+[«„"(]?[А-ЯЁA-Z]')
_ENDS_ON = frozenset('не ни в на и а но с к о от из за для по что как при до у или чтобы если бы ли же'.split())


def straddles_a_sentence_end(portion):
    """True when a portion holds the end of one sentence and the start of the next (not an abbreviation period)."""
    for match in _SENTENCE_BREAK.finditer(portion):
        word = match.group(1).casefold()
        if len(word) >= 2 and word not in _ABBREVIATIONS and not word.isdigit():
            return True
    return False


def head_removed(item, chunks):
    """``(item as the listener hears it, shift)``: the answer without the head the system elided in front of ``chunks``
    (shift = non-space characters dropped); atoms inside the dropped head are forgotten."""
    flat, got = nospace(item.answer), nospace(''.join(chunks))
    shift = len(flat) - len(got) if got and flat.endswith(got) else 0
    if not shift:
        return item, 0
    seen, index = 0, 0
    while seen < shift and index < len(item.answer):
        seen += not item.answer[index].isspace()
        index += 1
    spoken = item.answer[index:].lstrip()
    kept = [(k, a) for k, a in item.atoms if atom_spans(spoken, a)]
    return Item(item.id, item.category, item.question, spoken, kept, '', item.punctuated), shift


def portion_problems(item, portion_list, cfg):
    """``{portion index: [reason, ...]}`` for one answer: what a listener would call a bad cut."""
    problems = {}
    cuts = boundaries(portion_list)
    starts = [0] + cuts
    ends = cuts + [len(nospace(''.join(portion_list)))]

    def owner(position):
        return next(i for i, (a, b) in enumerate(zip(starts, ends)) if a <= position < b)

    for kind, atom in item.atoms:
        for start, end in atom_spans(item.answer, atom):
            if any(start < c < end for c in cuts):
                for i in {owner(start), owner(end - 1)}:
                    problems.setdefault(i, []).append(f'cuts {kind} «{atom}»')
    n = len(portion_list)
    for i, portion in enumerate(portion_list):
        words = norm_words(portion)
        last = words[-1] if words else ''
        flags = problems.setdefault(i, [])
        if i < n - 1 and last in _ENDS_ON and portion.rstrip()[-1:] not in SENTENCE_END:
            flags.append(f'ends on «{last}»')
        count = product_words(portion)
        if cfg['portion_mode'] == 'syllables':
            if count > cfg['max_words'] or syllables(portion) > cfg['max_syllables']:
                flags.append(f'over the limit ({count} words, {syllables(portion)} syllables)')
            if count < cfg['min_words'] and n > 1:
                flags.append(f'{count} word(s) < min_words {cfg["min_words"]}')
        if straddles_a_sentence_end(portion):
            flags.append('spans a sentence end')
        if portion.count('«') != portion.count('»') or portion.count('(') != portion.count(')'):
            flags.append('unbalanced quote or bracket')
    return {i: r for i, r in problems.items() if r}


def _score(reasons):
    weights = (('cuts ', 5), ('ends on', 4), ('over the limit', 3), ('min_words', 2), ('spans a sentence', 2), ('unbalanced', 1))
    return sum(next((w for key, w in weights if r.startswith(key) or key in r), 1) for r in reasons)


def quality(items, settings, *, worst=10, plans=None):
    """Portion-length histogram, share of boundaries at punctuation, the worst portions with reasons.

    ``plans``: ``{item.id: chunks}`` to judge chunks that were really produced (the streamed ones) instead of the
    offline plan ``portions(item.answer, settings)``; the head the system elided is accounted for."""
    cfg = resolve(settings)
    hist_words, hist_syl = Counter(), Counter()
    boundaries_total = at_punct = at_sentence = at_clause = 0
    portions_total = bad = one_word = straddling = 0
    ranked = []
    per_kind, atoms_seen = Counter(), Counter()
    for original in items:
        if plans is None:
            item, parts = original, portions(original.answer, settings)
        else:
            parts = list(plans[original.id])
            item, _ = head_removed(original, parts)
        portions_total += len(parts)
        for portion in parts:
            hist_words[min(product_words(portion), 10)] += 1
            hist_syl[min(syllables(portion) // 2 * 2, 20)] += 1
            one_word += product_words(portion) == 1 and len(parts) > 1
            straddling += straddles_a_sentence_end(portion)
        for portion in parts[:-1]:
            boundaries_total += 1
            tail = portion.rstrip()[-1:]
            if tail in PUNCT_END:
                at_punct += 1
                if tail in SENTENCE_END:
                    at_sentence += 1
                else:
                    at_clause += 1
        for kind, atom in item.atoms:
            atoms_seen[kind] += 1
            if cut_atoms(item.answer, [atom], parts):
                per_kind[kind] += 1
        problems = portion_problems(item, parts, cfg)
        bad += len(problems)
        for i, reasons in problems.items():
            ranked.append((_score(reasons), -len(parts[i]), item.id, parts[i], sorted(set(reasons))))
    ranked.sort(key=lambda row: (-row[0], row[1], row[2]))
    return {
        'answers': len(items), 'portions': portions_total, 'hist_words': dict(sorted(hist_words.items())),
        'hist_syllables': dict(sorted(hist_syl.items())), 'boundaries': boundaries_total,
        'boundaries_at_punctuation': at_punct, 'boundaries_at_sentence_end': at_sentence,
        'boundaries_at_clause_punctuation': at_clause,
        'share_at_punctuation': round(at_punct / boundaries_total, 3) if boundaries_total else None,
        'one_word_portions': one_word, 'portions_spanning_a_sentence_end': straddling,
        'portions_with_a_problem': bad, 'atoms_cut_by_kind': dict(sorted(per_kind.items())),
        'atoms_by_kind': dict(sorted(atoms_seen.items())),
        'worst': [(item_id, portion, reasons) for _, _, item_id, portion, reasons in ranked[:worst]],
    }


def main():  # pragma: no cover - report helper
    import json
    for name in ('controlled', 'words3', 'range_2_8'):
        print('==', name)
        print(json.dumps(quality(HAND_CORPUS, PROFILES[name]), ensure_ascii=False, indent=1))


if __name__ == '__main__':  # pragma: no cover
    main()

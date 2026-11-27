"""F1 (wave F, the owner's real call of 3 Nov 09:55): portions by meaning, not by 1-3 words.

Evidence: .superpowers/sdd/wave2/owner-call-0955-timeline.txt. The call cut «Это статья о правах» | «налогоплательщиков» | «в первой
части» | «Налогового кодекса» | «РФ. Она», «Крещение Руси» | «традиционно относят» | «к 988 году,» and «В том, что ресурсы» | «и
производство» | «распределяются» | «централизованно» | «по плану,»: every portion costs the listener a whole cycle, so an answer took a
minute and sounded fake. The class (brief F1): a sentence is a portion when it fits; else whole clauses; else phrases. Never across a
sentence end, never inside a phrase (a preposition and its noun, an adjective and its noun, a noun and its genitive, a number and its
unit), never a word that needs its head at the end; one word only when the sentence is one word.

The expected values are written by hand from the texts; the phrase checker below is independent of echo_sync (pymorphy3 directly).
"""
from __future__ import annotations

import re

import pymorphy3
import pytest
from razdel import sentenize

from echo_sync.engine import EchoEngine
from echo_sync.first_useful import first_cue
from echo_sync.portioner import portions, stable_prefix
from echo_sync.settings import CALL_SETTINGS, PRESETS, resolve

M = {'preset': 'meaning'}
MORPH = pymorphy3.MorphAnalyzer()
WORD = re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*")
PREPOSITIONS = frozenset('в во на с со к ко по о об от из за для до при про над под перед между через без у около после среди'.split())
UNIT_WORDS = re.compile(r'^(?:год|лет|век|градус|процент|рубл|метр|километр|секунд|минут|час|тонн|килограмм)')

# --- the owner's call: the three answers as they were cut, and as they are cut now -------------------------------------------------
TAX = ('Это статья о правах налогоплательщиков в первой части Налогового кодекса РФ. Она перечисляет, например, право получать '
       'бесплатную информацию о налогах.')
BAPTISM = 'Крещение Руси традиционно относят к 988 году, когда князь Владимир крестился и крестил киевлян.'
ECONOMY = 'В том, что ресурсы и производство распределяются централизованно по плану, а не рынком.'

# --- NEW wordings of the same classes (written for this task, never seen in a call) -------------------------------------------------
NEW = [
    'Это глава о правах владельцев земельных участков в составе Земельного кодекса Российской Федерации.',
    'Смысл рыночной экономики в том, что цены и объёмы производства определяются спросом покупателей.',
    'Куликовскую битву обычно датируют 1380 годом, когда Дмитрий Донской разбил войско Мамая.',
    'Закон сохранения энергии утверждает, что энергия замкнутой системы не возникает из ничего и не исчезает.',
    'Фотосинтез происходит в хлоропластах клеток зелёных растений под действием солнечного света.',
    'Средняя температура поверхности Венеры составляет около 460 градусов Цельсия из-за парникового эффекта.',
    'Это закон о защите прав потребителей в России. Он действует с 1992 года и регулирует продажу товаров.',
    'Когда вода остывает до нуля градусов, она превращается в лёд и расширяется.',
    'Инфляция означает рост общего уровня цен в экономике страны за определённый период времени.',
    'Статья 145 НК РФ освобождает небольшие организации от обязанностей плательщика налога на добавленную стоимость.',
]


def words(text):
    return WORD.findall(text)


def sentence_count(text):
    return len(list(sentenize(text)))


def phrase_splits(chunks):
    """Cuts with no punctuation that part a preposition from its noun, an adjective from the noun it agrees with, a noun from the
    genitive that follows it, or a number from its unit."""
    found = []
    for left, right in zip(chunks, chunks[1:]):
        a, b = words(left), words(right)
        if re.search(r'[,.;:!?…—–)»]\s*$', left):
            continue
        x, y = a[-1], b[0]
        px, ys = MORPH.parse(x.casefold())[0], MORPH.parse(y.casefold())
        if x.casefold() in PREPOSITIONS:
            found.append(('preposition', left, right))
        elif x.isdigit() and UNIT_WORDS.match(y.casefold()):
            found.append(('number_unit', left, right))
        elif px.tag.POS in ('ADJF', 'PRTF') and any(p.tag.POS == 'NOUN' and p.tag.case == px.tag.case for p in ys):
            found.append(('agreement', left, right))
        elif px.tag.POS == 'NOUN' and ys[0].tag.POS in ('NOUN', 'ADJF') and ys[0].tag.case == 'gent':
            found.append(('genitive', left, right))
    return found


# --- the preset and the call's profile ------------------------------------------------------------------------------------------------

def test_meaning_is_a_preset_and_a_portion_mode():
    assert PRESETS['meaning']['portion_mode'] == 'meaning'
    cfg = resolve(M)
    assert cfg['portion_mode'] == 'meaning'
    assert cfg['max_words'] == 9                         # the hard cap of a portion
    assert resolve({'portion_mode': 'meaning'})['portion_mode'] == 'meaning'


def test_the_call_profile_is_meaning_with_the_call_ack():
    cfg = resolve(CALL_SETTINGS)
    assert cfg['portion_mode'] == 'meaning' and 'ack_match' not in cfg and 'on_mismatch' not in cfg


def test_other_modes_are_unchanged_by_the_new_mode():
    # the legacy three-word mode and the call's old profile give exactly what they gave before F1 (pinned by hand)
    assert portions('Крещение Руси традиционно относят к 988 году.', {'portion_mode': 'words', 'words_per_portion': 3}) == [
        'Крещение Руси традиционно', 'относят к 988', 'году.']


# --- the owner's call, cut by meaning -------------------------------------------------------------------------------------------------

def test_the_tax_answer_is_cut_into_phrases_and_never_across_the_sentence_end():
    assert portions(TAX, M) == ['Это статья о правах налогоплательщиков', 'в первой части Налогового кодекса РФ.',
                                'Она перечисляет, например,', 'право получать бесплатную информацию о налогах.']


def test_the_baptism_answer_keeps_its_first_clause_whole():
    assert portions(BAPTISM, M) == ['Крещение Руси традиционно относят к 988 году,',
                                    'когда князь Владимир крестился и крестил киевлян.']


def test_the_economy_answer_is_two_portions_not_seven():
    assert portions(ECONOMY, M) == ['В том, что ресурсы и производство',
                                    'распределяются централизованно по плану, а не рынком.']


# --- the class on new wordings ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('text', NEW + [TAX, BAPTISM, ECONOMY])
def test_no_portion_crosses_a_sentence_end(text):
    for chunk in portions(text, M):
        assert sentence_count(chunk) == 1, chunk


@pytest.mark.parametrize('text', NEW + [TAX, BAPTISM, ECONOMY])
def test_no_cut_inside_a_phrase(text):
    assert phrase_splits(portions(text, M)) == []


@pytest.mark.parametrize('text', NEW + [TAX, BAPTISM, ECONOMY])
def test_sizes_are_meaning_sized(text):
    chunks = portions(text, M)
    sizes = [len(words(chunk)) for chunk in chunks]
    assert max(sizes) <= 9, chunks
    for chunk, size in zip(chunks, sizes):
        # one word only when the sentence is one word; never two words cut out of a longer sentence
        assert size >= 3 or any(len(words(s.text)) == size for s in sentenize(text)), chunks
    assert ' '.join(chunks) == ' '.join(text.split())                     # nothing lost, nothing added


def test_a_sentence_that_fits_is_one_portion():
    assert portions('Крещение Руси произошло в 988 году.', M) == ['Крещение Руси произошло в 988 году.']
    assert portions('Плотность показывает массу единицы объёма вещества.', M) == [
        'Плотность показывает массу единицы объёма вещества.']


def test_a_long_sentence_is_cut_at_its_clause_punctuation():
    assert portions('Когда вода остывает до нуля градусов, она превращается в лёд и расширяется.', M) == [
        'Когда вода остывает до нуля градусов,', 'она превращается в лёд и расширяется.']


def test_a_one_word_sentence_is_its_own_portion_and_never_joins_the_next():
    assert portions('Да. Его обычно относят к 1242 году.', M) == ['Да.', 'Его обычно относят к 1242 году.']


def test_an_abbreviation_period_is_no_sentence_end():
    chunks = portions('Население города около 70 тыс. человек, т. е. немного. А. С. Пушкин бывал там.', M)
    assert 'А. С. Пушкин бывал там.' in chunks
    assert all('70 тыс. человек' in chunk or '70' not in chunk for chunk in chunks)


# --- streaming: the plan of a streamed answer is the plan of the whole answer ---------------------------------------------------------

def streamed(text, settings):
    """The portions the engine stores when ``text`` arrives word by word through stable_prefix (no first cue)."""
    resolved = resolve(settings)
    published, chunks = '', []
    ends = [m.end() for m in WORD.finditer(text)]
    for k, end in enumerate(ends, 1):
        final = k == len(ends)
        while not final and end < len(text) and not text[end].isspace() and not text[end].isalnum():
            end += 1
        arrived = text if final else text[:end]
        prefix = arrived if final else stable_prefix(arrived, settings, committed=published)
        if not prefix or len(prefix) <= len(published):
            continue
        chunks += EchoEngine._portions_after(chunks, prefix[len(published):], resolved)
        published = prefix
    return chunks


@pytest.mark.parametrize('text', NEW + [TAX, BAPTISM, ECONOMY])
def test_a_streamed_answer_is_cut_as_the_whole_answer(text):
    assert streamed(text, M) == portions(text, M)


def test_a_quotation_mark_is_no_clause_boundary():
    text = ('Прививка даёт иммунной системе безопасный «образец» возбудителя, чтобы она научилась распознавать его и быстро '
            'реагировать.')
    chunks = portions(text, M)
    assert not any(chunk.endswith('«образец»') for chunk in chunks), chunks
    assert not any(chunk.endswith('безопасный') for chunk in chunks), chunks


def test_a_long_open_sentence_lets_its_first_clause_go_before_its_end_arrives():
    text = ('Прививка даёт иммунной системе безопасный образец возбудителя, чтобы она научилась его распознавать, быстро '
            'вырабатывала антитела и клетки памяти, а потом защищала человека от тяжёлого течения')
    committed = stable_prefix(text, M)
    assert committed and text.startswith(committed) and committed.endswith(','), committed
    assert stable_prefix(text[:60], M) == ''                       # a short open sentence waits


def test_the_first_cue_never_tears_a_phrase_for_new_information():
    # every place inside the window that says something new tears a genitive («принцип свободы | договора»): the restatement that keeps
    # its phrases whole is spoken, and the next portion carries the content
    answer = 'Статья 421 Гражданского кодекса закрепляет принцип свободы договора: стороны свободны решать.'
    cue, _ = streamed_first_cue('Статья 421 Гражданского кодекса закрепляет принцип', answer)
    assert cue is not None and answer.startswith(cue)
    assert phrase_splits([cue, answer[len(cue):].strip()]) == [], cue
    assert not cue.endswith(('свободы', 'принцип', '421'))


@pytest.mark.parametrize('text,unit', [
    # DEF-T-12 on sentences long enough to be cut: a number and a unit the lexicon does not know stay one unit
    ('Ёмкость такого конденсатора в новой схеме источника питания для этого прибора равна 100 нанофарад при комнатной '
     'температуре и нормальной влажности воздуха.', '100 нанофарад'),
    ('Ёмкость такого конденсатора в новой схеме источника питания для этого прибора равна сто нанофарад при комнатной '
     'температуре и нормальной влажности воздуха.', 'сто нанофарад'),
    # DEF-T-13: a Latin product name and its version stay one unit
    ('В нашей компании для этого сервиса протокол обмена давно использует Python 3.12 и надёжно доставляет данные между '
     'узлами сети.', 'Python 3.12'),
    ('На всех рабочих компьютерах нашего отдела бухгалтерии сейчас стоит Windows 11 с последними обновлениями безопасности.',
     'Windows 11'),
])
def test_a_number_stays_with_its_rare_unit_and_a_name_with_its_version_in_a_long_sentence(text, unit):
    chunks = portions(text, M)
    assert len(chunks) > 1, chunks                                          # the sentence is cut somewhere
    assert any(unit in chunk for chunk in chunks), chunks


def test_a_reciprocal_pronoun_is_never_cut_around_its_preposition():
    for text in ('Трение — это сила, которая мешает телам скользить друг по другу и нагревает их поверхности при каждом движении.',
                 'Магниты с одинаковыми полюсами отталкиваются друг от друга, а с разными притягиваются друг к другу.'):
        chunks = portions(text, M)
        assert not any(chunk.endswith('друг') for chunk in chunks), chunks


def test_a_name_after_a_title_stays_with_it():
    for text in ('Крещение Руси связывают с тем, что князь Владимир в 988 году крестился сам и крестил киевлян.',
                 'Самое глубокое пресноводное озеро на Земле — озеро Байкал в Восточной Сибири на юге России.'):
        chunks = portions(text, M)
        assert not any(chunk.endswith(('князь', 'озеро')) for chunk in chunks), chunks


def test_the_first_cue_respects_a_smaller_word_cap_of_the_profile():
    cue, _ = streamed_first_cue('Когда было крещение Руси', BAPTISM, {**CALL_SETTINGS, 'max_words': 5})
    assert cue is not None and len(words(cue)) <= 5


def test_a_listener_waiting_at_the_frontier_gets_the_first_phrase_of_an_open_sentence():
    # the cloud's text trickles in and the listener has repeated everything published: an open sentence that already plans two
    # portions lets its first one go (``eager``), instead of starving the listener until the sentence ends
    text = 'Короткое плечо даёт выигрыш в пути, но не даёт выигрыша в работе и'
    assert stable_prefix(text, M) == ''
    assert stable_prefix(text, M, eager=True) == 'Короткое плечо даёт выигрыш в пути,'
    # one open portion of 5+ words: the listener gets it up to its cheapest inner cut, its last words stay for the next one
    assert stable_prefix('Короткое плечо рычага даёт выигрыш в пути и', M) == ''
    assert stable_prefix('Короткое плечо рычага даёт выигрыш в пути и', M, eager=True) == 'Короткое плечо рычага даёт выигрыш'
    # its clause punctuation has arrived: the whole clause goes; three words or fewer open with no mark: nothing to give yet
    assert stable_prefix('Короткое плечо даёт выигрыш в пути, но', M, eager=True) == 'Короткое плечо даёт выигрыш в пути,'
    assert stable_prefix('Короткое плечо даёт и', M, eager=True) == ''
    # a mark after a number at the end of the arrived text may be its decimal point or comma («ГОСТ 2.105», «2,5»): no clause end
    for text in ('Общие требования к текстовым документам задаёт ГОСТ 2.', 'Средняя скорость течения этой реки составляет 2,'):
        assert not stable_prefix(text, M, eager=True).endswith(('2.', '2,')), stable_prefix(text, M, eager=True)


def test_a_listener_starving_at_the_frontier_gets_every_word_that_arrived():
    # the text trickles a word every few seconds and the listener has waited at the frontier as long as an idle segment would take
    # to flush (``starving``): every complete word that arrived goes - a meaning portion is not worth more silence than that
    assert stable_prefix('но не слово1 слово2 слово3 слово4', M, committed='но не слово1 слово2', eager=True) == 'но не слово1 слово2'
    assert stable_prefix('но не слово1 слово2 слово3 слово4', M, committed='но не слово1 слово2', starving=True) == (
        'но не слово1 слово2 слово3')                          # «слово4» may still be the middle of a word
    assert stable_prefix('но не слово1 слово2 слово3 слово4 ', M, committed='но не слово1 слово2', starving=True) == (
        'но не слово1 слово2 слово3 слово4')
    assert stable_prefix('но не слово1 слово2 сло', M, committed='но не слово1 слово2', starving=True) == 'но не слово1 слово2'


def test_stable_prefix_waits_for_the_end_of_a_short_sentence():
    assert stable_prefix('Это статья о правах налогоплательщиков в первой части', M) == ''
    assert stable_prefix('Это статья о правах налогоплательщиков в первой части Налогового кодекса РФ. Она', M) == (
        'Это статья о правах налогоплательщиков в первой части Налогового кодекса РФ.')


# --- the first cue of a call: meaning-sized and carrying something the question does not have ----------------------------------------

def streamed_first_cue(question, answer, settings=CALL_SETTINGS):
    """The first cue as the call path releases it: the answer arrives word by word (with its punctuation); ``(cue, words arrived)``."""
    ends = [m.end() for m in WORD.finditer(answer)]
    for k, end in enumerate(ends, 1):
        final = k == len(ends)
        while not final and end < len(answer) and not answer[end].isspace() and not answer[end].isalnum():
            end += 1
        cue = first_cue(answer if final else answer[:end], question, settings, final=final, last=final)
        if cue:
            return cue, k
    return None, None


def test_the_first_cue_of_the_baptism_answer_carries_the_date():
    cue, arrived = streamed_first_cue('Когда было крещение Руси', BAPTISM)
    assert cue == 'Крещение Руси традиционно относят к 988 году,'
    assert arrived == 7                                  # released at the clause end, not after the whole sentence


def test_a_new_date_answer_releases_its_whole_first_clause():
    cue, _ = streamed_first_cue('Когда была Куликовская битва',
                                'Куликовскую битву обычно датируют 1380 годом, когда Дмитрий Донской разбил войско Мамая.')
    assert cue == 'Куликовскую битву обычно датируют 1380 годом,'


def test_a_restating_opening_extends_to_a_unit_with_new_information():
    cue, _ = streamed_first_cue('Что такое фотосинтез',
                                'Фотосинтез — это процесс, при котором растения превращают свет в энергию.')
    assert cue is not None and len(words(cue)) >= 3
    assert re.search(r'процесс|растени|свет', cue)


def test_the_first_cue_of_the_tax_answer_is_a_phrase_not_one_word():
    cue, _ = streamed_first_cue('21-ая статья налогового кодекса. Что такое', TAX)
    assert cue == 'Это статья о правах налогоплательщиков'


def test_the_first_cue_of_the_economy_answer_is_the_subject_phrase():
    cue, _ = streamed_first_cue('в чём заключается смысл экономики плановой', ECONOMY)
    assert cue == 'В том, что ресурсы и производство'


@pytest.mark.parametrize('question,answer', [
    ('Что такое инфляция', 'Инфляция означает рост общего уровня цен в экономике страны за определённый период времени.'),
    ('Сколько длилась Столетняя война', 'Столетняя война длилась сто шестнадцать лет, с 1337 по 1453 год.'),
    ('Какая температура на Венере', 'Средняя температура поверхности Венеры составляет около 460 градусов Цельсия.'),
])
def test_first_cues_on_new_wordings_are_meaning_sized_and_not_a_restatement(question, answer):
    cue, _ = streamed_first_cue(question, answer)
    assert cue is not None
    # C7-A: a question for a number («Сколько…», «Какая температура…») runs on to its number, in a window of up to 12 words
    assert 3 <= len(words(cue)) <= (12 if re.match(r'(?:Сколько|Какая температура)', question) else 8)
    if re.match(r'(?:Сколько|Какая температура)', question):
        assert re.search(r'\d|сто ', cue), cue
    assert answer.startswith(cue)
    assert sentence_count(cue) == 1
    assert phrase_splits([cue, answer[len(cue):].strip()]) == []


# --- the real call path: ControlledMedia on the call profile, the answer streamed word by word, every cue repeated ------------------

HOST_KWARGS = dict(source_delivery='delegation', session_context_fallback=True, lookup_policy='required',
                   first_useful_gate=True, coalesce_seconds=3.2, quiet_reopen=True)        # controlled_host.serve's keywords


def call_cues(tmp_path, question, answer):
    """What the phone says when ``answer`` streams in for ``question`` and the listener repeats every cue word for word."""
    from echo_sync.controlled_media import ControlledMedia
    controller = ControlledMedia(tmp_path / 'controlled-state.sqlite3', session_id='native-probe-' + '0' * 32,
                                 settings=dict(CALL_SETTINGS), **HOST_KWARGS)

    def event(kind, tid, role, text, n=0):
        if kind == 'delta':
            return controller.provider({'type': 'turn.delta', 'turn_id': tid, 'delta': text, 'start_ms': n * 40,
                                        'end_ms': n * 40 + 39})
        return controller.provider({'type': f'turn.{kind}', 'turn': {'id': tid, 'role': role, 'transcript': text}})

    def speech(actions):
        return [a['text'] for a in actions if a['type'] == 'speak']

    asked = re.findall(r'\s*\S+', question)
    event('created', 'u1', 'user', asked[0])
    for n, piece in enumerate(asked[1:], 1):
        event('delta', 'u1', 'user', piece, n)
    event('done', 'u1', 'user', question)
    pieces, spoken = re.findall(r'\s*\S+', answer), []
    spoken += speech(event('created', 'a1', 'assistant', pieces[0]))
    for n, piece in enumerate(pieces[1:], 1):
        spoken += speech(event('delta', 'a1', 'assistant', piece, n))
    spoken += speech(event('done', 'a1', 'assistant', answer))
    assert spoken, 'total silence'
    for n in range(12):
        said = speech(event('done', f'ack{n}', 'user', spoken[-1]))
        if not said:
            break
        spoken.append(said[0])
    return spoken


def test_a_call_runs_on_the_meaning_profile_when_the_profile_is_at_its_defaults(tmp_path):
    # ROOT-1: controlled_host.serve builds ControlledMedia with controller_settings(profile); a default profile keeps CALL_SETTINGS' portions
    from echo_sync.controlled_host import controller_settings
    from echo_sync.controlled_media import ControlledMedia
    built = controller_settings(resolve(None))
    controller = ControlledMedia(tmp_path / 'controlled-state.sqlite3', session_id='native-probe-' + '0' * 32, settings=built, **HOST_KWARGS)
    assert {k: controller.settings[k] for k in CALL_SETTINGS} == CALL_SETTINGS
    assert resolve(controller.settings)['portion_mode'] == 'meaning'
    assert controller.engine.settings is controller.settings                 # the engine plans the later portions on it too


def test_the_call_path_speaks_the_baptism_answer_in_two_meaning_portions(tmp_path):
    assert call_cues(tmp_path, 'Когда было крещение Руси?', BAPTISM) == [
        'Крещение Руси традиционно относят к 988 году,', 'когда князь Владимир крестился и крестил киевлян.']


def test_the_call_path_speaks_the_tax_answer_without_one_word_cues(tmp_path):
    # The call's own question («21-ая статья налогового кодекса. Что такое») needs a source (generator.route_need): its answer
    # waits for the lookup this harness does not run. The cutting of the same answer is what is tested, so the question is one that does
    # not need a source.
    spoken = call_cues(tmp_path, 'О чём эта статья?', TAX)
    assert spoken == ['Это статья о правах налогоплательщиков', 'в первой части Налогового кодекса РФ.',
                      'Она перечисляет, например,', 'право получать бесплатную информацию о налогах.']


def test_the_call_path_on_a_new_answer_keeps_phrases_and_sentences_whole(tmp_path):
    answer = ('Закон сохранения энергии утверждает, что энергия замкнутой системы не возникает из ничего и не исчезает. '
              'Она только переходит из одной формы в другую.')
    spoken = call_cues(tmp_path, 'Что утверждает закон сохранения энергии?', answer)
    assert ' '.join(spoken) == ' '.join(answer.split())
    assert all(sentence_count(cue) == 1 and 3 <= len(words(cue)) <= 9 for cue in spoken), spoken
    assert phrase_splits(spoken) == []


def test_an_answer_that_only_restates_the_question_stays_silent_as_before():
    cue, _ = streamed_first_cue('Когда было крещение Руси', 'Крещение Руси.')
    assert cue is None


def test_a_segment_that_stops_mid_clause_releases_what_it_has():
    # the producer's turn is over (``last``) but the text may go on in the next segment: the best cut so far is spoken, never a wait
    text = 'Это статья о правах налогоплательщиков в первой'
    assert first_cue(text, '21-ая статья налогового кодекса. Что такое', CALL_SETTINGS, final=False, last=True) == (
        'Это статья о правах налогоплательщиков')
    assert first_cue(text, '21-ая статья налогового кодекса. Что такое', CALL_SETTINGS, final=False, last=False) is None


# --- a complete reply is cued even when it adds nothing to the question (coordinator's addition to F1 round 2) ---------------------
# A yes/no question asked without «ли» («Вы понимаете…?») is answered in its own words: the verb again («Понимаю.»). The «new
# information» gate only decides how far a first portion is EXTENDED while more text is coming; it never blocks a reply that is over.
SHORT_CUE = {'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2}
YES_NO_REPLIES = [
    ('Вы понимаете, что это важно?', 'Понимаю.'),                        # the coordinator's examples
    ('Вы примете наше предложение?', 'Принимаю.'),
    ('Сообщите?', 'Сообщу.'),
    ('Ты знаешь, где находится вокзал?', 'Знаю.'),                       # new wordings of the same class
    ('Вы придёте завтра на собрание?', 'Приду.'),
    ('Ты согласен с этим планом?', 'Согласен.'),
    ('Вы помните мой номер телефона?', 'Помню, конечно.'),
]


@pytest.mark.parametrize('settings', [CALL_SETTINGS, SHORT_CUE], ids=['meaning', 'short_cue'])
@pytest.mark.parametrize('question,reply', YES_NO_REPLIES)
def test_a_complete_reply_in_the_question_s_own_words_is_cued(question, reply, settings):
    assert first_cue(reply, question, settings, final=True, last=True) == reply
    # the producer's turn is over and the sentence is closed: nothing more follows it either
    assert first_cue(reply, question, settings, final=False, last=True) == reply


@pytest.mark.parametrize('settings', [CALL_SETTINGS, SHORT_CUE], ids=['meaning', 'short_cue'])
@pytest.mark.parametrize('question,reply', [
    ('Что такое инерция?', 'Инерция.'),                                  # a wh-question: the term read back answers nothing
    ('Что такое инерция?', 'Инерцией.'),
    ('Чай или кофе?', 'Чай или кофе.'),                                  # the question read back with its «или» / «ли»
    ('Правда ли, что Земля круглая?', 'Правда ли, что Земля круглая.'),
    ('Вы понимаете, что это важно?', 'Хорошо.'),                         # a filler is no reply
    ('Где находится вокзал?', 'Вокзал находится.'),
])
def test_an_echo_that_is_no_reply_is_still_not_cued(question, reply, settings):
    assert first_cue(reply, question, settings, final=True, last=True) is None


def test_the_gate_still_decides_the_extension_while_more_text_is_coming():
    # the reply is not over: «Понимаю» alone is not cued yet, the text that follows decides
    assert first_cue('Понимаю', 'Вы понимаете, что это важно?', CALL_SETTINGS, final=False, last=False) is None


def test_the_first_cue_keeps_the_symbol_that_ends_the_sentence():
    # «%», «°C», «₽» after the last word belong to the cue: a sentence's first cue never loses its unit (the rest has no word to carry it)
    for text in ('Погрешность измерения не превышает 0,5 %.', 'Вода кипит при 100 °C.', 'Билет стоит 500 ₽.'):
        assert first_cue(text, 'Какая точность', CALL_SETTINGS, final=True, last=True) == text
        if '°C' not in text:                        # «C.» may still be an initial until the text is final
            assert first_cue(text, 'Какая точность', CALL_SETTINGS, final=False, last=True) == text


def test_a_first_sentence_the_phone_handles_itself_is_cued_with_the_next_one():
    # «До свидания.» alone would end the call when the listener repeats it: the plan joins it to the next sentence, so does the cue
    q = 'Как попрощаться вежливо?'
    answer = 'До свидания. Всего доброго вам и удачи.'
    assert portions(answer, CALL_SETTINGS) == [answer]
    assert first_cue(answer, q, CALL_SETTINGS, final=True, last=True) == answer
    assert first_cue('Стоп, стоп. Нажмите на тормоз до упора.', 'Как остановить машину?', CALL_SETTINGS, final=True, last=True) == (
        'Стоп, стоп. Нажмите на тормоз до упора.')
    assert first_cue('До свидания.', q, CALL_SETTINGS, final=True, last=True) is None     # nothing else to say: never spoken


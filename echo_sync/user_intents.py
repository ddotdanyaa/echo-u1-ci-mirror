"""What a listener says besides repeating the portion: closed vocabularies, pure and without morphology.

Everything works on ``norm_words`` output (case-folded, ё -> е, punctuation gone). Each function answers one narrow
question and is deliberately strict: an intent is recognised only when the utterance is *essentially* that intent
(a few words), never because a longer sentence happens to contain one of its words. The classifier decides the order
in which they are asked (``classifier.analyze``).

* ``is_stop``              «стоп», «стоп-стоп», «стоп, пожалуйста», «стой», «хватит», «замолчи», «остановись», «Стой, подожди секунду»
* ``is_repeat_request``    «повтори», «ещё раз пожалуйста», «можно ещё раз», «повтори, я не расслышал», «Скажи-ка последнюю часть заново»
* ``going_on``             «дальше», «Ладно, поехали дальше», «продолжай», «на чём мы остановились», «вернёмся к прошлому вопросу»
* ``return_topic``         the topic of «вернёмся к <тема>» («Ладно, возвращаемся к цунами, где мы там прервались»)
* ``hearing_repair``       «не расслышал», «не понял», «что?», «чего?», «а?», «как?»
* ``clarification_request`` «расскажи подробнее», «объясни проще», «приведи пример», «а подробнее», «а почему»
* ``li_question``          «зависит ли инерция от массы», «правда ли …»
* ``topic_change``         «а теперь про сублимацию», «вернёмся к инерции», «давай всё же про компас», «расскажи про …»
* ``is_small_talk``        «Привет», «Слушай, ты меня хорошо слышишь», «Спасибо, ты молодец»
* ``disagreement``         «это неверно», «нет, это не так», «ты ошибся», «Нет, и это невер но» (+ what is wrong, if said)
* ``is_confirmation_tag``  «да?», «правильно?», «дальше?»: one word asked in the same breath as a repeat (not a question for the cloud)
* ``preamble_ends`` / ``is_preamble`` / ``is_topic_frame``: where a request may start after «Подожди, лучше скажи другое, …»

W1F-C (3 Nov): the commands and intents are small closed GRAMMARS ([lead]* CORE [adjunct]*, clauses), not exact phrase lists, and every
closed vocabulary reads the words through one ASR-robust view (``fold_asr``). Still no fuzzy matching, and a word outside the grammar keeps
the utterance what it is.
"""
from __future__ import annotations

import re

# Hesitation sounds that never carry content (ru_alignment strips the same ones from what was heard).
HESITATION_WORDS = frozenset({
    'э', 'ээ', 'эээ', 'ээээ', 'эм', 'эмм', 'эммм', 'мм', 'ммм', 'мммм', 'хм', 'хмм', 'гм', 'гмм', 'ы', 'ыы', 'э-э', 'э-э-э',
    'м-м', 'м-м-м', 'эм-м', 'а-а', 'у-у'})

_HYPHEN = re.compile('[-‐‑]')


def _parts(words):
    """Words with hyphenated compounds split («стоп-стоп» -> «стоп», «стоп»; «что-что» -> «что», «что»)."""
    return [part for word in words for part in _HYPHEN.split(word) if part]


# -- W1F-C: one ASR-robust view of the words for every closed vocabulary ---------------------------------------------------------------
# GPT-Live transcripts break words at delta boundaries: «Нет, и это невер но», «по вто ри», «треуг ольника» (W1, 3 Nov). Every closed
# vocabulary of this module reads the utterance through ONE view: hyphenated compounds split (``_parts``), then adjacent pieces whose
# concatenation IS a word of the closed lexicon (``_LEXICON``, built at the end of the module from every vocabulary here) folded back into
# that word. The same letters, only the word boundaries differ: no fuzzy match. Pieces that are all lexicon words already stay as they are
# («не так», «нет нет», «еще раз»), and content words have no lexicon here, so they are never touched («осьмин ога» stays).
_FOLD_MAX = 4                                    # pieces of one word


def fold_words(pieces, lexicon):
    """``pieces`` with every run of 2..4 adjacent pieces whose concatenation is a word of ``lexicon`` (and not all of them words of it
    already) replaced by that word; the longest run wins."""
    pieces = list(pieces)
    out, i = [], 0
    while i < len(pieces):
        for j in range(min(len(pieces), i + _FOLD_MAX), i + 1, -1):
            run = pieces[i:j]
            joined = ''.join(run)
            if joined in lexicon and not all(piece in lexicon for piece in run):
                out.append(joined)
                i = j
                break
        else:
            out.append(pieces[i])
            i += 1
    return out


def fold_asr(words):
    """The words of an utterance (``norm_words`` output) as every closed vocabulary here reads them: hyphenated compounds split, the
    recogniser's word boundaries inside a word of a closed vocabulary undone («невер но» -> «неверно», «по вто ри» -> «повтори»)."""
    return fold_words(_parts(words), _LEXICON)


def _phrase_end(parts, i, phrases):
    """The end of the longest phrase of ``phrases`` (tuples of words) that starts at ``parts[i]``, else ``None``."""
    best = None
    for phrase in phrases:
        if tuple(parts[i:i + len(phrase)]) == phrase and (best is None or i + len(phrase) > best):
            best = i + len(phrase)
    return best


# Discourse leads a listener says before a command (the ruling's «так/ладно/окей/ну/хорошо/давай(-ка)/слушай/а», the «-ка» of «давай-ка» /
# «скажи-ка», and the backchannel of «Ага, дальше», «Понятно, повтори», «Спасибо, дальше»).
COMMAND_LEADS = frozenset({'так', 'ладно', 'окей', 'ок', 'ну', 'хорошо', 'давай', 'давайте', 'слушай', 'слушайте', 'а', 'и', 'вот', 'итак',
                           'ка', 'да', 'ага', 'угу', 'понятно', 'ясно', 'отлично', 'спасибо'})


# -- stop -----------------------------------------------------------------------------------------------------------------

# «неважно», «проехали»: the listener drops the question he asked (the answer of it must not sound): the same family, a feature of its own (``stop_kind``).
NEVER_MIND = frozenset({'неважно', 'проехали'})
STOP_WORDS = frozenset({
    'стоп', 'стой', 'стойте', 'остановись', 'остановитесь', 'остановить', 'хватит', 'замолчи', 'замолчите', 'прекрати',
    'прекратите', 'отмена', 'отмени', 'отмените', 'stop', 'cancel', 'помолчи', 'помолчите', 'достаточно', 'довольно'}) | NEVER_MIND
# W1F-C: «Подожди», «Погоди минутку», «Пауза» hold the dictation like «стоп» (CL2 ruling 1: a stop is a pause, the plan is kept).
HOLD_WORDS = frozenset({'подожди', 'подождите', 'погоди', 'погодите', 'постой', 'постойте', 'обожди', 'обождите', 'пауза'})
STOP_CORES = STOP_WORDS | HOLD_WORDS
_STOP_LEADS = COMMAND_LEADS | {'нет', 'тихо'}      # «Нет, подожди», «Нет-нет, хватит», «Тихо, хватит»
# Adjuncts: «(на) (одну) секунду», «(ещё) немного», «пока», «пожалуйста», «-ка», and the words that make a command emphatic. Never a command
# alone: «Секунду», «Пока», «На секунду» are not a stop.
_MOMENTS = ('секунду', 'секундочку', 'секунды', 'минутку', 'минуту', 'минуточку', 'момент')
_A_LITTLE = ('немного', 'немножко', 'чуть')
_EMPHASIS = frozenset({'пожалуйста', 'уже', 'все', 'давай', 'давайте', 'теперь', 'сейчас', 'плиз', 'please', 'ка', 'пока'})
_ADJUNCTS = (tuple((word,) for word in _EMPHASIS) + tuple((word,) for word in _MOMENTS + _A_LITTLE)
             + tuple((lead, word) for lead in ('на', 'одну') for word in _MOMENTS) + tuple(('на', 'одну', word) for word in _MOMENTS)
             + tuple(('еще', word) for word in _A_LITTLE))
_MOST_STOP_CORES = 3                                   # «стоп, стоп, стоп» is a stop; «стоп стоп стоп стоп» is somebody's game


_ENOUGH = (('не', 'надо', 'больше'), ('больше', 'не', 'надо'), ('не', 'важно'))      # «не надо больше», «больше не надо» is «хватит»; the ear's «не важно» is «неважно»


def _enough(parts):
    """``parts`` with each phrase of ``_ENOUGH`` folded to the one word the stop family has for it."""
    out, i = [], 0
    while i < len(parts):
        phrase = next((p for p in _ENOUGH if tuple(parts[i:i + len(p)]) == p), None)
        out.append(('хватит' if phrase != ('не', 'важно') else 'неважно') if phrase else parts[i])
        i += len(phrase) if phrase else 1
    return out


def stop_kind(words, fillers):
    """What the stop is: ``'never_mind'`` («неважно», «проехали»: the question is dropped), ``'hold'`` («подожди», «пауза»: a pause for time), ``'stop'``; ``None`` when the utterance is no stop.
    A feature of the situation: the owner of the kind decides what each does."""
    if not is_stop(words, fillers):
        return None
    cores = {part for part in _enough(fold_asr(words)) if part in STOP_CORES}
    return 'never_mind' if cores & NEVER_MIND else 'hold' if cores <= HOLD_WORDS else 'stop'


def is_stop(words, fillers):
    """The utterance is a stop (or hold) command: [lead]* CORE [adjunct]*, one to three cores (стоп, стой, хватит, замолчи, остановись,
    прекрати, отмена … and подожди, погоди, постой, обожди, пауза), every other word a filler, a lead («так», «ладно», «давай-ка», «нет») or
    an adjunct («на секунду», «минутку», «немного», «пока», «пожалуйста», «уже»). Any other word keeps the utterance what it is: «Подожди, я
    хотел спросить про …» is a correction, «Стоит подождать до вечера» a statement."""
    parts = _enough(fold_asr(words))
    cores, i = 0, 0
    while i < len(parts):
        part = parts[i]
        if part in STOP_CORES:
            cores, i = cores + 1, i + 1
            continue
        end = _phrase_end(parts, i, _ADJUNCTS)
        if end is not None:
            i = end
            continue
        if part in fillers or part in _STOP_LEADS or part in HESITATION_WORDS:
            i += 1
            continue
        return False
    return 1 <= cores <= _MOST_STOP_CORES


# -- repeat requests -----------------------------------------------------------------------------------------------------

_REPEAT_VERBS = frozenset({'повтори', 'повторите', 'повтор', 'повторить'})
# W1F-C: «Скажи заново», «Произнеси ещё раз», «Давай снова»: a verb of saying asks for a repeat only with an «again» word.
_SAY_VERBS = frozenset({'скажи', 'скажите', 'произнеси', 'произнесите'})
_AGAIN = (('еще', 'раз'), ('еще', 'разок'), ('заново',), ('снова',))
_REPEAT_AUX = frozenset({'пожалуйста', 'можно', 'можешь', 'можете', 'давай', 'давайте', 'еще', 'раз', 'разок', 'это', 'я', 'ка', 'мне',
                         'нам'})
_HEARING_VERBS = frozenset({'расслышал', 'расслышала', 'расслышали', 'услышал', 'услышала', 'услышали', 'понял', 'поняла', 'поняли',
                            'уловил', 'уловила', 'уловили', 'разобрал', 'разобрала', 'разобрали'})
# What is to be repeated, when the listener names it: «повтори последнее», «повторите последнюю часть», «повтори последний кусок / фразу»
# (DEF-T-20). It is the portion that waits, whatever word is used for it.
_REPEAT_WHAT = frozenset({'последнее', 'последнюю', 'последний', 'последняя', 'часть', 'кусок', 'кусочек', 'фразу', 'фраза'})
_LONGEST_REPEAT_REQUEST = 8                            # words, fillers aside
# g25 (WAVE20): «громче», «помедленнее», «чётче», «не слышу», «плохо слышно»: the cue was not heard well: the portion again, as for «повтори». The prompter has no louder or slower voice
# of its own: what it can do is say it again. With «говори», «чуть», «немного», «можно» around; never with a word of its own («кто говорит громче»).
_LOUDER = frozenset({'громче', 'погромче', 'медленнее', 'медленней', 'помедленнее', 'помедленней', 'четче', 'почетче', 'отчетливее', 'разборчивее'})
_LOUDER_AUX = frozenset({'говори', 'говорите', 'скажи', 'скажите', 'произноси', 'чуть', 'чуть-чуть', 'немного', 'немножко', 'еще', 'плохо', 'тебя', 'вас'})
_NOT_HEARD = (('плохо', 'слышно'), ('плохо', 'слышу'), ('ничего', 'не', 'слышно'), ('ничего', 'не', 'слышу'), ('не', 'слыхать'))


# g25 (WAVE20): the owner asks for time: «секунду», «сейчас», «минутку», «момент», «дай подумать». No cue into it, no job; the prompter helps when the pause is
# over (controlled_media.TEMPO_PAUSE_SECONDS). After a start of the portion («общие, секунду») it is the same pause, and the help is what is missing. «подожди» stays a stop.
_PAUSE_PHRASES = (('секунду',), ('секундочку',), ('секунда',), ('сек',), ('сейчас',), ('щас',), ('сча',), ('минутку',), ('минуточку',), ('момент',), ('моментик',),
                  ('одну', 'секунду'), ('одну', 'минуту'), ('одну', 'минутку'), ('секунду', 'одну'), ('сейчас', 'скажу'),
                  ('дай', 'подумать'), ('дайте', 'подумать'), ('сейчас', 'соображу'), ('так', 'сейчас'))     # never «вспомн-»: «сейчас сейчас вспомню» is stuck, help at once (H3 rule 4, TEMPO_BLANK)


def pause_split(words, fillers):
    """g25: ``(head, True)`` when the utterance ends in a request for time and nothing else follows it: ``head`` is what was said before it (fillers aside: the start of a portion,
    or nothing), else None. One to three pause phrases in a row («сейчас, сейчас», «секунду, сейчас вспомню»)."""
    parts = [part for part in fold_asr(words) if part not in fillers or part in ('сейчас', 'так', 'секунду')]
    end, count = len(parts), 0
    while end > 0 and count < 3:
        found = next((len(p) for p in sorted(_PAUSE_PHRASES, key=len, reverse=True) if end >= len(p) and tuple(parts[end - len(p):end]) == p), None)
        if found is None:
            break
        end, count = end - found, count + 1
    while end > 0 and parts[end - 1] in COMMAND_LEADS:
        end -= 1
    return (parts[:end], True) if count else None


def is_repeat_request(words, fillers):
    """«повтори», «ещё раз пожалуйста», «можешь повторить», «повтори, я не расслышал», «Скажи-ка последнюю часть заново», «Давай снова»:
    nothing in it but the request - [скажи/произнеси/повтори/давай]? + (ещё раз | ещё разок | заново | снова) + [последнее / последнюю часть
    / фразу / кусок / это]?, or «повтори» itself, with leads, polite words and a hearing reason («я не расслышал», «не уловил») around."""
    parts = [part for part in fold_asr(words) if part not in fillers or part in ('еще', 'раз')]
    if not 1 <= len(parts) <= _LONGEST_REPEAT_REQUEST:
        return False
    anchored, i = False, 0
    while i < len(parts):
        part = parts[i]
        end = _phrase_end(parts, i, _AGAIN) or _phrase_end(parts, i, _NOT_HEARD)
        if end is not None or part in _REPEAT_VERBS or part in _LOUDER:
            anchored, i = True, (end if end is not None else i + 1)
            continue
        if part in _SAY_VERBS or part in _REPEAT_AUX or part in _HEARING_VERBS or part in _REPEAT_WHAT or part in COMMAND_LEADS or part in _LOUDER_AUX:
            i += 1
            continue
        if not anchored and (part in HOLD_WORDS or part in ('стой', 'стойте', 'нет')):     # «Подожди, повтори»; never «Ещё раз нет»
            i += 1
            continue
        if part == 'не' and i + 1 < len(parts) and parts[i + 1] in _HEARING_VERBS:
            i += 1
            continue
        return False
    return anchored


# -- going on: NEXT and RESUME (CL2, ruling 4 + amendment A) -----------------------------------------------------------------
# A standalone utterance, nothing in it but one of the closed forms below (leading fillers, «давай», «хорошо» and a «пожалуйста» aside):
# «продолжай рассказывать про инерцию» or «дальше будет интереснее» stay what they were. A word said in the same breath as a repeat
# («<portion>, дальше?») is a confirmation tag (``is_confirmation_tag``, Task E2), not this. What each form does is the engine's business
# (``engine.going_on``): it depends on whether an answer waits, is paused, or was left unfinished.

RESUME_MAX_WORDS = 6                    # (kept for old imports) the forms are clauses now, bounded by _LONGEST_GOING_ON
_LONGEST_GOING_ON = 16                  # words of an utterance made of going-on clauses only, leads included
NEXT_WORDS = frozenset({'дальше', 'далее', 'следующая', 'следующее', 'следующую', 'следующий', 'следующие', 'следующей', 'следующего'})
_NEXT_WHAT = frozenset({'часть', 'порция', 'порцию', 'фраза', 'фразу', 'кусок'})
# A hold word before a request to go on or to repeat is a lead too: «Подожди, на чём мы остановились?», «Подожди, повтори ещё раз».
_HOLD_LEADS = HOLD_WORDS | {'стой', 'стойте', 'нет'}
_GO_ON_LEAD = COMMAND_LEADS | _HOLD_LEADS | {'пожалуйста', 'напомни', 'напомните', 'теперь'}
_RETURN_VERBS = ('вернемся', 'вернемтесь', 'вернись', 'вернитесь', 'вернуться', 'возвращаемся', 'возвращайся', 'возвращайтесь',
                 'возвратимся')
_RETURN_VERB = r'(?:' + '|'.join(_RETURN_VERBS) + r')(?:\s+(?:все\s+же|все\s+таки|же|тогда|уж))?'
# W1F-C: the forms are CLAUSES. An utterance that is nothing but going-on clauses (leads aside) is one of the kinds below; the provider's
# punctuation is gone (``norm_words``), so the clauses are found by their closed grammar, never by commas. Each pattern is tried at a word
# start and must end at a word end.
_NEXT_CLAUSE = re.compile(
    r'(?:(?:идем|идемте|пошли|поехали|едем|двигаемся|давай|давайте|продолжай|продолжайте|продолжим|говори|говорите|переходим|переходи|'
    r'перейдем)\s+(?:ка\s+)?)?(?:(?:дальше|далее)(?:\s+(?:дальше|далее))?|следующ\w*(?:\s+(?:часть|порция|порцию|фраза|фразу|кусок))?)')
_CONTINUE_CLAUSE = re.compile(
    r'(?:продолжай|продолжайте|продолжи|продолжите|продолжим|продолжаем|доскажи|доскажите|договори|договорите|'
    r'(?:закончи|закончите)\s+(?:свою\s+)?(?:мысль|ответ)|что\s+(?:там\s+)?было\s+дальше)')
# «на чём/где (мы) (там) остановились|прервались|закончили», «что было последним», «с какого места», «что ты последним сказал», and «(продолжай)
# с того места, где (мы) остановились» (w1_01 step 5, cut by the provider after «где»).
_STOPPED = r'(?:остановились|остановился|остановилась|прервались|прервался|прервалась|закончили|закончил|закончила)'
_POSITION_CLAUSE = re.compile(
    r'(?:(?:на\s+чем|где)(?:\s+(?:мы|я|ты|вы))?(?:\s+(?:там|тогда|с\s+тобой|с\s+вами))?\s+' + _STOPPED + r'|'
    r'что\s+(?:там\s+|же\s+)?было\s+(?:последним|последнее)|'
    r'с\s+какого\s+места(?:\s+(?:продолжаем|продолжим|продолжить|начнем|начать))?|'
    r'(?:с|от)\s+того\s+места(?:\s+где(?:\s+(?:мы|я|ты|вы))?(?:\s+там)?(?:\s+' + _STOPPED + r')?)?|'
    r'что\s+(?:ты|вы)\s+(?:там\s+)?(?:последним\s+|последнее\s+)?(?:сказал|сказала|сказали|говорил|говорила|говорили)'
    r'(?:\s+(?:последним|последнее))?)')
_RETURN_CLAUSE = re.compile(
    r'(?:' + _RETURN_VERB + r'\s+(?:к|ко)\s+(?:(?P<which>прошлому|предыдущему|первому|тому)\s+(?:вопросу|ответу)|'
    r'тому\s+(?:что|о\s+чем)\s+(?:ты|вы)\s+(?:говорил|говорила|говорили|рассказывал|рассказывала|рассказывали)(?:\s+(?:раньше|до\s+этого))?|'
    r'(?P<start>тому\s+с\s+чего)(?:\s+(?:мы|ты|вы))?\s+(?:начинали|начали|начинал|начал|начала|начинала))|'
    r'что\s+(?:там\s+)?с\s+(?P<other>прошлым|предыдущим|первым)\s+вопросом|'
    # g29: the bare word and its short forms, the friend's turn is over: «вернись», «вернись назад», «вернись к ответу / к прошлому месту», «вернись к тому что было»
    + _RETURN_VERB + r'(?:\s+(?:назад|обратно)|\s+(?:к|ко|на)\s+(?:(?:прошлому|предыдущему|прошлое|предыдущее|тому)\s+(?:месту|место|ответу|ответ)|'
    r'ответу|месту|тому\s+что\s+было))?)')
# The repeat said after a position question in the same breath: «А что было последним? Скажи ещё раз.»
_REPEAT_CLAUSE = re.compile(
    r'(?:(?:скажи|скажите|повтори|повторите|произнеси|произнесите|давай|давайте)\s+(?:ка\s+)?)*(?:еще\s+(?:раз|разок)|заново|снова)|'
    r'(?:повтори|повторите)(?:\s+ка)?')
# Each clause ends at a word end (the lookahead makes the alternation try «продолжайте» after «продолжай»).
_CLAUSES = tuple((kind, re.compile(r'(?:' + pattern.pattern + r')(?=\s|$)'))
                 for kind, pattern in (('next', _NEXT_CLAUSE), ('continue', _CONTINUE_CLAUSE), ('position', _POSITION_CLAUSE),
                                       ('return', _RETURN_CLAUSE), ('repeat', _REPEAT_CLAUSE)))
# Words of «вернёмся к …» that name no topic of their own.
_NO_TOPIC = frozenset({'вопросу', 'вопрос', 'ответу', 'ответ', 'теме', 'тема', 'тому', 'этому', 'прошлому', 'предыдущему', 'первому',
                       'началу', 'разговору', 'нашему', 'про', 'о', 'об', 'обо', 'насчет'})
_TOPIC_POINTER = re.compile(r'(?:тому|том)\s+(?:что|о\s+чем)\s+(?:ты|вы)\s+(?:говорил|говорила|говорили|рассказывал|рассказывала|рассказывали)'
                            r'(?:\s+(?:раньше|до\s+этого))?(?:\s+|$)')
_LONGEST_TOPIC = 4                       # words of a topic, the words that name nothing left out


def _clause_at(parts, i):
    """``(kind, end, match)`` of the longest going-on clause that starts at ``parts[i]``, else ``None``."""
    text = ' '.join(parts[i:])
    best = None
    for kind, pattern in _CLAUSES:
        found = pattern.match(text)
        if found:
            end = i + len(found.group().split())
            if best is None or end > best[1]:
                best = (kind, end, found)
    return best


def _clauses(parts, fillers, start=0):
    """The going-on clauses ``parts[start:]`` is made of, leads aside (``[(kind, match), …]``), else ``None``. A hold word or «нет» leads
    only the first clause: after one it takes the request back («Дальше нет», «Продолжай, нет, подожди»)."""
    found, i = [], start
    while i < len(parts):
        if found and parts[i] in _HOLD_LEADS:
            return None
        if parts[i] in fillers or parts[i] in HESITATION_WORDS or parts[i] in _GO_ON_LEAD:
            i += 1
            continue
        clause = _clause_at(parts, i)
        if clause is None:
            return None
        kind, i, match = clause
        found.append((kind, match))
    return found


def going_on(words, fillers):
    """What an utterance made of going-on clauses only (leads, «давай», «пожалуйста» aside) asks for, else ``None``:

    * ``'next'``     «дальше», «далее», «следующая (часть)», «давай дальше», «хорошо, дальше», «идём / поехали / пошли / продолжай дальше»;
    * ``'continue'`` «продолжай(те)», «продолжи(те)», «давай продолжим», «доскажи(те)», «договори(те)», «закончи(те) мысль/ответ», «что (там)
      было дальше»;
    * ``'position'`` «на чём (мы) (там) остановились», «где мы прервались», «что было последним», «с какого места», «что ты последним сказал»,
      also with a repeat clause («А что было последним? Скажи ещё раз.»): the waiting portion again (engine.going_on), never a NEXT;
    * ``'return'`` / ``'return_first'`` «вернёмся к прошлому / предыдущему / тому / первому вопросу (ответу)», «вернёмся к тому, что ты говорил
      (раньше)», «вернись к тому, с чего мы начинали», «а что (там) с прошлым / первым вопросом», also with a position or repeat clause.
    A return to a NAMED topic («вернёмся к цунами») is ``return_topic``'s; anything else in the utterance makes it something else."""
    parts = fold_asr(words)
    if not parts or len(parts) > _LONGEST_GOING_ON:
        return None
    clauses = _clauses(parts, fillers)
    if not clauses:
        return None
    kinds = [kind for kind, _ in clauses]
    if all(kind == 'next' for kind in kinds):
        return 'next'
    if kinds == ['continue']:
        return 'continue'
    returns = [match for kind, match in clauses if kind == 'return']
    if len(returns) == 1 and all(kind in ('return', 'position', 'repeat') for kind in kinds):
        found = returns[0]
        first = found.group('start') or (found.group('which') or found.group('other') or '').startswith('перв')
        return 'return_first' if first else 'return'
    if 'position' in kinds and all(kind in ('position', 'repeat', 'continue') for kind in kinds):
        return 'position'                # «Продолжай с того места, где мы прервались» says where: that portion again
    return None


# W1 w1_08 step 4: the provider cut «На чём мы | остановились» into two finals, and the first piece, a question word in a three-word
# utterance, retired the answer that «Вернёмся к цунами» had just restored. The beginning of a position clause asks nothing by itself.
_POSITION_PREFIX = re.compile(r'на\s+чем(?:\s+(?:мы|я|ты|вы))?(?:\s+там)?|где\s+(?:мы|я)\s+там')


def position_prefix(words, fillers=frozenset()):
    """«На чём мы», «На чём мы там», «Где мы там»: only the beginning of a position question (leads aside), cut off by the recogniser."""
    parts = fold_asr(words)
    i = 0
    while i < len(parts) and (parts[i] in fillers or parts[i] in HESITATION_WORDS or parts[i] in _GO_ON_LEAD):
        i += 1
    return i < len(parts) and bool(_POSITION_PREFIX.fullmatch(' '.join(parts[i:])))


def _meta_tail(parts, start):
    """Is ``parts[start:]`` nothing but leads, position clauses and repeat clauses («, где мы там прервались», «. Скажи ещё раз.»)?"""
    clauses = _clauses(parts, frozenset(), start)
    return clauses is not None and all(kind in ('position', 'repeat') for kind, _ in clauses)


_ASKS_SOMETHING = frozenset({'как', 'что', 'почему', 'зачем', 'чем', 'где', 'когда', 'кто', 'какой', 'какая', 'какие', 'какое', 'сколько',
                             'чей', 'откуда', 'куда', 'ли', 'расскажи', 'расскажите', 'объясни', 'объясните', 'скажи', 'скажите', 'покажи',
                             'назови', 'опиши', 'поясни'})


def return_topic(words):
    """The topic words of «вернёмся к <тема>», else ``None``. Ruling 4e: whether that is a return to an unfinished answer is decided against
    the conversation map (engine.going_on).

    W1F-C: the return is a clause. A position or repeat clause after the topic («Ладно, возвращаемся к цунами, где мы там прервались»,
    «Вернёмся к цунами. На чём мы остановились?») is not part of it, nor is the pointer «к тому, что ты говорил про …»; words that name
    nothing («вопросу», «теме», «про») are left out. Anything that asks something new after the topic («…, почему оно такое высокое») makes
    it a question, not a return (``None``), and so does a topic of more than four words. The topic also carries the concatenations of its
    adjacent words, so a word the recogniser cut («Меркур ий») still has its stem."""
    parts = fold_asr(words)
    i = 0
    while i < len(parts) and (parts[i] in HESITATION_WORDS or parts[i] in _GO_ON_LEAD or parts[i] == 'можно'):
        i += 1
    found = re.match(_RETURN_VERB + r'\s+(?:к|ко)\s+', ' '.join(parts[i:]) + ' ')
    if not found:
        return None
    rest = parts[i + len(found.group().split()):]
    pointer = _TOPIC_POINTER.match(' '.join(rest))
    if pointer:
        rest = rest[len(pointer.group().split()):]
    cut = next((k for k in range(1, len(rest)) if _meta_tail(rest, k)), len(rest))
    topic = [word for word in rest[:cut] if word not in _NO_TOPIC]
    if not topic or len(topic) > _LONGEST_TOPIC or any(word in _ASKS_SOMETHING for word in rest[:cut]):
        return None
    return topic + [a + b for a, b in zip(topic, topic[1:])]


# -- «I did not hear»: phrases and interjections ---------------------------------------------------------------------------

HEARING_PHRASES = frozenset({
    'не расслышал', 'не расслышала', 'не расслышали', 'не услышал', 'не услышала', 'не услышали', 'не понял', 'не поняла',
    'не поняли', 'не слышу', 'не слышно', 'плохо слышно', 'не понимаю', 'не разобрал', 'не разобрала', 'что ты сказал',
    'что ты сказала', 'что вы сказали', 'не уловил', 'не уловила', 'не уловили',
    # c7-meta (w3_08): «Непонятно» alone is «не понял» said impersonally - one rule for both, the hearing repair (DEF-T-03: a word named
    # after it, «Непонятно слово X», is the word request, not this phrase; «Мне непонятно» is the frame of a question, E3a: it stays quiet)
    'непонятно', 'не понятно', 'ничего не понятно', 'ничего не понял', 'ничего не поняла'})
INTERJECTIONS = frozenset({'что', 'чего', 'как', 'а', 'ась', 'прости', 'простите', 'извини', 'извините', 'еще', 'что что',
                           'чего чего', 'че', 'чё'})
# Alone, without «?», these are too ambiguous to be taken for a request («а …», «ещё …», an apology).
AMBIGUOUS_WITHOUT_QUESTION_MARK = frozenset({'а', 'еще', 'как', 'прости', 'простите', 'извини', 'извините', 'ась', 'чего', 'чего чего',
                                             'че', 'чё'})
# …while «что» (the first entry of the default clarification list) is a request with or without «?».
CERTAIN_WITHOUT_QUESTION_MARK = frozenset({'что', 'что что'})


def hearing_repair(words, fillers):
    """``(phrase, 'phrase' | 'interjection')`` for «не расслышал», «что-что», «а», «как»; else ``None``.

    The phrase is the whole utterance (leading fillers aside): «не понял что такое налоги» is not one.
    """
    parts = fold_asr(words)
    while len(parts) > 1 and (parts[0] in fillers or parts[0] in HESITATION_WORDS):
        parts = parts[1:]
    if parts and parts[0] == 'я' and len(parts) > 1:
        parts = parts[1:]
    phrase = ' '.join(parts)
    if phrase in HEARING_PHRASES:
        return phrase, 'phrase'
    if phrase in INTERJECTIONS:
        return phrase, 'interjection'
    return None


# -- a new turn ----------------------------------------------------------------------------------------------------------

_ASK_VERBS = frozenset({'объясни', 'объясните', 'расскажи', 'расскажите', 'поясни', 'поясните', 'покажи', 'покажите', 'дай', 'дайте',
                        'приведи', 'приведите', 'скажи', 'скажите', 'можно', 'можешь', 'можете', 'давай', 'давайте', 'хочу'})
_ASK_FILLERS = frozenset({'пожалуйста', 'мне', 'нам', 'это', 'его', 'ее', 'их'})
_TAILS_ALONE = frozenset({'подробнее', 'подробней', 'поподробнее', 'более подробно', 'проще', 'попроще', 'понятнее',
                          'другими словами', 'по другому', 'другой пример', 'еще пример', 'еще один пример', 'иной пример'})
_TAILS_AFTER_A_VERB = _TAILS_ALONE | frozenset({'пример', 'иначе', 'короче', 'покороче', 'еще раз', 'еще', 'коротко', 'понятно',
                                                'на примере', 'с примером', 'с примерами'})
_LATER = frozenset({'потом', 'позже', 'попозже', 'после', 'затем', 'дальше'})     # c23: «подробнее потом» puts the detail off: no new turn
_WHY_AFTER_A = frozenset({'почему', 'зачем', 'как', 'отчего'})


def clarification_request(words, lead=()):
    """«расскажи подробнее», «объясни проще», «приведи пример», «а подробнее», «другой пример», «а почему», «а если наоборот».

    ``words`` are the words after the listener's leading fillers, ``lead`` those fillers («а» matters for «а почему»).
    A bare «пример», «объясни» or «почему» is not enough: those stay stray words.
    """
    parts = fold_asr(words)
    if not parts:
        return False
    if len(parts) >= 2 and parts[0] in ('подробнее', 'подробней', 'поподробнее') and not set(parts[1:]) & _LATER:       # the owner's call of 06.11: «а подробней пятьдесят первый счёт» stayed silent
        return True
    if lead and lead[-1] == 'а':
        if len(parts) == 1 and parts[0] in _WHY_AFTER_A:
            return True
        if parts[0] == 'если' and len(parts) >= 2:
            return True
    i = 0
    while i < len(parts) and parts[i] in _ASK_VERBS:
        i += 1
    verb = i > 0
    while i < len(parts) and parts[i] in _ASK_FILLERS:
        i += 1
    tail = ' '.join(parts[i:])
    return tail in (_TAILS_AFTER_A_VERB if verb else _TAILS_ALONE)


_NOT_A_QUESTION_BEFORE_LI = frozenset({'вряд', 'едва', 'то', 'чуть'})      # «вряд ли», «едва ли», «то ли … то ли»


def li_question(words):
    """«зависит ли инерция от массы»: the particle «ли» right after the first (up to third) word."""
    for i, word in enumerate(words[:4]):
        if word == 'ли' and i >= 1:
            return words[i - 1] not in _NOT_A_QUESTION_BEFORE_LI
    return False


_HOLD_OPENERS = r'(?:нет|подожди|подождите|погоди|погодите|постой|постойте|стой|стойте|обожди|ой|извини|извините|простите)'
_TOPIC_CHANGE = re.compile(
    r'^(?:'
    # W1F-C: the frame takes particles before «про» / «к»: «давай всё же про компас», «давай тогда про погоду», «давай-ка лучше о …»
    r'(?:теперь|давай(?:те)?|лучше)(?:\s+(?:ка|теперь|лучше|все\s+же|все\s+таки|же|тогда|уж|уже))*\s+(?:про|о|об|обо|к|ко|насчет)\s+\S+|'
    r'(?:' + '|'.join(_RETURN_VERBS) + r')(?:\s+(?:все\s+же|все\s+таки|же|тогда|уж))?\s+(?:к|ко)\s+\S+|'
    r'(?:перейдем|переходим|перейди|перейдите|перейти)\s+(?:к|ко)\s+\S+|'
    r'(?:поговорим|поговорить|побеседуем)\s+(?:про|о|об|обо)\s+\S+|'
    r'(?:что|как)\s+насчет\s+\S+|'
    r'(?:расскажи|расскажите|объясни|объясните|скажи|скажите)\s+(?:мне\s+)?(?:про|о|об|обо)\s+\S+|'
    # Root cause F2 (scenario sc03): the spoken reformulation of the question, also before the first cue of a call (no state yet);
    # the object may be cut by the provider right after «про» (the next turn is then merged into the question).
    r'(?:' + _HOLD_OPENERS + r'\s+)*(?:я\s+)?'
    r'(?:(?:хотел|хотела|хотели)\s+(?:спросить|узнать)|хочу\s+спросить)\s+(?:про|о|об|обо|насчет)(?:\s+\S+)?'
    r')')


# The owner's call of 2 Nov 16:09: «Привет, ну что скажешь» was taken for a question and the model's self-introduction («Привет! Я
# помогу с идеями, планами...») was dictated into the ear. A greeting, alone or followed only by small talk, and the connection checks
# start nothing, in any state: the prompter stays quiet and a waiting portion keeps waiting.
# W1F-C (w1_12 steps 3 and 5): small talk is a BAG of closed units, not a fixed sequence. «Слушай, ты меня хорошо слышишь», «Ты меня вообще
# слышишь», «Спасибо, ты молодец», «Спасибо» were taken for a failed repeat (and auto-repeated over the listener). Fillers, intensifiers and
# backchannel are dropped; every other word must belong to a unit: a greeting, a thanks / praise / «понятно», a connection check, a «как
# дела»; «как ты», «что скажешь», «поехали» only next to a greeting; «тут», «на связи» only with «ты» / «вы»; «ты», «меня» only next to
# one of the others. One content word makes it something else («Спасибо, а почему небо голубое?»).
_GREETING_UNITS = (('привет',), ('приветик',), ('приветствую',), ('здравствуй',), ('здравствуйте',), ('здрасьте',), ('добрый', 'день'),
                   ('добрый', 'вечер'), ('доброе', 'утро'), ('доброй', 'ночи'), ('алло',), ('ало',), ('хай',), ('салют',))
_SMALL_TALK_ANCHORS = (('спасибо',), ('спасибочки',), ('благодарю',), ('мерси',), ('молодец',), ('молодчина',), ('умница',), ('отлично',),
                       ('супер',), ('класс',), ('классно',), ('здорово',), ('круто',), ('прекрасно',), ('замечательно',), ('понятно',),
                       ('ясно',), ('слышишь',), ('слышите',), ('слышно',), ('слыхать',), ('проверка', 'связи'), ('раз', 'два'),
                       ('раз', 'два', 'три'), ('как', 'дела'), ('как', 'жизнь'), ('как', 'поживаешь'), ('как', 'поживаете'),
                       ('как', 'настроение'),
                       # c8b (the owner's call of 3 Nov 20:10): the small talk questions that follow a greeting
                       ('что', 'нового'), ('что', 'новенького'), ('как', 'у', 'тебя', 'дела'), ('как', 'у', 'вас', 'дела'),
                       ('как', 'дела', 'у', 'тебя'), ('как', 'дела', 'у', 'вас'), ('как', 'твои', 'дела'), ('как', 'ваши', 'дела'))
_AFTER_A_GREETING = (('как', 'ты'), ('как', 'вы'), ('как', 'сам'), ('как', 'сама'), ('что', 'скажешь'), ('че', 'скажешь'),
                     ('давай', 'начнем'), ('начнем',), ('поехали',), ('ты', 'готов'), ('готов',))
_PRESENCE = (('тут',), ('здесь',), ('на', 'связи'))
# c8b (the owner's call of 3 Nov 20:10: «Да, привет, привет. Ну что, как дела? Что-то слышишь меня» was cued as a question): the opener «ну что»
# / «что, …» («ну» is dropped) and the recogniser's «что-то» for «что, ты …» - only next to a greeting, like the company units: alone,
# «Что?» is a request to hear the portion again and «Что слышно?» stays what it was.
_OPENER = (('что',), ('что', 'то'), ('что-то',), ('че',), ('чо',))
_ADDRESS = (('ты',), ('вы',), ('меня',), ('тебя',), ('вас',), ('мне',), ('тебе',))
# Wave F / F2 fix round 1 (ruling 4): thanks and farewells are small talk too («Спасибо, удачи.», «До свидания», «Хорошего дня»). Kept out of
# the preamble words and the ASR fold lexicon (``_LEXICON``): they change no other grammar.
_FAREWELL_UNITS = (('пока',), ('до', 'свидания'), ('до', 'встречи'), ('до', 'завтра'), ('удачи',), ('всего', 'хорошего'),
                   ('всего', 'доброго'), ('хорошего', 'дня'), ('хорошего', 'вечера'), ('спокойной', 'ночи'), ('счастливо',))
_SMALL_TALK_UNITS = (('greeting', _GREETING_UNITS), ('anchor', _SMALL_TALK_ANCHORS + _FAREWELL_UNITS), ('company', _AFTER_A_GREETING),
                     ('presence', _PRESENCE), ('address', _ADDRESS), ('opener', _OPENER))
_SMALL_TALK_DROP = frozenset({'хорошо', 'нормально', 'вообще', 'сейчас', 'там', 'вот', 'точно', 'теперь', 'уже', 'все', 'большое',
                              'огромное', 'очень', 'да', 'ага', 'угу', 'ну', 'а', 'о', 'эй', 'слушай', 'слушайте'})


def is_small_talk(words, fillers=frozenset()):
    """«Привет», «Привет, ну что скажешь», «Алло, слышишь меня?», «Как дела?», «Слушай, ты меня хорошо слышишь», «Спасибо, ты молодец»: a
    greeting, a connection check, thanks or praise with no content word (fillers, intensifiers and backchannel aside)."""
    core = [w for w in fold_asr(words) if w not in fillers and w not in _SMALL_TALK_DROP and w not in HESITATION_WORDS]
    kinds, i = set(), 0
    while i < len(core):
        best = None
        for kind, units in _SMALL_TALK_UNITS:
            end = _phrase_end(core, i, units)
            if end is not None and (best is None or end > best[1]):
                best = (kind, end)
        if best is None:
            return False
        kinds.add(best[0])
        i = best[1]
    addressed = 'ты' in core or 'вы' in core
    if kinds & {'company', 'opener'} and 'greeting' not in kinds or 'presence' in kinds and not addressed:
        return False
    return bool(kinds & {'greeting', 'anchor'}) or ('presence' in kinds and addressed)


def topic_change(words):
    """«теперь про сублимацию», «вернёмся к инерции», «давай лучше о погоде», «давай всё же про компас», «расскажи про …»: said as a
    statement."""
    return bool(_TOPIC_CHANGE.match(' '.join(fold_asr(words))))


# =====================================================================================================================================
# Task E3a (WAVE 2): what counts as a question. Rulings 1-5 of the coordinator, answering the T-A findings DEF-T-01 .. DEF-T-06.
# Same rules as above: closed vocabularies on ``norm_words`` output, nothing is recognised because a longer sentence happens to contain
# one of the words. The classifier decides when each one is asked (``classifier.analyze``) and what the content words are.
# =====================================================================================================================================

# -- E3a ruling 1 (DEF-T-01): an indirect request is a question ---------------------------------------------------------------------

def _frame(head, connector=None):
    """``'хотелось бы узнать|понять'`` -> the words of the head, each a set of the alternatives; ``connector``: what must come next."""
    return tuple(frozenset(slot.split('|')) for slot in head.split()), (frozenset(connector.split('|')) if connector else None)


_REQUEST_FRAMES = (
    _frame('хочу узнать', 'про|о|об|что|как|почему|зачем'),
    _frame('хотелось бы узнать|разобраться|понять|услышать'),
    _frame('интересно узнать|услышать|понять', 'про|о|об'),
    _frame('было бы здорово понять|узнать'),
    _frame('в двух словах', 'про|о|об'),
    _frame('не понимаю', 'как|почему|зачем|что|чем'),
    _frame('мне непонятно'),
    # The speaker's own need to understand (coordinator ruling at INTEG7): ruling 5 made «нужно» / «надо» statements, and «Мне нужно понять
    # гидравлический удар» went silent. Never a statement about the world: «Нужно остановить платёж по счёту» (no мне / нам) stays one.
    _frame('мне|нам нужно|надо|необходимо|хочется понять|узнать|разобраться|выяснить|уточнить'),
    _frame('мне|нам хотелось бы понять|узнать|разобраться|выяснить|уточнить'),
)
_TERM_IS_A_RIDDLE = ('для', 'меня', 'загадка')
_LONGEST_TERM = 4                  # «<термин> для меня загадка»: a term of at most this many words


def indirect_request(words):
    """«хочу узнать про налоги», «хотелось бы разобраться в …», «инерция для меня загадка»: the words after the request frame, else ``None``.

    The frame itself says nothing: what follows it is returned (the connecting «про» / «как» included; for «<термин> для меня загадка»
    the term) and the classifier asks whether it holds a content word. A frame with nothing after it is no request.
    """
    parts = list(words)
    if parts[:1] == ['я']:
        parts = parts[1:]
    for head, connector in _REQUEST_FRAMES:
        size = len(head)
        if len(parts) > size and all(parts[i] in slot for i, slot in enumerate(head)):
            rest = parts[size:]
            if connector is None or rest[0] in connector:
                return rest
    if tuple(parts[-3:]) == _TERM_IS_A_RIDDLE and 1 <= len(parts) - 3 <= _LONGEST_TERM:
        return parts[:-3]
    return None


# -- E3a ruling 2 (DEF-T-02): a rhetorical or backchannel exclamation is not a question ----------------------------------------------

# The closed list. «Что?», «Как?», «А?», «не расслышал» are in none of these: they keep their meaning (a request to hear the portion again).
_EXCLAMATION_FILLERS = HESITATION_WORDS | frozenset({'ну', 'а', 'о'})
_EXCLAMATIONS = frozenset({
    ('серьезно',), ('правда',), ('неужели',), ('вот', 'как'), ('да', 'ладно'), ('кто', 'бы', 'сомневался'), ('и', 'что', 'с', 'того'),
    ('и', 'что'), ('как', 'так'), ('разве',), ('ого',)})
_EXCLAMATIONS_ALONE = frozenset({('да',), ('точно',)})         # too ambiguous in company: «Да, а почему?», «Точно, сто градусов»
_LONGEST_EXCLAMATION = 4                                      # words, fillers aside


def _only_exclamations(words):
    """Can ``words`` be read as a row of the phrases of the closed list?"""
    if not words:
        return True
    return any(tuple(words[:size]) in _EXCLAMATIONS and _only_exclamations(words[size:]) for size in range(min(4, len(words)), 0, -1))


def is_rhetorical(words):
    """«Серьёзно?», «Да ладно?», «Кто бы сомневался?», «Ну и что с того?», «И что?», «Как так?», «Ого?», «Да?»: at most four words, every one of
    them in the closed list (fillers хм / ну / а / о aside), «?» or not. Nothing else is: a content word, an objection marker («не так»,
    «неверно») or the hearing repairs «что?» / «как?» make the utterance something else."""
    core = [w for w in words if w not in _EXCLAMATION_FILLERS]
    if not 1 <= len(core) <= _LONGEST_EXCLAMATION:
        return False
    return tuple(core) in _EXCLAMATIONS_ALONE or _only_exclamations(core)


# W1F-C (w1_07 step 3): disagreement is a small closed GRAMMAR anchored at the start, not one fixed phrase. «Нет, и это невер но», «Нет же,
# это неверно», «Это вообще неверно», «Я с этим не согласен» were swallowed while the disputed portion kept being repeated.
#   [opener: нет / не / да нет / нет-нет / ну нет]? [particle]{0,2} [subject]? [particle]{0,2} MARKER [what is wrong …]
# The subject decides which markers it takes: «это / вот это / ответ» an impersonal one (неверно, неправильно, неправда, неточно, ошибочно,
# ошибка, не так), «ты / вы» one about the one who answered (ошибся, ошибаешься, не прав), «я (с этим) / с этим» «не согласен». Reported speech
# («Он сказал …», «В тексте написано …») and talk about oneself («Я не прав», «Мне кажется, я ошибся») never start the grammar.
_DISSENT_OPENERS = (('да', 'нет'), ('ну', 'нет'), ('нет', 'нет'), ('нет',), ('не',))
_DISSENT_PARTICLES = (('все', 'таки'), ('по', 'моему'), ('и',), ('же',), ('ну',), ('ведь',), ('вообще',), ('точно',))
_MOST_PARTICLES = 2
_IMPERSONAL_SUBJECTS = (('вот', 'это'), ('это',), ('ответ',))
_YOU = (('ты',), ('вы',))
_I_SUBJECTS = (('я', 'с', 'этим'), ('я', 'с', 'тобой'), ('я', 'с', 'вами'), ('я',), ('с', 'этим'), ('с', 'тобой'), ('с', 'вами'))
# Impersonal markers. One of the one-word ones said with nothing else (no opener, no subject, nothing after it) is not a disagreement with the
# answer: the listener may be talking to himself («Неправильно»). Their split spellings count as the same word («не верно»).
_WRONG_ONE_WORD = (('неверно',), ('неправильно',), ('неправда',), ('неточно',), ('ошибочно',), ('ошибка',), ('неверный',), ('неправильный',),
                   ('не', 'верно'), ('не', 'правильно'), ('не', 'правда'), ('не', 'точно'))
_WRONG_PHRASE = (('не', 'так'),)
# About the one who answered: «ты ошибся», «вы не правы»; the present-tense «ошибаешься» is addressed even said alone.
_YOU_WRONG = (('ошибся',), ('ошиблась',), ('ошиблись',), ('ошибаешься',), ('ошибаетесь',), ('неправ',), ('неправа',), ('неправы',),
              ('не', 'прав'), ('не', 'права'), ('не', 'правы'))
_YOU_WRONG_ALONE = (('ошибаешься',), ('ошибаетесь',))
_I_DISAGREE = (('не', 'согласен'), ('не', 'согласна'), ('не', 'согласны'))


def _particle_ends(parts, i, budget):
    """``[(end, used), …]``: where 0 .. ``budget`` discourse particles that start at ``parts[i]`` end."""
    ends, frontier = [(i, 0)], [(i, 0)]
    while frontier:
        j, used = frontier.pop()
        if used == budget:
            continue
        for particle in _DISSENT_PARTICLES:
            if tuple(parts[j:j + len(particle)]) == particle:
                ends.append((j + len(particle), used + 1))
                frontier.append((j + len(particle), used + 1))
    return ends


def _ends(parts, i, phrases):
    return [i + len(phrase) for phrase in phrases if tuple(parts[i:i + len(phrase)]) == phrase]


def _dissent_marker(parts, i, subject, opened):
    """The end of the disagreement marker at ``parts[i]`` that ``subject`` ('it' / 'you' / 'i' / None) takes, and whether it is a one-word
    impersonal one, else ``None``."""
    if subject in ('it', None):
        for end in _ends(parts, i, _WRONG_PHRASE):
            return end, False
        for end in _ends(parts, i, _WRONG_ONE_WORD):
            return end, True
    if subject == 'you' or (subject is None and opened):
        for end in _ends(parts, i, _YOU_WRONG):
            return end, False
    if subject is None:
        for end in _ends(parts, i, _YOU_WRONG_ALONE):
            return end, False
    if subject in ('i', None):
        for end in _ends(parts, i, _I_DISAGREE):
            return end, False
    return None


def disagreement(bare):
    """``None`` or ``(is_bare, what_is_wrong)`` for «это неверно» / «нет, не так, инерция не сила» / «Нет, и это невер но» / «Я с этим не
    согласен, там 360» (``bare``: the utterance after its leading fillers, normalized words joined by spaces).

    A single impersonal word («неправильно») is not a disagreement with the answer: the listener may be talking to himself.
    """
    parts = fold_asr(str(bare).split())
    for start in [0] + _ends(parts, 0, _DISSENT_OPENERS):
        for after_particles, used in _particle_ends(parts, start, _MOST_PARTICLES):
            subjects = ([(None, after_particles)] + [('it', end) for end in _ends(parts, after_particles, _IMPERSONAL_SUBJECTS)]
                        + [('you', end) for end in _ends(parts, after_particles, _YOU)]
                        + [('i', end) for end in _ends(parts, after_particles, _I_SUBJECTS)])
            for subject, after_subject in subjects:
                for at, _ in _particle_ends(parts, after_subject, _MOST_PARTICLES - used):
                    marker = _dissent_marker(parts, at, subject, start > 0)
                    if marker is None:
                        continue
                    end, one_word = marker
                    rest = ' '.join(parts[end:]) or None
                    if one_word and rest is None and start == 0 and subject is None:
                        continue
                    return rest is None, rest
    return None


# =====================================================================================================================================
# Task E3a-rest (WAVE 2): rulings 3, 4 and 5 of the coordinator, answering the T-A findings DEF-T-04, DEF-T-03 and DEF-T-06.
# Same rules as above (closed vocabularies on ``norm_words`` output; a longer sentence that happens to hold a word is not the intent).
# =====================================================================================================================================

# -- E3a ruling 3 (DEF-T-04): a spoken correction of the topic -------------------------------------------------------------------------

# «Нет, я про причины, а не определение», «Не про определение, а про причины», «Речь идёт о причинах, а не об определении», «Тема сейчас
# причины, а не определение», «Я не об этом, я про причины»: the listener says what the topic is (X) and, usually, what it is not (Y). The
# wrong answer is retired and X is what is asked now. Anchored at the start: «Он сказал нет я про причины» is reported speech.
_ABOUT = r'(?:про|о|об|обо)'
_CORRECTING = r'(?:нет|ой|подожди(?:те)?|постой(?:те)?|секунду|минуту)'          # the same words that open the repairs in the classifier
_OPENING = r'(?:' + _CORRECTING + r'\s+(?:(?:ну|вот|так|э|эм)\s+)*)'
_AND_NOT_Y = r'(?:\s+а\s+не\s+.+)?'
_CORRECTION_FORMS = (
    # «Нет, я про X(, а не (про) Y)»: without the «нет» (or «подождите») «я про X» is just a remark
    re.compile(r'^' + _OPENING + r'+я\s+' + _ABOUT + r'\s+(?P<x>.+?)' + _AND_NOT_Y + r'$'),
    # «Нет, я спрашивал(а) (про|о) X»
    re.compile(r'^' + _OPENING + r'*(?:я\s+)?спрашива(?:л|ла|ли)\s+' + _ABOUT + r'\s+(?P<x>.+?)' + _AND_NOT_Y + r'$'),
    # «Я спросил(а) не про Y, а про X» (and its twins «Я спрашивал не про Y, а про X», «Речь идёт не о Y, а о X»)
    re.compile(r'^' + _OPENING + r'*(?:(?:я\s+)?(?:спросил[аи]?|спрашива(?:л|ла|ли))|речь(?:\s+идет)?)\s+не\s+' + _ABOUT
               + r'\s+.+?\s+а\s+' + _ABOUT + r'\s+(?P<x>.+)$'),
    # «Речь (идёт)? (про|о) X, а не (про|о) Y»
    re.compile(r'^' + _OPENING + r'*речь\s+(?:идет\s+)?' + _ABOUT + r'\s+(?P<x>.+?)\s+а\s+не\s+.+$'),
    # «Не про Y, а про X»
    re.compile(r'^' + _OPENING + r'*не\s+' + _ABOUT + r'\s+.+?\s+а\s+' + _ABOUT + r'\s+(?P<x>.+)$'),
    # «Тема сейчас X, а не Y»
    re.compile(r'^' + _OPENING + r'*тема\s+сейчас\s+(?P<x>.+?)\s+а\s+не\s+.+$'),
    # «Я не об этом, я про X»
    re.compile(r'^' + _OPENING + r'*(?:я\s+)?не\s+(?:об\s+этом|про\s+это|о\s+том)\s+(?:я|а)\s+' + _ABOUT + r'\s+(?P<x>.+)$'),
)
# «Нет, я про то, как работает насос»: the pointer is not part of the request. «Нет, я про то» names nothing.
_POINTS_AT = frozenset({'то', 'том'})
_THEN_ASKS = frozenset({'как', 'что', 'почему', 'зачем', 'чем', 'где', 'когда', 'кто', 'какой', 'какая', 'какие', 'какое', 'сколько', 'чей',
                        'откуда', 'куда'})
# «Нет, я про него не слышал»: after «про» / «о» a personal pronoun points back at something already said and names no new topic.
_POINTS_BACK = frozenset({'него', 'нее', 'них', 'нем', 'ней', 'ним', 'ними', 'нему', 'мне', 'меня', 'тебе', 'тебя', 'нас', 'вас', 'нам',
                          'вам', 'себе', 'себя'})


def corrected_request(words):
    """``(start, stop)``: where in ``words`` the corrected request X stands for «Нет, я про X, а не Y», «Нет, я спрашивал про X», «Я спросил не
    про Y, а про X», «Речь идёт о X, а не о Y», «Не про Y, а про X», «Тема сейчас X, а не Y», «Я не об этом, я про X»; else ``None``.

    The slice is not empty and does not begin with a personal pronoun; whether it holds a content word is for the classifier to say."""
    text = ' '.join(words)
    for form in _CORRECTION_FORMS:
        match = form.match(text)
        if not match:
            continue
        start = text.count(' ', 0, match.start('x'))
        stop = start + match.group('x').count(' ') + 1
        if words[start] in _POINTS_AT:
            if stop - start < 2 or words[start + 1] not in _THEN_ASKS:
                continue
            start += 1
        elif words[start] in _POINTS_BACK:
            continue
        return start, stop
    return None


# -- E3a ruling 4 (DEF-T-03): a word that is not understood -----------------------------------------------------------------------------

# «Не понял это слово», «Непонятно слово X», «Это слово мне незнакомо», «Что это за слово?»: the listener cannot say the word back because he
# does not know it. Not «не понял» alone (that is the hearing repair) and not «Что такое слово?» (a question of its own).
_THIS = r'(?:(?:это|данное)\s+)?'
_UNFAMILIAR = r'(?:не\s?знакомо|не\s?понятно)'
_UNKNOWN_WORD_FORMS = (
    re.compile(r'^(?:я\s+)?не\s+(?:понял[аи]?|понимаю|знаю)\s+(?:это|этого|данное|данного)\s+слов[оа]$'),
    re.compile(r'^(?:мне\s+)?' + _UNFAMILIAR + r'\s+' + _THIS + r'слово(?:\s+(?P<term>.+))?$'),
    re.compile(r'^' + _THIS + r'слово\s+(?:(?P<term>.+?)\s+)?мне\s+' + _UNFAMILIAR + r'$'),
    re.compile(r'^что\s+(?:это\s+)?за\s+слово(?:\s+такое)?$'),
)
_LONGEST_NAMED_TERM = 3                                      # «непонятно слово гидравлический удар»: a term of at most this many words


def unknown_word_request(words):
    """``None`` unless the utterance is a request about a word that is not understood; else ``(start, stop)``: where in ``words`` the word is
    named («Непонятно слово гидравлический» -> the slice of «гидравлический»), ``(0, 0)`` when it is not («Не понял это слово»).

    The slice is at most three words. Whether it holds a content word (and what the word then is) is for the classifier to say."""
    text = ' '.join(words)
    for form in _UNKNOWN_WORD_FORMS:
        match = form.match(text)
        if not match:
            continue
        named = match.groupdict().get('term')
        if not named:
            return 0, 0
        size = named.count(' ') + 1
        if size > _LONGEST_NAMED_TERM:
            continue
        start = text.count(' ', 0, match.start('term'))
        return start, start + size
    return None


# -- E3a ruling 5 (DEF-T-06): a modal word asks only as a request ---------------------------------------------------------------------

# «Нужно остановить платёж по счёту.» / «Повторить опыт можно через неделю.» / «Можно сказать, что он прав.» are statements that merely contain a modal word.
# «верно» / «правда» ask only (a) with a trailing «?» (the classifier's question mark) or (b) with «ли» (``li_question``). The modals of permission and ability
# (можно, можешь, можете, могли бы, мог бы, не могли бы, не мог бы) ask also (c) as a REQUEST: at the start of the utterance (after its fillers), followed by a
# request verb or word; up to ten words (fix round 1: recall beats precision for requests, and live finals often lack «?»). The obligation modals (нужно, надо,
# нужен, нужна, стоит, следует, необходимо) ask as a request only in the narrow frame of fix round 2 (``_obligation_request``).
OBLIGATION_WORDS = frozenset({'нужно', 'надо', 'нужен', 'нужна', 'нужны', 'стоит', 'следует', 'необходимо'})      # «нужны» is mine: «Нужны примеры»
MODAL_WORDS = OBLIGATION_WORDS | frozenset({'можно', 'можешь', 'можете', 'верно', 'правда'})
_REQUEST_MODALS = (('не', 'могли', 'бы'), ('не', 'мог', 'бы'), ('могли', 'бы'), ('мог', 'бы'), ('можно',), ('можешь',), ('можете',))
_REQUEST_VERBS = frozenset({'узнать', 'сказать', 'показать', 'спросить', 'услышать', 'привести', 'назвать', 'объяснить', 'рассказать', 'пояснить', 'уточнить',
                            'повторить', 'подсказать', 'перечислить', 'описать', 'сравнить', 'дать', 'помочь',
                            'задать'})                                   # «задать» and «вопрос» are mine: «Можно задать вопрос», «Можно вопрос» were the recall regression
_REQUEST_WORDS = frozenset({'пример', 'подробнее', 'еще', 'иначе', 'проще', 'короче', 'вопрос'})
_MODAL_POLITE = frozenset({'пожалуйста', 'мне', 'нам', 'это', 'ли', 'вы', 'ты'})      # «можно мне пример», «могли бы вы объяснить» (вы / ты are mine)
# W1F-C (w1_01 step 3, «А можно какой-нибудь пример из жизни»): a determiner of the requested object stands where a polite word may.
_MODAL_POLITE |= frozenset({'какой-нибудь', 'какой-то', 'какую-нибудь', 'какую-то', 'какие-нибудь', 'какие-то', 'один', 'одну', 'другой',
                            'другую', 'хоть', 'хотя', 'бы'})
_LONGEST_MODAL_REQUEST = 10                                                       # words
# «Можешь объяснить, что такое налог» is a request, not «Можно сказать, что он прав»: the «что» of a definition question is the question word (my reading of (b)).
_DEFINITION_WORDS = (['такое'], ['значит'], ['означает'])
# Fix round 2 (coordinator): «Нужно подробнее», «Надо ещё пример», «Стоит уточнить», «Нужен пример», «Надо проще», «Нужно короче» are requests; «Нужно остановить платёж
# по счёту» and «Надо повторить опыт через неделю» are statements. An obligation modal, then - optionally after пожалуйста / бы / ещё - DIRECTLY a request OBJECT word, then at
# most two more words.
_OBLIGATION_OBJECTS = frozenset({'подробнее', 'пример', 'примеры', 'еще', 'иначе', 'проще', 'короче', 'уточнить', 'пояснить', 'объяснить', 'повторить'})
_OBLIGATION_OPTIONAL = frozenset({'пожалуйста', 'бы', 'еще'})
_ONCE_MORE = frozenset({'раз', 'разок', 'один', 'одну', 'одно'})        # «нужно ещё раз», «нужно ещё один пример»
_MOST_WORDS_AFTER_THE_OBJECT = 2


def _modal_frame(words):
    """``('request', i)`` / ``('that', i)`` / ``None``: the utterance starts with a modal of permission or ability and, after the optional polite words, a
    request verb or word (word ``i``). ``'that'``: the verb is followed by «что» (word ``i``): «Можно сказать, что он прав» is a statement."""
    parts = list(words)
    for modal in _REQUEST_MODALS:
        if tuple(parts[:len(modal)]) == modal:
            break
    else:
        return None
    i = len(modal)
    while i < len(parts) and parts[i] in _MODAL_POLITE:
        i += 1
    if i >= len(parts):
        return None
    if parts[i] in _REQUEST_VERBS:
        if parts[i + 1:i + 2] == ['что'] and parts[i + 2:i + 3] not in _DEFINITION_WORDS:
            return 'that', i + 1
        return 'request', i
    if parts[i] in _REQUEST_WORDS:
        return 'request', i
    return None


def _obligation_request(parts):
    """«Нужно подробнее», «Надо ещё пример», «Стоит уточнить», «Нужен пример», «Надо проще», «Нужно короче», «Нужно бы подробнее про налоги»: an obligation modal at the
    start, then - optionally after пожалуйста / бы / ещё - directly a request object word (подробнее, пример, примеры, ещё, иначе, проще, короче, уточнить, пояснить, объяснить,
    повторить), then at most two more words. «Нужно остановить платёж по счёту» (a verb phrase about the world) and «Надо повторить опыт через неделю» (three words after the
    object) are statements.

    «Ещё» is the object itself only when it asks for more or once more (alone, or before an object word, «раз», «один»): «Надо ещё подумать» and «Нужно ещё немного времени»
    are statements (my reading: the two clauses of the ruling meet there)."""
    if not parts or parts[0] not in OBLIGATION_WORDS:
        return False
    for i in range(1, len(parts)):
        word = parts[i]
        if word in _OBLIGATION_OBJECTS and (word != 'еще' or _asks_for_more(parts[i + 1:])):
            return len(parts) - i - 1 <= _MOST_WORDS_AFTER_THE_OBJECT
        if word not in _OBLIGATION_OPTIONAL:
            return False
    return False


def _asks_for_more(after):
    return not after or after[0] in _OBLIGATION_OBJECTS or after[0] in _ONCE_MORE


def modal_request(words):
    """«можно узнать про налоги», «можешь сказать цену», «можешь показать пример», «не могли бы вы повторить», «можно вопрос»: the utterance (after its leading
    fillers) starts with можно / можешь / можете / могли бы / мог бы / не могли бы / не мог бы, then, after the optional пожалуйста / мне / нам / это / ли /
    вы / ты, a request verb (узнать, сказать, показать, спросить, услышать, привести, назвать, объяснить, рассказать, пояснить, уточнить, повторить,
    подсказать, перечислить, описать, сравнить, дать, помочь, задать) or word (пример, подробнее, ещё, иначе, проще, короче, вопрос); at most ten words.

    A verb followed by «что» («Можно сказать, что он прав») makes a statement. The obligation modals ask as a request only in the narrow frame of ``_obligation_request``
    («Нужно подробнее», «Надо ещё пример», «Стоит уточнить», «Нужен пример»)."""
    parts = list(words)
    frame = _modal_frame(parts)
    if frame is not None:
        return frame[0] == 'request' and 2 <= len(parts) <= _LONGEST_MODAL_REQUEST
    return _obligation_request(parts)


def modal_that_index(words):
    """The index of the «что» in «Можно сказать, что он прав» / «Можешь сказать что угодно» (a request modal, a request verb, «что»): that «что» is the
    conjunction, not a question word; ``None`` for anything else. The statement has no bound of length."""
    frame = _modal_frame(words)
    return frame[1] if frame is not None and frame[0] == 'that' else None


# -- a tag question said in the same breath as a repeat ---------------------------------------------------------------------------

# «Вода кипит при ста градусах, да?»: the listener has repeated the portion and asks the prompter whether that was right, or whether to go on.
# That is the confirmation again, not a question for the cloud (Task E2, ruling 1). ONE word, a closed list; «всё» is «все» once ё is folded.
CONFIRMATION_TAGS = frozenset({'да', 'правильно', 'верно', 'точно', 'понял', 'ага', 'угу', 'так', 'нормально', 'все', 'дальше', 'следующее'})


def is_confirmation_tag(words, fillers):
    """«да?», «правильно?», «верно?», «точно?», «понял?», «ага?», «угу?», «так?», «нормально?», «всё?», «дальше?», «следующее?»: nothing in
    the utterance but one of these words, optionally after leading fillers («а дальше?», «и всё?»). Two words («да ведь?», «это всё?») and any
    other word («почему?») are not a tag: they ask something."""
    parts = fold_asr(words)
    while len(parts) > 1 and (parts[0] in fillers or parts[0] in HESITATION_WORDS):
        parts = parts[1:]
    return len(parts) == 1 and parts[0] in CONFIRMATION_TAGS


# =====================================================================================================================================
# W1F-C: a request at the start of ANY clause after a discourse preamble (W1: w1_09 steps 2 and 5, w1_08 step 6)
# =====================================================================================================================================
# «Подожди, лучше скажи другое, сколько рук у осьминога», «Ладно, давай всё же про компас, куда показывает его стрелка», «А про гитару ещё
# раз, сколько там струн»: the question word stood after the first three words and the request was taken for a failed repeat. A request may
# start a later clause when everything before it is a discourse PREAMBLE, a closed class: the hold and discourse words (подожди, стой,
# ладно, слушай, окей, лучше, а теперь, давай (всё же | тогда | лучше), нет, кстати, the backchannel and the small-talk words), the
# phrases «скажи другое», «другой / ещё (один) вопрос», «у меня (ещё | другой) вопрос», and the TOPIC FRAME clause «(а) (теперь | давай |
# лучше) (же | всё же | тогда | уж) про / о / насчёт <at most three words> (ещё раз)». Whether the rest IS a request is the classifier's
# question (``classifier._trigger`` on it). Bystander speech has no preamble («Мы вчера ходили в кино, там было шумно»), and a frame whose
# words report speech («А про Машу говорили, что …») is no frame.
_PREAMBLE_WORDS = (HOLD_WORDS | COMMAND_LEADS | {'стой', 'стойте', 'лучше', 'теперь', 'кстати', 'нет', 'же', 'тогда', 'уж', 'все', 'таки',
                                                  'пожалуйста'}
                   | {unit[0] for unit in _GREETING_UNITS + _SMALL_TALK_ANCHORS if len(unit) == 1})
_PREAMBLE_PHRASES = (('скажи', 'другое'), ('скажите', 'другое'), ('другой', 'вопрос'), ('еще', 'вопрос'), ('еще', 'один', 'вопрос'),
                     ('у', 'меня', 'вопрос'), ('у', 'меня', 'еще', 'вопрос'), ('у', 'меня', 'другой', 'вопрос'), ('все', 'таки'))
_PREAMBLE_PHRASES += tuple(unit for unit in _GREETING_UNITS if len(unit) > 1)
_TOPIC_FRAME = re.compile(r'^(?:(?:а|и|ну|так|ладно|теперь|давай|давайте|ка|лучше|еще|же|все|таки|тогда|уж)\s+)*(?:про|о|об|обо|насчет)\s+'
                          r'(?P<np>\S+(?:\s+\S+){0,2}?)(?:\s+еще\s+(?:раз|разок))?$')
_REPORTING = frozenset({'говорил', 'говорила', 'говорили', 'говорит', 'говорят', 'сказал', 'сказала', 'сказали', 'писал', 'писала',
                        'писали', 'пишет', 'пишут', 'читал', 'читала', 'читали', 'слышал', 'слышала', 'слышали', 'рассказывал',
                        'рассказывала', 'рассказывали', 'рассказывают', 'спорили', 'думал', 'думала', 'думали', 'знал', 'знала'})


def _preamble_scan(words):
    """Every word count at which the discourse preamble that opens ``words`` may end (in order). A word the recogniser cut in two
    («подо жди») and a hyphenated compound of preamble words («давай-ка», «нет-нет») count as one."""
    ends, i = [], 0
    while i < len(words):
        parts = _parts([words[i]])
        if parts and all(part in _PREAMBLE_WORDS or part in HESITATION_WORDS for part in parts):
            i += 1
        else:
            end = _phrase_end(words, i, _PREAMBLE_PHRASES)
            if end is None:
                end = next((j for j in range(min(len(words), i + _FOLD_MAX), i + 1, -1) if ''.join(words[i:j]) in _PREAMBLE_WORDS), None)
            if end is None:
                break
            i = end
        ends.append(i)
    return ends


def preamble_ends(words):
    """The word counts after which a request may start in ``words`` (``norm_words`` output), the longest preamble first: every point
    inside the discourse preamble that opens the utterance, never its end. ``[]`` when it opens with no preamble."""
    return [end for end in reversed(_preamble_scan(words)) if end < len(words)]


def is_preamble(words):
    """Is the clause ``words`` nothing but a discourse preamble («Подожди», «Лучше скажи другое», «Кстати»)?"""
    return bool(words) and len(words) in _preamble_scan(words)


def is_topic_frame(words):
    """Is the clause ``words`` a topic frame: «(а) (теперь | давай | лучше) (же | всё же | тогда | уж) про / о / насчёт <at most three words>
    (ещё раз)» («А про гитару ещё раз», «Давай всё же про компас»)? Not when a word of it reports speech or asks («про Машу говорили»)."""
    found = _TOPIC_FRAME.match(' '.join(fold_asr(words)))
    return bool(found) and not any(word in _REPORTING or word in _ASKS_SOMETHING for word in found.group('np').split())


# -- the closed lexicon of the ASR view (fold_asr) ------------------------------------------------------------------------------------
def _vocabulary_words(*vocabularies):
    words = set()
    for vocabulary in vocabularies:
        for entry in vocabulary:
            words.update(entry if isinstance(entry, tuple) else str(entry).split())
    return words


def _pattern_words(*patterns):
    return {word for pattern in patterns for word in re.findall(r'[а-я]{2,}', pattern.pattern)}


_LEXICON = frozenset(
    _vocabulary_words(STOP_CORES, _STOP_LEADS, _EMPHASIS, _ADJUNCTS, _REPEAT_VERBS, _SAY_VERBS, _AGAIN, _LOUDER, _NOT_HEARD, _PAUSE_PHRASES, _REPEAT_AUX, _HEARING_VERBS,
                      _REPEAT_WHAT, NEXT_WORDS, _NEXT_WHAT, _GO_ON_LEAD, _RETURN_VERBS, HEARING_PHRASES, INTERJECTIONS, _ASK_VERBS,
                      _TAILS_AFTER_A_VERB, _WHY_AFTER_A, _GREETING_UNITS, _SMALL_TALK_ANCHORS, _AFTER_A_GREETING, _PRESENCE, _ADDRESS,
                      _SMALL_TALK_DROP, _DISSENT_OPENERS, _DISSENT_PARTICLES, _IMPERSONAL_SUBJECTS, _YOU, _I_SUBJECTS, _WRONG_ONE_WORD,
                      _WRONG_PHRASE, _YOU_WRONG, _I_DISAGREE, CONFIRMATION_TAGS, _PREAMBLE_WORDS, _PREAMBLE_PHRASES)
    | _pattern_words(_NEXT_CLAUSE, _CONTINUE_CLAUSE, _POSITION_CLAUSE, _RETURN_CLAUSE, _REPEAT_CLAUSE, _TOPIC_CHANGE))


# =====================================================================================================================================
# Wave F (F2, 3 Nov): the owner's REAL call 09:55 - topic phrases and indirect questions got silence, remarks to the prompter got answers.
# Closed vocabularies only (kept out of the ASR fold lexicon above: they change no other grammar). The morphology - part of speech, case,
# person, lemma (pymorphy3) - is the classifier's (``classifier`` block «Wave F»).
# =====================================================================================================================================

# -- rule 1: what may stand before a topic phrase («ну хоть девятая статья налогового кодекса», «Так, значит, смысл плановой экономики») ---
TOPIC_LEADS = frozenset({'ну', 'хоть', 'хотя', 'бы', 'а', 'и', 'но', 'тогда', 'так', 'вот', 'значит', 'короче', 'типа', 'ладно', 'кстати',
                         'просто', 'давай', 'давайте', 'еще', 'же', 'вообще', 'теперь', 'например', 'итак', 'окей', 'ок',
                         # c7-meta (w3_14): «Допустим, Транссибирская магистраль» - a supposing lead, like «например»
                         'допустим', 'предположим', 'скажем'})
# «Вопрос получается …», «Вопрос такой: …», «Новый вопрос: …»: the explicit question marker; the words after it are the question.
QUESTION_MARKER = re.compile(r'(?:(?:новый|следующий|другой)\s+)?вопрос(?:\s+(?:получается|такой|следующий))?')
# Nouns of the dialogue itself: «Хороший вопрос», «Ответ на вопрос», «Речь про причины» name no topic of their own.
DIALOGUE_NOUNS = frozenset({'вопрос', 'ответ', 'речь', 'тема', 'разговор'})
TOPIC_MAX_WORDS = 8


def question_marker_end(words, start=0):
    """The word count after the explicit question marker that starts at ``words[start]`` («вопрос получается», «новый вопрос»), else
    ``None``."""
    for size in (3, 2, 1):
        if start + size <= len(words) and QUESTION_MARKER.fullmatch(' '.join(words[start:start + size])):
            return start + size
    return None


# -- rule 3: an indirect question inside a request or a complaint --------------------------------------------------------------------
# «(тебе нужно | надо | можешь | обязательно) сказать / объяснить / рассказать / назвать, что такое X / когда … / в чём …», «Объясни, почему …»,
# «Мне нужно, чтобы ты объяснил, что значит …», «Скажи вот что: какая …»: the embedded question is what is asked.
_SAY_IMPERATIVES = frozenset({'скажи', 'скажите', 'объясни', 'объясните', 'расскажи', 'расскажите', 'назови', 'назовите', 'поясни',
                              'поясните', 'подскажи', 'подскажите', 'уточни', 'уточните', 'ответь', 'ответьте'})
_SAY_INFINITIVES = frozenset({'сказать', 'объяснить', 'рассказать', 'назвать', 'пояснить', 'подсказать', 'уточнить', 'ответить'})
_SAY_PAST = frozenset({'сказал', 'сказала', 'сказали', 'объяснил', 'объяснила', 'объяснили', 'рассказал', 'рассказала', 'рассказали',
                       'назвал', 'назвала', 'назвали', 'пояснил', 'пояснила', 'пояснили', 'подсказал', 'подсказала', 'подсказали',
                       'ответил', 'ответила', 'ответили'})
# What makes an infinitive of saying a request (within the four words before it): obligation, ability, a wish, «обязательно», «попробуй».
_ASKING_FOR_IT = frozenset({'нужно', 'надо', 'необходимо', 'можно', 'можешь', 'можете', 'мог', 'могла', 'могли', 'должен', 'должна',
                            'должны', 'обязательно', 'хочу', 'хотелось', 'попробуй', 'попробуйте', 'постарайся', 'прошу', 'срочно'})
_EMBED_SKIP = frozenset({'мне', 'нам', 'пожалуйста', 'хотя', 'бы', 'хоть', 'уже', 'наконец', 'же', 'тогда', 'просто', 'все', 'таки',
                         'сейчас', 'кратко', 'коротко', 'честно', 'следующее'})
_EMBED_WORDS = frozenset({'когда', 'где', 'куда', 'откуда', 'почему', 'зачем', 'отчего', 'как', 'сколько', 'кто', 'кого', 'кому', 'кем',
                          'чей', 'чья', 'чье', 'чьи', 'какой', 'какая', 'какое', 'какие', 'какого', 'какую', 'каким', 'каком', 'каких',
                          'какими', 'какому', 'каков', 'какова', 'каково', 'каковы', 'чем'})
_DEFINES = frozenset({'такое', 'значит', 'означает'})
_ON_WHAT = frozenset({'в', 'во', 'о', 'об', 'на', 'за', 'из', 'от', 'с', 'со'})


def _embedded_start(words, j):
    """``(start, announced)``: where the embedded question starts at or after ``words[j]`` (after the optional «мне», «пожалуйста» …), and
    whether «вот что» / «следующее» announced it; ``None`` when no question word starts there."""
    n, announced = len(words), False
    while j < n:
        if words[j] in _EMBED_SKIP:
            announced = announced or words[j] == 'следующее'
            j += 1
        elif words[j:j + 2] == ['вот', 'что']:
            j, announced = j + 2, True
        else:
            break
    if j >= n:
        return None
    if words[j] == 'что':
        # «что такое X», «что значит X», «что это такое»; any other «что» after a verb of saying is the conjunction («сказать, что он прав»)
        defines = words[j + 1:j + 2] and (words[j + 1] in _DEFINES or words[j + 1:j + 3] == ['это', 'такое'])
        return (j, announced) if defines else None
    if words[j] in _ON_WHAT and words[j + 1:j + 2] and (words[j + 1] in _EMBED_WORDS or words[j + 1] in ('что', 'чему', 'ком')):
        return j, announced                                       # «в чём смысл …», «на что влияет …», «в каком году …»
    return (j, announced) if words[j] in _EMBED_WORDS else None


def indirect_question(words):
    """``(start, frame)``: where in ``words`` (``norm_words`` output) the question embedded in a request starts, and the frame that asks
    for it - ``'asked'``: an infinitive of saying that is asked for («тебе нужно обязательно сказать, что такое …», «можешь рассказать, кто
    …»), the past after «чтобы» («мне нужно, чтобы ты объяснил, что значит …») or a question announced by «вот что» / «следующее» («Скажи
    вот что: какая …»); ``'imperative'``: «Объясни, почему …» - then a question word. ``None`` when there is none. Whether what follows
    names anything is the classifier's question."""
    words = list(words)
    for i, word in enumerate(words):
        if word in _SAY_IMPERATIVES:
            frame = 'imperative'
        elif ((word in _SAY_INFINITIVES and any(w in _ASKING_FOR_IT for w in words[max(0, i - 4):i]))
              or (word in _SAY_PAST and 'чтобы' in words[max(0, i - 3):i])):
            frame = 'asked'
        else:
            continue
        found = _embedded_start(words, i + 1)
        if found is not None:
            return found[0], 'asked' if found[1] else frame
    return None


# -- rule 4: the prompter's own work ---------------------------------------------------------------------------------------------------
# Lemmas (pymorphy3 gives the lemma of every form). Its misbehaviour is a remark even unaddressed («Зачем вот это вот всё тянуть надо было»);
# its speaking is a remark when the clause addresses the prompter («ты должен был первым ответом мне это сказать»).
PROMPTER_MISBEHAVIOUR = frozenset({'тянуть', 'молчать', 'замолчать', 'тупить', 'затупить', 'сломаться', 'издеваться', 'тормозить',
                                   'зависнуть', 'суфлировать',
                                   # c7-meta (live run 20261103-164741, w3_14): its stalls in the listener's words - «что ты замираешь»,
                                   # «ты что, глючишь»
                                   'замирать', 'замереть', 'глючить', 'заглючить', 'зависать', 'лагать', 'медлить', 'тормознуть'})
PROMPTER_SPEECH = PROMPTER_MISBEHAVIOUR | frozenset({'отвечать', 'ответить', 'сказать', 'говорить', 'подсказывать', 'подсказать',
                                                     'настроить', 'настраивать'})
# «Повтори», «Что ты сказал?»: a request to hear the answer again, never a remark on the work.
REPEAT_VERBS = _REPEAT_VERBS


# -- fix round 1 (the coordinator's review, 3 Nov) -----------------------------------------------------------------------------------
# Ruling 3: the nouns of the prompter's own work name nothing a remark could be about («по одному слову», «первым ответом», «в итоге»).
PROMPTER_WORK_NOUNS = frozenset({'слово', 'ответ', 'раз', 'итог', 'пауза'})
# c7-meta round 2 (W4, oral exam): the aspects an exam ticket lists after its topic («Лизинг. Определение, виды лизинга.», «Факторинг:
# определение, виды»); lemmas (ё as е).
TICKET_ASPECTS = frozenset({'определение', 'понятие', 'сущность', 'суть', 'вид', 'тип', 'форма', 'классификация', 'функция', 'роль',
                            'значение', 'порядок', 'учет', 'оценка', 'признак', 'принцип', 'цель', 'задача', 'метод', 'способ',
                            'особенность', 'структура', 'состав', 'источник', 'характеристика', 'отличие', 'пример', 'назначение',
                            'преимущество', 'недостаток', 'правило', 'условие', 'этап', 'механизм', 'история', 'элемент', 'содержание',
                            'показатель'})
TICKET_MAX_WORDS = 14
# A «move on» line of an examiner («Хорошо. Давайте следующий билет.», «Следующий вопрос.», «Дальше по билету.»): a word of going on, a noun
# of the exam's units, and nothing else but these leads (lemmas). With content after it («Следующий вопрос: лизинг») it is the marker.
MOVE_ON_NEXT = frozenset({'следующий', 'дальше', 'далее', 'другой', 'новый'})
MOVE_ON_UNITS = frozenset({'билет', 'вопрос', 'тема', 'задание', 'пункт'})
MOVE_ON_LEADS = frozenset({'хорошо', 'ладно', 'так', 'ну', 'а', 'и', 'теперь', 'тогда', 'итак', 'окей', 'ок', 'спасибо', 'понятно', 'ясно',
                           'отлично', 'пожалуйста', 'давать', 'переходить', 'перейти', 'идти', 'пойти', 'к', 'по', 'на', 'вот', 'все',
                           'весь', 'уже'})
# c7-meta: a span of time after a determiner of totality is an adverbial («всё время», «каждый раз», «целый день»): it names nothing.
SPAN_NOUNS = frozenset({'время', 'раз', 'день', 'час', 'минута', 'секунда', 'вечер'})
TOTALITY_DETERMINERS = frozenset({'весь', 'каждый', 'целый'})
# Ruling 4: what heads no topic. Interjection-like nouns («Удачи», «Красота», «Тишина в классе»), the evaluations that are the only modifier of
# their noun («Хорошая работа», «Интересная мысль»), the hold words («Секунду», «Одну минуту», «Момент»). Lemmas.
INTERJECTION_HEADS = frozenset({'удача', 'красота', 'кошмар', 'ужас', 'жесть', 'тишина', 'капец', 'бред', 'ерунда', 'чушь', 'жуть'})
EVALUATIVE_ADJECTIVES = frozenset({'хороший', 'отличный', 'интересный', 'прекрасный', 'плохой', 'замечательный', 'классный', 'ужасный',
                                   'странный', 'неплохой', 'великолепный', 'чудесный', 'красивый', 'нормальный', 'крутой', 'шикарный',
                                   'потрясающий', 'отвратительный', 'полный'})
HOLD_NOUNS = frozenset({'секунда', 'секундочка', 'минута', 'минутка', 'минуточка', 'момент'})
# Alone, the captions a recogniser writes for a sound («Музыка», «Аплодисменты», «Смех», «Шум»): no term (with a complement they are one).
SOUND_CAPTIONS = frozenset({'музыка', 'аплодисменты', 'смех', 'шум'})
_THANKS = (('спасибо',), ('спасибочки',), ('благодарю',), ('мерси',))


def courtesy(words):
    """Is there a greeting, a thanks or a farewell in ``words`` (``norm_words`` output)? A noun phrase next to one is a vocative
    («Здравствуйте, Мария Ивановна», «Спасибо, удачи.»), not a topic."""
    parts = fold_asr(words)
    units = _GREETING_UNITS + _THANKS + _FAREWELL_UNITS
    return any(_phrase_end(parts, i, units) is not None for i in range(len(parts)))


# Ruling 5: the explicit marker in its marker form («Вопрос получается …», «Вопрос такой: …», «Вопрос: …», «Вопрос — …», «Новый / следующий /
# другой / ещё (один) вопрос …»), at the start of a text (after its fillers); the end of the match is where the question begins.
MARKER_FORM = re.compile(r'^(?:(?:нов\w*|следующ\w*|друг\w*|ещ[её](?:\s+один)?)\s+вопрос\b[\s:—–,-]*|'
                         # c7-meta round 2: «Следующий билет: факторинг, определение, виды.», «Новая тема — лизинг»
                         r'(?:нов\w*|следующ\w*|друг\w*)\s+(?:билет\w*|тем[аеуы])\b[\s:—–,-]*|'
                         r'вопрос(?:\s*[:—–]\s*|\s+-\s+|[\s,]+(?:получается|такой|следующий)\b[\s:—–,-]*))', re.I)

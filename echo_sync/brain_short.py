"""W9-brain (N117, N118): a shorter BRAIN and a shorter history for the text job, as a pure module beside ``fast_text`` (A2 owns that file; the wiring is a patch in the report).
Nothing here is sent anywhere by itself and the default stays the long text (the setting ``brain_short`` chooses). The cloud has no
model, so «faster first token» is a count of input characters, not a time; the measurement of TTFT is the laptop's. Every rule the long BRAIN carries is a row of ``KEEP``: a
needle that a variant must contain, so that shortening cannot silently drop the dash, a command mark, the doubt rule or the first-words rule."""
import re

from . import fast_text as FT
from .content_policy import MATERIAL_HOW, excerpt_of
from .material_pick import MaterialPicker

BRAIN_SHORT = ('Ты суфлёр: человек вслух произносит твой ответ по частям. Тебе дают то, что прозвучало в комнате.\n'
               'Если там есть вопрос или задание, ответь только на него; знака вопроса может не быть: «пять на пять», «17-я статья». Вводные слова, сомнения, жалобы и слова о тебе пропусти.\n'
               'Если вопроса нет, выведи ровно один символ: —. Это знак «вопроса нет», а не «не знаю»: на любой вопрос отвечай самым надёжным, что знаешь. Вопроса нет, когда это приветствие, '
               'разговор ни о чём, мысли вслух, замечание о тебе или о репетиции, просьба задавать вопросы, согласие или короткая реакция.\n'
               'Первые слова и есть ответ: число, имя, да или нет; объяснение после них. Факт: одна фраза. Определение или объяснение: две-три короткие фразы, первая годится как ответ сама по себе. '
               'Числа и номера статей цифрами. Без обращений, вопросов, предложений помочь, слов о себе и оговорок «по памяти». Дату, сумму или ставку, которых не знаешь точно, не называй.\n'
               'Если спрашивают, уверен ли ты, или спорят с ответом: проверь заново и обязательно ответь; верный повтори, неверный исправь. Строка «Сейчас прозвучало» с сомнением или спором: символ — запрещён.\n'
               'Просьба к подсказке — только метка: [стоп] (остановись, подожди), [продолжай] (продолжи с места, вернись к ответу, где остановились), [повтори] (не расслышал), [дальше] (следующая часть).\n'
               'Запись «Распознано: А / Б» — две записи одной реплики, в одной могли пропасть слова: собери сказанное и суди по этому.')
SHORT_POLICY = BRAIN_SHORT + '\n' + FT.BRAIN_KEEP
# What shortening must not lose: (name, needle) for the short text. The long BRAIN has them all (``test_every_rule_is_in_the_long_brain``).
KEEP = (('role', 'Ты суфлёр'), ('dash', 'выведи ровно один символ: —'), ('dash_is_not_idk', 'а не «не знаю»'), ('no_question_cases', 'приветствие'), ('no_question_react', 'короткая реакция'),
        ('first_words', 'Первые слова'), ('yes_no', 'да или нет'), ('fact_one', 'Факт: одна фраза'), ('explain', 'две-три короткие фразы'), ('first_alone', 'первая годится как ответ сама по себе'),
        ('digits', 'цифрами'), ('no_hedge', 'по памяти'), ('no_guess', 'не называй'), ('doubt', 'уверен ли ты'), ('doubt_answer', 'обязательно ответь'), ('doubt_line', 'Сейчас прозвучало'),
        ('doubt_no_dash', 'символ — запрещён'), ('stop', '[стоп]'), ('continue', '[продолжай]'), ('repeat', '[повтори]'), ('next', '[дальше]'), ('two_records', 'Распознано: А / Б'),
        ('lost_words', 'пропасть'))
# The long BRAIN's lines that tests/ assert by substring (file:line, needle). A variant that replaces the long text breaks these tests unless they read the variant: the table of what can break.
BREAKABLE = (('test_h2_brain.py:67', 'выведи ровно один символ: —'), ('test_h5_live.py:324', 'Это знак «вопроса нет», а не «не знаю»'), ('test_h5_live.py:327', 'На вопрос, требующий да или нет, начинай ответ со слова да или нет.'),
             ('test_h5_live.py:328', 'Первые слова ответа'), ('test_h6.py:447', 'Распознано: А / Б'), ('test_h6.py:447b', 'одной реплики'), ('test_h6.py:1143', 'сомнение или спор'),
             ('test_h7.py:251', 'На вопрос о факте'), ('test_h7.py:251b', 'определение или объяснение'), ('test_h7.py:252', 'первая фраза сама по себе годится как ответ'), ('test_h7.py:253', 'две-три короткие фразы'))
HISTORY_SHORT_EXCHANGES = 3
HISTORY_SHORT_CHARS = 200


def short_history(rows, *, played=None, limit=HISTORY_SHORT_EXCHANGES, chars=HISTORY_SHORT_CHARS):
    """The same rows ``build_request`` reads, fewer and cut to ``chars`` at a word; the exchange in play is not among them, a revised one keeps its mark."""
    rows = [r for r in rows or () if isinstance(r, dict)]
    if played:
        rows = [r for r in rows if (str(r.get('question') or ''), str(r.get('answer') or '')) != tuple(played)]
    return [{**r, 'question': _cut(r.get('question'), chars), 'answer': _cut(r.get('answer'), chars)} for r in rows[-limit:]]


def _cut(text, chars):
    text = str(text or '').strip()
    if len(text) <= chars:
        return text
    head = text[:chars]
    return (head.rsplit(' ', maxsplit=1)[0] if ' ' in head[chars // 2:] else head).rstrip(' ,;:')


def build_request(question, *, instructions=None, history=(), material='', played=None, also='', exchanges=HISTORY_SHORT_EXCHANGES, chars=HISTORY_SHORT_CHARS):
    """``fast_text.build_request`` with the short BRAIN and the short history: the same body, fewer input characters."""
    return FT.build_request(question, instructions=instructions or SHORT_POLICY, history=short_history(history, played=played, limit=exchanges, chars=chars), material=material, played=played, also=also)


def missing(text, table=KEEP):
    """The names of the rules of ``table`` whose needle is not in ``text``."""
    return [name for name, needle in table if needle not in text]


def input_chars(body):
    """The size of what the job reads: instructions plus every input text. The cloud's stand-in for «shorter, so a faster first token»."""
    return len(body['instructions']) + sum(len(part['text']) for m in body['input'] for part in m['content'])


# --- reserve_brief: the instructions of a job in their short form, for a road whose minute is small (reserve_text.py) ---------------------------------------
# What a job reads is the BRAIN, the owner's lines and material (``content_policy.build_instructions``, ``material_pick``), then the history. The brief changes the first and the third only:
# the short BRAIN (every rule of ``KEEP``) for the long one, and of the material the parts nearest to the question within ``MATERIAL_BRIEF_CHARS`` - picked by the picker the job's own
# material was picked by, from what the job was shown. Measured 13.11 (REVIEW_20261112/night/L4_answers.md).
MATERIAL_BRIEF_CHARS = 1500
BRIEF_EXCHANGES, BRIEF_HISTORY_CHARS = 2, 100      # U65: of the history the brief keeps the last two exchanges, a question and an answer cut at 100 characters (a screen: three of 200, ``HISTORY_SHORT_*``): the median job of a typical call is under 1 500 tokens
_BLOCK = re.compile(r'(⟦МАТЕРИАЛЫ ([0-9a-f]{12}) — )([^⟧]*?)(\. ' + re.escape(MATERIAL_HOW) + r'⟧\n)(.*?)(\n⟦КОНЕЦ МАТЕРИАЛОВ \2⟧)', re.S)
_SHOWN = re.compile(r'\d+(?= из \d+ знаков)')
_WHOLE = re.compile(r'показаны полностью \(всего знаков: (\d+)\)')


def brief_instructions(text, question='', *, material_chars=MATERIAL_BRIEF_CHARS):
    """``text`` (the instructions of a job) in the short form: ``SHORT_POLICY`` where the long BRAIN stood; a material block longer than ``material_chars`` shows the parts nearest to
    ``question`` within that many characters (the nearest one is cut at a boundary sooner than dropped) and its header tells the new size. Everything else - the owner's lines, the marks,
    the history - is as it came, and so is a text that has neither."""
    text = str(text or '')
    if FT.BRAIN_POLICY in text:
        text = text.replace(FT.BRAIN_POLICY, SHORT_POLICY, 1)
    text = short_history_block(text, limit=BRIEF_EXCHANGES, chars=BRIEF_HISTORY_CHARS)      # U65: the last exchanges only, cut (the call's history is six of 600 characters): the brief of a reserve road is a median under 1 500 tokens
    found = _BLOCK.search(text)
    if not found or len(found.group(5)) <= material_chars:
        return text
    picker = MaterialPicker(found.group(5), cap=material_chars)
    near = picker.pick(question).text.strip() or (excerpt_of(picker.parts[picker.rank(question)[0]], material_chars)[0] if picker.parts else '')
    if not near:
        return text
    how, whole = found.group(3), _WHOLE.fullmatch(found.group(3))
    if whole:
        how = f'подобраны части под вопрос и разговор: {len(near)} из {whole.group(1)} знаков; полный текст сохранён, но сюда не вмещается'
    else:
        how = _SHOWN.sub(str(len(near)), how, count=1)
    return text[:found.start()] + found.group(1) + how + found.group(4) + near + found.group(6) + text[found.end():]


# --- the screen: the instructions of a remark that has no form of a question (reserve_text.ReserveStream.one) ------------------------------------------------------------
# A final with no form goes to the job to be judged (the job says «—» to a remark): 14 of 39 jobs of the call of 11.11 were such a «—» and each cost a full request (4 562 tokens, a minute of a key holds 8 000). Asked in this
# short form (the short BRAIN, the last exchanges cut, no material) the same judgment costs about a fifth; the full request goes only when the answer says it is a question.
HISTORY_HEAD = 'Последние реплики этого разговора (для связи с вопросом):'
_ENTRY = re.compile(r'(?m)^(?=(?:Вопрос|Прозвучало без ответа): )')


def short_history_block(text, *, limit=HISTORY_SHORT_EXCHANGES, chars=HISTORY_SHORT_CHARS):
    """``text`` with the block of the last exchanges (``fast_text.build_request``) cut to ``limit`` exchanges of ``chars`` characters a question and an answer; the mark of a revised answer stays; a text with no block is as it came."""
    head, _, block = str(text or '').partition(HISTORY_HEAD + '\n')
    if not block:
        return str(text or '')
    entries = [entry.strip('\n') for entry in _ENTRY.split(block) if entry.strip()]
    kept = []
    for entry in entries[-limit:]:
        revised = entry.endswith(FT.REVISED_MARK)
        entry = entry[:-len(FT.REVISED_MARK)] if revised else entry
        asked, _, answer = entry.partition('\nОтвет: ')
        kept.append(_cut(asked, chars + 8) + (f'\nОтвет: {_cut(answer, chars)}' if answer else '') + (FT.REVISED_MARK if revised and answer else ''))
    return head + HISTORY_HEAD + '\n' + '\n'.join(kept)


def screen_instructions(text):
    """The instructions of a screening request: the short BRAIN, the last exchanges short, the owner's material left out. None when there is no material in ``text`` (nothing to leave out: the brief is already what a screen would be)."""
    text = str(text or '')
    found = _BLOCK.search(text)
    if not found:
        return None
    text = (text[:found.start()].rstrip('\n') + '\n\n' + text[found.end():].lstrip('\n')).strip('\n')
    return short_history_block(brief_instructions(text))

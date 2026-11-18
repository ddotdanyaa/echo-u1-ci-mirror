"""Public, isolated E41 recipient-policy slice. No network or user records.
The functions below are copied verbatim from the private PR head for CI.
Only synthetic scenarios belong in this public repository.
"""
from __future__ import annotations
import re
import unicodedata

_WORDS=re.compile(r"[^\W_]+(?:[-’'][^\W_]+)*",re.UNICODE)
def normalize(text):
    return ' '.join(_WORDS.findall(unicodedata.normalize('NFKC',str(text or '')).casefold().replace('ё','е')))
def _set(words):return frozenset(normalize(words).split())
def _words(text):return normalize(text).split()
_SENT=re.compile(r'(?<=[.!?…])\s+')
_IMPER=_set('подскажи подскажите скажи скажите назови назовите напомни напомните дай дайте расскажи расскажите объясни объясните приведи приведите '
            'покажи покажите посчитай посчитайте сосчитай подсчитай сформулируй сформулируйте определи определите переведи переведите уточни уточните '
            'проверь проверьте найди найдите поищи поищите сравни сравните перечисли перечислите опиши опишите раскрой раскройте продиктуй прочитай '
            'процитируй вычисли вычислите реши решите помоги помогите')
_CMD=_set('стоп стой стойте хватит достаточно тише дальше назад подожди подождите погоди погодите помолчи помолчите замолчи замолчите останови '
          'остановись остановитесь продолжай продолжайте продолжи продолжите вернись вернитесь')
_STARTERS=_set('слушай слушайте итак значит ну да нет так хорошо ладно спасибо привет коллеги ребята друзья смотри смотрите кстати короче '
               'вот а и но простите извините скажите скажи подскажи подскажите знаешь знаете представим представьте понимаешь допустим '
               'кажется хм ой ох ах ага угу окей ок алло пожалуйста минуточку секунду погоди подожди стоп стой')
_HEAD_ADVERBS=_set('сейчас теперь вообще тогда потом сначала далее дальше ещё еще вчера сегодня завтра утром вечером днем ночью например кстати конечно допустим впрочем')

def _vocative(text):
    """«Лена, …», «Серёж, а …»: обращение по имени в начале; слова-зачины не имена."""
    m=re.match(r'\s*([А-ЯЁ][а-яё]+)\s*,',str(text or ''))
    if not m:return False
    w=normalize(m.group(1))     # «Проходите,», «Отлично,», «Здравствуйте,»: глагол или наречие, не имя
    return w not in _STARTERS and w not in _HEAD_ADVERBS and w not in _IMPER and w not in _CMD and not w.endswith(('ите','йте','ть','ться','ся','сь','ешь','ем','ет','ют','ут','ат','ят','о'))

def _last_sentence(text):
    parts=[p for p in _SENT.split(text.strip()) if _words(p)]
    return parts[-1] if parts else text

def public_address_allowed(text):
    """E41: public *recipient* check for each spoken act, not a model-job verdict.

    Any unambiguous third-person vocative makes the entire untrusted ASR
    utterance unsuitable for publication, including its extracted question.
    This deliberately does not silence local answers.  A model-job admission
    or an UNKNOWN classification is not itself consent to public lookup.
    """
    text=str(text or '').strip()
    if not text:return False
    if any(_vocative(part) for part in _SENT.split(text)):
        return False
    # ASR often omits the comma: 'Лена сколько ...'. Treat this as ambiguous
    # for public disclosure only; avoid converting it into a silent TALK.
    m=re.match(r'^([А-ЯЁ][а-яё]{2,})\s+(?:а\s+)?(?:сколько|когда|почему|зачем|где|куда|какой|какая|какие|что)\b',text,re.I)
    if m and _vocative(m.group(1).capitalize()+','):
        return False
    return True

"""Import existing <id>–<id> proof register into a *review-only* task inventory.

The register class DONE is not acceptance, and its evidence filenames are NOT
an authorization to edit those files or publish them to free models. This
adapter deliberately does not manufacture executable READY tasks.
"""
from __future__ import annotations

import argparse
import ast
import os
import unicodedata
import time
import json
import hashlib
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

from tools import id_query


def suggestions(rows: list[dict]) -> dict:
    items = []
    seen = set()
    for row in rows:
        rid = row["id"]
        if rid in seen:
            raise ValueError("duplicate register ID")
        seen.add(rid)
        if row.get("accepted"):
            continue
        proof = row.get("files", [])
        impl = [f for f in proof if isinstance(f, str) and f.startswith("echo_sync/")]
        tests = [f for f in proof if isinstance(f, str) and f.startswith("tests/") and f.endswith(".py")]
        needs_owner = row.get("class") in ("OWNER", "LATER")
        items.append({
            "id": rid, "title": str(row.get("what", ""))[:240],
            "class": row.get("class"), "accepted": False,
            "status": "NEEDS_OWNER" if needs_owner else "NEEDS_SCOPE_REVIEW",
            "proof_sources": sorted(set(proof)),
            "proposed_touch_files": sorted(set(impl)),
            "proposed_tests": sorted(set(tests)),
            "privacy_safe": False,
            "depends_on": [],  # register has no guaranteed dependency DAG
            "review_required": [
                "which exact code files may change",
                "which immutable tests prove acceptance",
                "real DAG dependencies",
                "is source safe for a free third-party model",
                "what live/profile acceptance is still required",
            ],
        })
    return {"schema": "factory-review-v1", "origin": "tools.backlog_register.register",
            "not_executable": True, "tasks": items}


# --- K-E.1/K-E.2/K-E.4: live BACKLOG_ECHO.md section 4 -> open rows, checked against HEAD ---
# Backlog ID grammar is id_query.TOKEN (Latin/Cyrillic capitals + digits, ``.n``/``-n`` tails): one owner of
# "what is an ID".  4.6 (<id>-<id> register, owned by tools.backlog_register) and 4.13 (only repeats IDs
# defined elsewhere) are skipped.
ACTIVE_START = re.compile(r"^##\s+4\.\s")
ACTIVE_END = re.compile(r"^##\s+5\.\s")
SKIP_SECTIONS = re.compile(r"^###\s+4\.(?:6|13)(?:\s|$)")
PRIO_CELL = re.compile(r"P([0-4])")
PRIO = re.compile(r"(?<![\w])P([0-4])(?![\w])")
PATH = re.compile(r"(?<![\w/.-])((?:echo_sync|tools|tests)/[\w./-]*[\w-]\.[A-Za-z]{1,5})(?![\w/-])")
_B = r"(?<![\w])(?:%s)(?![\w])"          # whole-word wrapper; \w covers Cyrillic
WAITING = re.compile(_B % r"ждёт|ждет|после|зависит|нужен телефон|заблокирован\w*|блокирован\w*|отложен\w*|дубль|отказ", re.I)
STRONG_WAIT = re.compile(_B % r"нужен телефон|ждёт записи\w*|ждет записи\w*|ждёт владельца|ждет владельца", re.I)  # whole state
CLOSED = re.compile(r"(?<![\w])(?<!не )(?:сделано|закрыто|готово|выложено|выполнено)(?![\w])", re.I)
OPEN_WORD = re.compile(r"(?<![\w])(?:не сделан\w*|не начат\w*|нов\w*|откры\w*|обязательство|улучшение|блокер|частично|регресс\w*|open|new)(?![\w])", re.I)
CLASS_LABEL = re.compile(r"^\W*(?:обязательство|улучшение|блокер)\W*$", re.I)
# A Russian phone number: 8 or +7 or 7, an area/operator code 3xx 4xx 8xx 9xx, 11 digits in all (separators allowed), or
# the city form "(495) 123-45-67".  The ONE owner of the phone rule: "80000000000 байт" is a size, not a number.
PHONE = re.compile(r"(?<![\w.])(?:(?:\+7|[78])[\s(-]*[3489]\d{2}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"
                   r"|\(\s*[3489]\d{2,3}\s*\)[\s.-]*\d{3}[\s-]*\d{2}[\s-]*\d{2})(?!\d)")
PRIVATE = re.compile(_B % (
    r"<private-marker>|<private-marker>"                                                                    # the owner's own markers
    r"|запис\w*\s+(?:\w+\s+)?(?:звонк|разговор|аудио|голос)\w*"                   # recordings of calls and talks
    r"|(?:звонк|разговор|диалог)\w*\s+владельц\w*|владельц\w*\s+(?:из\s+)?(?:звонк|разговор|диалог)\w*"
    r"|транскрипт\w*\s+(?:\w+\s+)?(?:звонк|разговор|владельц|запис)\w*|расшифровк\w*\s+(?:\w+\s+)?(?:звонк|разговор|диалог)\w*|аудиозапис\w*"
    r"|личн\w*\s+(?:\w+\s+)?(?:аудио|запис|диалог|материал|данн|профил|разговор|голос)\w*"   # personal material and profile
    r"|(?:материал|слова|цитат|речь|голос)\w*\s+владельц\w*|персональн\w*"
    r"|владелец\s+(?:сказал|просил|написал|велел|хотел|ответил|недоволен|недовольна|жалуется|жаловался|требует|потребовал)\w*|вы\s+(?:сказали|просили|написали|велели)"   # unquoted words of the owner
    r"|/home/[\w.-]+|[A-Za-z]:[\\/]Users[\\/][\w.-]+"                                      # a person's home folder
    r"|" + PHONE.pattern + r"|[\w.+-]+@[\w-]+\.[\w.-]+"                                  # phone numbers (the one owner: PHONE), e-mail
    r"|api[- ]?ключ\w*|ключ\w*\s+(?:api|доступа|канал\w*|провайдер\w*)|секрет(?:ы|ов|а|у|ом|е|ами)?|парол\w*|\.env"   # keys, tokens, passwords
    r"|токен\w*\s+(?:доступа|авторизац\w*|бот\w*|канал\w*|провайдер\w*|api)|(?:api|auth|bearer|telegram)[- ]?token"
), re.I)

_PAIRS = {"«": "»", "“": "”", "„": "“", "‘": "’"}
_SENT_END = re.compile(r"[^.!?\n]*[.!?]?")
# Unambiguous labels cut to the end of the sentence; "Слова" only when a time, a colon or "владельца" follows it
# (so "Слова-паразиты" stays).  Case matters for "Слова", not for the others.
_LABELS = (r"(?<![\w])(?:(?i:Ваши слова|Вы сказали|Вам сказано|по словам владельца|со слов владельца)(?![\w])"
           r"|Слова(?=\s*(?::|\d{1,2}[:.]\d{2}|владельц)))")
_JUNK = r"(?:\s*(?:\([^)]*\)|\d{1,2}[:.]\d{2}(?:[:.]\d{2})?|L\s?\d{3,}|[,:;]))"
_LABEL_RE = re.compile(r"(?P<lab>" + _LABELS + r")(?P<junk>" + _JUNK + r"*)\s*")
# One numeric token (no overlapping date/clock/duration alternatives) and possessive repeats: a "(" followed by a
# long run of tokens and no ")" is linear, not exponential.
_META = (r"(?:L\s?+\d{3,}+|\d++(?:[.:]\d++)*+|(?<![\w])(?:в|с|до|и|МСК|мск|сек|мс|мин|ч)(?![\w]))")
_PAREN_META = re.compile(r"\((?:\s|[,;/]|" + _META + r")*+\)")
_CLOCK = re.compile(r"(?<![\d:.])\d{1,2}:\d{2}(?::\d{2})?:?(?!\d)")                       # 14:36  22:43:45  14:36:
# HH.MM only with a time-of-day marker (class 2): "до 2.50 с", "в 1.20 раза", "к 06.11" are technical, not a clock
_DOT_TIME = re.compile(r"(?<![\d.])(?:[01]?\d|2[0-3])\.[0-5]\d\s*(?:МСК|мск|ч(?![\w])|утра|вечера)")
_LREF = re.compile(r"(?<![\w])L\s?\d{3,}(?![\w])")
MIN_PUBLIC_CHARS = 60


def _normalize(text: str) -> str:
    """Control characters (< 0x20, DEL) and format characters (Cf) out, tabs and newlines to a space, spaces collapsed."""
    out = []
    for ch in text:
        if ch in "\t\n\r\x0b\x0c":
            out.append(" ")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F or unicodedata.category(ch) == "Cf":
            continue
        else:
            out.append(ch)
    return re.sub(r"\s+", " ", "".join(out).replace("**", "")).strip()


def _cut_labels(t: str) -> str:
    """"Ваши слова 14:36 (L1):" and the like.  With a quote after it only the label (and its time/reference/
    bracket) goes; without a quote the whole sentence goes (the words themselves follow).  A bare
    "Слова-паразиты" (no time, bracket or colon) is not a label."""
    out, pos = [], 0
    for m in _LABEL_RE.finditer(t):
        if m.start() < pos:
            continue
        out.append(t[pos:m.start()])
        rest = t[m.end():]
        if rest[:1] in ('«', '“', '"', '„', '‘', "'"):
            pos = m.end()
        else:
            out.append(" … ")                      # the cut sentence leaves a visible gap
            pos = m.end() + _SENT_END.match(rest).end()
    out.append(t[pos:])
    return "".join(out)


def _find_close(t: str, i: int):
    c = t[i]
    if c == "«":
        depth = 0
        for k in range(i, len(t)):
            depth += (t[k] == "«") - (t[k] == "»")
            if depth == 0:
                return k
        return None
    if c == "'":
        k = i + 1
        while True:
            k = t.find("'", k)
            if k < 0 or not (k + 1 < len(t) and (t[k + 1].isalnum() or t[k + 1] == "_")):
                return k if k >= 0 else None
            k += 1
    closers = {"“": "”", "„": "“”", "‘": "’", '"': '"'}[c]
    for k in range(i + 1, len(t)):
        if t[k] in closers and (c != "‘" or not (k + 1 < len(t) and t[k + 1].isalnum())):
            return k
    return None


def _cut_quotes(t: str) -> str:
    """Paired quotes («…» with nesting, “…”, „…“, ‘…’, "…", '…') are cut out; an unpaired «, “, „ or " goes to the
    end of its sentence; an apostrophe inside a word (don't) stays."""
    out, i = [], 0
    while i < len(t):
        c = t[i]
        if c in ("«", "“", "„", "‘", '"', "'"):
            if c == "'" and i > 0 and (t[i - 1].isalnum() or t[i - 1] == "_"):
                out.append(c)
                i += 1
                continue
            j = _find_close(t, i)
            if j is None:
                if c in ("'", "‘"):
                    out.append(c)
                    i += 1
                    continue
                i = _SENT_END.match(t, i + 1).end()
            else:
                i = j + 1
            out.append(" … ")                      # a quote leaves a visible gap, not a broken phrase
            continue
        out.append(" " if c in ("»", "”") else c)
        i += 1
    return "".join(out)


_MARK_PAREN = re.compile(r"\((?:[\s,;:.–…\-]|(?:тезис\s*+\d*+|владелец|обязательно|см\.?)(?![\w]))*+\)")
# origin labels with a date: "(слова 13.11, тезис 9)", "(владелец 13.11 вечером, 3 повтора)", "Определение от владельца 13.11"
_ORIGIN_PAREN = re.compile(r"\((?=[^)]*(?i:слова|владелец|поручени|определени|тезис))(?=[^)]*\d{1,2}\.\d{1,2})[^)]*+\)")
_ORIGIN = re.compile(r"(?i:определени\w*|поручени\w*)(?:\s+от\s+владельца)?\s+\d{1,2}\.\d{1,2}(?:\.\d{2,4})?")
_HAS_STAMP = re.compile(r"\d{1,2}:\d{2}|(?<![\w])L\s?\d{3,}|МСК|мск")


def _drop_meta_parens(w: str) -> str:
    """A bracket holding only dates/times/durations/references goes whole, but only when it holds a clock time, an
    L-reference or МСК: "(до 2.50 с)" is technical and stays."""
    return _PAREN_META.sub(lambda m: " " if _HAS_STAMP.search(m.group(0)) else m.group(0), w)


_SERVICE = re.compile(r"\[(?i:предположительно|неизвестно|доказано)[^\]]*\]")        # bracketed status marks of the backlog
_CALL_WORD = r"(?i:звон\w+|разговор\w*|диалог\w*)"
_DATE = r"\d{1,2}\.\d{1,2}(?:\.\d{2,4})?"
_CALL_DATE = re.compile(r"(?P<w>" + _CALL_WORD + r"(?:\s+[^\W\d]\w*){0,2}\s+)(?P<d>" + _DATE + r")(?![\d.])"
                        r"|(?P<d2>(?<![\d.])" + _DATE + r")(?P<w2>(?:\s+[^\W\d]\w*){0,2}\s+" + _CALL_WORD + r")")
_DANGLING = re.compile(r"(?<![\w])(?:в|с|на|к|и|а|по|до)\s+(?=[.,;:)…]|$)")
_PH_OPEN, _PH_CLOSE = "\ue000", "\ue001"                       # private-use placeholders that protect code in backticks


def _tidy(w: str) -> str:
    """Debris left by the cuts, repeated until nothing changes: empty or sign-only brackets and label-word brackets,
    runs of ,;: and of …, dangling prepositions/conjunctions before a sign or a "…", ".:" ".," "..", signs before
    ")" or ".", a "(" followed by signs."""
    for _ in range(14):
        before = w
        w = re.sub(r"\s+", " ", w)
        w = _MARK_PAREN.sub(" ", w)
        w = re.sub(r"…(?:[\s,;]*…)+", "…", w)
        w = re.sub(r"([,;:])[,;:\s]*[,;:]", r"\1", w)
        w = re.sub(r"[,;:–\-]+(?=\s*[).])", "", w)
        w = re.sub(r"\(\s*[,;:.–\-]+\s*", "(", w)
        w = _DANGLING.sub("", w)
        w = re.sub(r"\.\s*[:,]", ".", w)
        w = re.sub(r"(?<!\.)\.\.(?!\.)", ".", w)
        w = re.sub(r"\s+([.,;:)])", r"\1", w)
        if w == before:
            break
    return w.lstrip(" .,;:-…").rstrip(" .,;:-")


def _code_span(seg: str) -> bool:
    """A backticked piece that is code: an identifier or a path with no spaces, no Cyrillic, no quote, no clock time
    and no profile name of this machine (a path through the user's profile folder is the owner's name, not code)."""
    if re.search(r"[А-Яа-яЁё\s«»“”„‚‘’]", seg) or _RES_TIME.search(seg):   # a straight quote in f("a") is code; a spoken one has spaces
        return False
    low = seg.lower()
    return not any(n.lower() in low for n in _owner_names())


def _cut(text: str):
    """(clean, cut): the text without the owner's quotes, line references, labels, clock times and call dates (a
    cut leaves "…", brackets of stamps go whole), and whether anything was cut.  Control and format characters
    go always, before the comparison.  Code in backticks (fewer than 3 Cyrillic words) is protected from the cuts;
    a backticked piece of 3+ words is text and is cut like any text."""
    t = _normalize(text)
    saved: list[str] = []

    def keep(m):
        seg = m.group(0)
        if not _code_span(seg):                # words, quotes, times, the profile name in backticks are text: cut like anywhere
            return seg
        saved.append(seg)
        return "%s%d%s" % (_PH_OPEN, len(saved) - 1, _PH_CLOSE)

    def restore(x: str) -> str:
        return re.sub(_PH_OPEN + r"(\d+)" + _PH_CLOSE, lambda m: saved[int(m.group(1))], x)

    w = _SERVICE.sub(" ", t)
    w = re.sub(r"`[^`\n]*`", keep, w)
    w = _cut_labels(w)
    w = _ORIGIN_PAREN.sub(" ", w)
    w = _ORIGIN.sub(" ", w)
    w = _drop_meta_parens(w)
    w = _CLOCK.sub(" … ", w)
    w = _DOT_TIME.sub(" … ", w)
    w = _LREF.sub(" … ", w)
    w = _CALL_DATE.sub(lambda m: (m.group("w") + " … ") if m.group("d") else (" … " + m.group("w2")), w)
    w = _cut_quotes(w)
    done = restore(w)
    if done == t and not _RES_DEBRIS.search(done):
        return t, False
    return restore(_tidy(w)), True


# ---- the lock: what may still be in a text after the cuts.  Classes, each one short; anything left = ask Opus ----
_RES_QUOTE = re.compile(r"[«»“”„‚‘’\"]|(?<![\w])'|'(?![\w])")                                  # 1 direct speech
_RES_TIME = re.compile(r"(?<![\d:.])(?:[01]?\d|2[0-3]):[0-5]\d(?!\d)"                          # 2 time, L-reference
                       r"|(?<![\d.])(?:[01]?\d|2[0-3])\.[0-5]\d\s*(?:МСК|мск|ч(?![\w])|утра|вечера)"
                       r"|(?<![\w])L\s?\d{3,}(?![\w])")
_RES_OWNER = re.compile(r"(?<![\w])(?:владел\w*|хозя(?:ин|ев|йк)\w*|заказчик\w*)(?![\w])", re.I)   # 3 the owner is named
# 4 speech, narrow: a personal past-tense verb of speaking with he/she/they/I within 3 words; "his/your/my wish"
_RES_VERB = re.compile(r"^(?:сказал|говорил|попросил|просил|сообщил|пожаловал|отметил|заметил|потребовал|велел|ответил|написал"
                       r"|позвонил|звонил|предложил|назвал|поручил|рассказал|объяснил|уточнил|подтвердил|заявил)(?:а|и|ся|ась|ись)?$")
_RES_SUBJ = re.compile(r"^(?:он|она|они|я)$")
_RES_WISH = re.compile(r"(?<![\w])(?:его|её|ее|их|ваш\w*|мо(?:й|я|ё|и|его|ей|их)|тво(?:й|я|ё|и|его|ей|их))\s+(?:\w+\s+)?"
                       r"(?:пожелани|требовани|просьб|иде[яюиеёй]|мысл)\w*", re.I)
_RES_PHRASE = re.compile(r"(?<![\w])(?:ваши слова|вам сказано|по (?:его|её|ее|их|вашим|моим) словам"
                         r"|по словам (?:его|её|ее|их|вашим|моим)|со слов (?:его|её|ее|их|ваших|моих))(?![\w])", re.I)
_RES_PRON = r"(?<![\w])(?:я|мне|меня|мной|мною|мо(?:й|я|ё|и|его|ей|их|ему|ём|им|ими|ю)|ты|тебе|тебя|тобой|тво\w*|вы|вам|вас|вами|ваш\w*)(?![\w])"
_RES_PERSON = re.compile(_RES_PRON, re.I)                                                          # 5
_RES_LIST = re.compile(r"(?:" + _RES_PRON + r"[\s,;/|—-]*){3,}", re.I)                             # a list of forms, not a person
_RES_DEBRIS = re.compile(r"\((?:[^\w\s)]|\s)++\)|[,;:]{2,}|\(\s*[,;:]"
                         r"|\(\s*(?:тезис\s*\d*|владелец|обязательно|см\.?)\s*\)")                  # 6 debris


_GENERIC_NAMES = frozenset(("root", "runner", "user", "admin", "administrator", "ubuntu", "system", "default", "guest", "public", "owner"))
# product terms that contain "хозяин": rule/census of owners are parts of the project, not a person
_PRODUCT_OWNER = re.compile(
    r"(?<![\w])(?:реестр|перепись|переписи)\s+хозяев(?![\w])|owner_census", re.I)    # «правило хозяина» may paraphrase the owner: not here


def _owner_names() -> list[str]:
    """The profile name of this machine (home folder, USERNAME, USER): taken at run time, never written into the code.
    Generic account names (root, runner, admin, ...) are not a person."""
    names = {Path.home().name, os.environ.get("USERNAME", ""), os.environ.get("USER", "")}
    return sorted(n for n in names if re.fullmatch(r"[A-Za-zА-Яа-яЁё]{3,}", n or "") and n.lower() not in _GENERIC_NAMES)


def _name_pattern(name: str):
    # the name ANYWHERE inside a token (name_notes, a patronymic or surname built on it, a profile path, NameNotes): sending it out is the
    # worse mistake, so the check errs on the cutting side.  A 3-letter name is too short for a substring (Ann in "channel"):
    # it stays a whole word with up to 3 more letters.
    if len(name) >= 4:
        return re.compile(re.escape(name), re.I)
    return re.compile(r"(?<![\w])" + re.escape(name) + r"\w{0,3}(?![\w])", re.I)


_CYR_RE = re.compile(r"[А-Яа-яЁё]")


def residue(text: str) -> list[str]:
    """Classes of owner material that survived the cuts: "quote", "time", "owner", "speech", "person", "debris".
    Empty = nothing found.  The caller must not send a text with a non-empty residue to an external model.
    Quotes, times and the owner's names are looked for EVERYWHERE, inside backticks too; only pure code (a backticked
    piece without Cyrillic letters: identifiers, paths, calls) is skipped.  Speech and pronouns are not looked for
    in a backticked piece of fewer than 3 Cyrillic words (``вы`` in an API note), and a list of 3+ pronoun forms is
    a list, not a person."""
    whole = text                          # debris is judged on the text as it stands: "(`x`)" is a bracket with code, not a stump
    plain = re.sub(r"`[^`\n]*`", lambda m: " " if _code_span(m.group(0)) else m.group(0), text)
    # a backticked Cyrillic phrase of 2+ words is ordinary text (`хочу быстро` is speech with or without quotes);
    # one word (`вы` in an API note) and code are not looked at for speech and pronouns
    words_only = re.sub(r"`[^`\n]*`", lambda m: m.group(0) if len(re.findall(r"[А-Яа-яЁё]{2,}", m.group(0))) >= 2 else " ", text)
    out = []
    if _RES_QUOTE.search(plain):
        out.append("quote")
    if _RES_TIME.search(plain):
        out.append("time")
    owned = _PRODUCT_OWNER.sub(" ", plain)
    if _RES_OWNER.search(owned) or any(_name_pattern(n).search(owned) for n in _owner_names()):
        out.append("owner")
    words = re.findall(r"[\w-]+", _RES_LIST.sub(" ", words_only).lower())
    said = any(_RES_VERB.match(w) and any(_RES_SUBJ.match(x) for x in words[max(0, i - 3):i + 4]) for i, w in enumerate(words))
    if said or _RES_WISH.search(words_only) or _RES_PHRASE.search(words_only):
        out.append("speech")
    if _RES_PERSON.search(_RES_LIST.sub(" ", words_only)):
        out.append("person")
    if _RES_DEBRIS.search(whole):
        out.append("debris")
    return out


def screen(text: str, min_chars: int = MIN_PUBLIC_CHARS):
    """The ONE decision "may this row text go to an external model": (goal or None, classes).

    redact -> cut (quotes, references, times, labels, call dates) -> lock.  goal is None when any class is left:
    the residue classes above, plus "cut" when anything was cut and the text is cut up (three or more "…", or
    fewer than ``min_chars`` characters of meaningful text without "…" and code).  An uncut text is never "cut"."""
    from tools import agent_factory as _F
    clean, cut = _cut(_F.redact(text).strip("`* "))
    classes = residue(clean)
    if cut:
        meaningful = len(re.sub(r"…|`[^`\n]*`", "", clean).strip())
        if clean.count("…") >= 3 or meaningful < min_chars:
            classes.append("cut")
    return (None if classes else clean), classes


def _public_state(state: str, limit: int = 240) -> str:
    """A state text for output: through screen (redact, cuts, lock) with no length floor; empty when anything is left."""
    return (screen(state, 0)[0] or "")[:limit]


def public_goal(text: str, min_chars: int = MIN_PUBLIC_CHARS):
    """Text that may go to an external free model: the owner's quotes (nested «a «b» c» too, “…”, „…“, ‘…’,
    "…", '…'; an unpaired one up to the end of its sentence), line references (L12345, "(L1, L2)"), clock times
    (14:36, 22:43:45, 14:36:, "в 14.36", "09.15 МСК"; not 3.14 or 7.8.27), brackets holding only dates/times/
    references, and labels like "Ваши слова 14:36 (L1):" (without a quote after the label the sentence goes)
    are cut out.  Control and format characters are removed ALWAYS.  None when a cut happened and less than ~40
    characters are left."""
    clean, cut = _cut(text)
    return clean if not cut or len(clean.replace("…", "").strip()) >= min_chars else None


class ClosedCheckError(RuntimeError):
    """git could not answer 'which IDs are closed at HEAD'; an infrastructure failure, never 'nothing closed'."""


def _head(state: str) -> str:
    """Head of a state cell: up to the first ' · ' or ':' and at most 60 characters."""
    return re.split(r"\s·\s|:", state, maxsplit=1)[0][:60]


def _heads(state: str) -> list[str]:
    """[head] and, when the head is only a class label (obligation/improvement/blocker), the next segment's head."""
    segs = state.split(" · ")
    heads = [_head(segs[0])]
    if CLASS_LABEL.match(heads[0]) and len(segs) > 1:
        heads.append(_head(segs[1]))
    return heads


def classify_state(state: str, has_state_column: bool = True) -> str:
    """'open' | 'closed' | 'waiting' | 'unknown'.

    Open = new / open / partial and none of waits / after / depends / needs phone / postponed /
    blocked / duplicate / refused.  Words are whole words; only the head of the state cell counts
    (a bare class label is looked through to the next segment), except STRONG_WAIT words, which are
    searched in the whole state.  A table without a state column is judged by its cell heads.
    'unknown' = explicit state column whose wording is none of those (e.g. "в работе", a date): the
    caller must report it, never lose it silently."""
    heads = _heads(state) if has_state_column else [_head(c) for c in state.split(" | ")[1:]]
    if STRONG_WAIT.search(state) or any(WAITING.search(h) for h in heads):
        return "waiting"
    if any(CLOSED.search(h) and "частично" not in h.lower() for h in heads):
        return "closed"
    if any(OPEN_WORD.search(h) for h in heads):
        return "open"
    return "unknown" if has_state_column else "open"


def is_open_state(state: str, has_state_column: bool = True) -> bool:
    return classify_state(state, has_state_column) == "open"


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _find_col(header: list[str], *prefixes: str):
    for i, h in enumerate(header):
        hl = h.lower()
        if any(hl.startswith(p) for p in prefixes):
            return i
    return None


def parse_section4(markdown: str) -> list[dict]:
    """Every row of section 4 (first definition wins, repeats add to ``locations``) as
    {backlog_id, priority, state, text, row, section, line, locations, open}.

    The layout is decided PER ROW: a cell (2nd..5th) that is exactly P0-P4 is the priority and the
    next cell is the state (section 4.12 mixes both forms in one table); otherwise the table header
    names the columns."""
    if not isinstance(markdown, str):
        raise TypeError("backlog is text")
    started = ended = False
    section, skip, header = "", False, None
    seen: dict[str, dict] = {}
    for line_no, line in enumerate(markdown.lstrip("\ufeff").splitlines(), 1):
        if not started:
            started = bool(ACTIVE_START.match(line))
            continue
        if ACTIVE_END.match(line):
            ended = True
            break
        if line.startswith("### "):
            section = line.lstrip("# ").split(" ", 1)[0]
            skip, header = bool(SKIP_SECTIONS.match(line)), None
            continue
        if skip or not line.startswith("|"):
            continue
        cells = _cells(line)
        ident = cells[0].strip("`* ") if cells else ""
        if not id_query.TOKEN.fullmatch(ident):
            if ident.upper() in ("ID", "N"):
                header = cells
            continue
        if ident in seen:
            seen[ident]["locations"].append({"line": line_no, "section": section})
            continue
        hdr = header or []
        pi = _find_col(hdr, "приоритет", "пр.", "priority")
        si = _find_col(hdr, "состояние", "state", "status")
        ti = _find_col(hdr, "формулировка", "что", "задача", "title")
        for k in range(2, min(len(cells), 6)):        # per-row layout: a bare P-cell, state right after it
            if PRIO_CELL.fullmatch(cells[k].strip("`* ")):
                pi, si = k, (k + 1 if k + 1 < len(cells) else None)
                break
        pm = PRIO.search(cells[pi]) if pi is not None and pi < len(cells) else None
        state = cells[si] if si is not None and si < len(cells) else ""
        row_text = " | ".join(cells)
        text = cells[ti] if ti is not None and ti < len(cells) else (cells[1] if len(cells) > 1 else "")
        cls = classify_state(state if si is not None else row_text, si is not None)
        seen[ident] = {"backlog_id": ident, "priority": "P" + pm.group(1) if pm else None,
                       "state": state, "text": text, "row": row_text, "section": section,
                       "line": line_no, "locations": [{"line": line_no, "section": section}],
                       "open": cls == "open", "unknown": cls == "unknown",
                       # only the formulation and the state decide: a service cell such as "как сказал владелец"
                       # never reaches a goal, so it must not make the row private
                       "private": bool(PRIVATE.search(_cut(text)[0]) or PRIVATE.search(_cut(state)[0]))}
    if not started or not ended:
        raise ValueError("expected bounded authoritative section 4")
    return list(seen.values())


def _id_key(bid: str):
    return [int(t) if t.isdigit() else t for t in re.findall(r"\d+|\D+", bid)]


def _sort_key(row: dict):
    p = row["priority"]
    return (int(p[1]) if p else 9, _id_key(row["backlog_id"]))


def _exists(root: Path, rel: str) -> bool:
    return (Path(root) / rel).is_file()


def mentioned_paths(row_text: str, repo_root) -> tuple[list[str], list[str]]:
    """(files, tests): paths named in the row (`echo_sync/..`, `tools/..`, `tests/..`) that exist at repo_root."""
    files, tests = [], []
    for m in PATH.findall(row_text):
        rel = m.rstrip(".,;:")
        if rel in files or rel in tests or not _exists(repo_root, rel):
            continue
        (tests if rel.startswith("tests/") else files).append(rel)
    return files, tests


_CLOSED_CACHE: dict[str, tuple] = {}     # one entry per root: (HEAD sha, closed IDs)


def _git(root, *args) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as e:
        raise ClosedCheckError("git %s failed in %s: %s" % (args[0], root, e)) from e
    return r.stdout.decode("utf-8", "replace")


def _closing_ids(subject: str) -> list[str]:
    """IDs closed by a subject: the prefix before the first ':' must be ONLY IDs separated by commas
    and/or spaces (``<id>, <id>: ..``, ``<id> <id> <id>: ..``).  ``Revert <id>: ..`` and
    ``wave W7 E1: ..`` close nothing (``Revert``/``wave`` are not IDs)."""
    if ":" not in subject:
        return []
    parts = [p for p in re.split(r"[,\s]+", subject.split(":", 1)[0].strip()) if p]
    return parts if parts and all(id_query.TOKEN.fullmatch(p) for p in parts) else []


def _closed_set(root) -> set:
    head = _git(root, "rev-parse", "HEAD").strip()
    key = str(Path(root))
    cached = _CLOSED_CACHE.get(key)
    if cached is None or cached[0] != head:
        subjects = [c["subject"] for c in id_query.commits(root)]
        if not subjects:
            # id_query swallows git errors into []; ONE git log tells "no commits" from a failure
            # (a failure raises ClosedCheckError).
            subjects = _git(root, "log", "--format=%s").splitlines()
        cached = _CLOSED_CACHE[key] = (head, {i for s in subjects for i in _closing_ids(s)})
    return cached[1]


def is_closed_at_head(backlog_id: str, repo_root) -> bool:
    """True when a commit in the history of HEAD closes the ID with a ``<ID>[, <ID>]: ...`` subject
    (tools.id_query.commits, strict prefix rule above).  Cached per (root, HEAD sha), so a new
    closing commit is seen at once.  A git failure raises ClosedCheckError: callers treat it as an
    infrastructure failure, never as 'not closed'."""
    return backlog_id in _closed_set(repo_root)


MODULE_WORD = re.compile(r"(?<![\w])(?:модул\w*|файл\w*)(?![\w])", re.I)
_BARE_PY = re.compile(r"(?<![\w/.-])([A-Za-z_][\w]*)\.py(?![\w])")
_BARE_TICK = re.compile(r"`([a-z][a-z0-9_]{3,})`")


def _bare_names(row_text: str) -> list[tuple]:
    """[(stem, ticked, near_word)]: module stems named without a directory, ``latency_layers.py`` or a
    backticked ``controlled_media``; near_word = "модуль"/"файл" within 40 characters of the name."""
    seen: list[tuple] = []
    for rx, ticked in ((_BARE_PY, False), (_BARE_TICK, True)):
        for m in rx.finditer(row_text):
            name = m.group(1)
            if name == "__init__" or name in [n for n, _, _ in seen]:
                continue
            window = row_text[max(0, m.start() - 40):m.end() + 40]
            seen.append((name, ticked, bool(MODULE_WORD.search(window))))
    return seen


class OpenRows(list):
    """list of open rows plus ``.skipped_unknown``: [{backlog_id, state[:60]}] rows whose state wording
    is neither open, closed nor waiting (they are reported, not dropped silently)."""

    def __init__(self, it=()):
        super().__init__(it)
        self.skipped_unknown: list[dict] = []


def _safe_title(r: dict) -> str:
    """Row text up to 240 chars; text that looks private gives the ID only.  NOT a statement that the
    title may go to a free model: privacy_safe is decided by triage_portion alone."""
    t = (screen(r["text"], 0)[0] or "")[:240]
    return r["backlog_id"] if not t or r["private"] else t


def parse_open_rows(backlog_path, repo_root, include_closed: bool = False) -> list[dict]:
    """Open rows of BACKLOG_ECHO.md section 4, ordered P0 -> P4 -> no priority, then by ID.

    Each item: {backlog_id, priority, state, text, mentioned_files, mentioned_tests, private}
    (+ section, line, closed_at_head).  A private row (call records, keys, .env, personal data) has
    empty ``state`` and ``text``.  Rows closed at HEAD by a ``<ID>:`` commit are dropped unless
    include_closed=True.  The result's ``.skipped_unknown`` lists rows with unrecognised state wording.
    Raises ClosedCheckError when git cannot be read."""
    markdown = Path(backlog_path).read_bytes().decode("utf-8-sig")
    out = OpenRows()
    for r in parse_section4(markdown):
        if r["unknown"]:
            out.skipped_unknown.append({"backlog_id": r["backlog_id"],
                                        "state": "" if r["private"] else _public_state(r["state"], 60)})
        if not r["open"]:
            continue
        closed = is_closed_at_head(r["backlog_id"], repo_root)
        if closed and not include_closed:
            continue
        row = r["row"].replace("\\", "/")
        files, tests = mentioned_paths(row, repo_root)
        out.append({"backlog_id": r["backlog_id"], "priority": r["priority"],
                    "state": "" if r["private"] else _public_state(r["state"]),
                    "text": "" if r["private"] else r["text"],
                    "private": r["private"], "mentioned_files": files, "mentioned_tests": tests,
                    "section": r["section"], "line": r["line"], "closed_at_head": closed,
                    "text_len": len(r["text"]), "bare_names": _bare_names(row)})
    out.sort(key=_sort_key)
    return out


_CYR = dict(zip("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ", "A B V G D E E ZH Z I Y K L M N O P R S T U F KH TS CH SH SCH _ Y _ E YU YA".split()))
_CYR.update({k.lower(): v.lower() for k, v in list(_CYR.items())})
MAX_TOUCH = 3
MAX_TEXT = 1500
MAX_TESTS = 3
MAX_PARTS = 6          # a row is cut into at most this many parts (each part = a test task + a code task)
PART_TEXT = 900        # the row text kept in each part (the part tail names its files and number)


def _translit(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", "".join(_CYR.get(c, c) for c in text))


def _task_id(backlog_id: str) -> str:
    # "#" (a part of a cut row: R8#1) gets its own escape, so R8#1 never equals R8-1, R8.1 or R8_1
    return "bl_" + _translit(backlog_id.replace("#", "_x23_"))


def _module_index(root: Path) -> dict[str, list[str]]:
    """{stem: [rel paths]} of .py files under echo_sync/, tools/ and tests/ at root."""
    idx: dict[str, list[str]] = {}
    for top in ("echo_sync", "tools", "tests"):
        for p in sorted((Path(root) / top).rglob("*.py")) if (Path(root) / top).is_dir() else []:
            idx.setdefault(p.stem, []).append(p.relative_to(root).as_posix())
    return idx


def _is_src(rel: str) -> bool:
    """A module that may be a task's writing scope: echo_sync/** or tools/**, never a package __init__."""
    return rel.startswith(("echo_sync/", "tools/")) and not rel.endswith("/__init__.py")


def _id_variants(backlog_id: str) -> set[str]:
    """<id> -> {<id>, <id>, <id>}: how an ID can be spelled in a file name."""
    return {backlog_id, re.sub(r"[.-]", "_", backlog_id), re.sub(r"[.]", "-", backlog_id)}


def _tests_named_by_id(backlog_id: str, test_paths) -> list[str]:
    """Tests that can be the red test of an ID: ``test_v_<ID>*.py`` and ``test_<id_lower>*.py`` (any
    spelling of the ID, whole token: E5 does not match <id>).  Order: test_v_<ID> first, then by name."""
    out = []
    for path in test_paths:
        stem = PurePosixPath(path).stem.lower()
        for v in _id_variants(backlog_id):
            v = v.lower()
            m = re.match(r"test_(v_)?" + re.escape(v) + r"(?![0-9a-z])(?![_.-]\d)", stem)
            if m:
                out.append((0 if m.group(1) else 1, path))
                break
    return [p for _, p in sorted(out)]


def _protected(path: str) -> bool:
    """True when the gate forbids writing the path; the rule lives only in tools.factory_gate.is_forbidden."""
    from tools import factory_gate as G
    return G.is_forbidden(path, "code") is not None


PROFILE_TIMEOUT_S = 30
PROFILE_SIBLINGS = 2
PROFILE_MAX_ATTEMPTS = 3
ENV_STREAK_MAX = 5           # consecutive portions without pytest (no slot / no RAM) before Opus is asked
ENV_HOLD_ID = "ENV-PYTEST"    # the question is not about one row
_mono = time.monotonic       # seam for tests with a fake clock
PORTION_DEADLINE_S = 150      # after this the remaining rows wait for the next portion instead of being profiled
SECOND_MODULE_RATIO = 0.9


_IMPORTS_CACHE: dict = {}


def _import_stems(root: Path, rel: str, idx: dict) -> set:
    """Project modules a test imports, as file stems (``echo_sync.util`` -> util, ``from kit import x`` -> kit)."""
    key = (str(root), rel)
    if key not in _IMPORTS_CACHE:
        try:
            tree = ast.parse((root / rel).read_text(encoding="utf-8", errors="replace"))
        except (OSError, SyntaxError, ValueError):
            tree = None
        stems = set()
        for n in ast.walk(tree) if tree is not None else ():
            if isinstance(n, ast.Import):
                stems |= {a.name.split(".")[-1] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                if n.module:
                    stems.add(n.module.split(".")[-1])
                stems |= {a.name for a in n.names}
        _IMPORTS_CACHE[key] = stems
    return {x for x in _IMPORTS_CACHE[key] if x in idx and x != "__init__"}


def _neighbours(root: Path, named: list[str], idx: dict, all_tests: list[str], limit: int = PROFILE_SIBLINGS) -> list[str]:
    """Passing-side companions of the target: tests sharing the most imported project modules (the same
    fixture or helper module) with it, small files first; at most ``limit`` (the 30 s budget)."""
    mine = set().union(*[_import_stems(root, t, idx) for t in named]) if named else set()
    dirs = {str(PurePosixPath(t).parent) for t in named}
    scored = []
    for t in all_tests:
        if t in named or not PurePosixPath(t).name.startswith("test_"):
            continue
        shared = len(mine & _import_stems(root, t, idx))
        try:
            size = (root / t).stat().st_size
        except OSError:
            continue
        if shared and size <= 80_000:
            scored.append((-shared, str(PurePosixPath(t).parent) not in dirs, size, t))
    return [t for *_, t in sorted(scored)[:limit]]


def _profile_run(G, root, tests, timeout_s, wait_deadline=None):
    """One profile run.  ``wait_deadline`` (a _mono() time) is shared by all runs of a row: the slot wait of a run is what is left of it."""
    wait_s = None if wait_deadline is None else max(0.0, wait_deadline - _mono())
    try:
        return G.profile_tests(root, tests, timeout_s, ("echo_sync/", "tools/"), wait_s=wait_s)
    except Exception as e:  # an infrastructure failure of the profiler must not stop the triage
        return G.ProfileResult("unknown", {}, {}, False, "%s: %s" % (type(e).__name__, e))


def _localize(root: Path, bid: str, named: list[str], idx: dict, all_tests: list[str], timeout_s: float = PROFILE_TIMEOUT_S, wait_deadline=None):
    """Spectrum localisation for a row whose red target is an ID-named test and which names no source file.

    Two separate runs, each within ``timeout_s`` (<= 30 s): the target alone, then a few passing
    neighbours; the results are merged.  If the neighbours do not finish, the ranking uses the
    target alone and the notes say so.  Modules are ranked by Ochiai (only the target's own failures
    count).  -> (kind, payload, fallback, notes) with kind "unknown" (payload = reason) | "green" |
    "empty" | "red" (payload = (modules, leaders)); notes = [(event, reason)].
    green only when the target has a passed test and no failed/error/skipped one; skipped-only or a
    target that fails for the environment (missing module/data) is unknown, never a verdict."""
    from tools import factory_gate as G
    notes: list = []
    res = _profile_run(G, root, named, timeout_s, wait_deadline)
    fb = bool(getattr(res, "fallback", False))
    if res.verdict != "ok":
        # pytest never started (no slot / no RAM): the environment, not a failed profile: no attempt, no Opus question
        return ("env" if getattr(res, "env_reason", "") else "unknown"), res.diag, fb, notes
    neighbours = _neighbours(root, named, idx, all_tests)
    if neighbours:
        res2 = _profile_run(G, root, neighbours, timeout_s, wait_deadline)
        if res2.verdict == "ok":
            fb = fb or bool(res2.fallback)
            res = G.ProfileResult("ok", {**res.outcomes, **res2.outcomes}, {**res.calls, **res2.calls}, fb, "",
                                  {**res.reasons, **res2.reasons})
        else:
            notes.append(("profile_neighbours_env" if getattr(res2, "env_reason", "") else "profile_neighbours_unknown",
                          "ranked by the target alone: " + res2.diag))
    target = {k: v for k, v in res.outcomes.items() if k.split("::", 1)[0] in named}
    if not target:
        return "unknown", "no testcase of the target was recorded", fb, notes
    vals = set(target.values())
    if "passed" in vals and not vals & {"failed", "error", "skipped"}:
        return "green", None, fb, notes
    red = [k for k, v in target.items() if v in ("failed", "error")]
    if not red:
        return "unknown", "target has no failing test (outcomes: %s)" % ", ".join(sorted(vals)), fb, notes
    if all(G._env_reason(res.reasons.get(k, ""), root) for k in red):
        return "unknown", "environment: " + res.reasons.get(red[0], "")[:150], fb, notes
    mods, leaders = G.rank_modules(res.outcomes, res.calls, targets=set(named))
    mods = [m for m in mods if _is_src(m[0])]
    return ("red", (mods, leaders), fb, notes) if mods else ("empty", None, fb, notes)


def _chunk_files(root: Path, files: list[str], graph, size: int = MAX_TOUCH) -> list[list[str]]:
    """Cut the files of a row into groups of at most ``size``: files that import each other stay together, the order
    is deterministic (sorted paths, first group with room and most import edges), so re-triage gives the same parts."""
    chunks: list[list[str]] = []
    for f in sorted(files):
        best, best_score = None, -1
        for i, c in enumerate(chunks):
            if len(c) >= size:
                continue
            score = sum(1 for m in c if m in graph.edges.get(f, ()) or f in graph.edges.get(m, ()))
            if score > best_score:
                best, best_score = i, score
        if best is None:
            chunks.append([f])
        else:
            chunks[best].append(f)
    return chunks


def _cut_text(text: str, n: int) -> str:
    """The row text for a part: whole when short, else up to ``n`` characters ending at a sentence boundary."""
    if len(text) <= n:
        return text
    cut = text[:n]
    end = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "))
    return (cut[:end] if end > n // 2 else cut).rstrip(" .,;") + " …"


def _split_text(text: str, n: int) -> list[str]:
    """The row text for n parts: a short text goes whole to every part; a long one is divided between the parts by
    sentences in order (each part <= PART_TEXT), so no part loses the end of the row; a sentence longer than a part is cut."""
    if len(text) <= PART_TEXT or n <= 1:
        return [_cut_text(text, PART_TEXT)] * max(n, 1)
    sentences = [x for x in re.split(r"(?<=[.!?;])\s+", text) if x]
    share = -(-len(text) // n)
    buckets, cur = [], ""
    for sent in sentences:
        sent = sent if len(sent) <= PART_TEXT else _cut_text(sent, PART_TEXT)
        if cur and (len(cur) + 1 + len(sent) > PART_TEXT or (len(cur) >= share and len(buckets) < n - 1)):
            buckets.append(cur)
            cur = ""
        cur = (cur + " " + sent).strip()
    if cur:
        buckets.append(cur)
    while len(buckets) < n:                       # fewer sentences than parts: the rest of the parts get the head of the row
        buckets.append(_cut_text(text, PART_TEXT))
    if len(buckets) > n:                          # more text than n parts can carry: the tail is cut, visibly
        buckets = buckets[:n - 1] + [_cut_text(" ".join(buckets[n - 1:]), PART_TEXT)]
    return buckets


def _test_reads(files, extra=()) -> list[str]:
    """What the author of a NEW test must see: the code the test is about (the code part's touch files, then its read
    files). Live 19.11 18:06-18:14: unit_test tasks had read_files=[], the models saw no code at all, imported invented
    modules ('factory') or wrote 'assert False' stubs, and every one of them failed."""
    out: list[str] = []
    for f in list(files) + list(extra):
        if f.endswith(".py") and f not in out:
            out.append(f)
    return out[:MAX_TOUCH + 1]


def _import_hint(files) -> str:
    """' Проверяемый код: echo_sync.fast_text (импортируй из него).' for the goal of a new test, '' without code."""
    mods = [f[:-3].replace("/", ".") for f in files if f.endswith(".py") and not f.startswith("tests/")]
    return (" Проверяемый код: %s (импортируй из этих модулей, других не выдумывай)." % ", ".join(mods)) if mods else ""


def _children(F, root: Path, bid: str, tid: str, priority, text: str, chunks: list[list[str]], known, named: list[str], known_parts=None):
    """Parts of a too big row: for every group of files a pair "unit_test -> code".

    Part k (1-based) has the backlog_id ``<ID>#<k>``, task ids ``<tid>_c<k>`` (code) and ``<tid>_c<k>_test``
    (unit_test, tests/test_factory_<slug>_c<k>.py), fields parent / part / parts; the code part depends_on its test.
    All ids derive from the row ID and the part number only: the same row gives the same ids on every re-triage.
    Returns (pairs, record, error): pairs = [[test task, code task], ...] of the parts not yet known; record =
    {backlog_id, parts, children, code_tasks, test_tasks} for the loop to close the parent when its code tasks are
    done; error = a reason when the row cannot be cut honestly."""
    n = len(chunks)
    pieces = _split_text(text, n)
    slug = tid[3:].lower()
    pairs, record = [], {"backlog_id": bid, "parts": n, "children": [], "code_tasks": [], "test_tasks": [], "files": []}
    for k, files in enumerate(chunks, 1):
        cb, ctid = "%s#%d" % (bid, k), "%s_c%d" % (tid, k)
        record["children"].append(cb)
        record["code_tasks"].append(ctid)
        record["test_tasks"].append(ctid + "_test")
        record["files"].append(list(files))
        if cb in known:
            old = (known_parts or {}).get(cb)
            if old is not None and sorted(old) != sorted(files):
                return [], None, "раскладка части %s изменилась (было: %s; стало: %s): старые файлы не подменяю, ответить: answer --backlog-id %s --touch <файлы> --tests <тест>" % (
                    cb, ", ".join(sorted(old)), ", ".join(sorted(files)), bid)
            continue
        tpath = "tests/test_factory_%s_c%d.py" % (slug, k)
        base = {"backlog_id": cb, "priority": priority or "P4", "privacy_safe": True, "only_opus": False, "read_files": [],
                "task_type": "patch", "parent": bid, "part": k, "parts": n}
        tail = " Часть %d из %d строки %s: файлы %s. Остальные части делают другие подзадачи." % (k, n, bid, ", ".join(files))
        if named:
            tail += " Общий тест строки (%s) позеленеет только после всех частей: не требуй его от этой." % ", ".join(named)
        piece = pieces[k - 1]
        goal = (piece + tail)[:MAX_TEXT]
        test = None
        if (root / tpath).is_file():
            try:
                own = bool(id_query.pattern(cb).search((root / tpath).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                own = False
            if not own:
                return [], record, "файл теста занят чужой строкой: " + tpath
        else:
            test = dict(base, id=ctid + "_test", title=("Тест части %d/%d для %s" % (k, n, bid))[:120], depends_on=[],
                        goal=("Написать тест: он должен падать на текущем коде из-за дефекта части %d из %d строки и проходить после "
                              "исправления. Первой строкой файла напиши комментарий «# factory-backlog-id: %s».%s Строка: %s"
                              % (k, n, cb, _import_hint(files), goal))[:MAX_TEXT],
                        touch_files=[tpath], tests=[tpath], kind="unit_test", read_files=_test_reads(files))
        code = dict(base, id=ctid, title=("%s часть %d/%d: %s" % (bid, k, n, piece))[:120], goal=goal,
                    depends_on=[ctid + "_test"] if test else [], touch_files=list(files), tests=[tpath], kind="code")
        pairs.append([t for t in (test, code) if t])
    return pairs, record, None


def _screen(F, bid: str, raw_text: str):
    """(text, hold question or None) for a row: the text as it may go out, or why it may not.  Built on screen(),
    the one decision; used before profiling and before the task is made."""
    goal, classes = screen(raw_text)
    if goal is not None:
        return goal or bid, None
    rest = _cut(F.redact(raw_text).strip("`* "))[0]
    # a retold call, quote or named owner is never echoed, not even into the question line for Opus
    shown = " ".join(rest.split()[:8]) if set(classes) <= {"debris", "time", "cut"} and rest else "(текст скрыт)"
    why = "формулировка разрезана, дать техническую" if classes == ["cut"] else "остаток владельца/речи/разговора (%s)" % ", ".join(classes)
    return None, "текст строки %s — %s; дать техническую формулировку? Осталось: %s" % (bid, why, shown)


def triage_portion(backlog_path, head_root, known_backlog_ids, limit, profile_attempts=None, known_parts=None, env_streak=0) -> dict:
    """K-E.3: next portion of the live backlog as plan tasks (nothing is written).

    Returns {"tasks", "holds": [{backlog_id, question}], "stale": [backlog_id],
    "skipped": [{backlog_id, reason}], "skipped_unknown": [{backlog_id, state}], "events": [...],
    "parents": [{backlog_id, parts, children, code_tasks, test_tasks, files}] (every cut row, also when all its parts are
    already known; ``known_parts`` {child backlog_id: [files]} lets a changed layout skip the row),
    "profile_attempts": {backlog_id: n} (failed profile runs so far; the caller passes the old ones back as
    ``profile_attempts`` and stores the new ones), "env_streak": consecutive portions that could not profile for the
    environment (the caller passes the old value back as ``env_streak``; at 5 an event and a hold "ENV-PYTEST" appear), "deferred": [{backlog_id, reason}] (rows left for the next portion by the profiling deadline: NOT skipped,
    so a caller that marks skipped rows as seen does not lose them)} in P0 -> P4 order.
    - rows closed at HEAD (``<ID>:`` commit) -> stale; IDs in known_backlog_ids -> skipped; two IDs
      that give the same task id (<id> / <id>) -> both skipped "коллизия id";
    - private rows (<private-marker>/<private-marker>, call records, keys, .env, personal data) are checked FIRST: hold, plus an
      only_opus, privacy_safe=False task when a scope exists.  The hold is written only when the group
      passed read_plan and fits the limit.  privacy_safe is decided here only;
    - touch_files: existing echo_sync/** or tools/** files named in the row (never a package
      __init__); bare module names (``latency_layers.py``; a backticked name only when the text also
      says "модуль"/"файл") by stem, exactly one match or the row is skipped as ambiguous; with only
      tests named, the 1-2 modules the test imports (more -> hold); never a test file for kind=code;
      files the gate protects (tools.factory_gate rules) -> hold "область защищена воротами";
    - tests: ONLY tests that can be the task's red test: tests named in the row that exist, and tests
      named by the ID (tests/**/test_v_<ID>*.py, test_<id>*.py).  affected_tests neighbours are NOT
      put in (they are green on the base and the gate would call the task already_green; the runner
      adds regression neighbours itself).  Order: test_v_<ID>, then named, then alphabetical.  No
      such test -> sub-task kind=unit_test ``<id>_test`` on tests/test_factory_<slug>.py (an existing
      file is reused as the task's test, not rewritten) and the main task depends_on it;
    - > 3 touch files or text > 1500 chars -> hold "split into sub-tasks";
    - task id = ``bl_`` + transliterated backlog_id (agent_factory.TASK_ID); backlog_id is a field;
    - every task group passes agent_factory.read_plan before it is returned; at most ``limit`` tasks
      (sub-tasks count).
    Graph (tools.affected_tests) writes its pickle cache into %TEMP% and is built only when a test must
    be looked at for its imports."""
    from tools import agent_factory as F
    root = Path(head_root)
    rows = parse_open_rows(backlog_path, root, include_closed=True)
    attempts = {k: v for k, v in (profile_attempts.items() if isinstance(profile_attempts, dict) else ())
                if type(v) is int and v >= 0}      # a damaged value from an old state counts as 0
    out = {"tasks": [], "holds": [], "stale": [], "skipped": [], "skipped_unknown": list(rows.skipped_unknown), "events": [], "deferred": [], "profile_attempts": {}, "parents": [], "env_streak": 0}
    idx = _module_index(root)
    all_tests = sorted(p for paths in idx.values() for p in paths if p.startswith("tests/"))
    graph = None
    profiled = 0
    started = _mono()
    env_first = ""
    env_blocked = ""        # first no-slot/no-RAM result of this portion: the rest of the portion is not profiled

    def skip(bid, reason):
        out["skipped"].append({"backlog_id": bid, "reason": reason})

    # task-id collisions inside the portion or with known IDs (<id> and <id> are both <id>)
    owners: dict[str, list[str]] = {}
    for r in rows:
        if not r["closed_at_head"]:
            owners.setdefault(_task_id(r["backlog_id"]), []).append(r["backlog_id"])
    for k in known_backlog_ids:
        owners.setdefault(_task_id(k), [])
        if k not in owners[_task_id(k)]:
            owners[_task_id(k)].append(k)
    collide = {b: o for o in owners.values() if len(o) > 1 for b in o}

    for r in rows:
        bid = r["backlog_id"]
        if len(out["tasks"]) >= limit:
            break
        if r["closed_at_head"]:
            out["stale"].append(bid)
            continue
        if bid in known_backlog_ids:
            skip(bid, "уже известна")
            continue
        if bid in collide:
            skip(bid, "коллизия id: " + " и ".join(collide[bid]))
            continue
        private = r["private"]
        pfx = "приватная строка (only_opus): " if private else ""
        private_hold = {"backlog_id": bid, "question": "приватная строка (only_opus): звонки, ключи, личное; решить, кто делает"}
        # --- scope: named files, then bare module names
        touch = [f for f in r["mentioned_files"] if _is_src(f)]
        tests = list(r["mentioned_tests"])
        ambiguous = None
        for name, ticked, near in r["bare_names"]:
            if ticked and not near:
                continue
            hits = idx.get(name, [])
            src = [h for h in hits if _is_src(h)]
            tst = [h for h in hits if h.startswith("tests/")]
            found, bucket = (tst, tests) if name.startswith("test_") else (src, touch)
            if len(found) > 1:
                ambiguous = name
                break
            if found and found[0] not in bucket:
                bucket.append(found[0])
        if private and (ambiguous or not (touch or tests)):
            out["holds"].append(private_hold)
            continue
        if ambiguous:
            skip(bid, "неоднозначное имя: " + ambiguous)
            continue
        read_files: list[str] = []
        ctx: dict[str, str] = {}
        named_here = _tests_named_by_id(bid, all_tests)
        suspects = ""
        if not touch and named_here and not private and _screen(F, bid, r["text"])[1]:
            # it will be held anyway: do not spend 30 s of profile and an attempt on it
            out["holds"].append({"backlog_id": bid, "question": _screen(F, bid, r["text"])[1]})
            continue
        if not touch and named_here and profiled < limit:
            left = PORTION_DEADLINE_S - (_mono() - started)
            if left <= 0:
                out["deferred"].append({"backlog_id": bid, "reason": "отложено: дедлайн профилирования порции, строка ждёт следующей порции"})
                continue
            if env_blocked:
                out["deferred"].append({"backlog_id": bid, "reason": "среда: pytest не запущен (%s); строка ждёт следующей порции, попытка не засчитана" % env_blocked[:150]})
                continue
            profiled += 1
            from tools import factory_gate as _G
            kind, payload, fb, pnotes = _localize(root, bid, named_here, idx, all_tests, min(PROFILE_TIMEOUT_S, left),
                                                  wait_deadline=_mono() + max(0.0, min(_G.SLOT_WAIT_S, left)))
            for ev, why in pnotes:
                out["events"].append({"backlog_id": bid, "event": ev, "reason": why[:200]})
                if ev == "profile_neighbours_env" and not env_blocked:    # the second run found no slot/RAM either: stop profiling the portion
                    env_blocked, env_first = why, bid
            if kind == "env":
                env_blocked, env_first = payload or "no pytest slot", env_first or bid
                out["events"].append({"backlog_id": bid, "event": "profile_env", "reason": (payload or "")[:200]})
                out["deferred"].append({"backlog_id": bid, "reason": "среда: pytest не запущен (%s); попытка не засчитана" % (payload or "")[:150]})
                continue
            if fb:
                out["events"].append({"backlog_id": bid, "event": "profile_fallback",
                                      "reason": "sys.monitoring unavailable, sys.setprofile used"})
            if kind == "green":
                out["holds"].append({"backlog_id": bid, "question": pfx + "тест по ID %s зелёный на HEAD — закрыть строку %s или дать новый тест/область?" % (PurePosixPath(named_here[0]).name, bid)})
                continue
            if kind == "red":
                mods, leaders = payload
                top = mods[0][1]
                tied = [m for m in mods if m[1] >= top - 1e-9]
                if len(tied) > MAX_TOUCH:
                    out["holds"].append({"backlog_id": bid, "question": pfx + "локализация неоднозначна: " + "; ".join(
                        "%s (%.2f: %s)" % (m, sc, ", ".join(q for q, _, _ in leaders[m][:3])) for m, sc, _ in tied[:6])})
                    continue
                touch = [m for m, sc, _ in mods if sc >= SECOND_MODULE_RATIO * top][:MAX_TOUCH]
                rest = [m for m, _, _ in mods if m not in touch and not _protected(m)]
                read_files = rest[:1]
                for m in read_files:                 # context_targets act on read_files only (the runner skips touch files)
                    ctx[m] = leaders[m][0][0].split(".")[0]
                names, parts = 0, []
                for m in touch:                      # leaders go into the goal text: the runner picks identifiers from it
                    take = [q for q, _, _ in leaders[m][:max(0, 6 - names)]]
                    names += len(take)
                    if take:
                        parts.append("%s: %s" % (m, ", ".join(take)))
                suspects = " Подозреваемые функции (замер вызовов падающего теста): " + "; ".join(parts)
            else:
                # The profile gave no verdict.  A row is NOT turned into a task by the test's imports (they
                # point at helpers, not at the defect): retry on the next portion, after 3 failures ask Opus.
                why = (payload or kind)[:200]
                out["events"].append({"backlog_id": bid, "event": "profile_unknown" if kind == "unknown" else "profile_empty",
                                      "reason": why})
                if kind == "unknown":
                    n = attempts.get(bid, 0) + 1
                    out["profile_attempts"][bid] = n
                if kind == "unknown" and n < PROFILE_MAX_ATTEMPTS:
                    out["deferred"].append({"backlog_id": bid, "reason": "профиль не удался (%d/%d): %s" % (n, PROFILE_MAX_ATTEMPTS, why)})
                else:
                    # "empty" = the run finished and no source function was called: a deterministic result,
                    # retrying cannot change it, so ask at once.
                    if graph is None:
                        from tools.affected_tests import Graph
                        graph = Graph(root)
                    hints = sorted({d for t in named_here for d in graph.edges.get(t, ()) if _is_src(d)})
                    head = ("профиль не удался (%s)" % why) if kind == "unknown" else "профиль прошёл, но функций исходников в вызовах цели нет"
                    out["holds"].append({"backlog_id": bid, "question": pfx + head + ": дать область? Кандидаты по импортам теста (подсказка, не область): %s" % (", ".join(hints[:6]) or "нет")})
                continue
        if not touch and named_here and profiled >= limit:
            out["deferred"].append({"backlog_id": bid, "reason": "отложено: лимит профилей порции (%d)" % limit})
            continue
        if not touch and tests:
            if graph is None:
                from tools.affected_tests import Graph
                graph = Graph(root)
            mods = sorted({d for t in tests for d in graph.edges.get(t, ()) if _is_src(d)})
            if len(mods) > 2:
                out["holds"].append({"backlog_id": bid, "question": pfx + "уточнить область: тест(ы) %s импортируют %d модулей (%s); какие менять?" % (", ".join(tests), len(mods), ", ".join(mods[:6]))})
                continue
            touch = mods
        if not touch:
            if private:
                out["holds"].append(private_hold)
            else:
                skip(bid, "нет упомянутых файлов или модулей области")
            continue
        prot = [f for f in touch if _protected(f)]
        if prot:
            out["holds"].append({"backlog_id": bid, "question": pfx + "область защищена воротами: " + ", ".join(prot) + "; решает Opus"})
            continue
        if len(touch) > MAX_TOUCH or r["text_len"] > MAX_TEXT:
            # Automatic decomposition: by files (import-affine groups of <= 3), or one file per part when only the
            # text is too long.  Not possible honestly -> the Opus question as before.
            chunks = None
            if not private and len(touch) > MAX_TOUCH:
                if graph is None:
                    from tools.affected_tests import Graph
                    graph = Graph(root)
                chunks = _chunk_files(root, touch, graph)
            elif not private and len(touch) >= 2:
                chunks = [[f] for f in sorted(touch)]
            if chunks and len(chunks) <= MAX_PARTS:
                ptext, question = _screen(F, bid, r["text"])
                if question:
                    out["holds"].append({"backlog_id": bid, "question": question})
                    continue
                pairs, record, error = _children(F, root, bid, _task_id(bid), r["priority"], ptext, chunks, known_backlog_ids, named_here, known_parts)
                if error:
                    skip(bid, error)
                    continue
                if not pairs:
                    out["parents"].append(record)      # the consumer merges by backlog_id: idempotent
                    skip(bid, "уже известна (все части)")
                    continue
                take = []
                for pair in pairs:
                    if len(out["tasks"]) + sum(len(x) for x in take) + len(pair) > limit:
                        break
                    take.append(pair)
                if not take:
                    if not out["tasks"]:
                        out["holds"].append({"backlog_id": bid, "question": "limit меньше первой части (%d задач при limit %d): поднять limit или ответить: answer --backlog-id %s --touch <файл> --tests <тест> --note \"<указание кодеру>\"" % (len(pairs[0]), limit, bid)})
                        continue
                    out["deferred"].append({"backlog_id": bid, "reason": "отложено: не помещается в limit"})
                    break
                flat = [t for pair in take for t in pair]
                try:
                    F.read_plan(flat)
                except F.InvalidPlan as e:
                    skip(bid, "план не принял части: %s" % e)
                    continue
                out["tasks"].extend(flat)
                out["parents"].append(record)
                if len(take) < len(pairs):
                    out["deferred"].append({"backlog_id": bid, "reason": "отложено: остальные части не поместились в limit"})
                continue
            why = ("затронуто %d файлов: %s" % (len(touch), ", ".join(touch)) if len(touch) > MAX_TOUCH
                   else "текст %d символов, предел %d" % (r["text_len"], MAX_TEXT))
            if chunks and len(chunks) > MAX_PARTS:
                why += "; частей получилось больше %d" % MAX_PARTS
            out["holds"].append({"backlog_id": bid, "question": pfx + "разбить на подзадачи: " + why})
            continue
        tid = _task_id(bid)
        named = _tests_named_by_id(bid, all_tests)
        vnamed = sorted(t for t in named if PurePosixPath(t).name.lower().startswith("test_v_"))
        mentioned = sorted(tests)
        slug = tid[3:].lower()
        tpath = "tests/test_factory_%s.py" % slug
        if not named and (root / tpath).is_file():
            # An existing factory test file counts only when it carries this very ID (a whole token);
            # otherwise it belongs to another row (<id> / <id> slug clash): never reuse, never overwrite.
            try:
                own = bool(id_query.pattern(bid).search((root / tpath).read_text(encoding="utf-8", errors="replace")))
            except OSError:
                own = False
            if not own:
                skip(bid, "файл теста занят чужой строкой: " + tpath)
                continue
            named = [tpath]
        text = F.redact(r["text"]).strip("`* ") or bid
        if not private:
            text, question = _screen(F, bid, r["text"])
            if question:
                out["holds"].append({"backlog_id": bid, "question": question})
                continue
        group = []
        base = {"backlog_id": bid, "priority": r["priority"] or "P4", "privacy_safe": not private,
                "only_opus": private, "read_files": [], "task_type": "patch"}
        deps = []
        # The red target of a task is ONLY a test named by the row's ID (or the new test).  Every
        # other test the row mentions is green or red for foreign reasons on the base: it stays out of
        # `tests` (the gate needs ALL of them green, and a green one hides already_green) and is only
        # named in the goal; the runner compares the neighbours with the base by failure names.
        extra = [m for m in mentioned if m not in named]
        ordered: list[str] = []
        for t in vnamed + sorted(named):
            if t not in ordered:
                ordered.append(t)
        if not named:
            goal = ("Написать тест: он должен падать на текущем коде из-за дефекта строки и проходить после "
                    "исправления. Первой строкой файла напиши комментарий «# factory-backlog-id: %s».%s "
                    "Упомянутые тесты (не дублировать): %s. Строка: %s" % (bid, _import_hint(touch), ", ".join(extra) or "нет", text))
            group.append(dict(base, id=tid + "_test", title=("Тест для %s" % bid)[:120],
                              goal=goal[:1500], depends_on=[],
                              touch_files=[tpath], tests=[tpath], kind="unit_test",
                              read_files=_test_reads(touch, read_files)))
            ordered = [tpath]
            deps = [tid + "_test"]
        tail = suspects + ("" if not extra else " Проверь, что не ломаешь: " + ", ".join(extra))
        main_goal = text[:max(0, MAX_TEXT - len(tail))] + tail
        group.append(dict(base, id=tid, title=(bid + ": " + text)[:120], goal=main_goal[:MAX_TEXT], depends_on=deps,
                          touch_files=touch, tests=ordered[:MAX_TESTS], kind="code"))
        if read_files:
            group[-1]["read_files"] = read_files
            group[-1]["context_targets"] = ctx
        if len(out["tasks"]) + len(group) > limit:
            if not out["tasks"]:      # it would never fit: a question, not an endless deferral
                out["holds"].append({"backlog_id": bid, "question": "limit меньше группы (%d задач при limit %d): поднять limit или ответить: answer --backlog-id %s --touch <файл> --tests <тест> --note \"<указание кодеру>\"" % (len(group), limit, bid)})
                continue
            out["deferred"].append({"backlog_id": bid, "reason": "отложено: не помещается в limit"})
            break
        try:
            F.read_plan(group)
        except F.InvalidPlan as e:
            skip(bid, "план не принял: %s" % e)
            continue
        out["tasks"].extend(group)
        if private:
            out["holds"].append(private_hold)
    # consecutive portions that could not profile for the environment: a silent endless wait becomes visible (no strike)
    out["env_streak"] = (int(env_streak or 0) + 1) if env_blocked else 0
    if out["env_streak"] >= ENV_STREAK_MAX:
        out["events"].append({"backlog_id": env_first, "event": "env_starved", "reason": "%d порций подряд: %s" % (out["env_streak"], env_blocked[:150])})
        out["holds"].append({"backlog_id": ENV_HOLD_ID, "question": "среда не даёт pytest: RAM/слоты (%d порций подряд, строки ждут без попыток, начиная с %s): освободить память/слоты или поднять лимит ожидания?" % (out["env_streak"], env_first)})
    return out


def active_backlog_review(markdown: str) -> dict:
    """Review-only index of the OPEN rows of the current BACKLOG_ECHO.md section 4.

    Closed, waiting, duplicate and refused rows are no longer imported (the old import ignored the
    backlog status).  Dependencies in prose are still not a trusted DAG; paths are not resolved
    here (no repo root): use parse_open_rows for that.  ``id`` is the backlog ID; round 2 must give
    plan tasks their own id (agent_factory.TASK_ID forbids Cyrillic and dots) and keep backlog_id."""
    allrows = parse_section4(markdown)
    unknown = [r for r in allrows if r["unknown"]]
    rows = [r for r in allrows if r["open"]]
    rows.sort(key=_sort_key)
    tasks = [{
        "id": r["backlog_id"], "title": _safe_title(r),
        "priority": r["priority"], "backlog_state": "" if r["private"] else _public_state(r["state"]),
        "status": "NEEDS_TRIAGE", "accepted": False, "privacy_safe": False, "only_opus": False,
        "depends_on": [], "touch_files": [], "tests": [], "source": "BACKLOG_ECHO.md",
        "locations": r["locations"],
        "review_required": [
            "identify source/test paths and dependent tasks (triage_portion)",
            "approve privacy classification and model assignment",
        ],
    } for r in rows]
    return {
        "schema": "factory-review-v1",
        "origin": "BACKLOG_ECHO.md section 4",
        "sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        "not_executable": True,
        "skipped_unknown": [{"backlog_id": r["backlog_id"], "state": "" if r["private"] else _public_state(r["state"], 60)}
                            for r in unknown],
        "tasks": tasks,
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--source-backlog", type=Path, required=True,
                   help="the live BACKLOG_ECHO.md (it is not inside the repository)")
    p.add_argument("--repo-root", type=Path, default=None,
                   help="drop rows closed by a '<ID>:' commit at HEAD of this repository")
    args = p.parse_args(argv)
    from tools.backlog_register import register
    result = suggestions(register())
    backlog = active_backlog_review(args.source_backlog.read_bytes().decode("utf-8-sig"))
    if args.repo_root is not None:
        backlog["tasks"] = [t for t in backlog["tasks"] if not is_closed_at_head(t["id"], args.repo_root)]
        closed_check = "head:" + _git(args.repo_root, "rev-parse", "HEAD").strip()
    else:
        closed_check = "skipped"
        print("WARNING: no --repo-root, rows closed at HEAD are NOT filtered", file=sys.stderr)
    common = {task["id"] for task in result["tasks"]}
    result["tasks"].extend(item for item in backlog["tasks"] if item["id"] not in common)
    result["backlog_sha256"] = backlog["sha256"]
    result["closed_check"] = closed_check
    result["skipped_unknown"] = backlog["skipped_unknown"]
    result["not_executable"] = True
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tasks_needing_review": len(result["tasks"]),
                      "closed_check": closed_check,
                      "skipped_unknown": len(result["skipped_unknown"]),
                      "executable": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()

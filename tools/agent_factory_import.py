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
import math
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

try:
    from tools import factory_autofeed as AF
except ImportError:      # the public mirror (tools.factory_mirror.MODULES) does not carry the feed: the old path, no sweep, no sidecar
    from types import SimpleNamespace as _NS
    AF = _NS(closed_ids=lambda root: set(), sync_closed=lambda root, path=None: {"path": None, "added": [], "total": 0},
             load_sweep=lambda root, sweep=None: {}, guard_map=lambda sweep, ids: {}, verdict=lambda entries: None,
             red_paths=lambda entries: [])
try:
    from tools import factory_closures as FC
except ImportError:      # the public mirror may not carry the closures writer: no table, git alone decides
    FC = None
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
# "реализовано в ветке X" waits for a merge, not a coder (live 19.11 21:43: <id> became a test task and the free model
# invented a defect); "не реализовано" stays open
WAITING = re.compile(_B % r"ждёт|ждет|после|зависит|нужен телефон|заблокирован\w*|блокирован\w*|отложен\w*|дубль|отказ"
                     r"|(?<!не )реализован\w*", re.I)
# a cell part that starts with "дубль"/"отказ" (after a [..] tag) marks the row as no task (live 19.11 20:13: <id>'s
# notes said "**[sync17.11]** дубль: код и тесты уже на базе" and its test was junk); the formulation is never such a mark
_DUP_MARK = re.compile(r"^[\s*`]*(?:\[[^\]]*\][\s*`]*)?(?:дубль|отказ)\b", re.I)


def _marked_duplicate(cells: list) -> bool:
    return any(_DUP_MARK.match(part) for cell in cells for part in cell.split(" · "))


# A port (live 20.11): "реализовано на ветке ... `<sha>`" waited for a merge of an old branch that never comes (the
# unified code is rebuilt from inside, the old layout is not merged), so 22 rows waited for good while their guard
# tests are red on the head. With the commit named and no other wait in the state, the row is OPEN as a port task
# (factory_port: the commit's diff is the coder's reference); without a commit it still waits.
_IMPLEMENTED = re.compile(r"(?<![\w])(?<!не )реализован\w*(?![\w])", re.I)


def _port_of(state: str) -> str:
    from tools.factory_port import port_sha
    sha = port_sha(state)
    if not sha or STRONG_WAIT.search(state):
        return ""
    return "" if any(WAITING.search(_IMPLEMENTED.sub("", h)) for h in _heads(state)) else sha
STRONG_WAIT = re.compile(_B % r"нужен телефон|ждёт записи\w*|ждет записи\w*|ждёт владельца|ждет владельца", re.I)  # whole state
CLOSED = re.compile(r"(?<![\w])(?<!не )(?:сделано|закрыто|готово|выложено|выполнено)(?![\w])", re.I)
OPEN_WORD = re.compile(r"(?<![\w])(?:не сделан\w*|не начат\w*|нов\w*|откры\w*|обязательство|улучшение|блокер|частично|регресс\w*|open|new)(?![\w])", re.I)
CLASS_LABEL = re.compile(r"^\W*(?:обязательство|улучшение|блокер)\W*$", re.I)
# A Russian phone number: 8 or +7 or 7, an area/operator code 3xx 4xx 8xx 9xx, 11 digits in all (separators allowed), or
# the city form: a 3-4 digit code in brackets, then 7 digits.  The ONE owner of the phone rule: eleven digits starting
# with 80 are a size in bytes, not a number.
PHONE = re.compile(r"(?<![\w.])(?:(?:\+7|[78])[\s(-]*[3489]\d{2}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}"
                   r"|\(\s*[3489]\d{2,3}\s*\)[\s.-]*\d{3}[\s-]*\d{2}[\s-]*\d{2})(?!\d)")
# 21.11 order: only passwords, keys, tokens, .env, SECRETS_LOCAL, call recordings and call logs/transcripts are private.  A row that
# merely mentions a call, the owner, the phone, proxy or the call logic is an ordinary code row (the owner's <private-marker>/<private-marker> markers, "the
# owner said", "personal data" are gone from this list); a literal phone number, e-mail and profile folder stay (identifiers).
PRIVATE = re.compile(_B % (
    r"запис\w*\s+(?:\w+\s+)?(?:звонк|разговор|аудио|голос)\w*"                    # recordings of calls and talks
    r"|(?:журнал\w*|лог(?:и|ов|ами)?)\s+(?:\w+\s+)?звонк\w*|call[- ]?(?:logs?|recordings?)|(?:voice|audio)[- ]?recordings?"   # call logs ("логика звонка" is code)
    r"|голос\w*\s+запис\w*"                                                       # a voice recording
    r"|транскрипт\w*\s+(?:\w+\s+)?(?:звонк|разговор|запис)\w*|расшифровк\w*\s+(?:\w+\s+)?(?:звонк|разговор|диалог)\w*|аудиозапис\w*"
    r"|личн\w*\s+(?:\w+\s+)?(?:аудио|запис|диалог|разговор|голос)\w*"             # personal audio and dialogue
    r"|SECRETS_LOCAL|evidence[\\/][\w./\\-]*\.(?:wav|mp3|m4a|ogg)"                # the secrets folder, evidence audio
    r"|/home/[\w.-]+|[A-Za-z]:[\\/]Users[\\/][\w.-]+"                                      # a person's home folder
    r"|" + PHONE.pattern + r"|[\w.+-]+@[\w-]+\.[\w.-]+"                                  # phone numbers (the one owner: PHONE), e-mail
    r"|api[- ]?keys?|(?:private|secret|access)[- ]keys?|api[- ]?ключ\w*|ключ\w*\s+(?:api|доступа|канал\w*|провайдер\w*)|секрет(?:ы|ов|а|у|ом|е|ами)?|парол\w*|\.env"   # keys, tokens, passwords
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
MIN_PUBLIC_CHARS = 30    # 60 -> 30 (21.11): a short technical wording is a goal
SCREEN_OPEN = frozenset(("quote", "time"))   # residue classes that no longer stop a goal (the owner role word: see screen)
MIN_ROW_TEXT = 20     # a row text shorter than one short sentence (a bare priority, one word, nothing) is a question
                      # for Opus, never a goal; 35 characters such as "the controller is silent on a neighbour" are a task


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
    """"Ваши слова 14:36 (<id>):" and the like.  With a quote after it only the label (and its time/reference/
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


def _plain(text: str) -> str:
    """The text without pure-code backticked pieces (identifiers, paths, calls)."""
    return re.sub(r"`[^`\n]*`", lambda m: " " if _code_span(m.group(0)) else m.group(0), text)


def _name_hit(text: str) -> bool:
    """The profile name of this machine's person is in the text (anywhere in a token; product terms about owners are not a name)."""
    owned = _PRODUCT_OWNER.sub(" ", _plain(text))
    return any(_name_pattern(n).search(owned) for n in _owner_names())


def residue(text: str) -> list[str]:
    """Classes of owner material that survived the cuts: "quote", "time", "owner", "speech", "person", "debris".
    Empty = nothing found.  The caller must not send a text with a non-empty residue to an external model.
    Quotes, times and the owner's names are looked for EVERYWHERE, inside backticks too; only pure code (a backticked
    piece without Cyrillic letters: identifiers, paths, calls) is skipped.  Speech and pronouns are not looked for
    in a backticked piece of fewer than 3 Cyrillic words (``вы`` in an API note), and a list of 3+ pronoun forms is
    a list, not a person."""
    whole = text                          # debris is judged on the text as it stands: "(`x`)" is a bracket with code, not a stump
    plain = _plain(text)
    # a backticked Cyrillic phrase of 2+ words is ordinary text (`хочу быстро` is speech with or without quotes);
    # one word (`вы` in an API note) and code are not looked at for speech and pronouns
    words_only = re.sub(r"`[^`\n]*`", lambda m: m.group(0) if len(re.findall(r"[А-Яа-яЁё]{2,}", m.group(0))) >= 2 else " ", text)
    out = []
    if _RES_QUOTE.search(plain):
        out.append("quote")
    if _RES_TIME.search(plain):
        out.append("time")
    owned = _PRODUCT_OWNER.sub(" ", plain)
    if _RES_OWNER.search(owned) or _name_hit(text):
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
    fewer than ``min_chars`` characters of meaningful text without "…" and code).  An uncut text is never "cut".
    21.11: an owner quote, a time or L-reference and the word "owner" are not private (only secrets, recordings and
    dialogue are): they do not stop a goal.  Speech, a person, debris and the machine's profile name still do."""
    from tools import agent_factory as _F
    clean, cut = _cut(_F.redact(text).strip("`* "))
    classes = [c for c in residue(clean) if c not in SCREEN_OPEN and not (c == "owner" and not _name_hit(clean))]
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
    "…", '…'; an unpaired one up to the end of its sentence), line references (<id>, "(<id>, <id>)"), clock times
    (14:36, 22:43:45, 14:36:, "в 14.36", "09.15 МСК"; not 3.14 or 7.8.27), brackets holding only dates/times/
    references, and labels like "Ваши слова 14:36 (<id>):" (without a quote after the label the sentence goes)
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
    seg = segs[len(heads) - 1]
    if heads[-1].strip().lower() == "действует" and ":" in seg:   # "действует: ждёт итога <id>" - the tail decides
        heads.append(_head(seg.split(":", 1)[1]))
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


OWNED_ROW = re.compile(r"(?:fac|cl)-\d+(?:[.-]\d+)*")   # 8.1: fac-N = the factory's own work, cl-N = the coordinator's
OWNER_CELL = re.compile(r"как сказал владелец", re.I)    # <id>: the row's own cell with the owner's wording
DOC_MARK = re.compile(r"\(док\.")                          # <id>: the backlog marks documentation evidence "(док.: ...)"


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
        if not (id_query.TOKEN.fullmatch(ident) or OWNED_ROW.fullmatch(ident)):
            if ident.upper() in ("ID", "N"):
                header = cells
            continue
        if ident in seen:
            seen[ident]["locations"].append({"line": line_no, "section": section})
            continue
        hdr = header or []
        pi = _find_col(hdr, "приоритет", "пр.", "priority")
        si = _find_col(hdr, "состояние", "state", "status")
        ti = _find_col(hdr, "формулировка", "что", "задача", "title", "причина")
        for k in range(2, min(len(cells), 6)):        # per-row layout: a bare P-cell, state right after it
            if PRIO_CELL.fullmatch(cells[k].strip("`* ")):
                pi, si = k, (k + 1 if k + 1 < len(cells) else None)
                break
        pm = PRIO.search(cells[pi]) if pi is not None and pi < len(cells) else None
        state = cells[si] if si is not None and si < len(cells) else ""
        row_text = " | ".join(cells)
        if ti is None or ti >= len(cells):
            # no header names the text: the first cell that is neither the priority nor the state (acceptance 20.11:
            # the header "ID | Пр. | Причина" gave 12 rows their priority cell <id>/<id> as the text, cells[1] by default)
            ti = next((k for k in range(1, len(cells)) if k not in (pi, si)
                       and not PRIO_CELL.fullmatch(cells[k].strip("`* "))), None)
        text = cells[ti] if ti is not None else ""
        ai = _find_col(hdr, "acceptance", "проверка")
        acceptance = cells[ai] if ai is not None and ai < len(cells) and ai != ti else ""
        owner_cell = next((c.split(":", 1)[-1].strip() for k, c in enumerate(cells) if k and OWNER_CELL.search(c)), "")
        cls = classify_state(state if si is not None else row_text, si is not None)
        port_from = _port_of(state) if cls == "waiting" and si is not None else ""
        if port_from:
            cls = "open"
        if cls == "open" and _marked_duplicate([c for k, c in enumerate(cells)
                                                if k != 0 and k != (ti if ti is not None else 1)]):
            cls, port_from = "waiting", ""
        seen[ident] = {"backlog_id": ident, "priority": "P" + pm.group(1) if pm else None,
                       "state": state, "text": text, "row": row_text, "section": section,
                       "acceptance": acceptance, "owner_cell": owner_cell, "doc_marks": len(DOC_MARK.findall(row_text)),
                       "line": line_no, "locations": [{"line": line_no, "section": section}],
                       "open": cls == "open", "unknown": cls == "unknown", "port_from": port_from,
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
    ``wave <id> <id>: ..`` close nothing (``Revert``/``wave`` are not IDs)."""
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
    return cached[1] | AF.closed_ids(root)        # + the sidecar closed_by_commit.json (a record that outlives the history)


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
    """Open rows of BACKLOG_ECHO.md section 4, ordered <id> -> <id> -> no priority, then by ID.

    Each item: {backlog_id, priority, state, text, mentioned_files, mentioned_tests, private}
    (+ section, line, closed_at_head).  A private row (call records, keys, .env, personal data) has
    empty ``state`` and ``text``.  Rows closed at HEAD by a ``<ID>:`` commit are dropped unless
    include_closed=True.  The result's ``.skipped_unknown`` lists rows with unrecognised state wording.
    Raises ClosedCheckError when git cannot be read."""
    markdown = Path(backlog_path).read_bytes().decode("utf-8-sig")
    out = OpenRows()
    tabled = FC.table_ids(backlog_path) if FC is not None else {}      # the closures table of the backlog: a commit-backed record
    for r in parse_section4(markdown):
        if r["unknown"]:
            out.skipped_unknown.append({"backlog_id": r["backlog_id"],
                                        "state": "" if r["private"] else _public_state(r["state"], 60)})
        if not r["open"]:
            continue
        closed = r["backlog_id"] in tabled or is_closed_at_head(r["backlog_id"], repo_root)
        if closed and not include_closed:
            continue
        row = r["row"].replace("\\", "/")
        files, tests = mentioned_paths(row, repo_root)
        out.append({"backlog_id": r["backlog_id"], "priority": r["priority"],
                    "state": "" if r["private"] else _public_state(r["state"]),
                    "text": "" if r["private"] else r["text"],
                    "private": r["private"], "mentioned_files": files, "mentioned_tests": tests,
                    "section": r["section"], "line": r["line"], "closed_at_head": closed,
                    "text_len": len(r["text"]), "bare_names": _bare_names(row), "port_from": r.get("port_from", ""),
                    "acceptance": "" if r["private"] else r["acceptance"], "owner_cell": "" if r["private"] else r["owner_cell"],
                    "doc_marks": r["doc_marks"]})
    out.sort(key=_sort_key)
    return out


_CYR = dict(zip("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ", "A B V G D E E ZH Z I Y K L M N O P R S T U F KH TS CH SH SCH _ Y _ E YU YA".split()))
_CYR.update({k.lower(): v.lower() for k, v in list(_CYR.items())})
MAX_TOUCH = 5           # 3 -> 5 (21.11): the prompt (factory_channels.PROMPT_LIMIT_CHARS) is the real bound, not the file count
MAX_TEXT = 6000          # 1500 -> 6000 (21.11)
MAX_TESTS = 5           # 3 -> 5 (21.11)


def _translit(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", "".join(_CYR.get(c, c) for c in text))


def _task_id(backlog_id: str) -> str:
    # "#" (a part of a cut row: ID#1) gets its own escape, so ID#1 never equals ID-1, ID.1 or ID_1
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
    spelling of the ID, whole token: <id> does not match <id>).  Order: test_v_<ID> first, then by name."""
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
ENV_STREAK_MAX = 5           # consecutive portions without pytest (no slot / no RAM): an event "env_starved" is written, nobody is asked (21.11: tests run in the cloud)
_mono = time.monotonic       # seam for tests with a fake clock
PORTION_DEADLINE_S = 600      # 150 -> 600 (21.11: triage is a model call, not heavy); after this the remaining rows wait for the next portion instead of being profiled
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




def _cut_text(text: str, n: int) -> str:
    """The row text for a part: whole when short, else up to ``n`` characters ending at a sentence boundary."""
    if len(text) <= n:
        return text
    cut = text[:n]
    end = max(cut.rfind(". "), cut.rfind("; "), cut.rfind(", "))
    return (cut[:end] if end > n // 2 else cut).rstrip(" .,;") + " …"




def _test_reads(files, extra=()) -> list[str]:
    """What the author of a NEW test must see: the code the test is about (the code part's touch files, then its read
    files). Live 19.11 18:06-18:14: unit_test tasks had read_files=[], the models saw no code at all, imported invented
    modules ('factory') or wrote 'assert False' stubs, and every one of them failed."""
    out: list[str] = []
    for f in list(files) + list(extra):
        if f.endswith(".py") and f not in out:
            out.append(f)
    return out[:MAX_TOUCH + 1]


EXAMPLE_MAX_CHARS = 12000


def _example_test(root, files, mentioned, graph):
    """ONE existing test of the code a new test is about: the example of its setup (fixtures, fakes, temp files).
    Live 19.11 23:40: the authors saw the module but no test of it; their tests crashed on sqlite or hung 30 s.
    The test the row mentions first, else the smallest test importing a touch file directly; never a
    factory-written test (tests/test_factory_*), never a file over EXAMPLE_MAX_CHARS bytes. None when there is none."""
    root = Path(root)
    cands = [t for t in mentioned if t.endswith(".py")]
    if graph is not None:
        direct = {t for f in files for t in graph.rev.get(f, ()) if graph.is_test(t)}
        cands += sorted(direct, key=lambda t: ((root / t).stat().st_size if (root / t).is_file() else 10 ** 9, t))
    for t in cands:
        p = root / t
        if t.startswith("tests/test_factory_") or not p.is_file():
            continue
        if p.stat().st_size <= EXAMPLE_MAX_CHARS:
            return t
    return None


def _import_hint(files) -> str:
    """' Проверяемый код: echo_sync.fast_text (импортируй из него).' for the goal of a new test, '' without code."""
    # a package's __init__.py is imported by the package name (echo_sync.__init__ would be a second copy)
    mods = [re.sub(r"\.__init__$", "", f[:-3].replace("/", ".")) for f in files
            if f.endswith(".py") and not f.startswith("tests/")]
    return (" Проверяемый код: %s (импортируй из этих модулей, других не выдумывай)." % ", ".join(mods)) if mods else ""


def _trace_of(trace, bid):
    """The trace entries of one row from the caller's {backlog_id: entries}; a damaged value is no trace."""
    got = trace.get(bid) if isinstance(trace, dict) else None
    return got if isinstance(got, (list, tuple)) else ()


def _narrow(trace, files) -> list[str]:
    """<id>: the functions of ``files`` that the failing guard ran (the cloud trace: (rel, qualname, line) entries of
    factory_gate GateResult.path / base_red.result.path), sorted, at most 12; [] when the trace names none."""
    own = set(files)
    return sorted({str(q) for rel, q, *_ in (trace or ()) if rel in own})[:12]




def _screen(F, bid: str, raw_text: str):
    """(text, hold question or None) for a row: the text as it may go out, or why it may not.  Built on screen(),
    the one decision; used before profiling and before the task is made."""
    goal, classes = screen(raw_text)
    if goal is not None:
        size = len(re.sub(r"[`*\s]+", " ", goal).strip())
        if size >= MIN_ROW_TEXT:
            return goal, None
        # a bare priority, a bold title or nothing is no task text: the free model made up defects from "<id>"
        return None, "у строки %s нет формулировки задачи (%d знаков: %s); дать текст задачи или закрыть?" % (
            bid, size, " ".join(goal.split()[:8]) or "пусто")
    rest = _cut(F.redact(raw_text).strip("`* "))[0]
    # a retold call, quote or named owner is never echoed, not even into the question line for Opus
    shown = " ".join(rest.split()[:8]) if set(classes) <= {"debris", "time", "cut"} and rest else "(текст скрыт)"
    why = "формулировка разрезана, дать техническую" if classes == ["cut"] else "остаток владельца/речи/разговора (%s)" % ", ".join(classes)
    return None, "текст строки %s — %s; дать техническую формулировку? Осталось: %s" % (bid, why, shown)


def _port_task(r: dict, root: Path, all_tests: list) -> dict:
    """A row built on an old branch (r["port_from"]): ONE code task that brings the commit's behaviour over, its tests
    the row's own guard test (tests/**/test_v_<ID>.py, red on the head), its files the ones that define the functions
    the commit changed (factory_port; the coder sees the commit's diff as a reference). Never a test task: a port with
    no guard test, or whose functions are defined nowhere now, is a question (live 19.11 21:43: such a row as a test
    task got a defect the free model invented). Returns {"task": row} or {"hold": question}."""
    from tools import agent_factory as F
    from tools import factory_port
    bid, sha, private = r["backlog_id"], r["port_from"], r["private"]
    pfx = "приватная строка (only_opus): " if private else ""
    guard = [t for t in _tests_named_by_id(bid, all_tests) if PurePosixPath(t).name.lower().startswith("test_v_")]
    if not guard:
        return {"hold": pfx + "перенос `%s`: у строки нет теста-стража tests/**/test_v_%s.py; дать тест или закрыть"
                % (sha, bid)}
    names = factory_port.changed_names(root, sha)
    touch = [f for f in factory_port.locate(root, names, limit=2) if _is_src(f)]
    if not touch:
        return {"hold": pfx + "перенос `%s`: функции коммита (%s) в текущем коде не найдены; какие файлы менять?"
                % (sha, ", ".join(names[:6]) or "нет")}
    text = F.redact(r["text"]).strip("`* ") or bid
    if not private:
        text, question = _screen(F, bid, r["text"])
        if question:
            return {"hold": question}
    goal = ("Перенести в единую архитектуру поведение коммита %s со старой ветки (его дифф дан ниже как образец): "
            "тест %s должен пройти. Строка: %s" % (sha, guard[0], text))
    return {"task": {"backlog_id": bid, "priority": r["priority"] or "P4", "privacy_safe": not private,
                     "only_opus": private, "read_files": [], "task_type": "patch", "id": _task_id(bid),
                     "title": (bid + ": " + text)[:120], "goal": goal[:MAX_TEXT], "depends_on": [],
                     "touch_files": touch, "tests": guard[:1], "kind": "code", "port_from": sha}}


def _trace_touch(root: Path, bid: str, text: str, guards: list, graph=None) -> list:
    """Provisional writing scope of a row that is red in the cloud and names no file (at most 2 existing, writable
    source files): the best candidates of the row (candidate_files, any strength: the red guard proves a code defect),
    else the source modules the guard files import.  [] when there is nothing."""
    try:
        picks = [c[0] for c in candidate_files(root, bid, text) if c[1] >= CAND_MIN]
    except Exception:
        picks = []
    picks = [f for f in picks if _is_src(f) and _exists(root, f) and not _protected(f)]
    if not picks:
        try:
            if graph is None:
                from tools.affected_tests import Graph
                graph = Graph(root)
            picks = sorted({d for t in guards for d in graph.edges.get(t, ()) if _is_src(d) and _exists(root, d) and not _protected(d)})
        except Exception:
            picks = []
    return picks[:2]


# ---- <id>: candidate files for a row that names no file (deterministic, no model) ----
SCOPE_K = 5                  # candidates in a hold
CAND_MIN = 1.0               # the best candidate must reach this score, or the row stays a skip
STRONG_TAGS = ("id", "git", "sym")   # <id>: any row becomes a candidates hold only with one of these
SYM_MAX_FILES = 2            # <id>: a name without an inner "_" that more files define is a common word, not a sym
BRIDGE_MAX_MODULES = 4      # a .md paragraph naming more modules is a list or a table: it ties no words to a module
_SCOPE_CACHE: dict = {}      # one entry per root: (HEAD sha, index)
_QUOTES = re.compile(r"^[rRbBuUfF]{0,2}('''|\"\"\"|'|\")|('''|\"\"\"|'|\")$")   # a string token -> its text
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}|[А-Яа-яЁё]{4,}")
_ROW_IDENT = re.compile(r"`([A-Za-z_][\w.]*)(?:\(\))?`|(?<![\w.])([a-z_][a-z0-9]*_[a-z0-9_]+)(?![\w])")
_MOD_REF = re.compile(r"(?<![\w])([a-z][a-z0-9_]{3,})(?:\.py)?(?![\w])")
_STOP = frozenset("""это что как для или при без над под его она они все если чтобы когда после через только тест тесты
строка строки код файл файлы модуль задача задачи self none true false return
the and for not with from import def class""".split())


def _stem(word: str) -> str:
    """A Russian word cut to its first letters (база/базу/базы -> баз, законов/закона -> закон); English as is."""
    w = word.lower().replace("ё", "е")
    if "а" <= w[:1] <= "я":
        return w[:5] if len(w) >= 6 else w[:-1]
    return w


def _words(text: str) -> list:
    """Word stems of a text, identifiers also by their parts (quick_math -> quick_math, quick, math)."""
    out = []
    for w in _WORD.findall(text or ""):
        for part in [w] + (w.strip("_").split("_") if "_" in w.strip("_") else []):
            if len(part) >= 3 and part.lower() not in _STOP:
                out.append(_stem(part))
    return out


def _bm25(query, tf, length, df, n, avg) -> float:
    s = 0.0
    for w in query:
        f = tf.get(w, 0)
        if f:
            s += math.log(1 + (n - df[w] + .5) / (df[w] + .5)) * f * 2.2 / (f + 1.2 * (.25 + .75 * length / avg))
    return s


def _bm25_field(profiles) -> dict:
    """{tf, len, df, n, avg} of per-file word profiles: what _bm25 scores against."""
    from collections import Counter
    df = Counter(w for tf in profiles.values() for w in tf)
    lens = {f: sum(tf.values()) or 1 for f, tf in profiles.items()}
    return {"tf": profiles, "len": lens, "df": df, "n": max(1, len(profiles)),
            "avg": (sum(lens.values()) / len(lens)) if lens else 1.0}


def _census_field(path, only=None) -> dict:
    """<id>: the owner census (tools/owner_census_sites.ndjson: family, owner, file, func, decides in Russian) as one word
    profile per file, so the Russian row meets the code on what each place DECIDES.  Missing or damaged file -> empty."""
    from collections import Counter
    prof: dict = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        f = d.get("file") if isinstance(d, dict) else None
        if isinstance(f, str) and (only is None or f in only):
            prof.setdefault(f, Counter()).update(_words(" ".join(str(d.get(k) or "") for k in ("family", "owner", "func", "decides"))))
    return _bm25_field(prof)


CENSUS_WEIGHT = 0.5


def census_rank(text: str, path, k: int = SCOPE_K) -> list:
    """[(file, score)] best first of the census files against the row text (<id>, the same one candidate_files uses)."""
    f = _census_field(path)
    q = set(_words(text))
    ranked = sorted(((rel, _bm25(q, tf, f["len"][rel], f["df"], f["n"], f["avg"])) for rel, tf in f["tf"].items()),
                    key=lambda kv: (-kv[1], kv[0]))
    return [(rel, round(sc, 2)) for rel, sc in ranked if sc > 0][:k]


def _scope_index(root) -> dict:
    """What candidate_files ranks by, built once per (root, HEAD).  Files: echo_sync/** and tools/** that may be a
    scope (never tests, a package __init__ or a gate-protected file).  Per file: the ID tokens of its text, the names
    it defines (functions, classes, top-level names, attributes, its stem), a word profile of its comments, docstrings
    and names, and a bridge profile: the words of the paragraphs of the project's own .md files that name it (the
    Russian backlog meets the English code there).  Plus the files changed by the commits whose message names an ID."""
    import io
    import tokenize
    from collections import Counter
    root = Path(root)
    try:
        head = _git(root, "rev-parse", "HEAD").strip()
    except ClosedCheckError:
        head = ""
    cached = _SCOPE_CACHE.get(str(root))
    if cached is not None and head and cached[0] == head:
        return cached[1]
    paths = id_query._paths(root)
    src = [p for p in paths if p.endswith(".py") and _is_src(p) and not _protected(p)]
    srcset = set(src)
    ids: dict = {}
    syms: dict = {}
    code: dict = {}
    for rel in src:
        text = id_query._text(root / rel)
        if text is None:
            continue
        try:     # <id>: an ID counts in prose only (comments, strings); a name (``<id> = ..``) or a bare label
            toks = list(tokenize.generate_tokens(io.StringIO(text).readline))     # (``Relation('<id>', ..)``) is
            prose = " ".join(t.string for t in toks if t.type == tokenize.COMMENT or (   # the code's own name for
                t.type == tokenize.STRING and _QUOTES.sub("", t.string) not in id_query.TOKEN.findall(t.string)))
        except (tokenize.TokenError, IndentationError, SyntaxError):                   # something, not a backlog row
            toks, prose = [], text
        for i in set(id_query.TOKEN.findall(prose)):
            ids.setdefault(i, set()).add(rel)
        names, notes = {PurePosixPath(rel).stem}, []
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            tree = None
        for n in ast.walk(tree) if tree is not None else ():
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
                notes.append(ast.get_docstring(n) or "")
            elif isinstance(n, (ast.Name, ast.Attribute)) and isinstance(n.ctx, ast.Store):
                names.add(n.id if isinstance(n, ast.Name) else n.attr)   # <id>: defined here, never a read of it
        if tree is not None:
            notes.append(ast.get_docstring(tree) or "")
        notes += [t.string for t in toks if t.type == tokenize.COMMENT]
        for name in names:
            syms.setdefault(name, set()).add(rel)
        code[rel] = Counter(_words(" ".join(notes) + " " + " ".join(sorted(names))))
    by_stem: dict = {}
    for p in src:
        by_stem.setdefault(PurePosixPath(p).stem, []).append(p)
    unique = {s: ps[0] for s, ps in by_stem.items() if len(ps) == 1 and len(s) >= 4}
    bridge: dict = {}
    for rel in paths:
        if not rel.lower().endswith(".md"):
            continue
        for block in re.split(r"\n\s*\n|\n(?=[-*|#] )", id_query._text(root / rel) or ""):
            block = block[:2000]
            mods = {unique[m] for m in _MOD_REF.findall(block)
                    if m in unique and ("_" in m or m + ".py" in block or "`" + m in block)}
            if not mods or len(mods) > BRIDGE_MAX_MODULES:
                continue
            words = set(_words(block))
            for f in mods:
                bridge.setdefault(f, Counter()).update(words)
    git_ids: dict = {}
    try:
        log = _git(root, "log", "--name-only", "--format=\x01%s\x02")   # <id>: the subject only; a body lists
    except ClosedCheckError:                                              # neighbours ("частично в <id>, <id>")
        log = ""
    for block in log.split("\x01"):
        message, _, files = block.partition("\x02")
        changed = [f.strip() for f in files.splitlines() if f.strip() in srcset]
        for i in set(id_query.TOKEN.findall(message)):
            book = git_ids.setdefault(i, {})
            for f in changed:
                book[f] = book.get(f, 0) + 1

    field = _bm25_field
    index = {"src": srcset, "ids": ids, "syms": syms, "git": git_ids, "code": field(code), "bridge": field(bridge),
             "census": _census_field(root / "tools" / "owner_census_sites.ndjson", srcset)}
    if head:
        _SCOPE_CACHE[str(root)] = (head, index)
    return index


def candidate_files(root, bid: str, text: str, k: int = SCOPE_K) -> list:
    """[(rel, score, tags)] best first: the source files a row that names no file most likely means.  Signals: the
    row's ID in the file (4, tag id), commits whose message names the ID (2 + 0.5 per commit, at most 4, tag git), a
    backticked or snake_case name of the row that the file defines (3 each, tag sym), the row's words against the
    file's comments and names (<id> / 4) and its .md bridge (<id> / 2) (tag doc).  A proposal for the head model,
    never a scope by itself: the score does not tell code from not-code."""
    ix = _scope_index(root)
    memo = ix.setdefault("memo", {})          # per HEAD: an unchanged row is ranked once, not on every portion
    if (bid, text, k) in memo:
        return memo[(bid, text, k)]
    score: dict = {}
    tags: dict = {}

    def add(rel, pts, tag):
        if pts <= 0:
            return
        score[rel] = score.get(rel, 0.0) + pts
        if tag not in tags.setdefault(rel, []):
            tags[rel].append(tag)
    for rel in ix["ids"].get(bid, ()):
        add(rel, 4.0, "id")
    for rel, c in ix["git"].get(bid, {}).items():
        add(rel, min(4.0, 2.0 + 0.5 * c), "git")
    sym: dict = {}
    for m in _ROW_IDENT.finditer(text or ""):
        raw = m.group(1) or m.group(2)
        name = raw[:-3] if raw.endswith(".py") else raw.split(".")[-1]     # `law_base.py` -> law_base, `a.b` -> b
        where = ix["syms"].get(name, ())
        if "_" not in name.strip("_") and len(where) > SYM_MAX_FILES:
            continue        # <id>: a plain word many files define (`sys.path` -> path, `log`, `usage`) names no module
        for rel in where:
            sym.setdefault(rel, set()).add(name)
    for rel, names in sym.items():
        add(rel, 3.0 * len(names), "sym")
    query = set(_words(text))
    for key, weight in (("code", 0.25), ("bridge", 0.5), ("census", CENSUS_WEIGHT)):
        f = ix[key]
        for rel, tf in f["tf"].items():
            add(rel, weight * _bm25(query, tf, f["len"][rel], f["df"], f["n"], f["avg"]), key if key == "census" else "doc")
    ranked = sorted(score.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
    memo[(bid, text, k)] = [(rel, round(sc, 2), list(tags[rel])) for rel, sc in ranked]
    return [(rel, sc, list(t)) for rel, sc, t in memo[(bid, text, k)]]


def _localized_scope(root, bid, text, ask, events) -> tuple:
    """(touch, note) from the Agentless localization (tools.slicer_localize) run on the strong candidate shortlist
    with the free model's ``ask(prompt) -> text``.  Only existing, writable src files survive, the functions the model
    named (checked against the real ast) go into the note.  Nothing valid or any fault -> ([], ""): the old path
    (hold for the head pick) stays."""
    try:
        cands = candidate_files(root, bid, text)
        if not strong_candidates(cands):
            return [], ""
        from tools import slicer_localize
        # only files the factory may write are shown to the model: a protected module never leaves the machine
        shortlist = [c[0] for c in cands if _is_src(c[0]) and not _protected(c[0])]
        if not shortlist:
            return [], ""
        res = slicer_localize.localize(root, text, shortlist, ask, max_touch=MAX_TOUCH)
        touch = [f for f in res["touch_files"] if _is_src(f) and _exists(root, f) and not _protected(f)][:MAX_TOUCH]
        if not touch:
            events.append({"backlog_id": bid, "event": "localize_empty", "reason": "no valid file from the model"})
            return [], ""
        parts = ["%s: %s" % (f, ", ".join(res["functions"][f][:6])) for f in touch if res["functions"].get(f)]
        note = ("Functions to inspect: " + "; ".join(parts)) if parts else ""
        events.append({"backlog_id": bid, "event": "localized", "reason": ", ".join(touch)[:200]})
        return touch, note[:300]
    except Exception as e:      # a localization failure must not stop the triage
        events.append({"backlog_id": bid, "event": "localize_failed", "reason": ("%s: %s" % (type(e).__name__, e))[:200]})
        return [], ""


WEAK_CANDIDATES = "кандидаты слабые"


def strong_candidates(cands) -> bool:
    """<id>: may these candidates make a hold?  Only with a code signal (STRONG_TAGS: the row's ID in the source, a
    commit subject naming the ID with code files, a name of the row that the source defines), public row or not.
    Live 20.11: every task made from a words-only (``doc``) pick was a non-code or too broad row (<id> dispatcher
    design, <id> proxy watchdog, <id> a work rule) scoped wrongly by the free head; the coordinator rejected all 5
    promotions.  The head does not reliably answer not_code, so words alone never reach it."""
    return bool(cands) and cands[0][1] >= CAND_MIN and any(t in STRONG_TAGS for _, _, tags in cands for t in tags)


def _weak_reason(cands) -> str:
    if not cands or cands[0][1] < CAND_MIN:
        return "кандидатов нет"
    return WEAK_CANDIDATES + ": только совпадения слов (%s), нет ID в коде, коммита с ID или имени из кода" % (
        ", ".join(c[0] for c in cands[:2]))


def weak_candidate_holds(root, backlog_path, bids) -> dict:
    """{backlog_id: reason} of the given rows whose candidates are not strong (strong_candidates) at ``root``: a
    candidates hold raised for them by the older rule is dropped by the loop (factory_loop._drop_weak_candidates).
    Rows not in the backlog (or without a section-4 entry) are not named: their hold is not this rule's business."""
    want = set(bids)
    out = {}
    if not want:
        return out
    for r in parse_section4(Path(backlog_path).read_bytes().decode("utf-8-sig")):
        bid = r["backlog_id"]
        if bid in want:
            cands = candidate_files(root, bid, r["text"])
            if not strong_candidates(cands):
                why = _weak_reason(cands)
                out[bid] = why if why.startswith(WEAK_CANDIDATES) else WEAK_CANDIDATES + " для удержания: " + why
    return out


BRIEF_ACCEPT = 600           # <id>: characters of the acceptance cell, of the row's owner cell and of one owner message in a goal
BRIEF_OWNER = 400
BRIEF_MESSAGES = 2


def _row_brief(F, r, owner_words=None) -> str:
    """<id>: what the coder and the critic must see besides the row's formulation: its acceptance cell, its owner-wording
    cell (OWNER_CELL) and up to BRIEF_MESSAGES verbatim owner messages that name the ID (tools.backlog_register.owner_excerpts),
    all clipped and redacted.  Live 21.11: a one-line synthesized goal made the free models invent APIs 6 times."""
    parts = []
    acc = F.redact(r.get("acceptance") or "").strip("`* ")
    if acc and acc not in ("—", "-"):
        parts.append("Приёмка строки: %s." % acc[:BRIEF_ACCEPT])
    cell = F.redact(r.get("owner_cell") or "").strip("`* ")
    if cell:
        parts.append("Owner wording in the row: %s." % cell[:BRIEF_OWNER])
    try:
        from tools import backlog_register
        words = backlog_register.owner_excerpts(r["backlog_id"], owner_words, k=BRIEF_MESSAGES, chars=BRIEF_OWNER)
    except Exception:       # the words file is a convenience: the goal stays without it
        words = []
    for w in words:
        parts.append("Owner verbatim: «%s»" % F.redact(w))
    return (" " + " ".join(parts)) if parts else ""


def _doc_only_row(r, cands) -> str:
    """<id> (owner rule 2: non-code is cut before the executors): why a row is not a change of the code, or "".  By
    structure, not by phrases: the row names no file, test or defined name, no commit or ID in the code makes a strong
    candidate, and its evidence carries the backlog's documentation marker "(док.: ...)"."""
    if r["mentioned_files"] or r["mentioned_tests"] or r["bare_names"] or not r.get("doc_marks"):
        return ""
    if strong_candidates(cands):
        return ""
    return "строка описывает документ или процесс: нет файла, теста, имени из кода и коммита с ID (метка «док.» ×%d)" % r["doc_marks"]


def _row_owner(bid) -> str:
    head = str(bid).lower().split("-", 1)[0]
    return head if head in ("fac", "cl") and "-" in str(bid) else "echo"


def triage_portion(backlog_path, head_root, known_backlog_ids, limit, profile_attempts=None, env_streak=0,
                   scopes=None, ask=None, sweep=None, trace=None, owner_words=None, self_repo=False) -> dict:
    """Screen backlog rows and hand them to the architect without manufacturing tasks.

    Hints are optional: the architect owns file discovery, contracts and decomposition.
    This pass performs no local test profiling and never guesses test/code pairs.
    """
    root = Path(head_root)
    out = {"tasks": [], "holds": [], "stale": [], "skipped": [], "to_slice": [],
           "skipped_unknown": [], "events": [], "deferred": [], "profile_attempts": {},
           "already_green": [], "needs_trace": [], "not_code": []}
    try:
        AF.sync_closed(root)
    except Exception as exc:
        out["events"].append({"event": "closed_sidecar_failed", "reason": str(exc)[:200]})
    rows = parse_open_rows(backlog_path, root, include_closed=True)
    out["skipped_unknown"] = list(rows.skipped_unknown)
    tabled = FC.table_ids(backlog_path) if FC is not None else {}
    try:
        guards = AF.guard_map(AF.load_sweep(root, sweep), [r["backlog_id"] for r in rows])
    except Exception as exc:
        guards = {}
        out["events"].append({"event": "sweep_failed", "reason": str(exc)[:200]})
    idx = _module_index(root)
    accepted = 0
    for row in rows:
        bid = row["backlog_id"]
        owner = _row_owner(bid)                 # 8.1: one queue, three owners: ECHO tasks, the factory's, the coordinator's
        if owner == "cl" or (owner == "fac") != bool(self_repo):
            out["skipped"].append({"backlog_id": bid, "reason": "coordinator_row" if owner == "cl" else
                                   "fac_row" if owner == "fac" else "echo_row"})
            continue
        if row["closed_at_head"]:
            if bid not in tabled:
                out["stale"].append(bid)
            continue
        if bid in known_backlog_ids:
            out["skipped"].append({"backlog_id": bid, "reason": "already known"})
            continue
        if accepted >= max(0, limit):
            out["deferred"].append({"backlog_id": bid, "reason": "portion limit"})
            continue
        accepted += 1
        if row["private"]:
            out["holds"].append({"backlog_id": bid, "question": "private (only_opus)"})
            continue
        red = AF.red_paths(guards.get(bid)) if AF.verdict(guards.get(bid)) == "red" else []
        if row.get("doc_marks") and not red:
            why = _doc_only_row(row, candidate_files(root, bid, row["text"]))
            if why:
                out["not_code"].append({"backlog_id": bid, "reason": why})
                continue
        hints = list(row["mentioned_files"]) + list(row["mentioned_tests"])
        for name, ticked, near in row["bare_names"]:
            if not ticked or near:
                hints.extend(idx.get(name, []))
        hints = sorted({path for path in hints if not _protected(path)})
        out["to_slice"].append({"backlog_id": bid, "hints": hints, "guard": red[0] if red else ""})
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

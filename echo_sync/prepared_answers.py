"""W2 / С10, С11: готовые ответы без модели. Список вопрос-ответ из материала (``load``) и долгий кэш устойчивых ответов на диске (``remember``); поиск за доли миллисекунды (``lookup``).

Форма результата как у ``quick_math.answer`` и ``reference_kb.lookup``: произносимая строка или ``None``, поэтому готовый путь уха берёт её как попадание базы, без нового маршрута. Сравнение только через
``fast_text.same_question``: те же числа, то же «не», каждое значимое слово вопроса списка есть в услышанном. Два разных ответа на один вопрос — ответа нет. Изменчивые данные (``needs_current_data``,
``needs_verification``) не берутся ни в список, ни в кэш; короткий или отсылочный вопрос («а почему», «что это такое») тоже. Кэш: один JSON, запись через временный файл, у каждой записи хэш ответа,
срок ``ttl``, не больше ``max_entries``; повреждённый файл — пустой кэш. Включает ``prepared_answers`` = "on" (выключено по умолчанию). Ничего не пишет в журнал: ни слова вопроса или ответа. Не бросает."""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path

from .fast_text import _atoms, _words, same_question
from .generator import needs_current_data, needs_verification

TTL_S = 30 * 86400
MAX_ENTRIES = 500
MIN_WORDS = 3                 # слов вопроса; меньше — общая фраза
MAX_QUESTION = 300
MAX_ANSWER = 1200
MAX_HEARD_WORDS = 40
_REFERRING = re.compile(r'\b(?:это|этот|эта|эти|он|она|они|его|ее|её|их|там|выше|предыдущ\w*|данн\w*|тот|та|те)\b|^(?:а|и|ну)\s+(?:почему|как|что|сколько)\b', re.I)


def _clean(value, limit):
    text = ' '.join(str(value or '').split())
    return text if 0 < len(text) <= limit else ''


def _stable(question, answer):
    """Is the pair a standalone question with an answer that does not change? -> (question, answer) cleaned, else None."""
    question, answer = _clean(question, MAX_QUESTION), _clean(answer, MAX_ANSWER)
    if not question or not answer or _REFERRING.search(question.casefold()):
        return None
    if needs_current_data(question) or needs_verification(question):
        return None
    atoms = _atoms(question)
    if len(question.split()) < MIN_WORDS or not (_words(atoms) or any(atom.kind == 'n' for atom in atoms)):
        return None
    return question, answer


def parse_pairs(text):
    """Pairs ``[(question, answer)]`` from a JSON list (``{"q","a"}``, ``{"question","answer"}`` or ``[q, a]``) or from text blocks ``В:``/``О:`` (``Q:``/``A:``); a block ends at a blank line."""
    try:
        text = str(text or '')
        if text.lstrip()[:1] in '[{':
            data = json.loads(text)
            data = data if isinstance(data, list) else data.get('pairs', []) if isinstance(data, dict) else []
            out = []
            for row in data:
                if isinstance(row, dict):
                    q, a = row.get('q', row.get('question')), row.get('a', row.get('answer'))
                elif isinstance(row, (list, tuple)) and len(row) == 2:
                    q, a = row
                else:
                    continue
                if isinstance(q, str) and isinstance(a, str) and q.strip() and a.strip():
                    out.append((q.strip(), a.strip()))
            return out
        out, question, answer = [], None, []

        def flush():
            if question and answer:
                out.append((question, ' '.join(answer)))
        for line in text.splitlines():
            line = line.strip()
            m = re.match(r'(?i)^(В|Q|Вопрос)\s*[:.)]\s*(.*)$', line)
            n = re.match(r'(?i)^(О|A|Ответ)\s*[:.)]\s*(.*)$', line)
            if m:
                flush()
                question, answer = m.group(2).strip(), []
            elif n and question:
                answer = [n.group(2).strip()]
            elif not line:
                flush()
                question, answer = None, []
            elif answer:
                answer.append(line)
        flush()
        return out
    except Exception:                    # noqa: BLE001 - a bad file is no pairs
        return []


def load(path, **kw):
    """``PreparedAnswers`` from the pairs file at ``path`` (missing or unreadable: empty)."""
    try:
        pairs = parse_pairs(Path(path).read_text(encoding='utf-8'))
    except Exception:                    # noqa: BLE001
        pairs = []
    return PreparedAnswers(pairs, **kw)


def _digest(question, answer):
    return hashlib.sha256((question + '\0' + answer).encode('utf-8')).hexdigest()


class PreparedAnswers:
    def __init__(self, pairs=(), *, cache_path=None, ttl=TTL_S, max_entries=MAX_ENTRIES, clock=None):
        self.cache_path = Path(cache_path) if cache_path else None
        self.ttl, self.max_entries, self.clock = ttl, max_entries, clock or time.time
        self.skipped = 0
        self._prepared = []          # (question, answer)
        self._cached = []            # dicts: q, a, t, h
        self._index = None
        try:
            for q, a in pairs:
                kept = _stable(q, a)
                if kept:
                    self._prepared.append(kept)
                else:
                    self.skipped += 1
        except Exception:            # noqa: BLE001
            self._prepared = []
        self._read_cache()

    def __len__(self):
        return len(self._prepared) + len(self._cached)

    # -- the cache on disk ---------------------------------------------------------------------------------------------------

    def _read_cache(self):
        self._cached = []
        if not self.cache_path:
            return
        try:
            data = json.loads(self.cache_path.read_text(encoding='utf-8'))
            if not isinstance(data, dict) or data.get('schema') != 1:
                return
            now = self.clock()
            for row in data.get('entries', [])[-self.max_entries:]:
                q, a, t = row.get('q'), row.get('a'), row.get('t')
                if (isinstance(q, str) and isinstance(a, str) and type(t) in (int, float) and 0 <= now - t <= self.ttl
                        and row.get('h') == _digest(q, a) and _stable(q, a)):
                    self._cached.append({'q': q, 'a': a, 't': t, 'h': row['h']})
        except Exception:            # noqa: BLE001 - damaged: an empty cache
            self._cached = []

    def _write_cache(self):
        tmp = self.cache_path.with_name(self.cache_path.name + '.tmp')
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({'schema': 1, 'entries': self._cached}, ensure_ascii=False), encoding='utf-8')
        os.replace(tmp, self.cache_path)

    def remember(self, question, answer):
        """Keep a settled answer for later (С11). False for a question that is not standalone, changes with time, or an answer too long or empty; the same question again replaces its answer."""
        try:
            kept = _stable(question, answer)
            if not kept or not self.cache_path:
                return False
            q, a = kept
            self._cached = [row for row in self._cached if not same_question(row['q'], q) or not same_question(q, row['q'])]
            self._cached.append({'q': q, 'a': a, 't': self.clock(), 'h': _digest(q, a)})
            del self._cached[:-self.max_entries]
            self._index = None
            self._write_cache()
            return True
        except Exception:            # noqa: BLE001
            return False

    # -- the search ----------------------------------------------------------------------------------------------------------

    def _build(self):
        rows = []
        for q, a in self._prepared + [(row['q'], row['a']) for row in self._cached]:
            rows.append((frozenset(atom.atom for atom in _atoms(q) if atom.atom in _words(_atoms(q)) or atom.kind == 'n'), q, a, len(rows) < len(self._prepared)))
        self._index = rows

    def lookup(self, text, history=()):
        """The prepared answer for ``text``, else ``None``. Never raises."""
        try:
            return self._lookup(text, history)
        except Exception:            # noqa: BLE001
            return None

    def _lookup(self, text, history):
        text = _clean(text, 4 * MAX_QUESTION) if isinstance(text, str) else ''
        if not text or len(text.split()) > MAX_HEARD_WORDS or not len(self):
            return None
        if needs_current_data(text, history) or needs_verification(text, history):
            return None
        if self._index is None:
            self._build()
        heard = {atom.atom for atom in _atoms(text)}
        found = {}
        for lemmas, q, a, prepared in self._index:
            if lemmas and lemmas <= heard and same_question(text, q):
                found.setdefault(prepared, set()).add(a)
        for prepared in (True, False):        # the owner's list before the cache
            answers = found.get(prepared)
            if answers:
                return next(iter(answers)) if len(answers) == 1 else None
        return None

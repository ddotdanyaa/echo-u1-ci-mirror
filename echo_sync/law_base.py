"""w4-law (idea С12): a local base of laws on SQLite (standard library only) and the spoken answers from it.

Rows: document, article, part, point, the verbatim text, the edition date, the source address. ``build`` writes a base from
``parse_page`` results; ``lookup(text, history)`` answers a plain request - «статья 81 ТК часть 1 пункт 3», «что говорит статья 19
Конституции», «какая статья про испытательный срок», «следующая часть», «с какого слова начинается» - or returns ``None``. Never raises.

* The text is never paraphrased. The only change is ``speak``: numbers and abbreviations that the voice breaks on («5%», «т.е.») are
  brought to speech, each edit is recorded as a span and ``restore`` gives the original back exactly (the tests check it on every row).
* The reference is read with ``reference_kb`` (tokens, numbers, «статья»); the document is named here (the codes it knows are only НК ГК ТК).
  A document or article that the base does not have is ``None`` - never a neighbour's article with the same number (rule of ``search_identity``).
* The answer is ONE string, like ``reference_kb.lookup``: the engine portions it and moves its cursor on «дальше». ``lookup`` keeps no state:
  «с какого слова» reads the header of the last law line of ``history``. An article is given whole, never cut and with no pointer:
  the engine's cursor (``portioner``) divides it, and «дальше» / «следующая часть» are the engine's NEXT, not a lookup here.
* A search by meaning is words only (a stem of the first five letters, no morphology; an article-level index ``terms``: how many rows of the article have the word, is it in the title): one confident
  article, or two or three candidates, else ``None``. SQLite FTS5 is present in the laptop's Python but is not used: the row-level bm25 of the first version put an article with the words in
  one row above the article that is about them (see REPORT.md); its index was a third of the file.
* The page parser (``parse_page``) is the only place that knows the markup of the source; the laptop fits it to the real pages.
"""
from __future__ import annotations

import datetime
import html.parser
import math
import os
import re
import sqlite3
from collections import namedtuple
from typing import Optional, Sequence

from . import reference_kb as rk
from . import ru_numbers as numbers
from . import search_identity as si
from .speech_text import cardinal      # law-speak: the number words are speech_text's (tts-render), law_base keeps no number table
from .settings import environment

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'law_base.sqlite')
CONFIDENT = 0.5              # the second article's score must be at most this share of the first's for the first to be named alone
TITLE = 1.0                  # a query word in a one-word title adds this much to the row count of the word (less for a longer title), before the weight of the word
STALE_DAYS = 365             # an edition older than this is said
SCHEMA = 2

Doc = namedtuple('Doc', 'code title spoken edition source in_force full', defaults=(1, ''))
Row = namedtuple('Row', 'doc article part point kind text repealed edition source seq sub', defaults=('',))

SPOKEN = {'konst': 'Конституции', 'gk': 'Гражданского кодекса', 'nk': 'Налогового кодекса', 'tk': 'Трудового кодекса', 'uk': 'Уголовного кодекса',
          'koap': 'Кодекса об административных правонарушениях', 'gpk': 'Гражданского процессуального кодекса', 'apk': 'Арбитражного процессуального кодекса',
          'sk': 'Семейного кодекса', 'zhk': 'Жилищного кодекса'}
_ABBR = {'нк': 'nk', 'гк': 'gk', 'тк': 'tk', 'ук': 'uk', 'коап': 'koap', 'гпк': 'gpk', 'апк': 'apk', 'ск': 'sk', 'жк': 'zhk'}
_SPELLED = {('эн', 'ка'): 'nk', ('гэ', 'ка'): 'gk', ('ге', 'ка'): 'gk', ('тэ', 'ка'): 'tk', ('те', 'ка'): 'tk', ('у', 'ка'): 'uk', ('эс', 'ка'): 'sk',
            ('жэ', 'ка'): 'zhk', ('гэ', 'пэ', 'ка'): 'gpk', ('а', 'пэ', 'ка'): 'apk', ('ко', 'а', 'пэ'): 'koap'}
_ADJ = (('налогов', 'nk'), ('гражданск', 'gk'), ('трудов', 'tk'), ('уголовн', 'uk'), ('семейн', 'sk'), ('жилищн', 'zhk'), ('административн', 'koap'))

# -- storage ---------------------------------------------------------------------------------------------------------

_DB = {'path': None, 'conn': None, 'override': False}


def use(path):
    """Use this base file (tests, the laptop); ``None`` goes back to the default place. The connection opens on the first question."""
    conn = _DB['conn']
    if conn is not None:
        conn.close()
    _DB.update(path=path, conn=None, override=path is not None, total=None)


def _conn():
    if _DB['conn'] is None:
        path = _DB['path'] if _DB['override'] else environment('ECHO_LAW_DB', DEFAULT_DB)
        if not os.path.isfile(path):
            return None
        conn = sqlite3.connect('file:%s?mode=ro' % path.replace('?', '%3f'), uri=True, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        _DB['conn'] = conn
    return _DB['conn']


def _yo(word):
    return word.lower().replace('ё', 'е')


def stem(word):
    """There is no morphology: a word is indexed and asked as its first five letters («испытательный» / «испытания» -> «испыт»)."""
    word = _yo(word)
    return word[:5] if len(word) > 5 else word


_WORD = re.compile(r'[а-яёa-z]{3,}', re.I)


def _stems(text):
    return ' '.join(stem(w) for w in _WORD.findall(text))


def build(path, parsed):
    """Write a base: ``parsed`` is a list of ``(Doc, [Row])``, one per page. The pages of one code are one document (the НК and the ГК have several laws, the parts).
    An article met twice is kept once - the first page in the order given. Replaces the file."""
    if os.path.exists(path):
        os.remove(path)
    conn = sqlite3.connect(path)
    docs, laws, seen = {}, {}, set()
    with conn:
        conn.executescript('''
            CREATE TABLE docs(code TEXT PRIMARY KEY, title TEXT, spoken TEXT, edition TEXT, source TEXT, in_force INTEGER);
            CREATE TABLE laws(source TEXT PRIMARY KEY, code TEXT, title TEXT, edition TEXT);
            CREATE TABLE rows(id INTEGER PRIMARY KEY, doc TEXT, article TEXT, part TEXT, point TEXT, sub TEXT, kind TEXT, text TEXT, repealed INTEGER, edition TEXT, source TEXT, seq INTEGER);
            CREATE INDEX rows_ref ON rows(doc, article, seq);
            CREATE TABLE articles(id INTEGER PRIMARY KEY, doc TEXT, article TEXT, title TEXT, repealed INTEGER);
            CREATE TABLE terms(stem TEXT, aid INTEGER, n INTEGER, title REAL, PRIMARY KEY(stem, aid)) WITHOUT ROWID;
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);''')
        rid, aid, duplicates = 0, 0, 0
        for doc, rows in parsed:
            titles = {r.article: r.text for r in rows if r.kind == 'title'}
            again = {a for a in titles if (doc.code, a) in seen}
            duplicates += len(again)
            rows = [r for r in rows if r.article not in again]
            if not rows:
                continue
            seen.update((doc.code, a) for a in titles)
            known = docs.get(doc.code)
            docs[doc.code] = doc if known is None else known._replace(edition=max(known.edition, doc.edition), source=min(known.source, doc.source))
            laws.setdefault(doc.source, (doc.code, doc.full or doc.title, doc.edition))
            batch, words = [], {}
            for r in rows:
                rid += 1
                batch.append((rid, r.doc, r.article, r.part, r.point, r.sub, r.kind, r.text, int(r.repealed), r.edition, r.source, r.seq))
                if r.text and not r.repealed:
                    found = words.setdefault(r.article, ({}, set()))
                    if r.kind == 'title':
                        found[1].update(_stems(r.text).split())
                    else:
                        for w in set(_stems(r.text).split()):
                            found[0][w] = found[0].get(w, 0) + 1
            conn.executemany('INSERT INTO rows(id,doc,article,part,point,sub,kind,text,repealed,edition,source,seq) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', batch)
            for article in sorted({r.article for r in rows}):                  # the article-level index: how many rows of the article have the word, and is it in the title
                aid += 1
                counts, in_title = words.get(article, ({}, set()))
                conn.execute('INSERT INTO articles VALUES(?,?,?,?,?)', (aid, doc.code, article, titles.get(article, ''), int(article not in words)))
                weight = round(TITLE / (1 + len(in_title) / 3), 3)             # a word of a short title says more about the article than a word of a long one
                conn.executemany('INSERT INTO terms VALUES(?,?,?,?)', [(w, aid, counts.get(w, 0), weight if w in in_title else 0) for w in set(counts) | in_title])
        conn.executemany('INSERT INTO docs VALUES(?,?,?,?,?,?)', [(d.code, d.title, d.spoken, d.edition, d.source, d.in_force) for d in docs.values()])
        conn.executemany('INSERT INTO laws VALUES(?,?,?,?)', [(src, *v) for src, v in sorted(laws.items())])
        conn.executemany('INSERT INTO meta VALUES(?,?)', [('schema', str(SCHEMA)), ('duplicate_articles', str(duplicates))])
    conn.commit()
    conn.execute('ANALYZE')
    conn.execute('VACUUM')
    conn.close()


def stats(path=None):
    """Counts of a base file (``path``) or of the one in use."""
    conn = _conn() if path is None else sqlite3.connect(path)
    if conn is None:
        return {'rows': 0, 'documents': 0, 'bytes': 0}
    p = path or _DB['path'] if _DB['override'] else path or environment('ECHO_LAW_DB', DEFAULT_DB)
    try:
        one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        return {'rows': one('SELECT count(*) FROM rows'), 'documents': one('SELECT count(*) FROM docs'), 'articles': one('SELECT count(*) FROM articles'), 'bytes': os.path.getsize(p),
                'laws': one('SELECT count(*) FROM laws'), 'terms': one('SELECT count(*) FROM terms'),
                'repealed_articles': one("SELECT count(*) FROM rows WHERE kind='title' AND repealed=1"), 'cut_articles': one("SELECT count(*) FROM rows WHERE kind='cut'")}
    finally:
        if path is not None:
            conn.close()


# -- the page parser: the only place that knows the markup of the source -----------------------------------------------
# Input is either a real page of consultant.ru (one article per page; ``_Page`` and ``_parse_real``) or, for the older fake markup
# and plain files, the line parser of the first version (``_Blocks``). ``parse_page`` chooses by the element ``document-page__content``.

_SKIP_CLASS = re.compile(r'toc|footer|nav|menu|breadcrumb|banner', re.I)
_BLOCKS = frozenset('h1 h2 h3 h4 h5 h6 p li div tr br'.split())


class _Blocks(html.parser.HTMLParser):
    """Text of a page as lines: block elements break the line, tables of contents and footers are dropped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines, self.cur, self.skip, self.stack, self.title = [], [], 0, [], None

    def _flush(self, title=False):
        text = re.sub(r'\s+', ' ', ''.join(self.cur).replace('\xa0', ' ')).strip()
        self.cur = []
        if text:
            self.lines.append(text)
            if title and self.title is None:
                self.title = text

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get('class') or ''
        self.stack.append((tag, bool(_SKIP_CLASS.search(cls)), 'title' in cls and tag == 'div'))
        if self.stack[-1][1]:
            self._flush()
            self.skip += 1
        elif tag in _BLOCKS:
            self._flush()

    def handle_endtag(self, tag):
        while self.stack:
            top = self.stack.pop()
            if top[0] == tag:
                break
        else:
            return
        if top[1]:
            self._flush()
            self.skip -= 1
        elif tag in _BLOCKS:
            self._flush(title=top[2])

    def handle_data(self, data):
        if not self.skip:
            self.cur.append(data)


_NUM = r'\d+(?:\.\d+)*(?:-\d+)?'                                    # an article number: 19, 19.1, 346.43, 25.12-1
_HEADING = re.compile(r'^Статья\s+(' + _NUM + r')\.?\s*(.*)$')
_PART = re.compile(r'^(\d+(?:\.\d+)*)\.\s+(\S.*)$')
_POINT = re.compile(r'^(\d+(?:\.\d+)*)\)\s+(\S.*)$')
_SUBPOINT = re.compile(r'^([а-яё](?:\.\d+)?)\)\s+(\S.*)$')
_NOTE = re.compile(r'^\((?:в\s+ред|п\.|пп\.|ч\.|часть|абзац|статья|введен|введена|введено|см\.|утратил|исключен|наименование)', re.I)
_EDITION = re.compile(r'(?:ред\.\s+от|с\s+изм\.\s+от)\s+(\d\d)\.(\d\d)\.(\d{4})')
_ANY_DATE = re.compile(r'(\d\d)\.(\d\d)\.(\d{4})')


def _edition(title):
    """ISO date of the edition from the title of the law: the latest of «(ред. от ...)» and «с изм. от ...», else the last date in the title."""
    found = _EDITION.findall(title) or _ANY_DATE.findall(title)[-1:]
    return max('%s-%s-%s' % (y, m, d) for d, m, y in found) if found else ''


# What the pages of consultant.ru look like (checked on the downloaded pages of konst, tk, gk, nk):
#   head:  <link rel="canonical" href=".../document/cons_doc_LAW_<law>/<hash>/"> is the address of the page.
#   body:  <div class="document-page__title-link"><a>"Трудовой кодекс Российской Федерации" от 30.12.2001 N 197-ФЗ (ред. от 25.05.2026)</a></div> names the law and
#          its edition; <div class="document-page__content"> is the article: <h1>[ТК РФ ]Статья 81. Заголовок</h1>, then one <p> per paragraph (a table is
#          <table><tr><td><p>, a formula is <img alt="Рисунок N">, indices are <sub> and <sup>).
#   not law text INSIDE the content: div.document__edit «(в ред. ...)», div.document__insert («см. текст в предыдущей редакции», the guides «Вопросы применения»,
#          «КонсультантПлюс: примечание»), div.doc-limit («Полный текст документа вы можете просмотреть в коммерческой версии» - the page is cut),
#          footnote marks «<*>», «<21>» and, behind a line of dashes, the footnotes themselves, the signature of the President after the last article.
#   OUTSIDE the content (never read): «Открыть полный текст документа», «Комментарии к статье», the navigation to the next article, banners.

_VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
_DROP_CLASSES = frozenset('document__edit document__insert doc-roll doc-limit document-page__notes notes document-page__balloon'.split())
_FLOW = frozenset('p div li ul ol section blockquote dd dt h2 h3 h4 h5 h6 table tr td th'.split())
_FOOTNOTE_MARK = re.compile(r'\s*<(?:\*+|\d{1,3})>')
_FOOTNOTE_START = re.compile(r'<(?:\*+|\d{1,3})>')          # a line that starts with the mark is a footnote
_DASHES = re.compile(r'^-{8,}$')
_IMAGE = '[рисунок]'


def _clean(text):
    """A line of a page: no footnote marks, one space between words (the non-breaking space too)."""
    return re.sub(r'\s+', ' ', _FOOTNOTE_MARK.sub('', text)).strip()


class _Page(html.parser.HTMLParser):
    """One consultant page -> ``lines`` [(text, 'h1' | 'p' | 'row' | 'foot')], ``notes`` [(index of the next line, annotation)], ``law`` (title of the law), ``canonical``."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.lines, self.notes, self.law_buf = [], [], [], []
        self.cur, self.row, self.note = [], [], None
        self.content = self.skip = self.h1 = self.table = self.in_law = 0
        self.limit, self.canonical, self.law = False, None, ''

    def _live(self):
        return self.content and not self.skip

    def _flush(self, tag='p'):
        raw = ''.join(self.cur).strip()
        text = _clean(raw)
        self.cur = []
        if text:
            self.lines.append((text, 'foot' if tag == 'p' and _FOOTNOTE_START.match(raw) else tag))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'link':
            if (a.get('rel') or '').lower() == 'canonical' and self.canonical is None:
                self.canonical = a.get('href') or ''
            return
        if tag in _VOID:
            if self._live():
                self.cur.append(' ' if tag == 'br' else _IMAGE if tag == 'img' else '')
            return
        classes = set((a.get('class') or '').split())
        role = None
        if 'document-page__content' in classes and not self.content:
            role, self.content = 'content', 1
        elif self.content and classes & _DROP_CLASSES:
            role = 'skip'
            if not self.skip and 'document__edit' in classes:
                self.note = []
            self.limit = self.limit or 'doc-limit' in classes
            self.skip += 1
        elif 'document-page__title-link' in classes and not self.law and not self.in_law:
            role, self.in_law = 'law', 1
        self.stack.append((tag, role))
        if role in ('skip', 'content') or not self._live():
            return
        if tag == 'h1':
            self._flush()
            self.h1 += 1
        elif tag == 'table':
            self._flush()
            self.table += 1
        elif tag == 'tr' and self.table:
            self.row, self.cur = [], []
        elif tag in ('td', 'th') and self.table:
            self.cur = []
        elif tag == 'sup':
            self.cur.append('^')
        elif tag in _FLOW and not self.table and not self.h1:
            self._flush()

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                break
        else:
            return
        popped, self.stack = self.stack[i:], self.stack[:i]
        for name, role in reversed(popped):
            self._close(name, role)

    def _close(self, tag, role):
        if role == 'skip':
            self.skip -= 1
            if not self.skip and self.note is not None:
                text = _clean(''.join(self.note))
                self.note = None
                if text:
                    self.notes.append((len(self.lines), text))
            return
        if role == 'law':
            self.in_law, self.law = 0, _clean(''.join(self.law_buf))
            return
        if not self._live():
            return
        if tag == 'h1':
            self.h1 -= 1
            if not self.h1:
                self._flush('h1')
        elif tag in ('td', 'th') and self.table:
            self.row.append(_clean(''.join(self.cur)))
            self.cur = []
        elif tag == 'tr' and self.table:
            cells = [c for c in self.row if c]
            self.row = []
            if cells:
                self.lines.append(('; '.join(cells), 'row'))
        elif tag == 'table':
            self.table = max(0, self.table - 1)
        elif tag == 'p' and (self.table or self.h1):
            self.cur.append(' ')
        elif tag in _FLOW and not self.table and not self.h1:
            self._flush()
        if role == 'content':
            self._flush()
            self.content = 0

    def handle_data(self, data):
        if self.in_law:
            self.law_buf.append(data)
        if self.content:
            if not self.skip:
                self.cur.append(data)
            elif self.note is not None:
                self.note.append(data)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


_HEAD_ARTICLES = re.compile(r'^(?:[A-Za-zА-Яа-яЁё]{2,6}\s+РФ\s+)?Стать[яи]\s+(' + _NUM + r')((?:\s*(?:,|и)\s*(?:[Сс]тать[яи]\s+)?' + _NUM + r')*)(?:\s*[-–—]\s*(' + _NUM + r'))?\s*\.?\s*(.*)$')
_LOST = re.compile(r'^(?:утрати\w+\s+силу|исключ[её]н\w*)\b', re.I)
_LAW_NAME = re.compile(r'^"([^"]+)"')
_LAW_ID = re.compile(r'cons_doc_LAW_(\d+)')
_BULLET = re.compile(r'^[-–—]\s+\S')
_SIGNATURE_END = re.compile(r'^N \d+-Ф[А-Я]*$')
_SIGNATURE = re.compile(r'^(?:Президент|Российской Федерации|Президент Российской Федерации|[А-ЯЁ]\.\s?[А-ЯЁ]+|Москва, Кремль|\d{1,2} [а-я]+ \d{4} года|N \d+-Ф[А-Я]*)$')
_ARTICLE_PREFIX = re.compile(r'^Стать[яи]\s+' + _NUM + r'(?:\s*(?:,\s*[Сс]татья|[-–—]|и)\s*' + _NUM + r')*\s*\.\s*(?=(?:Утратил|Исключ))')


def _articles(first, more, last):
    """Article numbers in a heading: «45.1, статья 45.2», «45.1 - 45.2» (the whole numbers between are added when both are whole)."""
    found = [first] + re.findall(_NUM, more or '')
    if last and first.isdigit() and last.isdigit() and 0 < int(last) - int(first) < 60:
        found = [str(n) for n in range(int(first), int(last) + 1)]
    elif last:
        found.append(last)
    return list(dict.fromkeys(found))


def _structure(lines):
    """Lines of the body -> ``[(kind, part, point, sub, text)]``.

    Numbers are kept as the page has them: parts «1.», points «1)», subpoints «а)». An article whose paragraphs are not numbered (the Labour Code, many
    others) is read by the custom of the lawyers: every paragraph is a part («часть вторая»), the points «1)» stand under the paragraph before them."""
    items = []
    for text, tag in lines:
        for pattern, kind in ((_PART, 'part'), (_POINT, 'point'), (_SUBPOINT, 'sub')):
            m = None if tag == 'row' else pattern.match(text)
            if m:
                items.append((kind, m.group(1), m.group(2)))
                break
        else:
            items.append(('row' if tag == 'row' else 'plain', '', text))
    numbered = any(kind == 'part' for kind, _, _ in items)
    out, part, point, sub, counter, previous = [], '', '', '', 0, ''
    for kind, number, text in items:
        if kind == 'part':
            part, point, sub = number, '', ''
            out.append(('part', part, '', '', text))
        elif kind == 'point':
            point, sub = number, ''
            out.append(('point', part, point, '', text))
        elif kind == 'sub':
            sub = number
            out.append(('sub', part, point, sub, text))
        elif kind == 'row':
            out.append(('cont' if part else 'body', part, point, sub, text))
        elif numbered:
            if not part:
                out.append(('body', '', '', '', text))
            elif point and previous[-1:] in (';', ',', ':') or _BULLET.match(text):
                out.append(('cont', part, point, sub, text))                  # goes on with the point (or the list) before it
            else:
                point = sub = ''
                out.append(('cont', part, '', '', text))                      # a closing paragraph of the part
        elif part and (_BULLET.match(text) or previous[-1:] in (';', ',', ':')):
            out.append(('cont', part, point, sub, text))                      # an item of a list: «...:» / «...;» goes on in the next paragraph
        else:
            counter += 1
            part, point, sub = str(counter), '', ''
            out.append(('para', part, '', '', text))
        previous = text
    return out


def _parse_real(markup, code, source, edition):
    page = _Page()
    page.feed(markup)
    page.close()
    page._flush()
    law = page.law
    page_url = source or page.canonical or ''
    heading = next((t for t, tag in page.lines if tag == 'h1'), '')
    body = [(t, tag) for t, tag in page.lines if tag not in ('h1', 'foot') and not _DASHES.match(t)]       # the footnotes sit behind a line of dashes, mid-article too
    head = _HEAD_ARTICLES.match(heading)
    if head is None:                                                      # no <h1>: the first line is the heading
        head = next((m for m in (_HEAD_ARTICLES.match(t) for t, _ in body[:2]) if m), None)
        if head is not None:
            heading, body = body[0][0], body[1:]
    name = _LAW_NAME.match(law)
    short = re.sub(r'\s*\((?:часть|Часть)[^)]*\)', '', name.group(1)).strip() if name else law
    law_id = _LAW_ID.search(page_url) or _LAW_ID.search(page.canonical or '')
    edition = edition or _edition(law)
    doc = Doc(code, short, SPOKEN.get(code, short), edition, 'https://www.consultant.ru/document/cons_doc_LAW_%s/' % law_id.group(1) if law_id else page_url, 1, law)
    if head is None:
        return doc, []
    articles, title = _articles(head.group(1), head.group(2), head.group(3)), head.group(4).strip().rstrip('.').strip()
    body = [(t, tag) for t, tag in body if t != heading and not re.fullmatch(r'Стать[яи] ' + _NUM, t)]
    if body and _SIGNATURE_END.match(body[-1][0]):                        # the President's signature behind the last article of a code
        while body and _SIGNATURE.match(body[-1][0]):
            body.pop()
    if body:
        body[0] = (_ARTICLE_PREFIX.sub('', body[0][0]), body[0][1])
    items = _structure(body)
    lost = bool(_LOST.match(title)) or bool(items) and all(_LOST.match(t) for _, _, _, _, t in items)
    rows, seq = [], 0
    for article in articles:
        seq += 1
        rows.append(Row(code, article, '', '', 'title', title, lost, edition, page_url, seq))
        for kind, part, point, sub, text in items:
            seq += 1
            rows.append(Row(code, article, part, point, kind, text, lost or bool(_LOST.match(text)), edition, page_url, seq, sub))
        if page.limit:
            seq += 1
            rows.append(Row(code, article, '', '', 'cut', '', lost, edition, page_url, seq))
    return doc, rows


def parse_page(markup, code, source, edition=None):
    """Consultant page markup (or plain text of a law) -> ``(Doc, [Row])``. Annotations («(в ред. ...)», «КонсультантПлюс: ...») are not law text."""
    if 'document-page__content' in markup and re.search(r'<h1[\s>]', markup):                # a real page of the source (the fake markup of the tests has <h3>)
        return _parse_real(markup, code, source, edition)
    if '<' in markup:
        parser = _Blocks()
        parser.feed(markup)
        parser._flush()
        lines, title = parser.lines, parser.title or (parser.lines[0] if parser.lines else '')
    else:
        lines = [re.sub(r'\s+', ' ', l).strip() for l in markup.splitlines() if l.strip()]
        title = lines[0] if lines else ''
    edition = edition or _edition(title)
    doc = Doc(code, title, SPOKEN.get(code, title), edition, source, 1)
    rows, article, part, point, seq = [], None, '', '', 0

    def add(kind, text, art=None, prt='', pnt=''):
        nonlocal seq
        seq += 1
        rows.append(Row(code, art or article, prt, pnt, kind, text, False, edition, source, seq))

    for line in lines:
        head = _HEADING.match(line)
        if head:
            article, part, point = head.group(1), '', ''
            heading = head.group(2).strip().rstrip('.') if not head.group(2).lower().startswith('утратил') else head.group(2).strip()
            add('title', heading)
            continue
        if article is None or line.startswith('КонсультантПлюс') or _NOTE.match(line) or line == title:
            continue
        m = _PART.match(line)
        if m:
            part, point = m.group(1), ''
            add('part', m.group(2), prt=part)
            continue
        m = _POINT.match(line)
        if m:
            point = m.group(1)
            add('point', m.group(2), prt=part, pnt=point)
            continue
        m = _SUBPOINT.match(line)
        if m and point:
            add('point', m.group(2), prt=part, pnt=point.split('.')[0] + m.group(1) if False else point + m.group(1))
            continue
        add('body' if not part else 'cont', line, prt=part, pnt=point)
    lost = {r.article for r in rows if r.kind in ('title', 'body') and r.text.lower().startswith('утратил')}
    rows = [r._replace(repealed=r.article in lost) for r in rows]
    return doc, rows


# -- speech ------------------------------------------------------------------------------------------------------------

_PERCENT = re.compile(r'(?<![\d,.])(\d{1,3})\s?%')
_ABBREVIATIONS = ((re.compile(r'(?<![\w.])т\.\s?е\.'), 'то есть'), (re.compile(r'(?<![\w.])т\.\s?д\.'), 'так далее'), (re.compile(r'(?<![\w.])т\.\s?п\.'), 'тому подобное'),
                  (re.compile(r'(?<![\w.])и\s+др\.'), 'и другие'), (re.compile(r'(?<![\w.])и\s+пр\.'), 'и прочее'), (re.compile(r'№|(?<![\w])N(?=\s?\d)'), 'номер'),
                  (re.compile(r'\[рисунок\]'), 'здесь рисунок или формула, их нет в тексте'),
                  (re.compile(r'\^(-?)(\d+)'), lambda m: ' в степени %s%s' % ('минус ' if m.group(1) else '', m.group(2))))        # the page's <sup>


def _percent(match):
    n = int(match.group(1))
    last2, last = n % 100, n % 10
    if n == 0 or not (last == 0 or last >= 5 or 11 <= last2 <= 14):         # «1%», «2%»: the case depends on the sentence - left as written
        return None
    return '%s процентов' % cardinal(n)


def speak(text):
    """``(spoken, edits)``: the text with numbers and abbreviations the voice breaks on brought to speech; ``edits`` = [(start, end, original)] in ``spoken``."""
    spans = []
    for pattern, said in _ABBREVIATIONS:
        spans += [(m.start(), m.end(), said(m) if callable(said) else said) for m in pattern.finditer(text)]
    for m in _PERCENT.finditer(text):
        said = _percent(m)
        if said:
            spans.append((m.start(), m.end(), said))
    spans.sort()
    out, edits, pos, shift = [], [], 0, 0
    for start, end, said in spans:
        if start < pos:
            continue
        out.append(text[pos:start])
        begin = sum(len(x) for x in out)
        out.append(said)
        edits.append((begin, begin + len(said), text[start:end]))
        pos = end
    out.append(text[pos:])
    return ''.join(out), edits


def restore(spoken, edits):
    """The exact original of ``speak``'s output."""
    out, pos = [], 0
    for start, end, original in edits:
        out += [spoken[pos:start], original]
        pos = end
    out.append(spoken[pos:])
    return ''.join(out)


# -- reading a request -------------------------------------------------------------------------------------------------

_PART_WORDS = frozenset('часть части частью'.split())
_POINT_WORDS = frozenset('пункт пункта пункте пункту пунктом'.split())
_SUB_WORDS = frozenset('подпункт подпункта подпункте подпункту подпунктом'.split())
_ALLOWED = rk._FILLER | frozenset('''прочитай прочти прочитайте зачитай зачти дословно целиком полностью говорит говорится сказано написано текст найди открой
покажи продиктуй конституции конституция конституцию конституцией кодекс кодекса кодексе кодексу кодексом российская россии российский основного основной
закона закон часть части частью пункт пункта пункте пункту пунктом подпункт подпункта подпункте подпункту подпунктом пожалуйста мне нам статью статьей'''.split())
_STARTS = re.compile(r'(?:с\s+какого|каким)\s+слов\w+\s+(?:начинается|начинаем|начало)|как\s+начинается|с\s+чего\s+начинается')
# «какая статья про X», «в какой статье трудового кодекса говорится об X», «найди статью про X»: the topic is what follows про / об / о
_TOPIC = re.compile(r'(?:^|\s)(?:какая|какие|в\s+какой|на\s+какой|где|найди|подскажи|скажи|покажи)\s+(?:там\s+)?(?:мне\s+)?(?:стать\w+)(?:\s+\w+){0,5}?\s+(?:про|об?|обо|касающ\w+|посвященн\w+)\s+(.+?)[.?!\s]*$')
_TOPIC_STOP = frozenset('это этом этой тот тех там тут нас мне том нем про обо что где как какая какие какой есть идет говорится написано такое такой вообще который которая которые говорит речь'.split())
Request = namedtuple('Request', 'doc article part point verbatim sub loose', defaults=('', False))
_PUNKT_DOCS = frozenset(('nk', 'gk', 'sk'))     # the Tax, Civil and Family codes call the numbered item «1.» a пункт and «1)» a подпункт; the other codes: часть and пункт
_LETTERS = frozenset('абвгдежзийклмнопрстуфхцчшщэюя')


def _doc_codes(tokens):
    found, n = set(), len(tokens)
    for i, t in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < n else ''
        nxt2 = tokens[i + 2] if i + 2 < n else ''
        if t in _ABBR:
            found.add(_ABBR[t])
        for size in (3, 2):
            key = tuple(tokens[i:i + size])
            if key in _SPELLED:
                found.add(_SPELLED[key])
        if t.startswith('конституци') or (t.startswith('основн') and nxt.startswith('закон') and not nxt2.startswith('о')):
            found.add('konst')
        if nxt.startswith('кодекс') and t.startswith('административн'):
            found.add('koap')
        if t.startswith('кодекс') and nxt == 'об' and nxt2.startswith('административн'):
            found.add('koap')
        if t.startswith('арбитражн') and nxt.startswith('процессуальн') and nxt2.startswith('кодекс'):
            found.add('apk')
        elif t.startswith('гражданск') and nxt.startswith('процессуальн') and nxt2.startswith('кодекс'):
            found.add('gpk')
        elif nxt.startswith('кодекс'):
            for prefix, code in _ADJ:
                if t.startswith(prefix):
                    found.add(code)
    return found


def _tokens(text):
    return rk._TOKEN.findall(numbers.merge_digit_groups(_yo(text)))


def _keywords(tokens):
    out = list(rk._keywords(tokens) if True else ())
    out = [k for k in out if k[0] == 'article']
    for i, t in enumerate(tokens):
        if t in _PART_WORDS:
            out.append(('part', i, i + 1))
        elif t in _POINT_WORDS:
            out.append(('point', i, i + 1))
        elif t in _SUB_WORDS:
            out.append(('sub', i, i + 1))
    return sorted(out, key=lambda k: k[1])


def _request(text, history_code=None):
    """``Request`` for a plain reference, or ``None``: the whole utterance must be the reference and filler words.

    «часть» / «пункт» / «подпункт» are read the way the document says them: in the Tax, Civil and Family codes the numbered item «1.» is a пункт (``part``)
    and «1)» a подпункт (``point``); in the others «1.» is a часть, «1)» a пункт and the letter «а)» a подпункт. A «пункт» that fits no numbered item is
    tried as «N)» (``loose``): an article without numbered items has only «1)»."""
    tokens = _tokens(text)
    if not tokens or len(tokens) > 20:
        return None
    mentions, used, got = rk._mentions(tokens), set(), {}
    keywords = _keywords(tokens)
    consumed = set()
    for kind, start, end in keywords:
        cands = [m for m in mentions if id(m) not in used and rk._adjacent(tokens, m, (kind, start, end)) is not None]
        cands.sort(key=lambda m: (m.start < end, abs(m.start - end)))
        if cands and kind not in got:
            m = cands[0]
            used.add(id(m))
            got[kind] = m.key
            consumed.update(range(m.start, m.end))
        elif kind != 'article' and kind not in got and end < len(tokens) and tokens[end] in _LETTERS and (end + 1 == len(tokens) or tokens[end + 1] not in _LETTERS):
            got[kind] = tokens[end]                                       # «пункт а», «подпункт б»
            consumed.add(end)
        consumed.update(range(start, end))
    codes = _doc_codes(tokens)
    if len(codes) > 1:
        return None
    if len(mentions) != len(used):
        return None
    for i, t in enumerate(tokens):
        if i not in consumed and t not in _ALLOWED and t not in _ABBR and not t.startswith(('кодекс', 'конституци', 'российск', 'основн', 'налогов', 'гражданск', 'трудов', 'уголовн',
                                                                                              'семейн', 'жилищн', 'арбитражн', 'административн', 'процессуальн', 'правонарушен')):
            if not any(t in key for key in _SPELLED):
                return None
    if 'article' not in got:
        return None
    doc = next(iter(codes), None) or history_code
    part, point, sub, loose = got.get('part', ''), got.get('point', ''), got.get('sub', ''), False
    if doc in _PUNKT_DOCS:
        if part:
            point, sub = point or sub, ''
        else:
            part, point, sub, loose = point, sub, '', bool(point and not sub)
    return Request(doc, got['article'], part, point, 'дословно' in tokens, sub, loose)


# -- answers -----------------------------------------------------------------------------------------------------------

_LABEL = re.compile(r',\s+(часть|пункт|подпункт)\s+([^\s,:;.]+)')


def _line_code(line):
    """The last law answer's header -> ``(code, article, part, point)``; ``None`` for any other line."""
    if not isinstance(line, str):
        return None
    m = re.search(r'Статья\s+(\d+(?:\.\d+)*(?:-\d+)?)\s+(' + '|'.join(re.escape(v) for v in sorted(SPOKEN.values(), key=len, reverse=True)) + r')((?:,\s+(?:часть|пункт|подпункт)\s+[^\s,:;.]+)*)(?=[:,.\s]|$)', line)
    if not m:
        return None
    code = next(k for k, v in SPOKEN.items() if v == m.group(2))
    part = point = ''
    for word, value in _LABEL.findall(m.group(3) or ''):
        if word == 'часть' or (word == 'пункт' and code in _PUNKT_DOCS):
            part = value
        elif not point:
            point = value
    return code, m.group(1), part, point


def _last_law(history):
    if isinstance(history, str):
        history = (history,)
    try:
        lines = list(history)[-3:]
    except TypeError:
        return None
    for line in reversed(lines):
        found = _line_code(line)
        if found:
            return found
    return None


def _history_doc(history):
    if isinstance(history, str):
        history = (history,)
    try:
        for line in reversed(list(history)[-3:]):
            codes = _doc_codes(_tokens(line)) if isinstance(line, str) and len(line) < 2000 else set()
            if len(codes) == 1:
                return next(iter(codes))
    except TypeError:
        pass
    return None


def _date_words(iso):
    months = 'января февраля марта апреля мая июня июля августа сентября октября ноября декабря'.split()
    y, m, d = (int(x) for x in iso.split('-'))
    return '%d %s %d года' % (d, months[m - 1], y)


def _part_word(code, para=False):
    return 'часть' if para or code not in _PUNKT_DOCS else 'пункт'


def _label(code, article, part='', point='', sub='', para=False):
    out = 'Статья %s %s' % (rk._article_number(article), SPOKEN[code])
    if part:
        out += ', %s %s' % (_part_word(code, para), part)
    if point:
        out += ', %s %s' % ('подпункт' if code in _PUNKT_DOCS else 'пункт', point)
    if sub:
        out += ', %s %s' % ('подпункт' if point or code in _PUNKT_DOCS else 'пункт', sub)
    return out


def _edition_note(edition, today, stale_days):
    try:
        age = (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(edition)).days
    except (TypeError, ValueError):
        return ''
    return ' Редакция от %s.' % _date_words(edition) if age > stale_days else ''


def _has(r, point, sub):
    """Does the row belong to the point (and subpoint) asked: «3» is the point «3)» with its subpoints and tails; «а» alone is the letter «а)» of a part."""
    if sub:
        return r['kind'] == 'sub' and r['sub'] == sub and (not point or r['point'] == point)
    return (r['point'] == point and r['kind'] in ('point', 'sub', 'cont')) or (r['kind'] == 'sub' and r['sub'] == point and not r['point'])


def _first_run(body, part):
    """The rows of a part number: from its first row until another part begins (a list that starts again at «1.» - the notes of an article of the Criminal Code - is not the part)."""
    out = []
    for r in body:
        if r['part'] == part:
            out.append(r)
        elif out:
            break
    return out


def _resolve(body, part, point, sub, loose):
    """The rows of what is asked: ``(rows, part, point, sub)``. A point without a part is looked for in every part, the first that has it."""
    if loose and part and not point and not sub and not any(r['part'] == part and r['kind'] in ('part', 'para') for r in body):
        if any(r['kind'] == 'point' and r['point'] == part for r in body):
            part, point = '', part
    if not (point or sub):
        return (_first_run(body, part) if part else body), part, point, sub
    if not part:
        part = next((r['part'] for r in body if _has(r, point, sub)), '')
    return [r for r in _first_run(body, part) if _has(r, point, sub)], part, point, sub


def _join_unit(rows, code, bare=False):
    """The spoken text of rows: a point or a subpoint is said with its number, a part's number is in the header. ``bare``: the first row is the unit asked, its number is in the header too."""
    out = []
    for i, r in enumerate(rows):
        text = speak(r['text'])[0] if r['text'] else ''
        if not text:
            continue
        if bare and i == 0:
            out.append(text)
        elif r['kind'] == 'point':
            out.append('%s %s. %s' % ('Подпункт' if code in _PUNKT_DOCS else 'Пункт', r['point'], text))
        elif r['kind'] == 'sub':
            out.append('%s %s. %s' % ('Подпункт' if r['point'] or code in _PUNKT_DOCS else 'Пункт', r['sub'], text))
        else:
            out.append(text)
    return ' '.join(out)


_LOST_SPOKEN = re.compile(r'^утратил[аио]\s+силу(.*)$', re.I | re.S)


def _compose(conn, code, req_part, req_point, article, doc, today, stale_days, req_sub='', loose=False):
    rows = [dict(r) for r in conn.execute('SELECT * FROM rows WHERE doc=? AND article=? ORDER BY seq', (code, article))]
    if not rows:
        return None
    number, head = rk._article_number(article), 'Статья %s %s' % (rk._article_number(article), SPOKEN[code])
    note = _edition_note(rows[0]['edition'] or (doc['edition'] if doc else ''), today, stale_days)
    title = next((r['text'] for r in rows if r['kind'] == 'title'), '')
    body = [r for r in rows if r['kind'] not in ('title', 'cut')]
    cut = ' Страница источника обрезана: здесь не весь текст статьи.' if any(r['kind'] == 'cut' for r in rows) else ''
    if all(r['repealed'] for r in rows if r['kind'] != 'cut'):
        text = speak(next((r['text'] for r in body if r['text']), title))[0]
        lost = _LOST_SPOKEN.match(text)
        if lost:
            return '%s утратила силу%s%s' % (head, lost.group(1), note)
        return ('%s. %s%s' % (head, text, note)) if text else '%s утратила силу.%s' % (head, note)
    if req_point or req_sub or req_part:
        sel, part, point, sub = _resolve(body, req_part, req_point, req_sub, loose)
        kind = next((r['kind'] for r in body if r['part'] == part and r['kind'] in ('part', 'para')), 'part')
        if not sel:
            if req_sub:
                what, wanted = 'подпункта', req_sub
            elif req_point:
                what, wanted = 'подпункта' if code in _PUNKT_DOCS else 'пункта', req_point
            else:
                what, wanted = 'части' if code not in _PUNKT_DOCS or any(r['kind'] == 'para' for r in body) else 'пункта', req_part
            where = ' %s %s' % ('части' if kind == 'para' or code not in _PUNKT_DOCS else 'пункта', req_part) if req_part and (req_point or req_sub) else ''
            return 'В статье %s %s нет %s %s%s.' % (number, SPOKEN[code], what, wanted, where)
        return '%s: %s%s' % (_label(code, article, part, point, sub, kind == 'para'), _join_unit(sel, code, bare=bool(point or sub)), note)
    runs = []                                                      # the parts in the order of the page; a part number met again (the notes) is another run, not the first part
    for r in body:
        if runs and runs[-1][0] == r['part']:
            runs[-1][2].append(r)
        else:
            runs.append((r['part'], r['kind'], [r]))
    if title:
        head += '. ' + speak(title)[0] + '.'
    chunks = []
    for p, kind, rs in runs:
        word = _part_word(code, kind == 'para').capitalize()
        chunks.append(('%s %s. ' % (word, p) if p else '') + _join_unit(rs, code))
    if not title and not chunks:
        return None
    if len(runs) == 1 and not title:
        return '%s: %s%s%s' % (head, chunks[0], cut, note)
    return '%s%s %s%s%s' % (head, '' if title else '.', ' '.join(chunks), cut, note)


def _doc_row(conn, code):
    return conn.execute('SELECT * FROM docs WHERE code=?', (code,)).fetchone()


def _foreign(text, tokens, conn):
    """The utterance names a document the base does not have («закон о персональных данных», УК when it is not loaded)."""
    have = {r['code'] for r in conn.execute('SELECT code FROM docs')}
    asked = _doc_codes(tokens)
    if asked and not asked <= have:
        return True
    keys = si._docs(text)
    if any(k.startswith('law:') or k == 'zk' for k in keys):
        return True
    return not asked and any(k in SPOKEN and k not in have for k in keys)


def _topic_words(topic):
    """``[(stem, whole)]`` for the words of the topic: ``whole`` - the word is no longer than its stem, so the stem still has its ending («плата») and other endings may stand for it."""
    words = {}
    for w in _WORD.findall(_yo(topic)):
        if _yo(w) not in _TOPIC_STOP and _yo(w) not in rk._FILLER and len(stem(w)) >= 3:
            words.setdefault(stem(w), len(_yo(w)) <= 5)
    return list(words.items())


_ENDINGS = 'аяоеыиуюьй'


def _term_rows(conn, word, codes, whole=False):
    """``{article id: (rows with the word, in the title)}`` for a stem. A ``whole`` word is a stem with its ending («плата», «срок»): the same stem with other endings («платы», «срока»,
    «сроки») counts too, half a row each, so that the stem written exactly is still preferred. A stem cut from a longer word («прогул» -> «прогу») is asked as it is."""
    join, args = ('', [])
    if codes:
        join, args = ' JOIN articles ON articles.id = terms.aid WHERE articles.doc IN (%s) AND' % ','.join('?' * len(codes)), sorted(codes)
    where = '' if join else ' WHERE'
    out = {r[0]: (float(r[1]), r[2]) for r in conn.execute('SELECT terms.aid, terms.n, terms.title FROM terms%s%s stem = ?' % (join, where), args + [word])}     # (stem, aid) is the key
    if not whole or len(word) == 5 and word[-1] not in _ENDINGS:
        return out
    low = word if len(word) < 5 else word[:4]
    for r in conn.execute('SELECT terms.aid, terms.n, terms.title FROM terms%s%s stem >= ? AND stem < ? AND stem != ?' % (join, where), args + [low, low + '􏿿', word]):
        n, t = out.get(r[0], (0.0, 0))
        out[r[0]] = (n + 0.5 * r[1], max(t, r[2]))
    return out


# People say «увольнение», the Labour Code says «расторжение трудового договора»; «алименты» are in the Family Code under «содержание». A stem asked is also looked for under these (at 0.7).
_SYNONYMS = {'уволь': ('расто',), 'уволе': ('расто',), 'зарпл': ('зараб',), 'алиме': ('содер',), 'больн': ('нетру',), 'декре': ('берем',), 'прием': ('заклю',)}


def _word_rows(conn, word, whole, codes):
    found = _term_rows(conn, word, codes, whole)
    for other in _SYNONYMS.get(word, ()):
        for aid, (n, t) in _term_rows(conn, other, codes).items():
            m, u = found.get(aid, (0.0, 0))
            found[aid] = (m + 0.7 * n, max(u, 0.7 * t))
    return found


def _search(conn, topic, codes, today, stale_days):
    """«Какая статья про X»: articles that have every word of X (a stem of the first five letters, no morphology). The rarer the word the more it counts, a word in the title adds
    ``TITLE`` of a row. One article when its title is only the words asked, or when it is clearly (``CONFIDENT``) better than the next; else two or three candidates; else ``None``."""
    words = _topic_words(topic)
    if not words:
        return None
    total = _DB.get('total')
    if not total:
        total = _DB['total'] = conn.execute('SELECT count(*) FROM articles WHERE repealed = 0').fetchone()[0] or 1
    score, have, in_title = {}, {}, {}
    for w, whole in words:
        found = _word_rows(conn, w, whole, codes)
        idf = math.log(1 + total / max(1, len(found)))
        for aid, (n, t) in found.items():
            score[aid] = score.get(aid, 0.0) + idf * (n / (n + 1.5) + t)
            have[aid] = have.get(aid, 0) + 1
            in_title[aid] = in_title.get(aid, 0) + (1 if t else 0)
    pool = [a for a in have if have[a] == len(words)] or ([a for a in have if have[a] >= len(words) - 1] if len(words) >= 3 else [])
    if not pool:
        return None
    ranked = sorted(pool, key=lambda a: -score[a])
    exact = [a for a in ranked if in_title[a] == len(words)][:40]                 # the words asked are in the title: is the title nothing but them?
    exact = [a for a in exact if len(words) >= len(_stems(conn.execute('SELECT title FROM articles WHERE id = ?', (a,)).fetchone()[0]).split())]
    if len(exact) == 1:
        ranked = exact
    elif len(ranked) > 1 and score[ranked[1]] <= CONFIDENT * score[ranked[0]]:
        ranked = ranked[:1]
    out = []
    for aid in ranked[:3]:
        r = conn.execute('SELECT doc, article, title FROM articles WHERE id = ?', (aid,)).fetchone()
        said = ' — ' + rk._spoken_title(r['title']) if r['title'] else ''
        if not said:                                                   # an article without a title (the Constitution): its first words say what it is about
            first = conn.execute("SELECT text FROM rows WHERE doc=? AND article=? AND kind NOT IN ('title','cut') AND text != '' ORDER BY seq LIMIT 1", (r['doc'], r['article'])).fetchone()
            said = ', начинается со слов «%s»' % ' '.join(speak(first[0])[0].split()[:6]) if first else ''
        out.append('статья %s %s%s' % (rk._article_number(r['article']), SPOKEN[r['doc']], said))
    if len(out) == 1:
        return 'Об этом %s.' % out[0]
    return 'Подходят %s. Назовите номер.' % '; '.join(out)


def passages(text: str, limit: int = 12) -> list:
    """``answer_witness``: the rows of the law on the words of ``text``, verbatim, those of the best articles first and in each the row with most of the words. Evidence that tells two numbers apart, never an answer: no rule of ``_search`` asks here that one
    article be sure. ``[]`` when there is none. Never raises."""
    try:
        conn = _conn()
        words = _topic_words(text) if conn is not None else []
        if len(words) < 2:
            return []
        total = conn.execute('SELECT count(*) FROM articles WHERE repealed = 0').fetchone()[0] or 1
        score, have = {}, {}
        for w, whole in words:
            found = _word_rows(conn, w, whole, None)
            idf = math.log(1 + total / max(1, len(found)))
            for aid, (n, t) in found.items():
                score[aid] = score.get(aid, 0.0) + idf * (n / (n + 1.5) + t)
                have[aid] = have.get(aid, 0) + 1
        pool = sorted((a for a in have if have[a] >= max(2, len(words) - 1)), key=lambda a: -score[a])[:3]
        stems, out = [w for w, _ in words], []
        for aid in pool:
            r = conn.execute('SELECT doc, article FROM articles WHERE id = ?', (aid,)).fetchone()
            rows = [row[0] for row in conn.execute("SELECT text FROM rows WHERE doc = ? AND article = ? AND kind NOT IN ('title', 'cut') AND text != '' AND repealed = 0 ORDER BY seq", (r['doc'], r['article']))]
            out += sorted(rows, key=lambda row: -sum(w in _yo(row) for w in stems))[:4]
        return out[:limit]
    except Exception as error:  # noqa: BLE001
        _degraded('law_base.search', error)
        return []


def _lookup(text, history, today, stale_days):
    if not isinstance(text, str) or not text.strip() or len(text) > 300:
        return None
    conn = _conn()
    if conn is None:
        return None
    low = _yo(text.strip())
    today = today or datetime.date.today().isoformat()
    tokens = _tokens(low)
    last = _last_law(history)
    if _STARTS.search(low):
        req = _request(_STARTS.sub(' ', low), None)
        if req is not None and req.doc and not _foreign(text, tokens, conn):
            code, article, part, point, sub, loose = req.doc, req.article, req.part, req.point, req.sub, req.loose
        elif last:
            code, article, part, point = last[:4]
            sub, loose = '', False
        else:
            return None
        rows = [dict(r) for r in conn.execute("SELECT * FROM rows WHERE doc=? AND article=? AND kind NOT IN ('title','cut') AND text!='' ORDER BY seq", (code, article))]
        cand, part, point, sub = _resolve(rows, part, point, sub, loose)
        cand = [r for r in cand if r['text']]
        if not cand:
            return None
        first = ' '.join(cand[0]['text'].split()[:3])
        para = cand[0]['kind'] == 'para'
        return '%s начинается со слов «%s».' % (_label(code, article, part, point, sub, para), first)
    req = _request(low, _history_doc(history))
    if req is not None:
        if _foreign(text, tokens, conn) or not req.doc or req.doc not in SPOKEN:
            return None
        doc = _doc_row(conn, req.doc)
        if doc is None:
            return None
        answer = _compose(conn, req.doc, req.part, req.point, req.article, doc, today, stale_days, req.sub, req.loose)
        if answer is None:
            return None
        if si.identity(text, {'title': answer[:120].replace(' дефис ', '-'), 'text': ''}) in ('document', 'article'):         # the search_identity rule: a row of another document or article is no answer («123.20 дефис 2» is said, «123.20-2» is read back)
            return None
        return answer
    if 'стат' in low:
        m = _TOPIC.search(low)
        if m and not _foreign(text, tokens, conn):
            return _search(conn, m.group(1), _doc_codes(tokens), today, stale_days)
    return None


def _degraded(component, error):
    from . import degradation  # noqa: PLC0415 - U78
    degradation.note(component, error)


def lookup(text: str, history: Sequence[str] = (), *, today: Optional[str] = None, stale_days: int = STALE_DAYS) -> Optional[str]:
    """The spoken answer from the law base, else ``None``. Never raises. See the module text."""
    try:
        return _lookup(text, history, today, stale_days)
    except Exception as error:  # noqa: BLE001
        _degraded('law_base.lookup', error)
        return None

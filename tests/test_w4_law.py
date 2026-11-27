"""w4-law: local full-text base of laws on SQLite FTS5: verbatim answers, continuation, search by words, foreign-article guard, speed."""
import os
import statistics
import tempfile
import time
import unittest

from echo_sync import law_base as lb
from echo_sync import portioner
import sys; sys.path.insert(0, os.path.dirname(__file__))
import helpers_law as H

TODAY = '2026-11-05'


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.dir.name, 'law.sqlite')
        cls.parsed = H.build(cls.path)
        lb.use(cls.path)

    @classmethod
    def tearDownClass(cls):
        lb.use(None)
        cls.dir.cleanup()

    def ask(self, text, history=(), **kw):
        return lb.lookup(text, history, today=TODAY, **kw)


class Parse(Base):
    def test_rows_of_a_page(self):
        doc, rows = next(p for p in self.parsed if p[0].code == 'tk')
        self.assertEqual((doc.edition, doc.source), ('2024-08-08', 'https://www.consultant.ru/document/cons_doc_LAW_34683/'))
        got = {(r.article, r.part, r.point): r.text for r in rows}
        self.assertTrue(got[('81', '1', '3')].startswith('несоответствия работника занимаемой должности'))
        self.assertEqual(got[('81', '1', '')], 'Трудовой договор может быть расторгнут работодателем в случаях:')
        self.assertEqual(got[('70', '', '')], 'Испытание при приеме на работу')
        self.assertNotIn('в ред.', ' '.join(got.values()))            # annotations are not law text
        self.assertNotIn('КонсультантПлюс', ' '.join(got.values()))
        self.assertTrue(all(r.source and r.edition for r in rows))

    def test_repealed_article_flagged(self):
        _, rows = next(p for p in self.parsed if p[0].code == 'tk')
        self.assertTrue(all(r.repealed for r in rows if r.article == '82'))
        self.assertFalse(any(r.repealed for r in rows if r.article == '81'))


class Reference(Base):
    def test_article_part_point(self):
        a = self.ask('статья 81 ТК часть 1 пункт 3')
        self.assertTrue(a.startswith('Статья 81 Трудового кодекса, часть 1, пункт 3:'), a)
        self.assertIn('несоответствия работника занимаемой должности или выполняемой работе вследствие недостаточной квалификации, подтвержденной результатами аттестации;', a)
        self.assertNotIn('расторгнут работодателем', a)

    def test_constitution_phrases(self):
        a = self.ask('что говорит статья 19 Конституции')
        self.assertTrue(a.startswith('Статья 19 Конституции'), a)
        self.assertIn('Все равны перед законом и судом.', a)
        self.assertEqual(self.ask('девятнадцатая статья конституции'), a)

    def test_cases_and_colloquial_names(self):
        for q in ('прочитай статью 19 Конституции России', 'в статье девятнадцать основного закона', 'ст. 19 Конституции РФ', 'что в девятнадцатой статье Конституции'):
            self.assertIn('Все равны перед законом', self.ask(q) or '', q)
        self.assertIn('Имя гражданина', self.ask('статья 19 гэ ка'))
        self.assertIn('Налогоплательщики', self.ask('статья 19 налогового кодекса'))

    def test_foreign_article_with_same_number_is_never_taken(self):
        self.assertIsNone(self.ask('статья 19 Уголовного кодекса'))          # the code is known but not in the base
        self.assertIsNone(self.ask('статья 19 закона о персональных данных'))
        self.assertIsNone(self.ask('статья 21 Конституции'))                  # no such article in this base: not a neighbour's
        self.assertIsNone(self.ask('статья 19'))                              # which document?
        a = self.ask('статья 19 ГК')
        self.assertIn('Гражданского кодекса', a)
        self.assertNotIn('Права потребителя', a)

    def test_document_from_history(self):
        a = self.ask('а статья 81 часть 1', ['статья 70 ТК'])
        self.assertIn('Трудового кодекса', a or '')

    def test_missing_part_is_said(self):
        a = self.ask('статья 81 ТК часть 7')
        self.assertIn('нет части 7', a)

    def test_repealed_and_old_edition_are_said(self):
        self.assertIn('утратила силу', self.ask('статья 82 ТК'))
        self.assertIn('Редакция от 8 августа 2024 года', lb.lookup('статья 70 ТК', today='2026-11-05', stale_days=30))
        self.assertNotIn('Редакция', lb.lookup('статья 70 ТК', today='2024-09-01', stale_days=365))

    def test_not_a_law_question(self):
        for q in ('сколько будет два плюс два', 'расскажи про инерцию', 'статья в газете', 'привет', ''):
            self.assertIsNone(self.ask(q), q)


class Verbatim(Base):
    def test_spoken_equals_base_except_reversible_speech_edits(self):
        for q in ('прочитай дословно статью 81 ТК', 'статья 81 ТК часть 2'):
            a = self.ask(q)
            _, rows = next(p for p in self.parsed if p[0].code == 'tk')
            part2 = next(r.text for r in rows if (r.article, r.part, r.point) == ('81', '2', ''))
            spoken, edits = lb.speak(part2)
            self.assertIn(spoken, a)
            self.assertEqual(lb.restore(spoken, edits), part2)
            self.assertNotEqual(spoken, part2)                  # «т.е.» and «5%» were brought to speech

    def test_speech_edits_reversible_and_local(self):
        for text in ('т.е. не более 5% штата', 'и т. д., и т. п., и др.', 'N 197-ФЗ', '12% и 3% и 1%', 'без чисел', 'Статья 81. Расторжение; 15 руб.'):
            spoken, edits = lb.speak(text)
            self.assertEqual(lb.restore(spoken, edits), text)
            outside = ''.join(spoken[i] for i in range(len(spoken)) if not any(s <= i < e for s, e, _ in edits))
            self.assertEqual(len(outside), len(text) - sum(len(o) for _, _, o in edits))
        self.assertEqual(lb.speak('5% штата')[0], 'пять процентов штата')
        self.assertEqual(lb.speak('1% штата')[0], '1% штата')       # the case is not safe: left as written

    def test_first_portion_short_and_to_the_point(self):
        a = self.ask('что говорит статья 81 ТК')
        first = portioner.portions(a)[0]
        self.assertLessEqual(len(first.split()), 6)
        self.assertTrue(a.startswith('Статья 81 Трудового кодекса'))
        self.assertIn('ликвидации организации', a)

    def test_long_article_is_given_whole_and_the_engine_cursor_divides_it(self):
        a = self.ask('статья 81 ТК')
        self.assertNotIn('Дальше — ', a)                   # no pointer of the base's own: the engine's cursor moves on
        self.assertIn('невозможно перевести', a)           # the later part is in the same answer, never cut here
        self.assertGreater(len(portioner.portions(a)), 2)
        self.assertIsNone(self.ask('следующая часть', [a]))     # «следующая часть» / «дальше» are the engine's NEXT, not a lookup of the base
        self.assertIsNone(self.ask('дальше', [a]))


class Continuation(Base):
    def test_which_word_it_starts_with(self):
        first = self.ask('статья 19 Конституции часть 1')
        a = self.ask('с какого слова начинается', [first])
        self.assertIn('«Все равны перед»', a)
        b = self.ask('с какого слова начинается статья 81 ТК пункт 2')
        self.assertIn('«сокращения численности или»', b)
        self.assertIsNone(self.ask('с какого слова начинается', ['привет']))


class Search(Base):
    def test_single_confident_match(self):
        a = self.ask('какая статья про испытательный срок')
        self.assertIsNotNone(a)
        self.assertIn('статья 70 Трудового кодекса — испытание при приёме на работу', a)
        # w6-integ: law_build/law_base.py names 70 and 71 (испытание / результат испытания) and asks the number: a late right answer over an early wrong one; the newer rule wins
        self.assertTrue('статья 71' not in a or a.endswith('Назовите номер.'), a)

    def test_ambiguous_names_two_or_three_candidates(self):
        a = self.ask('какая статья про испытания')
        self.assertIn('статья 70', a)
        self.assertIn('статья 71', a)
        self.assertIn('Назовите номер', a)

    def test_nothing_found_is_none(self):
        self.assertIsNone(self.ask('какая статья про космические ракеты'))
        self.assertIsNone(self.ask('какая статья про'))


class Speed(unittest.TestCase):
    def test_5000_articles_under_5_ms(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'big.sqlite')
            lb.build(path, H.synthetic(5000))
            lb.use(path)
            try:
                for q in ('статья 100 ТК часть 2 пункт 1', 'какая статья про %s %s' % (H.WORDS[10], H.WORDS[20]), 'статья 250 нк'):
                    self.assertIsNotNone(lb.lookup(q, today=TODAY), q)
                    times = []
                    for _ in range(60):
                        t = time.perf_counter()
                        lb.lookup(q, today=TODAY)
                        times.append(time.perf_counter() - t)
                    self.assertLess(statistics.median(times), 0.005, (q, statistics.median(times)))
                    self.assertLess(max(times[5:]), 0.05)
            finally:
                lb.use(None)

    def test_table_of_300_cases(self):
        """300 requests over a 5-document base where every article number exists in every document: each answer is the right document's text, symbol for symbol."""
        import random
        rnd = random.Random(3)
        names = {'tk': 'ТК', 'gk': 'ГК', 'nk': 'НК', 'uk': 'УК', 'sk': 'СК'}
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'small.sqlite')
            parsed = H.synthetic(100)
            lb.build(path, parsed)
            lb.use(path)
            try:
                by = {(doc.code, r.article, r.part, r.point, r.kind): r.text for doc, rows in parsed for r in rows}
                cases = []
                for _ in range(300):
                    code = rnd.choice(list(names))
                    article, part, point = str(rnd.randint(1, 20)), str(rnd.randint(1, 3)), rnd.choice(['', '1', '2'])
                    cases.append((code, article, part, point))
                self.assertEqual(len(cases), 300)
                for code, article, part, point in cases:
                    q = 'статья %s %s часть %s%s' % (article, names[code], part, ' пункт ' + point if point else '')
                    a = lb.lookup(q, today=TODAY, stale_days=10 ** 6)
                    want = by[(code, article, part, point, 'point' if point else 'part')]
                    # w6-integ: law_build/law_base.py (fitted to the real pages) says «пункт» for the codes whose articles are in points (ГК, НК): the newer rule wins
                    self.assertTrue(a.startswith('Статья %s %s, %s %s' % (article, lb.SPOKEN[code], lb._part_word(code), part)), (q, a))
                    self.assertIn(want, a, q)
                    for other in names:
                        if other != code:
                            self.assertNotIn(by[(other, article, part, point, 'point' if point else 'part')], a, q)
                self.assertGreaterEqual(lb.stats()['rows'], 300)
            finally:
                lb.use(None)


class Builder(unittest.TestCase):
    def test_tool_builds_from_files(self):
        import subprocess, sys, json
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, 'tk.html')
            with open(src, 'w', encoding='utf-8') as f:
                f.write(H.page(H.TK[0], H.TK_ARTICLES))
            out = os.path.join(d, 'law.sqlite')
            r = subprocess.run([sys.executable, os.path.join(root, 'tools', 'build_law_base.py'), '--out', out, '--doc', 'tk=%s::%s' % (src, H.TK[1])], capture_output=True, text=True, cwd=root)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout)['documents'], 1)
            lb.use(out)
            try:
                self.assertIn('Испытание', lb.lookup('статья 70 ТК', today=TODAY))
            finally:
                lb.use(None)


if __name__ == '__main__':
    unittest.main()

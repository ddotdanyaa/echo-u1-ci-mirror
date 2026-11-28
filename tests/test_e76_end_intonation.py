"""E76: the end of an answer is heard. The SSML builder, how the manager hands it to the worker, and (when Irina is installed) the real voice."""
import os
import tempfile
import unittest
import wave
import xml.dom.minidom
from pathlib import Path
from unittest.mock import patch

try:
    from echo_sync import sapi_worker
    from echo_sync.sapi_worker import END_STYLES, SapiWorkerError, SapiWorkerManager, _XML_BAD, end_ssml
except ImportError:  # pragma: no cover
    sapi_worker = None

HEAD = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ru-RU">'


def body(ssml):
    return ssml[len(HEAD):-len('</speak>')]


def text_of(ssml):
    """What the engine would read: all text nodes joined (markup removed)."""
    document = xml.dom.minidom.parseString(ssml.encode('utf-8'))
    out = []

    def walk(node):
        for child in node.childNodes:
            if child.nodeType == child.TEXT_NODE:
                out.append(child.data)
            else:
                walk(child)
    walk(document)
    return ''.join(out)


@unittest.skipIf(sapi_worker is None, 'echo_sync.sapi_worker is not importable')
class EndSsmlTable(unittest.TestCase):
    CASES = (
        ('в 1223 году.', {}, '<prosody pitch="-30%">в 1223 году.</prosody>'),                     # a number goes into the span with its noun and the word before it; the dot too
        ('Закон принят 6 декабря 2011 года.', {}, 'Закон <prosody pitch="-30%">принят 6 декабря 2011 года.</prosody>'),   # a whole date
        ('Срок — до 25 марта.', {}, 'Срок — <prosody pitch="-30%">до 25 марта.</prosody>'),       # the preposition that governs the number
        ('Работает с 9:00 до 18:00.', {}, 'Работает с 9:00 <prosody pitch="-30%">до 18:00.</prosody>'),
        ('Это было в XIX веке.', {}, 'Это было в <prosody pitch="-30%">XIX веке.</prosody>'),
        ('Прибыль 3 млн руб.', {}, '<prosody pitch="-30%">Прибыль 3 млн руб.</prosody>'),      # scale word and dotted abbreviation
        ('Налог составляет 25%.', {}, 'Налог <prosody pitch="-30%">составляет 25%.</prosody>'),
        ('Проезд обойдётся вам в 500 ₽.', {}, 'Проезд обойдётся вам <prosody pitch="-30%">в 500 ₽.</prosody>'),
        ('Это статья 252.', {}, 'Это <prosody pitch="-30%">статья 252.</prosody>'),
        ('Столица России — Москва.', {}, 'Столица России — <prosody pitch="-30%">Москва.</prosody>'),
        ('Да.', {}, '<prosody pitch="-30%">Да.</prosody>'),
        ('Нет', {}, '<prosody pitch="-30%">Нет</prosody>'),
        ('«Да»', {}, '«<prosody pitch="-30%">Да»</prosody>'),                                      # an opening quote stays outside
        ('Так? Нет!!!', {}, 'Так? <prosody pitch="-30%">Нет!!!</prosody>'),
        ('кто-нибудь…', {}, '<prosody pitch="-30%">кто-нибудь…</prosody>'),
        ('Это входит в т.ч. НДС.', {}, 'Это входит в <prosody pitch="-30%">т.ч. НДС.</prosody>'),
        ('Спад привёл к росту цен.', {'words': 2}, 'Спад привёл к <prosody pitch="-30%">росту цен.</prosody>'),
        ('один два', {'pitch': '-20%', 'rate': '-10%'}, 'один <prosody pitch="-20%" rate="-10%">два</prosody>'),
        ('Если x < 5 & y > 3, то A&B.', {'words': 3},
         'Если x &lt; 5 &amp; y <prosody pitch="-30%">&gt; 3, то A&amp;B.</prosody>'),             # & < > escaped
    )

    def test_table(self):
        for text, kwargs, want in self.CASES:
            with self.subTest(text=text, kwargs=kwargs):
                self.assertEqual(body(end_ssml(text, **kwargs)), want)

    def test_the_text_itself_is_never_changed(self):
        """Numbers stay digits and nothing is added or dropped: the engine reads the same characters as in plain speech."""
        texts = [case[0] for case in self.CASES] + [
            'Тег <b>жирный</b> и &amp; литерал.', 'a\x00b\x0bc', 'Кавычки "двойные" и \'одинарные\'.', '1 < 2 > 0 & 3.',
            'в 15:30 по Москве.', 'Дробь 3,5 и 1 000 000 рублей.', '<speak>тест</speak>', ']]> конец']
        for text in texts:
            with self.subTest(text=text):
                ssml = end_ssml(text)
                self.assertIsNotNone(ssml)
                xml.dom.minidom.parseString(ssml.encode('utf-8'))                  # well-formed XML
                self.assertEqual(text_of(ssml), _XML_BAD.sub(' ', text))           # the same text, markup apart

    def test_nothing_to_mark(self):
        for text in ('', '   ', '...', '—', '«»', ' . '):
            with self.subTest(text=text):
                self.assertIsNone(end_ssml(text))

    def test_xml_forbidden_characters_are_blanked(self):
        ssml = end_ssml('ab\x00cd\x1fef ￾ gh')
        xml.dom.minidom.parseString(ssml.encode('utf-8'))
        self.assertNotRegex(ssml, '[\x00-\x08\x0b\x0c\x0e-\x1f￾]')


@unittest.skipIf(sapi_worker is None, 'echo_sync.sapi_worker is not importable')
class ManagerHandsOverTheMarkup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.requests = []
        manager = SapiWorkerManager('k')
        self.addCleanup(manager.close)

        def fake_request(this, text, output, trace=None, ssml=None):
            self.requests.append((text, ssml))
            with wave.open(str(output), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b'\x00\x01' * 2400)
        self.fake = patch.object(SapiWorkerManager, '_request_locked', fake_request)
        self.fake.start()
        self.addCleanup(self.fake.stop)
        self.manager = manager
        self.out = str(Path(self.tmp.name) / 'cue.wav')

    def test_plain_without_end(self):
        self.manager.synthesize('в 1223 году.', self.out)
        self.assertEqual(self.requests, [('в 1223 году.', None)])

    def test_markup_only_with_a_known_end(self):
        self.manager.synthesize('в 1223 году.', self.out, end='fall')
        text, ssml = self.requests[-1]
        self.assertEqual(text, 'в 1223 году.')                                         # the text is still sent: the worker's fallback
        self.assertEqual(body(ssml), '<prosody pitch="-30%">в 1223 году.</prosody>')
        for end in (None, '', 'rise', 'FALL', 5):
            self.manager.synthesize('в 1223 году.', self.out, end=end)
            self.assertIsNone(self.requests[-1][1], end)

    def test_a_text_with_no_word_is_plain(self):
        self.manager.synthesize('...', self.out, end='fall')
        self.assertIsNone(self.requests[-1][1])

    def test_a_builder_failure_is_plain_speech_not_a_failed_cue(self):
        with patch.object(sapi_worker, 'end_ssml', side_effect=RuntimeError('boom')):
            self.manager.synthesize('в 1223 году.', self.out, end='fall')
        self.assertEqual(self.requests[-1], ('в 1223 году.', None))
        self.assertTrue(os.path.exists(self.out))

    def test_the_style_table_is_what_the_measurement_chose(self):
        self.assertEqual(END_STYLES, {'fall': {'pitch': '-30%'}})


def real_voice_manager():
    if os.name != 'nt' or sapi_worker is None:
        return None
    manager = SapiWorkerManager('e76-real', startup_timeout=20, request_timeout=30)
    try:
        manager.warm()
    except Exception:
        manager.close()
        return None
    return manager


def pcm_of(path):
    with wave.open(str(path), 'rb') as audio:
        return audio.readframes(audio.getnframes())


@unittest.skipIf(sapi_worker is None, 'echo_sync.sapi_worker is not importable')
class RealIrina(unittest.TestCase):
    """Needs Windows and Microsoft Irina Desktop; skipped elsewhere. Measures nothing by ear: it pins what the engine does with the markup."""

    @classmethod
    def setUpClass(cls):
        cls.manager = real_voice_manager()
        if cls.manager is None:
            raise unittest.SkipTest('Microsoft Irina Desktop is not available')
        cls.tmp = tempfile.TemporaryDirectory()

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, 'manager', None):
            cls.manager.close()
            cls.tmp.cleanup()

    def render(self, text, name, end=None, ssml=None):
        path = Path(self.tmp.name) / (name + '.wav')
        if ssml is None:
            self.manager.synthesize(text, str(path), end=end)
        else:
            with self.manager._lock:
                self.manager._request_locked(text, path, None, ssml)
        return pcm_of(path)

    def test_the_tag_alone_changes_nothing_so_only_the_pitch_does(self):
        """pitch="+0%" around the last word (numbers with their noun, escaped & < >) gives the very same samples as plain speech."""
        texts = ['Закон о бухгалтерском учёте принят 6 декабря 2011 года.', 'Налоговый кодекс вступил в силу 1 января 1999 года.',
                 'Декларацию нужно сдать до 25 марта.', 'Налог составляет 25%.', 'Проезд обойдётся вам в 500 ₽.', 'Битва на реке Калке произошла в 1223 году.',
                 'Это статья 252.', 'Да.', 'Если x < 5 и y > 3, то A & B.', 'Столица России — Москва.', 'Отчёт нужно сдавать всегда.',
                 'Работает с 9:00 до 18:00.', 'Прибыль 3 млн руб.', 'Это было в XIX веке.', 'Тираж 5 тыс. экземпляров.', 'Звоните по номеру 8 800 555 35 35.',
                 'Приказ № 94н от 31 октября 2000 года.', 'В период 2019–2021 годов.', 'Ему 22 года.', 'Сумма 1 234,56 руб.', 'Он ответил: «Да».',
                 'Это сказал А. С. Пушкин.', 'Подождите…', 'Среда, 5 ноября 2026 года.']
        for i, text in enumerate(texts):
            with self.subTest(text=text):
                neutral = end_ssml(text, pitch='+0%')
                self.assertEqual(self.render(text, 'p%d' % i, ssml=neutral), self.render(text, 'q%d' % i))

    def test_fall_moves_the_last_word_and_not_the_length(self):
        text = 'Спад производства привёл к росту цен.'
        plain = self.render(text, 'plain')
        with self.assertNoLogs('echo-sync', level='WARNING'):                             # the voice accepted the markup
            fall = self.render(text, 'fall', end='fall')
        self.assertNotEqual(plain, fall)
        self.assertLessEqual(abs(len(plain) - len(fall)), 2 * 24)                        # within 1 ms of samples: no pause, no stretch

    def test_markup_the_voice_refuses_is_spoken_plain(self):
        text = 'Спад производства привёл к росту цен.'
        bad = HEAD + 'Спад производства привёл к росту <prosody volume="-6dB">цен</prosody>.</speak>'
        with self.assertLogs('echo-sync', level='WARNING') as logged:                     # the loss is not silent
            refused = self.render(text, 'refused', ssml=bad)
        self.assertTrue(any('refused the markup' in line for line in logged.output), logged.output)
        self.assertEqual(refused, self.render(text, 'plain2'))
        self.assertEqual(self.render('Да.', 'after'), self.render('Да.', 'after2'))     # the worker is still in step afterwards


if __name__ == '__main__':
    unittest.main()

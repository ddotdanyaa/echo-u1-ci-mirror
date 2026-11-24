"""U19-S5: English runs of a cue are read by the English voice (Zira) inside the Irina SSML; no key since one-input U19."""
import os
import tempfile
import unittest
import wave
import xml.dom.minidom
from pathlib import Path
from unittest.mock import patch

from echo_sync import sapi_worker
from echo_sync.controlled_host import voice_key
from echo_sync.sapi_worker import SapiWorkerManager, lang_ssml


class LangSsml(unittest.TestCase):
    def test_one_word_in_russian_is_plain(self):
        self.assertIsNone(lang_ssml('Ссылка в Excel.'))
        self.assertIsNone(lang_ssml('Это просто русский текст.'))
        self.assertIsNone(lang_ssml('...'))

    def test_a_mixed_cue_has_one_voice_element(self):
        ssml = lang_ssml('Он сказал: what is the main risk here? Это важно.')
        self.assertEqual(ssml.count('<voice '), 1)
        self.assertIn('>what is the main risk here</voice>', ssml)
        doc = xml.dom.minidom.parseString(ssml.encode('utf-8'))
        self.assertEqual(len(doc.getElementsByTagName('voice')), 1)
        self.assertEqual(''.join(n.data for n in doc.getElementsByTagName('voice')[0].childNodes), 'what is the main risk here')

    def test_text_is_not_changed_and_escaped(self):
        ssml = lang_ssml('Он сказал: the cat & the dog are here. Ок.')
        doc = xml.dom.minidom.parseString(ssml.encode('utf-8'))
        said = ''.join(n.data for n in doc.documentElement.childNodes if n.nodeType == n.TEXT_NODE) + doc.getElementsByTagName('voice')[0].firstChild.data
        self.assertIn('the cat & the dog are here', said)

    def test_pure_english_is_all_in_the_voice(self):
        ssml = lang_ssml('What is the main risk here?')
        self.assertEqual(ssml.count('<voice '), 1)
        self.assertIn('>What is the main risk here</voice>?</speak>', ssml)

    def test_voice_key_apart_only_when_on(self):
        self.assertEqual(voice_key('v', 'fall'), 'v:fall:speech')
        self.assertEqual(voice_key('v', None, True), 'v:speech:voices')


class ManagerWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.requests = []

        def fake_request(this, text, output, trace=None, ssml=None):
            self.requests.append((text, ssml))
            with wave.open(str(output), 'wb') as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(24000)
                audio.writeframes(b'\x00\x01' * 2400)
        p = patch.object(SapiWorkerManager, '_request_locked', fake_request)
        p.start()
        self.addCleanup(p.stop)
        self.manager = SapiWorkerManager('u19-s5')
        self.out = str(Path(self.tmp.name) / 'cue.wav')

    def test_english_run_is_voiced_with_no_flag_and_a_russian_cue_is_plain(self):
        self.manager.synthesize('Он сказал: what is the main risk here? Ок.', self.out)
        self.assertIn('<voice ', self.requests[-1][1])
        self.manager.synthesize('Ссылка в Excel.', self.out)
        self.assertIsNone(self.requests[-1][1])

    def test_language_wins_over_the_end(self):
        text = 'Он сказал: what is the main risk here? Ок.'
        self.manager.synthesize(text, self.out, end='fall')
        self.assertIn('<voice ', self.requests[-1][1])
        self.assertNotIn('<prosody', self.requests[-1][1])

    def test_russian_cue_keeps_the_end(self):
        self.manager.synthesize('Ссылка в Excel.', self.out, end='fall')
        self.assertIn('<prosody', self.requests[-1][1])
        self.manager.synthesize('Ссылка в Excel.', self.out)
        self.assertIsNone(self.requests[-1][1])

    def test_builder_failure_is_plain(self):
        with patch.object(sapi_worker, 'lang_ssml', side_effect=RuntimeError('x')):
            self.manager.synthesize('what is the main risk here?', self.out)
        self.assertIsNone(self.requests[-1][1])

    def test_the_call_path_gives_the_english_voice_its_words(self):
        from echo_sync.controlled_host import render_cue_pcm
        self.assertTrue(render_cue_pcm(self.manager, 'Главный риск: what is the main risk here? Ок, 5 дней.', self.tmp.name))
        text, ssml = self.requests[-1]
        self.assertIn('>what is the main risk here?</voice>', ssml)      # not «вхат ай эс те риск» in Irina's letters
        self.assertIn('пять дней', ssml)

    def test_say_leaves_the_english_run_to_the_english_voice(self):
        # the one way a text becomes a voice file: ``speak`` must not bring English to Russian letters before the worker builds the voice markup (a call of 16.11: «вхат ай эс те риск»)
        sapi_worker.say(self.manager, 'Он сказал: what is the main risk here? Всего 5 раз.', self.out)
        text, ssml = self.requests[-1]
        self.assertIn('what is the main risk here?', text)
        self.assertIn('<voice ', ssml)
        self.assertNotIn('вхат', text)
        self.assertIn('пять раз', text)


class RefusedMarkup(unittest.TestCase):
    def test_lang_fallback_is_counted(self):
        m = SapiWorkerManager('u19-s5b')
        with patch.object(SapiWorkerManager, '_start_locked'), patch.object(SapiWorkerManager, '_alive_locked', return_value=True), \
                patch.object(SapiWorkerManager, '_cancel_idle_locked'), patch.object(SapiWorkerManager, '_schedule_idle_locked'), \
                patch.object(SapiWorkerManager, '_read_response_locked', side_effect=lambda t: {'type': 'result', 'id': 'i1', 'ok': True, 'voice': m.VOICE, 'culture': m.CULTURE, 'ssml': False}), \
                patch('echo_sync.sapi_worker.uuid.uuid4') as u:
            u.return_value.hex = 'i1'
            m._process = type('P', (), {'stdin': type('S', (), {'write': lambda s, x: None, 'flush': lambda s: None})()})()
            m._request_locked('hi there', Path(tempfile.gettempdir()) / 'x.wav', None, sapi_worker.lang_ssml('what is the main risk here?'))
        self.assertEqual(m.lang_fallbacks, 1)


def _pcm(path):
    with wave.open(str(path), 'rb') as a:
        return a.readframes(a.getnframes())


@unittest.skipUnless(os.name == 'nt', 'Windows SAPI')
class RealVoices(unittest.TestCase):
    def test_english_wav_equals_plain_zira(self):
        import subprocess
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        text = 'What is the main risk here?'
        manager = SapiWorkerManager('u19-s5-real', startup_timeout=20, request_timeout=30)
        try:
            manager.warm()
        except Exception:
            manager.close()
            self.skipTest('Irina is not available')
        self.addCleanup(manager.close)
        a = Path(tmp.name) / 'lang.wav'
        manager.synthesize(text, str(a))
        b = Path(tmp.name) / 'zira.wav'
        script = ("Add-Type -AssemblyName System.Speech;$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                  "try{$s.SelectVoice('Microsoft Zira Desktop')}catch{exit 3};"
                  "$f=[System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(24000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono);"
                  f"$s.SetOutputToWaveFile('{b}',$f);$s.Speak('{text}');$s.Dispose()")
        r = subprocess.run(['powershell', '-NoProfile', '-Command', script], capture_output=True)
        if r.returncode != 0:
            self.skipTest('Zira is not available')
        self.assertEqual(manager.lang_fallbacks, 0)
        self.assertEqual(_pcm(a), _pcm(b))


if __name__ == '__main__':
    unittest.main()


def test_the_host_marks_lang_per_cue_not_for_every_cue():
    host = (Path(__file__).resolve().parents[1] / 'echo_sync' / 'controlled_host.py').read_text(encoding='utf-8')
    assert 'lang=lang_ssml(text) is not None' in host and 'end,lang,ranges_on' in host

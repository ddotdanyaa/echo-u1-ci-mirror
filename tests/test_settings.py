"""materials/echo_settings.json: defaults in code, forgiving loader, validated values."""
import json
import tempfile
import unittest
from pathlib import Path

try:
    from echo_sync import settings as cfg
    from echo_sync.textutil import normalize
except ImportError:
    cfg = normalize = None


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(cfg, 'Settings module has not been implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'echo_settings.json'

    def test_defaults_are_simple_and_backward_compatible(self):
        d = cfg.resolve(None)
        self.assertEqual(d['portion_mode'], 'words')
        self.assertEqual(d['words_per_portion'], 3)
        self.assertEqual((d['target_syllables'], d['max_syllables'], d['max_words'], d['min_words'], d['long_word_syllables']), (8, 12, 5, 1, 6))
        self.assertEqual(d['abbreviations'], {})
        self.assertNotIn('ack_match', d)      # the repeat is judged by the aligned match in every call: the key left
        self.assertNotIn('on_mismatch', d)      # a try that is no repeat is silence in every call: the key left
        self.assertNotIn('echo_guard', d)      # our own voice is judged by the controller's cue window only: the engine's guard left with its key
        self.assertNotIn('inline_repeat', d)      # the portion is said once: the key left with the second path
        self.assertIn('так', d['fillers'])
        self.assertEqual(d['cancel_min_words'], 3)
        self.assertEqual((d['question_window'], d['repeat_cover'], d['attempt_extra_words']), (3, 0.8, 3))
        self.assertNotIn('bank_min_words', d)      # the classifier has no bank of its own: one lookup (``PreparedAnswers``)
        self.assertEqual(d['sec_per_syllable'], 0.2)

    def test_default_clarifications_replay_the_portion_and_exclude_phone_commands(self):
        clarifications = cfg.resolve(None)['clarifications']
        for phrase in ('еще', 'ещё', 'а', 'что', 'не понял', 'не расслышал', 'не слышу', 'еще раз', 'ещё раз'):
            self.assertIn(normalize(phrase), clarifications, phrase)
        # The phone handles these WHOLE utterances itself, they never reach the server.
        for phrase in ('стоп', 'хватит', 'замолчи', 'тише', 'пока', 'до свидания', 'закончить разговор', 'это всё'):
            self.assertNotIn(normalize(phrase), clarifications, phrase)

    def test_every_key_is_documented_in_settings_md(self):
        document = (Path(__file__).resolve().parents[1] / 'SETTINGS.md').read_text(encoding='utf-8')
        for key in cfg.DEFAULTS:
            self.assertIn(f'`{key}`', document, f'{key} is missing from SETTINGS.md')

    def test_u07_keys_are_off_by_default_and_clamped(self):
        d = cfg.resolve(None)
        self.assertEqual((d['pcm_record_calls'], d['pcm_record_mb']), (20, 2048))
        self.assertNotIn('pcm_record', d)      # a phone call is always recorded: no switch
        r = cfg.resolve({'pcm_record_calls': 50})
        self.assertEqual(r['pcm_record_calls'], 50)

    def test_adopt_missing_words_has_no_key_the_keep_of_chatter_replaced_it(self):
        self.assertNotIn('adopt_missing_words', cfg.resolve({'adopt_missing_words': 2}))
        self.assertNotIn('keep_ready', cfg.resolve({'keep_ready': 'on'}))

    def test_missing_file_gives_defaults(self):
        self.assertEqual(cfg.load(self.path), cfg.resolve(None))
        self.assertEqual(cfg.load(None), cfg.resolve(None))

    def test_partial_file_overrides_only_the_given_keys(self):
        self.path.write_text(json.dumps({'portion_mode': 'syllables', 'target_syllables': 6}), encoding='utf-8')
        loaded = cfg.load(self.path)
        self.assertEqual(loaded['portion_mode'], 'syllables')
        self.assertEqual(loaded['target_syllables'], 6)
        self.assertEqual(loaded['max_syllables'], 12)

    def test_file_is_re_read_on_every_call(self):
        self.path.write_text('{"words_per_portion": 2}', encoding='utf-8')
        self.assertEqual(cfg.load(self.path)['words_per_portion'], 2)
        self.path.write_text('{"words_per_portion": 5}', encoding='utf-8')
        self.assertEqual(cfg.load(self.path)['words_per_portion'], 5)

    def test_bom_and_unicode_are_accepted(self):
        self.path.write_text(json.dumps({'abbreviations': {'ВВП': 'валовой внутренний продукт'}}, ensure_ascii=False), encoding='utf-8-sig')
        self.assertEqual(cfg.load(self.path)['abbreviations'], {'ВВП': 'валовой внутренний продукт'})

    def test_broken_json_or_wrong_shape_falls_back_to_defaults(self):
        for text in ('{not json', '[1, 2]', '"text"', '', 'null'):
            self.path.write_text(text, encoding='utf-8')
            self.assertEqual(cfg.load(self.path), cfg.resolve(None), text)

    def test_invalid_values_fall_back_per_key(self):
        loaded = cfg.resolve({'portion_mode': 'poetry', 'words_per_portion': 'три',
                              'target_syllables': -4, 'max_words': 0,
                              'sec_per_syllable': -1, 'max_syllables': 10})
        defaults = cfg.resolve(None)
        for key in ('portion_mode', 'words_per_portion',
                    'target_syllables', 'max_words', 'sec_per_syllable'):
            self.assertEqual(loaded[key], defaults[key], key)
        self.assertEqual(loaded['max_syllables'], 10)

    def test_unknown_keys_are_ignored(self):
        self.assertEqual(cfg.resolve({'shout': True}), cfg.resolve(None))

    def test_numbers_are_accepted_as_json_numbers_only(self):
        self.assertEqual(cfg.resolve({'words_per_portion': 4})['words_per_portion'], 4)
        self.assertEqual(cfg.resolve({'words_per_portion': 4.0})['words_per_portion'], 4)
        self.assertEqual(cfg.resolve({'words_per_portion': 4.5})['words_per_portion'], 3)
        self.assertEqual(cfg.resolve({'words_per_portion': True})['words_per_portion'], 3)
        self.assertEqual(cfg.resolve({'sec_per_syllable': 1})['sec_per_syllable'], 1.0)
        self.assertEqual(cfg.resolve({'repeat_cover': 0})['repeat_cover'], 0.0)

    def test_limits_are_kept_consistent(self):
        loaded = cfg.resolve({'target_syllables': 20, 'max_syllables': 10, 'min_words': 7, 'max_words': 3})
        self.assertLessEqual(loaded['target_syllables'], loaded['max_syllables'])
        self.assertLessEqual(loaded['min_words'], loaded['max_words'])

    def test_lists_and_dictionaries_are_cleaned(self):
        loaded = cfg.resolve({'fillers': ['Так', ' ну ', 5, '', 'Ещё'], 'clarifications': 'не список',
                              'abbreviations': {'ВВП': 'продукт', 'x': 5, 3: 'y', 'пусто': ''}})
        self.assertEqual(loaded['fillers'], ['так', 'ну', 'еще'])
        self.assertEqual(loaded['clarifications'], cfg.resolve(None)['clarifications'])
        self.assertEqual(loaded['abbreviations'], {'ВВП': 'продукт'})

    def test_u14_memory_has_no_switch(self):
        d = cfg.resolve({k: 'on' for k in ('conversation_ledger', 'recall_words', 'ledger_carry', 'topic_recap', 'resume_next_day')})      # always on: no key
        for key in ('conversation_ledger', 'recall_words', 'ledger_carry', 'topic_recap', 'resume_next_day'):
            self.assertNotIn(key, d)
            self.assertNotIn(key, cfg.DEFAULTS)

    def test_u19_language_flags_matrix(self):
        d = cfg.resolve(None)
        self.assertNotIn('answer_lang', d)       # one-input U19: the answer line and the voice follow the turn, no key
        self.assertNotIn('tts_lang', d)
        self.assertNotIn('lang_turn', d)         # f84a05a9: the language of the turn gates the Russian ear always, no key
        self.assertNotIn('lang_turn', cfg.DEFAULTS)
        self.assertNotIn('cross_script', d)      # a rule of the language of the turn (the repeat compares scripts), no key
        self.assertNotIn('ear_en', d)            # the English ear is no rule: an English turn waits for the cloud's final
        for lt in ('off', 'shadow', 'on', 'bogus'):
            self.assertNotIn('lang_turn', cfg.resolve({'lang_turn': lt}), lt)      # a profile that still says it changes nothing
        once = cfg.resolve({'lang_turn': 'on'})
        self.assertEqual(cfg.resolve(once), once)

    def test_resolve_is_idempotent(self):
        once = cfg.resolve({'portion_mode': 'syllables', 'sec_per_syllable': 0.3})
        self.assertEqual(cfg.resolve(once), once)

    def test_defaults_cannot_be_modified_through_a_resolved_copy(self):
        value = cfg.resolve(None)
        value['fillers'].append('нечто')
        value['abbreviations']['x'] = 'y'
        again = cfg.resolve(None)
        self.assertNotIn('нечто', again['fillers'])
        self.assertEqual(again['abbreviations'], {})


if __name__ == '__main__':
    unittest.main()

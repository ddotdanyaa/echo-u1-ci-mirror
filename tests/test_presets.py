import json
import tempfile
import unittest
from pathlib import Path

from echo_sync.settings import resolve, DEFAULTS
from echo_sync.portioner import portions


class PresetTests(unittest.TestCase):
    def test_preset_profiles_and_default_compatibility(self):
        self.assertEqual(resolve(None)['words_per_portion'], 3)
        strict = resolve({'preset': 'strict_triples'})
        self.assertEqual((strict['portion_mode'], strict['words_per_portion']), ('words', 3))
        adaptive = resolve({'preset': 'adaptive'})
        self.assertEqual((adaptive['portion_mode'], adaptive['target_syllables'], adaptive['max_syllables'], adaptive['max_words']), ('syllables', 8, 12, 6))
        slow = resolve({'preset': 'slow'})
        self.assertEqual((slow['portion_mode'], slow['target_syllables'], slow['max_syllables'], slow['max_words']), ('syllables', 5, 8, 3))

    def test_explicit_valid_override_wins_and_invalid_preset_uses_defaults(self):
        self.assertEqual(resolve({'preset': 'slow', 'target_syllables': 7})['target_syllables'], 7)
        invalid = resolve({'preset': 'unknown'})
        self.assertEqual(invalid['portion_mode'], DEFAULTS['portion_mode'])
        self.assertEqual(invalid['target_syllables'], DEFAULTS['target_syllables'])

    def test_invalid_explicit_override_falls_back_to_selected_preset(self):
        resolved = resolve({'preset': 'slow', 'target_syllables': 'slow'})
        self.assertEqual(resolved['target_syllables'], 5)
        self.assertEqual(resolved['max_syllables'], 8)
        self.assertEqual(resolved['portion_mode'], 'syllables')

    def test_malformed_preset_values_are_safe_in_resolve_and_load(self):
        malformed = ([], {}, True, 7)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'echo_settings.json'
            for value in malformed:
                with self.subTest(value=value):
                    self.assertEqual(resolve({'preset': value}), resolve(None))
                    path.write_text(json.dumps({'preset': value}), encoding='utf-8')
                    self.assertEqual(__import__('echo_sync.settings', fromlist=['load']).load(path), resolve(None))

    def test_resolving_presets_never_mutates_defaults(self):
        original = list(DEFAULTS['fillers'])
        resolve({'preset': 'adaptive'})['fillers'].append('test')
        self.assertEqual(DEFAULTS['fillers'], original)

    def test_presets_keep_function_words_numbers_and_abbreviations_intact(self):
        text = 'Он говорил о 15 % роста ВВП и статье 228 УК РФ.'
        settings = {'preset': 'slow', 'abbreviations': {'ВВП': 'валовой внутренний продукт'}}
        result = portions(text, settings)
        self.assert_group_in_one_portion(result, 'о 15 %')
        self.assert_group_in_one_portion(result, 'статье 228')
        self.assert_group_in_one_portion(result, 'УК РФ')
        self.assert_group_in_one_portion(result, 'валовой внутренний продукт')
        function_words = {'о', 'и', 'в', 'на', 'к', 'с', 'из', 'по', 'за', 'для', 'от', 'до'}
        for portion in result:
            last = portion.rstrip(' ,.;:!?…—–)').split()[-1].strip('«»„“()[]{}')
            self.assertNotIn(last.lower(), function_words, (portion, last))

    def assert_group_in_one_portion(self, portions_list, group):
        self.assertEqual(sum(group in portion for portion in portions_list), 1, (group, portions_list))


if __name__ == '__main__':
    unittest.main()

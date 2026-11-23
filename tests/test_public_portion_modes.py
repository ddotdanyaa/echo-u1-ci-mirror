import unittest

from echo_sync.settings import resolve
from echo_sync.portioner import portions


class PublicPortionModeTests(unittest.TestCase):
    def test_compatibility_aliases_keep_existing_profiles(self):
        for alias, old in (('fixed_3', 'strict_triples'), ('slow_assistive', 'slow')):
            with self.subTest(alias=alias):
                selected = dict(resolve({'preset': alias}))
                existing = dict(resolve({'preset': old}))
                selected.pop('preset'); existing.pop('preset')
                self.assertEqual(selected, existing)
                self.assertEqual(resolve({'preset': alias})['preset'], alias)

    def test_new_profiles_have_explicit_different_load_budgets(self):
        semantic = resolve({'preset': 'semantic_short'})
        pronunciation = resolve({'preset': 'pronunciation_short'})
        self.assertEqual(semantic['portion_mode'], 'syllables')
        self.assertEqual(pronunciation['portion_mode'], 'syllables')
        self.assertEqual(semantic['target_syllables'], 10)
        self.assertEqual(pronunciation['target_syllables'], 6)
        self.assertGreater(semantic['max_words'], pronunciation['max_words'])

    def test_explicit_settings_override_profile_and_keep_canonical_content(self):
        text = 'Финансовая система состоит из нескольких связанных частей. Ставка равна 15 %.'
        for preset in ('fixed_3','semantic_short','pronunciation_short','adaptive','slow_assistive'):
            with self.subTest(preset=preset):
                cfg = resolve({'preset': preset, 'target_syllables': 7})
                self.assertEqual(cfg['target_syllables'], 7)
                self.assertEqual(' '.join(portions(text, cfg)), text)


if __name__ == '__main__':
    unittest.main()

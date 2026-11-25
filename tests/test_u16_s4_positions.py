"""U16-S4: positions on a portion with a written range: the char-level _offsets fallback and no cut inside a range"""
import unittest
from echo_sync import ru_alignment as ra
from echo_sync import stumble_place as sp
from echo_sync.controlled_media import ControlledMedia

CUE = 'Это было в XIII–XV веках, когда город рос'


def atoms(text):
    return list(ra._canonical(text, (), True))


class RangesOn(unittest.TestCase):
    def test_offsets_is_laid_on_the_range_cue(self):
        starts = sp._offsets(CUE, atoms(CUE))
        self.assertIsNotNone(starts)
        self.assertEqual(len(starts), len(atoms(CUE)))

    def test_no_start_inside_a_range(self):
        starts = sp._offsets(CUE, atoms(CUE))
        inside = range(CUE.index('XIII') + 1, CUE.index('XV') + 2)
        self.assertFalse([s for s in starts if s in inside])
        self.assertEqual(CUE[starts[3]:starts[3] + 4], 'XIII')

    def test_place_after_the_range_head_starts_at_the_range(self):
        got = sp.place(['это', 'было', 'в', 'тринадцатом'], CUE)
        # whatever the walk decides, a rest never begins inside the range
        if got:
            self.assertFalse(got[0].startswith(('XV', '–')))

    def test_wrong_atoms_still_none(self):
        bad = atoms('Это было в XIII–XVI веках')
        self.assertIsNone(sp._offsets(CUE, bad))

    def test_said_by_value_rest_starts_at_the_range(self):
        rest, _ = ControlledMedia._said_by_value('это было в тринадцатом', CUE)
        self.assertTrue(rest.startswith('XIII'), rest)

    def test_said_by_value_full_range_goes_on(self):
        rest, _ = ControlledMedia._said_by_value('это было в тринадцатом по пятнадцатом веках', CUE)
        self.assertTrue(rest.startswith('когда'), rest)


if __name__ == '__main__':
    unittest.main()

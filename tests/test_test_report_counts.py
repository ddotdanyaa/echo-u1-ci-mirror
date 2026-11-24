"""Failure observations from subTests must not produce negative passed counts."""
import importlib.util
from pathlib import Path
import unittest


class ReportCountTests(unittest.TestCase):
    def helper(self):
        path = Path(__file__).resolve().parents[1]/'tools/run_tests.py'
        spec = importlib.util.spec_from_file_location('echo_test_runner_counts', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        helper = getattr(module, 'result_counts', None)
        self.assertTrue(callable(helper), 'Runner needs explicit method/subtest accounting')
        return helper

    def test_many_failed_subtests_count_one_failed_method(self):
        helper = self.helper()
        class Cases(unittest.TestCase):
            def runTest(self):
                for i in range(4):
                    with self.subTest(i=i):
                        self.assertEqual(i, -1)
        result = unittest.TestResult(); Cases().run(result)
        report = helper(result)
        self.assertEqual(report['total'], 1)
        self.assertEqual(report['failures'], 4)
        self.assertEqual(report['failed_test_methods'], 1)
        self.assertEqual(report['passed'], 0)

    def test_pass_fail_error_skip_and_expected_outcomes_remain_separate(self):
        helper = self.helper()
        class Cases(unittest.TestCase):
            def test_pass(self): pass
            def test_fail(self): self.fail('controlled')
            def test_error(self): raise ValueError('controlled')
            @unittest.skip('controlled')
            def test_skip(self): pass
            @unittest.expectedFailure
            def test_expected(self): self.fail('controlled')
        result = unittest.TestResult(); unittest.defaultTestLoader.loadTestsFromTestCase(Cases).run(result)
        report = helper(result)
        self.assertEqual(report['total'], 5)
        self.assertEqual(report['passed'], 1)
        self.assertEqual(report['error_test_methods'], 1)
        self.assertEqual(report['skipped'], 1)
        self.assertEqual(report['expected_failures'], 1)

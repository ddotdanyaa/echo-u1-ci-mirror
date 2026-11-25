"""Run reproducible offline tests with project-local dependencies; never install packages."""
import argparse
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


def result_counts(result):
    """Keep assertion observations separate from affected test methods."""
    def owners(items):
        return {id(getattr(test, 'test_case', test)) for test, *_ in items}
    failed = owners(result.failures)
    errors = owners(result.errors)
    skipped = owners(result.skipped)
    expected = owners(result.expectedFailures)
    unexpected = {id(test) for test in result.unexpectedSuccesses}
    not_passed = failed | errors | skipped | expected | unexpected
    return {'total': result.testsRun, 'passed': result.testsRun - len(not_passed),
            'failures': len(result.failures), 'errors': len(result.errors),
            'failed_test_methods': len(failed), 'error_test_methods': len(errors),
            'skipped': len(result.skipped), 'expected_failures': len(result.expectedFailures),
            'unexpected_successes': len(result.unexpectedSuccesses)}


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pattern', default='test*.py')
    parser.add_argument('--name', default='current_suite')
    parser.add_argument('--hermes-source', type=Path)
    args = parser.parse_args()
    if Path(args.name).name != args.name:
        parser.error('--name must be a filename stem')
    sys.path[:0] = [str(root), str(root / '.test-deps')]
    evidence = root / 'evidence'
    evidence.mkdir(exist_ok=True)
    # Imports from real Hermes must never default to the user's normal home.
    with tempfile.TemporaryDirectory(prefix='test-home-', dir=evidence) as temporary:
        if args.hermes_source:
            source = args.hermes_source.resolve(strict=True)
            os.environ['HERMES_SOURCE'] = str(source)
            sys.path.append(str(source))
        else:
            os.environ.pop('HERMES_SOURCE', None)
        os.environ['HERMES_HOME'] = temporary
        os.environ['HERMES_GATEWAY_LOCK_DIR'] = str(Path(temporary) / 'locks')
        started = time.perf_counter()
        with (evidence / f'{args.name}.log').open('w', encoding='utf-8') as stream:
            suite = unittest.defaultTestLoader.discover(str(root / 'tests'), pattern=args.pattern)
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        report = {
            **result_counts(result),
            'seconds': round(time.perf_counter() - started, 3),
            'success': result.wasSuccessful(), 'physical_iphone': False,
            'hermes_source': str(args.hermes_source) if args.hermes_source else None,
            'skips': [{'test': str(test), 'reason': reason} for test, reason in result.skipped],
        }
        (evidence / f'{args.name}.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False))
        return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from echo_sync.plugin import EchoPlugin


class GenerationTraceWiringTests(unittest.TestCase):
    def test_default_generator_trace_is_inside_supplied_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('echo_sync.plugin.PrivateCodexGenerator') as factory:
                plugin = EchoPlugin(directory)
                factory.assert_called_once_with(trace_path=Path(directory) / 'echo-sync' / 'generation-latency.jsonl')
                self.assertIs(plugin._generate, factory.return_value)

    def test_injected_generator_is_preserved_without_constructing_default(self):
        with tempfile.TemporaryDirectory() as directory:
            sentinel = lambda *args: 'local answer'
            with patch('echo_sync.plugin.PrivateCodexGenerator') as factory:
                plugin = EchoPlugin(directory, generate=sentinel)
                factory.assert_not_called()
                self.assertIs(plugin._generate, sentinel)


if __name__ == '__main__':
    unittest.main()

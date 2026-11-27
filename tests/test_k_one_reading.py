"""K (M1, U94.1 / U15): the kind of an utterance is read by ONE reader per call and judged by ONE table. The old side doors are gone and the number of readers is a lock.

Gone in this change (each one was a second road to the same verdict, or dead code that the census counted as a place of the family):
  * ``classifier.classify``: a public ``(kind, reason)`` entrance beside the judge, called by tests only;
  * ``ControlledMedia._tempo_across``: the ear's «behind / ahead» verdict, with no caller left;
  * ``utterance_judge.diff_hash``: it froze the shadow diff of the judge's order, which was deleted with ``judge_order``.
The lock counts the places that call ``analyze``: the call's own reading (``cm_probes``, which ``ControlledMedia._classify`` reaches), the host with no controller (``plain_ruling``), the ear's shadow
(``ear_shadow``, a trace, not a verdict), the warm-up and the classifier's own rule for a friend's question over the owner's words. A new reader is a new row of the judge, not a new call."""
import ast
import logging
import re
from pathlib import Path

from echo_sync import classifier, utterance_judge
from echo_sync.controlled_media import ControlledMedia
from helpers_w1f import Wire

ECHO = Path(__file__).resolve().parents[1] / 'echo_sync'
READERS = {'classifier.py': 1, 'cm_probes.py': 1, 'ear_shadow.py': 1, 'utterance_judge.py': 1, 'warm.py': 1}      # file -> calls of ``analyze(`` (the number is the lock)


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def _calls(name):
    found = {}
    for path in sorted(ECHO.glob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        count = sum(isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name) and node.func.id == name) or (isinstance(node.func, ast.Attribute) and node.func.attr == name))
                    for node in ast.walk(tree))
        if count:
            found[path.name] = count
    return found


def test_the_side_doors_of_the_kind_are_gone():
    assert not hasattr(classifier, 'classify')
    assert not hasattr(utterance_judge, 'diff_hash')
    assert not hasattr(ControlledMedia, '_tempo_across')
    text = '\n'.join(path.read_text(encoding='utf-8') for path in ECHO.glob('*.py'))
    assert not re.search(r'\bdef classify\(|_tempo_across|diff_hash', text)


def test_the_readers_of_a_text_are_counted():
    assert _calls('analyze') == READERS


def test_the_real_controller_reads_a_final_once_and_names_the_row_that_judged_it(tmp_path, caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')
    wire = Wire(tmp_path)
    wire.user('u1', 'Что такое инерция?', 0.0, 2.0)
    wire.until(6.0)
    lines = [record.getMessage() for record in caplog.records if record.getMessage().startswith('echo-sync judge tid=u1')]
    assert lines, 'a final has one judge line'
    assert re.search(r'kind=question reason=\S+ rule=\S+ chain=\S+ analyses=\d+', lines[-1]), lines[-1]
    assert not any(record.getMessage().startswith('echo-sync classify ') for record in caplog.records)      # the old side door wrote its own line for the same words

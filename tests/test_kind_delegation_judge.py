"""kind: the model's delegation is EVIDENCE for the one judge (cm_kind), not a judge of its own. The real chain ControlledMedia -> NativeMediaSocket on the
virtual-time rig: a delegation on an unfinished question is read by the judge (``_delegation_opens``), counted in the ``analyses`` of that final, and a
delegation on speech the judge does not read as a question opens nothing. No ``probe('analyze')`` / bare ``analyze(`` stands outside the judge."""
import re
from pathlib import Path

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_wire
from test_first_cue_never_silent import created, done

ECHO = Path(__file__).resolve().parents[1] / 'echo_sync'


def _judged(log, tid):
    return re.findall(r'echo-sync judge tid=%s kind=(\w+) reason=\S+ rule=\S+ chain=\S+ analyses=(\d+)' % tid, log)


def test_a_delegation_on_a_question_partial_is_read_by_the_judge_and_counted(tmp_path, monkeypatch, caplog):
    caplog.set_level('INFO')

    async def body(rig):
        await rig.feed(created('u1', 'user', 'Что такое фотосинтез'))
        await rig.feed(F.delegation('d-u1', 'u1'))
        await rig.advance(0.5)
    run_wire(tmp_path, monkeypatch, body)
    log = caplog.text
    assert 'cause=delegation' in log                                  # the delegation made the judge take the partial: the question is opened
    rows = _judged(log, 'u1')
    assert rows and rows[0][0] == 'question' and int(rows[0][1]) == 2, rows      # one reading ahead of the judge + the judge's own: all counted


def test_a_delegation_on_speech_that_is_no_question_opens_nothing(tmp_path, monkeypatch, caplog):
    caplog.set_level('INFO')

    async def body(rig):
        await rig.feed(created('u1', 'user', 'ну вот так вот'))
        await rig.feed(F.delegation('d-u1', 'u1'))
        await rig.advance(0.5)
    run_wire(tmp_path, monkeypatch, body)
    assert 'cause=delegation' not in caplog.text and not _judged(caplog.text, 'u1')     # no verdict, no question: the evidence did not stand


def test_no_analyze_is_made_outside_the_judge():
    bare = {}
    for path in ECHO.glob('*.py'):
        text = path.read_text(encoding='utf-8')
        hits = len(re.findall(r"probe\(\s*'analyze'", text))
        if hits:
            bare[path.name] = hits
    assert bare == {'cm_kind.py': 1}, bare                            # the one reading: KindMixin._classify
    for name in ('cm_question.py', 'cm_route.py', 'cm_portion.py', 'controlled_media.py'):
        assert not re.search(r'(?<![\w.])analyze\(', (ECHO / name).read_text(encoding='utf-8')), name

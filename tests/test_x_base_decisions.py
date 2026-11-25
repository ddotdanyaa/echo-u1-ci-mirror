"""X-BASE: the multiset of the ``echo-sync decision`` lines the controller says on the replay of each journal of the corpus (the manifest). A recorder, not a check:
without ``ECHO_BASE_OUT`` it skips. With it, one file per journal ``{journal}.json`` = ``{'lines': [...]}`` goes to that folder; two folders are compared by
``python -m tools.move_check decisions a b`` (a step that must not change a decision, e.g. U15-S1, leaves the difference at 0).
"""
import json
import logging
import os
from pathlib import Path

import pytest

from tools import harvest as H

import test_h3_tempo                                           # noqa: F401
from test_h3_tempo import call, the_whole_call                 # noqa: F401 - call is the fixture
from test_harvest import replay, harvested

OUT = os.environ.get('ECHO_BASE_OUT')


class Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines = []

    def emit(self, record):
        message = record.getMessage()
        if message.startswith('echo-sync decision '):
            self.lines.append(message)


@pytest.mark.parametrize('path', harvested(), ids=lambda path: path.stem if path else 'none')
def test_record_the_decision_lines(call, monkeypatch, path):
    if not OUT or path is None:
        pytest.skip('a recorder: set ECHO_BASE_OUT to a folder')
    fixture = json.loads(path.read_text(encoding='utf-8'))
    rig = call(fast_text='on', max_auto_repeats=fixture.get('profile', {}).get('max_auto_repeats', 1))
    seen, logger = Lines(), logging.getLogger('echo-sync')
    logger.addHandler(seen)
    level = logger.level
    logger.setLevel(logging.INFO)
    try:
        replay(rig, monkeypatch, fixture)
    finally:
        logger.removeHandler(seen)
        logger.setLevel(level)
    Path(OUT).mkdir(parents=True, exist_ok=True)
    (Path(OUT) / (path.stem + '.json')).write_text(json.dumps({'journal': path.stem, 'n': len(seen.lines), 'lines': sorted(seen.lines)}, ensure_ascii=False, indent=0), encoding='utf-8')

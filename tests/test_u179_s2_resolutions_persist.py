# factory-backlog-id: U179.s2
from pathlib import Path

from echo_sync import reasons
from echo_sync.controlled_media import ControlledMedia


def test_resolutions_survive_a_restart_in_the_project_folder(tmp_path):
    db = str(tmp_path / 'echo.db')
    kind = sorted(reasons.KINDS)[0]
    first = ControlledMedia(db, session_id='s-u179')
    assert first.resolutions.path is not None
    journal = Path(first.resolutions.path)
    assert tmp_path in journal.parents
    rec, outcome = first.resolutions.resolve('t-u179', resolution=kind)
    assert outcome == 'new'
    assert journal.exists()
    second = ControlledMedia(db, session_id='s-u179')
    got = second.resolutions.records.get('t-u179')
    assert got is not None
    assert got['resolution'] == kind
    assert got['tid'] == 't-u179'
    assert Path(second.resolutions.path) == journal

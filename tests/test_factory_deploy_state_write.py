# factory-backlog-id: U104.2
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / 'tools')):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tools import deploy  # noqa: E402


def test_concurrent_state_writers_do_not_share_staging_file(tmp_path, monkeypatch):
    target = tmp_path / 'current.json'
    real_write_text = pathlib.Path.write_text
    state = {'nested': False}

    def patched(self, data, *args, **kwargs):
        result = real_write_text(self, data, *args, **kwargs)
        if not state['nested'] and data == 'A' and self.name.endswith('.tmp'):
            state['nested'] = True
            deploy._write(target, 'B')
        return result

    monkeypatch.setattr(pathlib.Path, 'write_text', patched)
    error = None
    try:
        deploy._write(target, 'A')
    except FileNotFoundError as exc:
        error = exc
    monkeypatch.setattr(pathlib.Path, 'write_text', real_write_text)

    assert state['nested'] is True
    assert error is None
    assert target.read_text(encoding='utf-8') == 'A'
    assert sorted(p.name for p in tmp_path.iterdir()) == ['current.json']

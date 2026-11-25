import pathlib
from unittest.mock import MagicMock
from tools.factory_loop import Loop

def test_prune_snapshots_keeps_active_hypo_roots(tmp_path):
    cfg = MagicMock()
    cfg.state_dir = str(tmp_path / 'loop_dir')
    cfg.review_model = 'large'
    cfg.large_model = 'large'
    cfg.small_model = 'small'
    
    loop = Loop(cfg)
    snapshots_dir = tmp_path / 'src_snapshots'
    snapshots_dir.mkdir()
    loop.snapshots_dir = snapshots_dir
    
    snap_path = snapshots_dir / 'snap_1'
    snap_path.mkdir()
    (snap_path / 'data.json').write_text('{}')
    
    # Simulate an active hypothesis search
    mock_prefetch = MagicMock()
    mock_prefetch.ctx = {'root': str(snap_path.resolve())}
    loop._hypers['test_hypo'] = mock_prefetch

    loop._prune_snapshots()
    assert snap_path.exists(), 'Snapshot should be kept while HY search is active in _hypers'

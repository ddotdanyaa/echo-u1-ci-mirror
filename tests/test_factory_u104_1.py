# factory-backlog-id: U104.1
import gc
import warnings
from echo_sync.helper_pool import SpareHelper

def test_spare_helper_ensure_later_no_running_loop():
    helper = SpareHelper(lambda: None)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        res = helper.ensure_later()
        gc.collect()

    assert res is None
    runtime_warnings = [
        warning for warning in w
        if issubclass(warning.category, RuntimeWarning)
        and "never awaited" in str(warning.message)
    ]
    assert not runtime_warnings

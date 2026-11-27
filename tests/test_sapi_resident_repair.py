# factory-backlog-id: rel-base-w5x7-repair-over-attempt
import threading
import time
from echo_sync.sapi_worker import SapiWorkerManager

def test_resident_worker_repair_after_max_restarts():
    # Use a popen_factory that always fails to trigger MAX_AUTO_RESTARTS
    def failing_popen(*args, **kwargs):
        raise RuntimeError("Simulated process failure")

    manager = SapiWorkerManager(
        profile_key="test_profile",
        popen_factory=failing_popen,
        startup_timeout=0.01,
        request_timeout=0.01,
        idle_timeout=0.01
    )
    
    # Force the manager to reach MAX_AUTO_RESTARTS
    manager.keep_resident()
    
    # Wait for the supervisor to give up
    # MAX_AUTO_RESTARTS is typically 5. We wait for failures to accumulate.
    deadline = time.time() + 2
    while manager._failures < manager.MAX_AUTO_RESTARTS and time.time() < deadline:
        time.sleep(0.01)
    
    # Capture the supervisor thread that gave up
    old_supervisor = manager._supervisor
    
    # This call should re-arm the supervisor and spawn a NEW thread
    manager.keep_resident()
    
    # The bug is that manager._supervisor still points to old_supervisor,
    # so _touch_supervisor() sees it as "still running" and doesn't start a new one.
    assert manager._supervisor is not old_supervisor, "A new supervisor thread should have been spawned"

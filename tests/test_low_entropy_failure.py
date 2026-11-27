# factory-backlog-id: U94.7.s1
import asyncio
from echo_sync.native_media_socket import NativeMediaSocket

def test_low_entropy_failure_suppression():
    class MockController:
        def __init__(self):
            self.diagnostics = 0
        def diagnostic_line(self, code, epoch, model_answer, now):
            return "low_entropy_key", "spoken"
        def diagnostic_began(self, now):
            self.diagnostics += 1

    def emit(event): pass
    
    clock = [0.0]
    controller = MockController()
    # diagnostic_audio must be provided to avoid 'no_audio' outcome
    socket = NativeMediaSocket(controller, emit, None, None, None, clock=lambda: clock[0], diagnostic_audio={"low_entropy_key": b"pcm"})
    
    # Trigger 10 identical failures. 
    # If entropy logic is missing, it will announce 10 times.
    for i in range(10):
        socket._announce(code=400, reason="identical reason")
        # Ensure the task is spawned
        if socket.diagnostic_task:
            asyncio.run(socket.diagnostic_task)
            socket.diagnostic_task = None
    
    # Expect suppression: only a subset of these should have been announced.
    assert controller.diagnostics < 5, f"Expected low-entropy suppression, but got {controller.diagnostics} announcements"

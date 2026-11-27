"""Windows ASGI uses Selector: the existing helper needs a private Proactor."""
import asyncio
import os
import sys
import pytest
from echo_sync.helper_bridge import ThreadedHelperBridge

@pytest.mark.skipif(os.name!='nt',reason='Windows event-loop regression')
def test_helper_pipe_on_selector_loop_closes_without_global_policy_change(tmp_path):
    script=tmp_path/'child.py'
    script.write_text("import sys,struct\nsys.stdout.buffer.write(b'O'+struct.pack('>I',2)+b'ok');sys.stdout.buffer.flush()\nsys.stdin.buffer.read()\n",encoding='utf-8')
    async def run():
        original=asyncio.get_running_loop()
        bridge=ThreadedHelperBridge(script,python=sys.executable)
        try:
            await bridge.start()
            assert await bridge.receive(5)==('O',b'ok')
            assert asyncio.get_running_loop() is original
        finally:
            assert await bridge.close()==0
        assert not bridge.thread.is_alive()
        assert await bridge.close()==0
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:runner.run(run())

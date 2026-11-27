"""fac-red-async (prompt part): live 19.11 20:51, the test of <id> was an `async def` test with @pytest.mark.asyncio;
the project has no async pytest plugin, so it failed with pytest's own 'async def functions are not natively
supported' and never ran the code. The test writer must be told to drive async code with asyncio.run()."""
from tools import agent_factory as F
from tools import agent_factory_runner as W


def test_the_test_writer_is_told_to_drive_async_code_with_asyncio_run():
    task = F.read_plan([dict(id='T1', title='Test for the spare helper', kind='unit_test',
                             touch_files=['tests/test_x.py'], tests=['tests/test_x.py'], read_files=[],
                             privacy_safe=True, estimated_tokens=100)])['T1']
    prompt = W.build_coder_prompt(task, {}, light=True)
    assert 'asyncio.run(' in prompt and 'pytest-asyncio' in prompt

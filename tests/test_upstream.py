"""Run with HERMES_SOURCE pointing at an unmodified Hermes checkout; no credentials/calls."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as S
from unittest.mock import patch

SOURCE = os.environ.get('HERMES_SOURCE')
if SOURCE:
    sys.path.insert(0, SOURCE)


@unittest.skipUnless(SOURCE, 'Set HERMES_SOURCE for actual Hermes middleware/transport tests')
class UpstreamTests(unittest.TestCase):
    def test_actual_canonical_native_completion_is_empty_only_in_opted_in_profile(self):
        import asyncio
        import importlib.util
        import time
        import host_patch
        from gateway import response_filters
        from gateway.run import GatewayRunner
        from gateway.config import Platform
        from gateway.session import SessionSource
        from gateway.platforms.event import MessageEvent
        from gateway.session_settlement_recovery import completion_payload
        with tempfile.TemporaryDirectory() as tmp:
            root, home = Path(tmp) / 'source', Path(tmp) / 'echo-profile'
            for rel in host_patch.REQUIRED_HASHES:
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((Path(SOURCE) / rel).read_bytes())
            # This EchoSource already has the exact guarded patch. Include its
            # original backup so strict production validation can verify both bytes.
            backup_rel = host_patch.TARGET + '.echo-sync.bak'
            source_backup = Path(SOURCE) / backup_rel
            if source_backup.is_file():
                backup = root / backup_rel
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(source_backup.read_bytes())
            host_patch.apply_patch(root, home)
            spec = importlib.util.spec_from_file_location('echo_patched_response_filters', root / host_patch.TARGET)
            patched = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(patched)
            runner = object.__new__(GatewayRunner)
            runner._delivery_adapter_for = lambda source: None  # no I/O transport attached in this offline test
            runner._voice_mode = {}
            source = SessionSource(platform=Platform.LOCAL, chat_id='native-test', user_id='operator')
            entry = S(session_id='native-test')
            event = MessageEvent(text='wrong repeat', source=source)
            result = {'final_response':'NO_REPLY', 'completed':True, 'failed':False, 'messages':[], 'api_calls':1}
            async def run():
                response, silent, messages = await runner._hmwa_shape_agent_response(result, source, [], entry, '', '', 1, entry.session_id, 'local', time.time())
                self.assertTrue(silent)
                self.assertEqual(response, 'NO_REPLY')
                delivered = await runner._hmwa_deliver_turn_response(event, source, entry, '', 1, result, messages, response, '', silent)
                self.assertEqual(delivered, '')
                payload = completion_payload({'admission_id':'test-admission'}, {'outcome':'completed'}, delivered, {'result':result})
                self.assertEqual(payload['text'], '')
                self.assertEqual(payload['content'], '')
                self.assertEqual(payload['status'], 'complete')
            with patch.dict(os.environ, {'HERMES_HOME':str(home)}), patch.object(response_filters, 'silence_allowed', patched.silence_allowed):
                self.assertTrue(response_filters.silence_allowed(None, True))
                asyncio.run(run())
            other = Path(tmp) / 'normal-profile'
            with patch.dict(os.environ, {'HERMES_HOME':str(other)}):
                self.assertFalse(patched.silence_allowed(None, True))

    def test_whole_actual_agent_completes_chunks_and_silence_without_stream_or_provider(self):
        import json
        import run_agent
        from echo_sync.plugin import EchoPlugin
        from hermes_cli import plugins
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'config.yaml').write_text(json.dumps({'model': {'provider':'openai-codex', 'streaming':False, 'openai_runtime':'auto'}, 'compression':{'enabled':False}, 'auxiliary':{'title_generation':{'enabled':False}, 'background_review':{'enabled':False}}, 'memory':{'memory_enabled':False, 'user_profile_enabled':False}}))
            generations = []
            def generate(*args):
                generations.append(args)
                return 'Первый второй третий четвёртый пятый шестой'
            plugin = EchoPlugin(home, generate=generate)
            manager = plugins.PluginManager()
            manager._discovered = True
            manager._hooks.setdefault('pre_llm_call', []).append(plugin.capture)
            manager._middleware.setdefault('llm_execution', []).append(plugin.execute)
            with patch.dict(os.environ, {'HERMES_HOME':tmp}), patch.object(plugins, '_delivery_manager', return_value=manager), patch('model_tools.get_tool_definitions', return_value=[]), patch('model_tools.check_toolset_requirements', return_value={}):
                agent = run_agent.AIAgent(model='gpt-5-codex', provider='openai-codex', api_mode='codex_responses', base_url='https://chatgpt.com/backend-api/codex', api_key='test-oauth-placeholder', quiet_mode=True, max_iterations=1, enabled_toolsets=[], skip_context_files=True, skip_memory=True)
                agent._persist_session = lambda *a, **k: None
                agent._save_trajectory = lambda *a, **k: None
                agent._cleanup_task_resources = lambda *a, **k: None
                called, deltas, history = [], [], []
                def forbidden(*args, **kwargs):
                    called.append(args)
                    raise AssertionError('No outer provider request is allowed')
                agent._interruptible_api_call = forbidden
                agent._interruptible_streaming_api_call = forbidden
                try:
                    replies = []
                    for text in ['Что это?', 'первый второй третий', 'неправильно', 'четвертый пятый шестой']:
                        result = agent.run_conversation(text, conversation_history=history, stream_callback=deltas.append)
                        self.assertTrue(result['completed'], result)
                        self.assertFalse(result.get('failed'), result)
                        self.assertEqual(result['api_calls'], 1, result)
                        history = result['messages']
                        replies.append(result['final_response'])
                    self.assertEqual(replies, ['Первый второй третий', 'четвёртый пятый шестой', 'NO_REPLY', 'NO_REPLY'])
                    self.assertEqual(len(generations), 1)
                    self.assertEqual(called, [])
                    self.assertEqual(deltas, [])
                finally:
                    agent.close()
                    # Hermes keeps routed profile log lock files open independently
                    # of AIAgent.close(); release only this test's temporary home.
                    import hermes_logging
                    hermes_logging.enable_profile_log_routing([home, home / 'secondary-profile'])
                    hermes_logging.release_profile_log_handlers(home)
                    hermes_logging.release_profile_log_handlers(home / 'secondary-profile')

    def test_actual_hook_provider_wrapper_and_transport_repeat_gate(self):
        from echo_sync.plugin import EchoPlugin
        from agent.turn_api_call import perform_api_call
        from agent.transports.codex import ResponsesApiTransport
        from hermes_cli import plugins
        generations = []
        with tempfile.TemporaryDirectory() as tmp:
            def generate(*args):
                generations.append(args)
                return 'Первый второй третий четвёртый пятый шестой'
            plugin = EchoPlugin(tmp, generate=generate)
            manager = plugins.PluginManager()
            manager._discovered = True
            manager._hooks.setdefault('pre_llm_call', []).append(plugin.capture)
            manager._middleware.setdefault('llm_execution', []).append(plugin.execute)
            transport = ResponsesApiTransport()
            terminal = []
            def forbidden(request, **kwargs):
                terminal.append(request)
                raise AssertionError('Outer provider must never run')
            agent = S(_disable_streaming=True, api_mode='codex_responses', provider='openai-codex',
                      base_url='https://chatgpt.com/backend-api/codex', model='gpt-5-codex',
                      session_id='actual-source', platform='tui', _has_pending_redirect=lambda:False,
                      _interruptible_api_call=forbidden, _interruptible_streaming_api_call=forbidden)
            with patch.object(plugins, '_delivery_manager', return_value=manager):
                results = []
                for i, text in enumerate(['Что это?', 'первый второй третий', 'неправильно', 'четвертый пятый шестой']):
                    turn = f'turn-{i}'
                    manager.invoke_hook('pre_llm_call', session_id=agent.session_id, turn_id=turn, user_message=text)
                    verdict = perform_api_call(agent, api_kwargs={'input':[]}, _original_api_kwargs={}, _llm_middleware_trace=[], _moa_prepared_request=None, _retry=S(), thinking_spinner=None, retry_count=0, api_call_count=1, api_request_id=turn, effective_task_id='task', turn_id=turn, interrupted=False)
                    self.assertTrue(transport.validate_response(verdict.response))
                    normalized = transport.normalize_response(verdict.response)
                    self.assertEqual(normalized.finish_reason, 'stop')
                    self.assertFalse(normalized.tool_calls)
                    results.append(normalized.content)
                self.assertEqual(results, ['Первый второй третий', 'четвёртый пятый шестой', 'NO_REPLY', 'NO_REPLY'])
                self.assertEqual(len(generations), 1)
                self.assertEqual(terminal, [])


if __name__ == '__main__':
    unittest.main()

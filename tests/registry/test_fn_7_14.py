"""Реестр 7.14: подключение к Hermes и звуковому помощнику Conduit.

Две половины, обе без сети. (1) Плагин: Hermes вызывает register(ctx), контроллер ставит свой ввод и своё
промежуточное звено, и ход разговора, прошедший через них, отвечает из подготовленного банка, не обращаясь к облаку.
(2) Звонок: настоящий controlled_host.serve принимает звонок Conduit (подставной телефон, помощник облака и SAPI на
виртуальном времени, HostRig) и подключает контроллер: журнал звонка и подсказка, которую услышал телефон.
Подделки только на границе: модуль hermes_constants, ctx Hermes, телефон, облачный помощник, синтез.
"""
import json
import logging
import sys
import types
from pathlib import Path

import pytest

import helpers_s6_fault as F
from helpers_spoken_diagnostics import run_host

QUESTION = 'Что такое равновесие весов?'
ANSWER = 'Равновесие весов наступает, когда обе чаши весят одинаково, и стрелка стоит ровно посередине.'
BANK_QUESTION = 'Что такое запасной ключ?'
BANK_ANSWER = 'Запасной ключ лежит у соседей на верхней полке.'
CODEX = dict(provider='openai-codex', api_mode='codex_responses', base_url='https://chatgpt.com/backend-api/codex',
             model='test-model', session_id='s1', turn_id='1')


@pytest.fixture(autouse=True)
def decisions_are_logged(caplog):
    caplog.set_level(logging.INFO, logger='echo-sync')


def journal(home):
    files = sorted((f for f in (Path(home) / 'logs' / 'echo_calls').glob('*.jsonl') if '.v5tap' not in f.name))
    assert len(files) == 1, files
    return [json.loads(line) for line in files[0].read_text(encoding='utf-8').splitlines()]


def hermes_ctx(registered):
    """Внешняя граница: то, что Hermes передаёт плагину при загрузке."""
    return types.SimpleNamespace(
        get_config=lambda key, default=None: default,
        register_hook=lambda name, fn: registered['hooks'].__setitem__(name, fn),
        register_middleware=lambda name, fn: registered['middleware'].__setitem__(name, fn),
        register_cli_command=lambda name, help_text, setup, fn: registered['cli'].__setitem__(name, fn))


def test_hermes_loads_the_profile_and_a_turn_is_answered_by_the_controller(tmp_path, monkeypatch):
    materials = tmp_path / 'materials'
    materials.mkdir()
    (materials / 'qa.json').write_text(json.dumps([{'question': BANK_QUESTION, 'answer': BANK_ANSWER}], ensure_ascii=False), encoding='utf-8')
    monkeypatch.setitem(sys.modules, 'hermes_constants', types.SimpleNamespace(get_hermes_home=lambda: tmp_path))
    registered = {'hooks': {}, 'middleware': {}, 'cli': {}}
    import echo_sync
    echo_sync.register(hermes_ctx(registered))
    assert set(registered['hooks']) == {'pre_llm_call'} and set(registered['middleware']) == {'llm_execution'}
    assert {'echo-host-info', 'echo-import'} <= set(registered['cli'])

    registered['hooks']['pre_llm_call'](user_message=BANK_QUESTION, **CODEX)
    reply = registered['middleware']['llm_execution'](request={}, next_call=lambda request: pytest.fail('ход ушёл мимо контроллера'), **CODEX)
    spoken = reply.output_text
    assert spoken and spoken != 'NO_REPLY', 'контроллер промолчал на вопрос из банка'
    assert BANK_ANSWER.startswith(spoken), spoken
    # чужой провайдер контроллер не обслуживает и в обход облака не пускает
    other = dict(CODEX, provider='openai', turn_id='2')
    registered['hooks']['pre_llm_call'](user_message=BANK_QUESTION, **other)
    assert registered['middleware']['llm_execution'](request={}, next_call=lambda request: pytest.fail('провалилось к провайдеру'), **other).output_text == 'NO_REPLY'


def test_a_conduit_call_is_accepted_and_the_controller_speaks_and_journals(tmp_path, monkeypatch):
    async def body(host):
        # звонок принят: handshake Conduit прошёл, телефон получил ready, заголовок журнала назван
        head = journal(host.home)[0]
        assert head['ev'] == 'call_open' and head['source'] == 'phone'
        await host.ask(QUESTION, tid='u1')
        await host.answer(ANSWER, tid='a1')
        await host.advance(2)
        # опоры: реплики дошли до журнала, значит контроллер подключён к потоку звонка
        rows = journal(host.home)
        assert [r['text'] for r in rows if r['ev'] == 'user_final'] == [QUESTION]
        assert [r['text'] for r in rows if r['ev'] == 'assistant_final'] == [ANSWER]
        # внешний эффект: решение принято, подсказка опубликована телефону и совпадает с журналом
        assert [r for r in rows if r['ev'] == 'decision'], 'решения контроллера нет в журнале'
        cues = [r['text'] for r in rows if r['ev'] == 'cue']
        heard = host.spoken()
        assert cues and cues == heard
        assert ' '.join(heard).split()[0] == ANSWER.split()[0]
        assert 'error' not in {f.type for f in host.ws.frames}
    run_host(tmp_path, monkeypatch, body)

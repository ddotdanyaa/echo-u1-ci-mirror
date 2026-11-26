"""Live lab, level1-c of 06.11 (question 19, step 73): «Какой штраф за неуплату налога».  The model delegated the question to the public lookup, and the
final of the question hit the local reference base: its cue «Двадцать процентов от неуплаченной суммы.» began to sound (``_publish_reference``: from then on
nothing of the model or of the lookup is this question's answer).  The lookup came back with three rows (lookup_end source_count 3), ``grounding`` kept
none of them (the local answer owns the question), ``no_source`` refused to answer a «штраф» from memory (``route_need (CHANGES)``), and the socket reported
the lookup as failed: the error frame ``controlled_sources_unavailable`` and the spoken «Поиск не ответил.», which CUT the cue 0.8 s after it began.
A lookup nobody needs is no failure: nothing is voiced and the cue that sounds is not cut."""
import asyncio

from cm_patch import patch_controller
import echo_sync.controlled_media as cm
from echo_sync.controlled_media import ControlledMedia
from echo_sync.native_media_socket import NativeMediaSocket

QUESTION = 'Какой штраф за неуплату налога'
BANK = 'Двадцать процентов от неуплаченной суммы. Это штраф по статье 122.'
ROWS = [{'title': 'Налоговый кодекс', 'text': 'Налог на прибыль организаций уплачивается по ставке, установленной главой 25.', 'url': 'https://example.test/%d' % n} for n in range(3)]


def test_a_lookup_that_grounds_nothing_is_no_failure_while_the_local_answer_sounds(tmp_path, monkeypatch):
    patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(), **kwargs: BANK)

    async def run():
        sent = []

        async def emit(frame):
            sent.append(frame)

        async def lookup(_):
            return ROWS

        c = ControlledMedia(tmp_path / 's.db', session_id='s')
        wire = NativeMediaSocket(c, emit, lambda: None, lookup, lambda _: None, diagnostics=True)
        actions = c.provider({'type': 'turn.done', 'turn': {'id': 'u', 'role': 'user', 'transcript': QUESTION}})
        assert any(a['type'] == 'speak' and a['text'].startswith('Двадцать процентов') for a in actions), actions
        assert c.local_answer and c.direct_content and c.published, 'precondition: the local reference answer owns the question'
        await wire._lookup({'epoch': c.epoch, 'question': c.question_text})
        errors = [x['error']['code'] for x in sent if x.get('type') == 'error']
        assert errors == [], errors
        assert not any(x.get('stage') == 'diagnostic_start' for x in sent), 'a spoken failure over the cue that sounds'
        assert not any(x.get('type') == 'output_audio_buffer.clear' for x in sent), 'the cue that sounds was cut'
        await wire.close()
    asyncio.run(run())


def test_a_lookup_that_raises_is_no_failure_while_the_local_answer_sounds_and_a_silent_question_still_hears_it(tmp_path, monkeypatch):
    async def run(local):
        sent = []
        if local:
            patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(), **kwargs: BANK)
        else:
            patch_controller(monkeypatch, 'reference_lookup', lambda text, history=(), **kwargs: None)

        async def emit(frame):
            sent.append(frame)

        async def lookup(_):
            raise TimeoutError('no network')

        c = ControlledMedia(tmp_path / ('a.db' if local else 'b.db'), session_id='s')
        wire = NativeMediaSocket(c, emit, lambda: None, lookup, lambda _: None, diagnostics=True)
        c.provider({'type': 'turn.done', 'turn': {'id': 'u', 'role': 'user', 'transcript': QUESTION}})
        assert bool(c.local_answer) is local, 'precondition'
        await wire._lookup({'epoch': c.epoch, 'question': c.question_text})
        await wire.close()
        return [x['error']['code'] for x in sent if x.get('type') == 'error']
    assert asyncio.run(run(True)) == []
    assert asyncio.run(run(False)) == ['controlled_sources_unavailable'], 'with no answer that sounds the failure is still told'

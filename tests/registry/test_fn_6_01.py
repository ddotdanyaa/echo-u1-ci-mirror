"""Registry 6.01 «Журнал разговора»; state by the registry: РАБОТАЕТ НА СЕРВЕРЕ (checked by test or probe, not on the phone).

Proved through the real controller (tests/helpers_night_memory.Call: World, NativeMediaSocket, engine, fast_text, CallTrace; only the cloud, the synthesis and the clock are scripted).
The ledger is the memory of the call, so it is read through its outward exit, the command «повтори мои / последние N слов» (recall_words, function 6.02, needed to read it):
 1 the owner's words come back VERBATIM, in order, across several utterances and portions, the refined final of a turn replacing its first final, the command itself left out
 2 the words of the prompt that was played (its portions heard to the end) come back too (no owner named in the command)
 3 with conversation_ledger=off the same calls repeat nothing: the cue and the synthesis stay empty
Keys: the code default conversation_ledger=off, the test sets the live value memory; recall_words=on (live; code default off), fast_text=on (live; code default off);
v6_memory and topic_recap are off here, so that the card of 6.03 cannot be the exit. Dummy check (off / on): LEDGER below switched to 'off' makes 1 and 2 red, 3 stays green.
Cloud stand: nothing here is a measure of the laptop or the phone."""
import re

import pytest

import helpers_night_memory as M

LEDGER = 'memory'
LINES = ['Сегодня мы разберём устройство простого маятника.', 'Длина нити определяет период колебаний.', 'Масса груза на период не влияет.']
SLIP, FIXED = 'Амплитуда зависит от цвета подвеса.', 'Амплитуда должна быть небольшой.'      # a refined final replaces the first final of one turn


def words(text):
    return re.findall(r'[\w-]+', text)


def stand(tmp_path, ledger=LEDGER):
    return M.Call(tmp_path, conversation_ledger=ledger, recall_words='on', v6_memory='off', topic_recap='off')


def command(call, text):
    """Say ``text`` and return what the owner heard in answer (the cues new since the command)."""
    before = len(call.cues())
    call.say(text)
    call.owner_follows()                                                    # the answer comes in portions, the owner says each back
    return call.cues()[before:]


def test_the_owners_words_come_back_verbatim_in_order(tmp_path):
    call = stand(tmp_path)
    try:
        for line in LINES:
            call.say(line)
        call.refine(call.say(SLIP), FIXED)
        spoken = [w for line in LINES + [FIXED] for w in words(line)]
        heard = command(call, 'повтори мои последние 12 слов')
        said = ' '.join(heard)
        assert words(said) == spoken[-12:], heard                           # 12 words as asked: the REFINED final, not the command itself
        assert not any(w in said for w in ('цвета', 'подвеса')), heard      # what the refined final replaced is not repeated
        assert call.w.synth_calls[-len(heard):] == heard                    # and that very text went to the synthesis
        assert not call.w.errors and not call.w.violations
    finally:
        call.close()


def test_the_words_of_the_played_prompt_come_back_as_the_prompts(tmp_path):
    call = stand(tmp_path)
    try:
        call.say(LINES[0])
        call.ask(M.Q_WARRANTY)                                              # the answer comes in two portions, the owner says each back
        played = [cue for cue in call.cues() if cue.startswith('Гарантия') or cue.startswith('Она покрывает')]
        assert len(played) == 2, call.cues()
        heard = command(call, 'повтори последние пять слов')                # no owner named: the words the owner heard
        assert words(' '.join(heard)) == words(M.A_WARRANTY)[-5:], heard
    finally:
        call.close()


def test_with_the_ledger_off_nothing_is_repeated(tmp_path):
    call = stand(tmp_path, ledger='off')
    try:
        for line in LINES:
            call.say(line)
        before = len(call.w.synth_calls)
        command(call, 'повтори мои последние 12 слов')      # the key is gone from settings.DEFAULTS (an unknown key is ignored): memory is always kept
        assert [text for text in call.cues() if 'Масса груза' in text] and len(call.w.synth_calls) > before
    finally:
        call.close()

import pytest as _pt_no_lead
pytestmark = _pt_no_lead.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)

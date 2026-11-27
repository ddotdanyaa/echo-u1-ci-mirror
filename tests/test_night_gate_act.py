"""night-gate: the gate ``ControlledMedia._act`` is the one entry of the irreversible, always on (no switch: ``act_gate`` is gone): one line ``why kind=act act= reason= by= basis= verdict=``
per entry, and only a verdict «do» is carried out. Here: the closed table, the journal line, the stale basis, and a scene that walks the rows (a stop, a resume, a new question over an answer, «следующий
билет», an answer nobody gives, an abandon)."""
import json
import logging
import re
from pathlib import Path

import pytest

import helpers_s6_ack as H
from echo_sync import settings as cfg
from echo_sync.controlled_media import ControlledMedia
from echo_sync.settings import CALL_SETTINGS

ROOT = Path(__file__).resolve().parents[1]
ANSWER = 'Налог платят раз в квартал. Ставка составляет шесть процентов. Срок уплаты двадцать пятое число.'
SECOND = 'Вычет дают на детей. Его размер тысяча четыреста рублей.'
THIRD = 'Декларацию сдают до тридцатого апреля. Её подают в инспекцию по месту жительства.'
GATE_LINE = re.compile(r'^echo-sync why kind=(?:act|cut) ')


def make(tmp_path, name, facts=False, **more):
    d = H.Dictation(tmp_path / name, None, settings=dict(CALL_SETTINGS), **more)
    d.controller.facts_why = facts
    return d


def lines(caplog, pattern='echo-sync why kind=act '):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(pattern)]


def fields(line):
    return dict(re.findall(r'(\w+)=(\S*)', line))


# --- the setting -------------------------------------------------------------------------------------------------------------

def test_the_switch_is_gone_the_gate_is_a_rule():
    assert 'act_gate' not in cfg.DEFAULTS and 'act_gate' not in cfg.resolve({'act_gate': 'off'})
    assert '`act_gate`' not in (ROOT / 'SETTINGS.md').read_text(encoding='utf-8')
    assert not hasattr(ControlledMedia, 'act_gate')


# --- the table is closed -----------------------------------------------------------------------------------------------------

def test_an_unknown_reason_or_a_wrong_act_is_refused_before_anything_is_done(tmp_path):
    c = make(tmp_path, 'a').controller
    epoch = c.epoch
    with pytest.raises(KeyError):
        c._act('close_question', 'because_i_say_so')
    with pytest.raises(ValueError):
        c._act('cut_sound', 'drop_question')
    assert c.epoch == epoch


def test_every_reason_of_a_reply_token_move_is_a_word_the_journal_knows():
    from echo_sync import why_journal
    words = {step[1] for row in ControlledMedia.ACTS.values() for step in row[1] if step[0] == 'epoch'}
    assert words == set(why_journal.EPOCH), 'the words told to _new_epoch are the ones of why_journal.EPOCH, no more and no fewer'


# --- one line per entry ---------------------------------------------------------------------------------

def test_the_gate_writes_one_line_per_entry_with_the_site_the_basis_and_the_verdict(tmp_path, caplog):
    caplog.set_level('INFO', logger='echo-sync')
    c = H.Dictation(tmp_path / 'a', ANSWER, settings=dict(CALL_SETTINGS)).controller
    caplog.clear()

    def _answer_watchdog():
        return c._drop_question()
    epoch = c.epoch
    cut = _answer_watchdog()
    got = lines(caplog)
    assert len(got) == 1, got
    f = fields(got[0])
    assert (f['act'], f['reason'], f['by'], f['basis'], f['verdict'], f['did']) == ('close_question', 'drop_question', '_answer_watchdog', 'now', 'do', '1')
    assert cut == [{'type': 'cancel', 'epoch': epoch + 1}] and int(f['epoch']) == epoch + 1
    assert c.act_told(cut[0]) == ('close_question', 'drop_question', '_answer_watchdog'), 'the transport can ask which entry built its cut'
    assert c.act_told({'type': 'cancel', 'epoch': epoch + 1}) is None, 'by identity: a look-alike is nobody\'s'


def test_a_stale_basis_is_told_and_obeyed(tmp_path, caplog):
    caplog.set_level('INFO', logger='echo-sync')
    c = H.Dictation(tmp_path / 'on', ANSWER, settings=dict(CALL_SETTINGS)).controller
    epoch, revision = c.epoch, c.state()['revision']
    for n, basis in enumerate([(epoch - 1, None, 'u0'), (None, revision - 1, None), (epoch - 1, revision - 1, 'u0')]):
        caplog.clear()
        before = c.epoch
        verdict, actions = c._act('close_question', 'drop_question', basis=basis)
        f = fields(lines(caplog)[0])
        assert verdict == 'stale' and f['verdict'] == 'stale' and f['did'] == '0', (n, f)
        assert c.epoch == before and not actions, n
        assert c.question_id == 'q1', 'a verdict about what is gone erases nothing of what stands'
    caplog.clear()
    assert c._act('close_question', 'drop_question', basis=(c.epoch, c.state()['revision'], 'u1'))[0] == 'do', 'a basis that still stands is fresh'
    assert fields(lines(caplog)[0])['basis'] == '%s/%s/u1' % (c.epoch - 1, c.state()['revision'])


# --- a scene that walks the rows ------------------------------------------------------

def scene(tmp_path, facts, caplog):
    """One conversation at the controller, as the wire feeds it; returns every action list, the state after each step and the journal, the nonce and the times of the wall clock out."""
    caplog.clear()
    d = H.Dictation(tmp_path / str(facts), None, settings=dict(CALL_SETTINGS))
    c = d.controller
    c.facts_why = facts
    out = []

    def keep(label, actions):
        state = dict(c.state() or {})
        out.append((label, actions, c.epoch, c.question_id, c.cue_outstanding, c.repeat_at, c.resume_repeat, c.suspended, c.candidate, c.held_source, c.unsettled, c.settled_segment,
                    {k: state.get(k) for k in ('revision', 'chunk_index', 'completed', 'paused', 'chunks', 'abandoned')}))

    def say(label, text, **kw):
        keep(label, d.say(text, **kw).actions)

    def answer(tid, text):
        actions = c.provider(H.done(tid, 'assistant', text))
        d.play(actions)
        keep('answer ' + tid, actions)

    def ticks(label, seconds, step=0.5):
        got = []
        for _ in range(int(seconds / step)):
            d.clock.advance(step)
            actions = c.tick(now=d.clock())
            d.play(actions)
            got += actions
        keep(label, got)

    keep('begin_call', c.begin_call())
    say('question', 'Когда платят налог?')
    answer('a1', ANSWER)
    say('repeat of the portion', d.current or 'Налог платят раз в квартал.')
    say('stop', 'стоп')
    say('resume', 'продолжай')
    say('a new question over the answer', 'А какой вычет дают на детей?')
    answer('a2', SECOND)
    say('move on', 'Давайте следующий билет.')
    say('a question nobody answers', 'Сколько стоит патент на год?')
    ticks('the watchdog', 40.0)
    say('one more question', 'Когда сдают декларацию?')
    answer('a3', THIRD)
    say('other speech', 'мы вчера ходили в кино с друзьями вечером', gap=6.0)
    say('other speech again', 'потом ещё поехали на дачу к родителям надолго', gap=30.0)
    say('and again', 'а завтра собираемся пойти гулять по городу', gap=30.0)
    say('the last question', 'Какой срок у патента?')
    answer('a4', SECOND)
    keep('speech started', c.speech_started())
    d.clock.advance(600.0)      # the line dropped long ago: the portion that still waits is a stale one for the next call
    keep('new call', c.begin_call())
    journal = [r.getMessage() for r in caplog.records if r.name == 'echo-sync']
    dump = json.dumps(out, ensure_ascii=False, default=str).replace(c.nonce, 'NONCE')
    return dump, [line.replace(c.nonce, 'NONCE') for line in journal]


@pytest.mark.parametrize('facts', [False, True])
def test_the_scene_walks_the_gate_and_every_verdict_is_do(tmp_path, caplog, facts):
    caplog.set_level('INFO', logger='echo-sync')
    _, journal = scene(tmp_path, facts, caplog)
    gate = [line for line in journal if GATE_LINE.match(line)]
    seen = {(fields(line)['act'], fields(line)['reason']) for line in gate}
    # the scene really walks the gate: the kinds of acts, not one row
    assert {('supersede', 'open_question'), ('supersede', 'new_question'), ('pause', 'stop'), ('close_question', 'move_on'), ('close_question', 'drop_question'),
            ('close_question', 'abandon'), ('cut_sound', 'speech_started'), ('close_question', 'new_call')} <= seen, sorted(seen)
    assert all(fields(line)['verdict'] == 'do' and fields(line)['did'] == '1' for line in gate), 'in a scene where nothing is late every verdict is «do»'
    assert (len([line for line in journal if line.startswith('echo-sync why kind=drop ')]) > 0) is facts


def test_the_drop_lines_of_step_0_keep_their_site_and_word_through_the_gate(tmp_path, caplog):
    """``why kind=drop`` (facts_journal) named the caller of ``_new_epoch`` by the frames; the gate stands between them now and hands the site on."""
    caplog.set_level('INFO', logger='echo-sync')
    scene(tmp_path, True, caplog)
    drops = [fields(r.getMessage()) for r in caplog.records if r.getMessage().startswith('echo-sync why kind=drop subject=question ')]
    pairs = {(f['rule'], f['by']) for f in drops}
    assert {('open_question', '_open_question'), ('accept_user', '_accept_user'), ('drop_question', '_answer_watchdog')} <= pairs, sorted(pairs)
    assert not [f for f in drops if f['by'] in ('_act', '_drop_question', '_new_epoch')], 'never the gate\'s own name'


# --- the wire: its cut says why, its phrases ask the gate ----------------------------------------------------------------------

def wire_run(tmp_path, caplog):
    import asyncio

    async def run():
        w = H.Wire(tmp_path / 'w', settings=dict(CALL_SETTINGS))
        asked = []
        real = w.controller.may_sound
        w.controller.may_sound = lambda what, basis: asked.append((what, basis)) or real(what, basis)
        await w.begin(ANSWER)
        await w.user('стоп')
        w.socket.diagnostic_audio.get = lambda key: bytes(4800)      # a service phrase with sound: «Ошибка. Повторите вопрос.»
        w.socket._announce('controlled_answer_timeout')
        await w.settle()
        sent = [f.get('type') for f in w.sent]
        await w.close()
        return sent, asked
    caplog.clear()
    sent, asked = asyncio.run(run())
    return sent, asked, [r.getMessage() for r in caplog.records if r.getMessage().startswith('echo-sync why kind=cut ')]


def test_the_wire_says_which_entry_of_the_gate_it_cut_for(tmp_path, caplog):
    caplog.set_level('INFO', logger='echo-sync')
    sent, asked, cuts = wire_run(tmp_path, caplog)
    assert cuts, 'the cancel branch writes its reason'
    got = [(f['act'], f['rule'], f['by']) for f in map(fields, cuts)]
    assert ('supersede', 'open_question', '_open_question') in got and ('pause', 'stop', '_accept_user') in got, got
    # the service phrase asked the gate once, before its first frame, with the marks it was decided on
    assert [what for what, _ in asked] == ['say'] and len(asked[0][1]) == 3

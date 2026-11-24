"""The conversation memory proved END TO END (night 12-13.11): a call of three hours through the real controller with ``v6_memory=on``, ``conversation_ledger=memory``, ``topic_recap=on``
(tests/helpers_night_memory.py says what is real and what is scripted). What is checked is the request the text model was really sent, never the card on its own.

 1 a condition said at minute 5 is in the request at minute 40 and at minute 170, when the question hangs on it
 2 a correction is above the earlier fact: «не 500, а 700» - 700 is in the request, and 500 is told only as the line before its correction, under the heading that says the correction stands (U88, accepted 15.11)
 3 a slip of the recogniser is no fact: what a refined final replaced, or the next utterance took back, is not told as a fact
 4 who said it: the owner's words (the prompt said aloud) and the words of the room are not mixed
 5 speed: the card is not built on the hot path of a prompt, and the time of a request does not grow with the call
 6 bounds: v6_memory_chars / _lines / _step_min hold through the three hours; what goes first is a written rule
 7 the account of what was sent out: one journal line per request, how many characters and lines of memory went to the model (numbers, no words)
Cloud stand: nothing here is a measure of the laptop or the phone."""
import json
import re
import statistics

import pytest

import helpers_night_memory as M
from echo_sync import v6_memory as V


class Played:
    """What a played call left: everything a test reads, taken before the stand is closed."""

    def __init__(self, call, marks):
        self.requests = [request for n, _, request in call.requests if n == call.calls]
        self.when = [minute for n, minute, _ in call.requests if n == call.calls]
        self.cards = [row[1:] for row in call.cards if row[0] == call.calls]              # (minute, question, what the hook left after the policy, the history it left)
        self.hook_s = [row[1:] for row in call.hook_s if row[0] == call.calls]
        self.journal = [row for row in call.journal(last=True) if row.get('ev', '').startswith('memory_card')]
        self.said_back, self.cues, self.marks = list(call.said_back), call.cues(), dict(marks)
        self.ledger, self.began = call.c.convo, call.c.call_began
        self.profile = dict(call.profile)

    def request_for(self, question, after=0.0):
        return next(request for minute, request in zip(self.when, self.requests) if minute >= after - 1e-6 and M.asked(request).endswith(question))


def play(tmp_path, until, *, earlier=True, redial_at=None, **profile):
    call = M.Call(tmp_path, **profile)
    try:
        if earlier:
            M.earlier_call(call)
        if redial_at is None:
            marks = M.plant(call, until)
        else:
            marks = M.plant(call, redial_at)
            call.redial(20.0)                      # the line dropped, the phone dialled again 20 s later: the same conversation
            call.zero -= redial_at * 60.0 + 20.0   # the minutes of the stand go on
            call.go(39.5)
            marks[40.0] = call.minute()
            call.ask(M.Q_COND)
        return Played(call, marks)
    finally:
        call.close()


@pytest.fixture(scope='module')
def three_hours(tmp_path_factory):
    """THE call: 178 minutes, the laptop as it is in the field (the state file of an earlier call is there)."""
    return play(tmp_path_factory.mktemp('three_hours'), 178.0)


def has_the_condition(request):
    return 'скидка пять процентов' in M.whole(request) and 'больше трёхсот единиц' in M.whole(request)


# -- 1 ------------------------------------------------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize('minute', [40.0, 170.0])
def test_1_the_condition_of_minute_5_is_in_the_request_at_minute_40_and_170(three_hours, minute):
    request = three_hours.request_for(M.Q_COND, after=minute)
    assert has_the_condition(request), M.memory_of(request)[:600]
    line = M.lines_with(request, 'скидка пять процентов')[0]
    assert line.startswith('- 5 мин, '), line                      # and when it was said


def test_1_the_prompt_at_minute_40_and_170_says_the_condition(three_hours):
    """The model of the stand answers from the request alone: the prompt in the owner's ear is right only because the memory was in the request."""
    assert M.UNKNOWN not in three_hours.cues, [cue for cue in three_hours.cues if cue == M.UNKNOWN]
    assert sum('пять процентов' in cue for cue in three_hours.cues) >= 2


def test_1_on_a_laptop_with_no_earlier_call_too(tmp_path):
    played = play(tmp_path, 41.0, earlier=False)
    assert played.began is None and has_the_condition(played.request_for(M.Q_COND, after=40.0))


def test_1_the_start_of_the_call_is_on_the_clock_of_the_ledger(three_hours):
    """The first cause of an empty card on the laptop: ``call_began`` is the engine's wall clock, the records of the ledger carry the controller's monotonic clock."""
    assert three_hours.began is not None and three_hours.began > 1e9                    # the stand is the field: a wall clock
    first = next(r for r in three_hours.ledger.records() if r.kind == 'user')
    assert first.at < 1e6                                                                   # and a monotonic one
    sent = [row for row in three_hours.journal if row['ev'] == 'memory_card']
    assert sent and all(row['mode'] == 'on' for row in sent)
    assert sum(1 for row in sent if row['chars'] > 0) >= len(sent) - 2, 'the card is empty in %d of %d requests' % (sum(1 for row in sent if not row['chars']), len(sent))


def test_1_a_redial_in_the_middle_of_the_call_keeps_the_memory(tmp_path):
    """The line drops at minute 20 and the phone dials again 20 s later (``begin_call`` keeps the conversation): the condition of minute 5 is in the request at minute 40."""
    played = play(tmp_path, 41.0, redial_at=20.0)
    assert has_the_condition(played.request_for(M.Q_COND, after=39.0))


# -- 2 ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def stands_after_its_correction(memory, old, fix):
    """U88, the format the coordinator ACCEPTED (15.11): the memory card tells the numbers in spoken order and both of them, the old value and its correction as two lines, the correction AFTER the value it corrects,
    under the heading of the exact things that says so (``v6_memory.HEAD['exact']``): every line with the old value has a line with the new one below it, so the old one never stands alone."""
    lines = memory.split('\n')
    olds = [i for i, line in enumerate(lines) if old in line and fix not in line]
    fixes = [i for i, line in enumerate(lines) if fix in line]
    assert olds and fixes and max(olds) < max(fixes), (olds, fixes, memory[:600])      # two lines, the correction after
    assert 'после прежнего' in V.HEAD['exact'] and V.HEAD['exact'] in lines[:min(olds)], (V.HEAD['exact'], memory[:600])      # under the heading that says the correction stands after the old value


@pytest.mark.parametrize('minute', [45.0, 172.0])
def test_2_the_correction_is_above_the_earlier_fact(three_hours, minute):
    request = three_hours.request_for(M.Q_PRICE, after=minute)
    assert '700' in M.memory_of(request), M.memory_of(request)[:600]
    stands_after_its_correction(M.memory_of(request), '500 рублей.', '700 рублей')      # the card shows the numbers in spoken order: 500 never stands without the value that follows it
    assert 'Цена 700 рублей за штуку.' in three_hours.cues and 'Цена 500 рублей за штуку.' not in three_hours.cues


# -- 3 ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_3_what_a_refined_final_replaced_is_nowhere_in_the_request(three_hours):
    request = three_hours.request_for(M.Q_PAY, after=50.0)
    assert 'Срок оплаты 30 дней' in M.memory_of(request), M.memory_of(request)[:600]
    refined = three_hours.marks[15.0]      # the first final goes to the model as the words of its own turn before the provider refines it (nothing can unsay that); after the refinement it is nowhere
    assert not any('90 дней' in M.whole(r) for minute, r in zip(three_hours.when, three_hours.requests) if minute > refined + 0.5)


def test_3_what_the_next_utterance_took_back_is_not_a_fact(three_hours):
    request = three_hours.request_for(M.Q_SHIP, after=55.0)
    assert 'пятьдесят дней' in M.memory_of(request), M.memory_of(request)[:600]
    stands_after_its_correction(M.memory_of(request), 'пятнадцать', 'пятьдесят')      # the old number is told with the correction below it, both in spoken order
    assert 'Доставка займёт пятьдесят дней.' in three_hours.cues


# -- 4 ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_4_the_owners_said_back_words_are_never_told_as_said_in_the_room(three_hours):
    """The owner says the prompt aloud and the microphone hears it: that is the prompter's own answer, not a thing the room said and nobody answered."""
    back = {M.said(text) for text in three_hours.said_back}
    assert len(back) > 30
    wrong = [(M.asked(request), line) for request in three_hours.requests for line in M.room_lines(request) if M.said(line) in back]
    assert not wrong, (len(wrong), wrong[:3])


def test_4_what_we_said_is_told_as_ours_and_what_the_room_said_as_the_rooms(three_hours):
    for minute in (60.0, 174.0):
        request = three_hours.request_for(M.Q_OURS, after=minute)
        ours = M.lines_with(request, '24 месяца')
        assert ours, M.memory_of(request)[:600]
        assert not [line for line in ours if M.ROOM.match(line)], ours                   # the warranty was OUR answer
    request = three_hours.request_for(M.Q_COND, after=170.0)
    assert all(M.ROOM.match(line) for line in M.lines_with(request, 'скидка пять процентов'))      # the condition was the room's
    assert 'Мы называли гарантию 24 месяца.' in three_hours.cues


# -- 5 ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_5_the_time_in_the_hook_does_not_grow_with_the_call(three_hours):
    """Through the real controller: what the hook costs a request in the last half hour against the first hour (the ledger is about five times longer by then)."""
    early = [s for minute, s in three_hours.hook_s if 25.0 <= minute < 60.0]
    late = [s for minute, s in three_hours.hook_s if 148.0 <= minute]
    assert len(early) >= 30 and len(late) >= 30
    ratio = statistics.median(late) / statistics.median(early)
    assert ratio < 2.0, 'median %.2f ms -> %.2f ms, x%.1f' % (statistics.median(early) * 1000, statistics.median(late) * 1000, ratio)


def test_5_nothing_is_rebuilt_on_the_hot_path(tmp_path, monkeypatch):
    """The request of a question only READS what was made ready when the words were written: no rebuild of the projection inside the hook, whatever the controller wrote before it
    (an answer that takes the place of the answer before it, a final the judge looked at twice)."""
    inside, calls = [], []
    real_apply, real_rebuild = V.Memory.apply, V.Projection._rebuild

    def apply(self, *a, **k):
        inside.append(1)
        try:
            return real_apply(self, *a, **k)
        finally:
            inside.pop()

    def rebuild(self, *a, **k):
        if inside:
            calls.append(len(self._rows))
        return real_rebuild(self, *a, **k)
    monkeypatch.setattr(V.Memory, 'apply', apply)
    monkeypatch.setattr(V.Projection, '_rebuild', rebuild)
    played = play(tmp_path, 62.0)
    assert len(played.requests) > 40
    assert len(calls) <= 1, 'the projection was rebuilt whole inside the hook %d times in %d requests' % (len(calls), len(played.requests))


# -- 6 ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def sections(text):
    """{part: its lines} of a card."""
    out, name = {}, None
    heads = {head: part for part, head in V.HEAD.items()}
    for line in text.split('\n'):
        if line in heads:
            name = heads[line]
            out[name] = []
        elif line.strip() and name:
            out[name].append(line)
    return out


def minute_of(line):
    m = re.match(r'^- (?:(\d+) ч )?(\d+) мин', line)
    return int(m.group(1) or 0) * 60 + int(m.group(2))


def test_6_the_three_numbers_hold_in_every_request_of_the_three_hours(three_hours):
    chars, lines, step = (three_hours.profile[key] for key in ('v6_memory_chars', 'v6_memory_lines', 'v6_memory_step_min'))
    assert (chars, lines, step) == (V.START['chars'], V.START['lines'], V.START['step_min'])
    for minute, question, text, history in three_hours.cards:
        assert len(text) <= chars, (minute, len(text))
        parts = sections(text)
        assert len(parts.get('retrieved', ())) <= lines, (minute, parts.get('retrieved'))
        per_step = {}
        for line in parts.get('outline', ()):
            per_step[minute_of(line) // step] = per_step.get(minute_of(line) // step, 0) + 1
        assert all(n <= 2 for n in per_step.values()), (minute, per_step)
        assert history == [] or not text.startswith(V.HEAD['exchanges'])          # the card stands in place of the old block, never beside it
        assert minute < 30.0 or parts.get('outline'), minute                         # and half an hour into the call every request has the outline of it


@pytest.mark.parametrize('lines,step', [(0, 5), (2, 20), (4, 5), (20, 1)])
def test_6_what_goes_first_is_the_written_rule(three_hours, lines, step):
    """V.PARTS is the order of priority: a smaller budget takes parts away from the bottom of it and never from the middle; inside the budget no part above is shorter than with a bigger one."""
    shown = []
    for budget in (1500, 2000, 3000, 4000, 8000, 20000):
        card = V.build_card(three_hours.ledger, M.Q_PRICE, budget=budget, lines=lines, step_min=step)
        assert card.chars == len(card.text) <= budget
        assert len(card.part('retrieved')) <= lines
        shown.append([name for name in V.PARTS if card.part(name)])
    assert all(set(a) <= set(b) for a, b in zip(shown, shown[1:])), shown
    order = [name for name in V.PARTS if name not in ('pinned', 'carry')]
    for names in shown:
        have = [name for name in order if name in names]
        if lines:
            assert have == order[:len(have)] or 'retrieved' not in names, names        # a part is there only with every part above it (retrieval may find nothing)


# -- 7 ------------------------------------------------------------------------------------------------------------------------------------------------------------------

def test_7_the_journal_counts_what_went_to_the_model_in_numbers_only(three_hours):
    rows = [row for row in three_hours.journal if row['ev'] == 'memory_card']
    assert len(rows) == len(three_hours.cards) > 100
    total = 0
    for row, (minute, question, text, history) in zip(rows, three_hours.cards):
        sent = text if history == [] and text else ''                                    # on: the card is what the hook left after the policy
        assert row['sent_chars'] == len(sent), (minute, row)
        assert row['sent_lines'] == (sent.count('\n') + 1 if sent else 0), (minute, row)
        total += len(sent)
        assert row['sent_total_chars'] == total
    dumped = json.dumps(rows, ensure_ascii=False)
    for word in ('скидка', 'рублей', 'поставк', 'гарант', 'кофе', 'Казан'):
        assert word not in dumped
    assert total > 0

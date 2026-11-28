"""Shared pieces of the break tests of the answer / road family (U237). Nothing here decides what is correct: it only records what the phone heard and what each road and each search was asked.

The stand is tests/helpers_always_answer.py: the REAL controlled_host.serve + ControlledMedia + NativeMediaSocket + fast_text + reserve_text + reserve_search, with only the phone, the helper pipe, SAPI,
the local ear, the roads of the text and the network of the search faked. ``BStand`` adds the journal of what each road and each reserve search was ASKED (``requests``, ``search_bodies``)."""
import json
import re

import helpers_always_answer as H
from helpers_always_answer import GAP_S, M, MARKS, N, QUESTIONS, SYNTH_TICK_S, TOPICS, Stand, blank, cut, empty, fail, hang, heard, late, ok, run_stand, text_of

Q_INERTIA, Q_PHOTO, Q_SKY, Q_RAINBOW = QUESTIONS
TOPIC = dict(zip(QUESTIONS, TOPICS))          # the words every road of the stand puts in its answer to this question
Q_VAT = 'Какая сейчас ставка НДС?'            # route_need == CHANGES: a rate «now», never answered from memory
Q_RATE = 'Какой сейчас курс доллара к рублю?'
Q_CODE = 'Что говорится в девятнадцатой статье Налогового кодекса?'
ALIVE_BOUND_S = 14.0                          # never silence: an answer or the phrase of the system not later than this after the question (C cells: M + 4 + a tick)


class BStand(Stand):
    """``requests``: (virtual time, alias, the request the road was asked, json); ``search_bodies``: the body of every request of the reserve search (what left the laptop for the public search)."""

    def __init__(self, *args, profile=None, **kwargs):
            # These scenes count the ANSWERS the roads gave. The host's own repeat of an unconfirmed answer (settings max_auto_repeats, timer_policy REPEAT_SECONDS) is another rule with its own tests (test_b_timers, test_c22_repeat_wiring); a caller's profile still wins.
            super().__init__(*args, profile={'max_auto_repeats': 0, **(profile or {})}, **kwargs)
            self.requests, self.search_bodies = [], []

    def _road(self, alias, cancelled, primary, timeout=None, question=''):
        self.requests.append((self.loop.time(), alias, question))
        return super()._road(alias, cancelled, primary, timeout, question)

    def _search_post(self, url, headers, body, timeout):
        self.search_bodies.append(json.dumps(body, ensure_ascii=False))
        return super()._search_post(url, headers, body, timeout)

    def asked_text(self, since=0.0):
        return ' '.join(q for t, _, q in self.requests if t >= since)


class Heard:
    """What the phone heard from ``t_q`` (until ``until``): ``answers`` (whole, not a phrase of the system), ``service`` (a phrase of the system), ``other`` (cut off or empty)."""

    def __init__(self, host, t_q, until=None):
        saw = heard(host, t_q)

        def pick(items):
            return [i for i in items if until is None or i['first'] < until]
        self.t_q, self.answers, self.service, self.other = t_q, pick(saw['answers']), pick(saw['service']), pick(saw['other'])
        self.items = sorted(self.answers + self.service + self.other, key=lambda i: i['first'])
        self.text = text_of(self.items)

    def first_sound(self, items=None):
        firsts = [i['first'] - self.t_q for i in (self.items if items is None else items)]
        return min(firsts) if firsts else None


def core(text):
    """The letters and digits of a text, folded: «...» and a zero-width space are no word."""
    return re.sub(r'[\W_]+', '', str(text).casefold())


def words_of(text):
    return re.findall(r'\w+', str(text))


async def hold_the_line(host, seconds, every=30.0):
    """The phone keeps its line open as a real one does (a microphone packet at least every ``every`` s): the host hangs up on a socket silent for RECEIVE_TIMEOUT_S (timer_policy), a silence of the room is no silence of the line."""
    left = seconds
    while left > 0:
        host.phone_audio()
        step = min(every, left)
        await host.advance(step)
        left -= step


def local_call():
    """The rig of a call whose GPT-Live is dead at the opening (the local mode; the question comes from the ear alone)."""
    return {'handshake': False, 'setup': ['no_offer']}

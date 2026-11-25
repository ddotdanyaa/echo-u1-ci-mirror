"""One rehearsal of one seed: ``tools.replay.stand.Stand`` (the real ControlledMedia, NativeMediaSocket, ShadowEar, FastText) with the boundaries set by a line of ``plan``.

What changes against the a1 stand (everything else is the a1 rig as it is):
  the ear      its words: ``ear_model.Ear`` (N2 errors, the noise level of the line); its text 0.15 s after the end (p90 0.34), 12_LATENCY_CHAIN §3.2
  the cloud    the final after the end: a question 2.35 s (p90 3.48), a repeat 1.95 (p90 2.44), anything else 1.89 (p90 6.08) (§3.1-3.2); 4 % lost; log-normal by median and p90
  the model    first text 1.2 s median, p90 3 s, 2 % a tail of 10 s, 4 % failures; answers from the bank (``plan.BANK``) or the a1 families
  the people   2-3 words a second, pauses, stutters, an inexact repeat, silence, the question asked again; a friend, strangers, a television, noise, faults of the link
The seed sets everything. Seconds are seconds of the conversation on the stand's clock, not a measurement on a laptop or a phone.
"""
import logging
import math
import random
import re

from tools.replay import stand as A
from tools.replay.stand import Q, EVENTS, ARTICLES, VERBS, normalize
from tools.rehearsal import plan as P
from tools.rehearsal.ear_model import Ear

USER = {'repeat': 55, 'partial': 8, 'wrong': 4, 'stop': 6, 'doubt': 4, 'question': 9, 'chatter': 5, 'silence': 8, 'fix': 3}
IDLE = {'question': 45, 'chatter': 20, 'silence': 20, 'again': 4, 'resume': 4, 'fix': 5}
STOPPED = {'question': 4, 'chatter': 2, 'resume': 2, 'again': 1, 'silence': 3}
FRIEND = ('question', 'fix', 'doubt', 'follow', 'object', 'cancel', 'back', 'newq')          # who asks; the rest after a cue is the user
ADVANCING = ('repeat', 'partial', 'wrong', 'stutter', 'resume', 'self')                       # what may move the cursor on
OTHERS = {
    'chatter': ('Ой, а где тут столовая?', 'Слушай, ты домашку сделал?', 'Пойдём потом в магазин.', 'Скинь мне конспект вечером.', 'Да ладно, не может быть.'),
    'tv': ('В Москве сегодня до двадцати трёх градусов тепла, местами дожди.', 'Курс доллара на торгах составил девяносто два рубля.',
           'Сборная выиграла со счётом три один и вышла в финал турнира.', 'Президент подписал закон о бюджете на следующие три года.'),
    'laugh': ('Ха-ха-ха!', 'Ахаха, ну ты даёшь.', 'Хи-хи.'),
    'door': ('',),
    'aside': ('Маша, подай ручку.', 'Подожди секунду, я сейчас.', 'Нет, это не тебе.', 'Закрой окно, дует.'),
    'argue': ('Нет, ты не прав!', 'Да я тебе говорю, так и есть!', 'Ну с чего ты взял?', 'Сам посмотри в учебнике!'),
    'rhet': ('Ну кто так делает, а?', 'И что теперь, все так живут?', 'А кому сейчас легко?'),
    'again_other': ('Повторите, пожалуйста.', 'Повторите.'),
    'stop_other': ('Стоп.', 'Стой, подожди.'),
}
TAIL_P, TAIL_S, FAIL_P = 0.02, 10.0, 0.04
WAIT_S = 10.0                    # how long the people wait in silence for the answer to a question


def lognormal(rng, median, p90):
    """A log-normal draw from its median and p90 (the shape of every latency in 12_LATENCY_CHAIN)."""
    return median * math.exp(rng.gauss(0, 1) * math.log(p90 / median) / 1.2816)


class Spec:
    def __init__(self, name, line=None):
        self.name = name
        self.title, raw = P.parse(line if line is not None else P.PLAN[name])
        self.raw = raw
        self.minutes = float(raw.get('min', 2))
        self.ask = raw.get('ask', 'money,mult,verb,year,article,op09,tax,num').split(',')
        self.noise = raw.get('noise', 'clean')
        self.tempo = float(raw.get('tempo', 0)) or None                 # None: 2-3 words a second
        self.stutter = raw['st'].split(',') if 'st' in raw else ['mid', 'filler', 'first', 'restart']
        self.user = self.weights(USER, raw.get('user'))
        self.idle = self.weights(IDLE, raw.get('idle'))
        self.others = self.weights({}, raw.get('others'))
        self.orate = float(raw.get('orate', 0))
        self.over = raw.get('over') == '1'
        self.intro = float(raw.get('intro', 0.15 * 0))
        self.long = int(raw.get('long', 0))
        self.burst = tuple(int(x) for x in raw['burst'].split('/')) if 'burst' in raw else None
        self.faults = [(f.split('@')[0], float(f.split('@')[1])) for f in raw['faults'].split(',')] if 'faults' in raw else []
        self.pause = tuple(float(x) for x in raw['pause'].split('@')) if 'pause' in raw else None
        self.chat = tuple(float(x) for x in raw['chat'].split('@')) if 'chat' in raw else None
        self.lostq = float(raw.get('lostq', 0))
        self.barge = float(raw.get('barge', 0.12))
        self.rotate = raw.get('rotate') == '1'
        self.first = float(raw['first']) if 'first' in raw else None
        self.approx = raw.get('approx')
        self.flags = dict(kv.split(':', 1) for kv in raw['flags'].split(',')) if 'flags' in raw else {}

    @staticmethod
    def weights(base, text):
        if not text:
            return dict(base)
        out = {} if text.startswith('=') else dict(base)             # ``=k:w,...``: only these
        text = text.lstrip('=')
        for kv in text.split(','):
            k, v = kv.split(':')
            out[k] = float(v)
        return out


def classic(rng, family):
    """One question of the a1 families (``tools.replay.stand.ask`` with the family chosen by the line)."""
    if family == 'money':
        a, b = rng.sample(range(20, 100, 10), 2)
        return Q('money', (a, b), f'Если у меня было {a} рублей и я потратил {b} рублей, сколько денег осталось?')
    if family == 'mult':
        a, b = rng.randint(2, 9), rng.randint(2, 9)
        return Q('mult', (a, b), f'Сколько будет {a} умножить на {b}?')
    if family == 'verb':
        pos, neg = rng.choice(VERBS)[::rng.choice((1, -1))]
        return Q('verb', (pos, neg), f'Нужно не {neg}, а {pos} эту жидкость при таком давлении?')
    if family == 'year':
        n = rng.randrange(len(EVENTS))
        return Q('year', (n,), f'В каком году было {EVENTS[n][0]}?')
    n = rng.choice(ARTICLES)
    return Q('article', (n,), f'Что говорит статья {n} Налогового кодекса?')


def longer(fact, n):
    """The same answer and ``n`` more sentences: a long answer of many portions (Р031, Р065-Р067, Р083)."""
    if not n:
        return fact
    more = [f'{P.SENTENCES[k % len(P.SENTENCES)][:-1]}, часть {k // len(P.SENTENCES) + 1}.' if k >= len(P.SENTENCES) else P.SENTENCES[k] for k in range(n)]
    return P.Fact(fact.family, fact.params + (n,), fact.text, fact.reply + ' ' + ' '.join(more))


class Mind(A.Mind):
    """The a1 mind, but of two records («Распознано: A / B») it answers the question when one of them is a question: the ear joins a command with the next
    question (the a1 finding F7/A9) and an ideal mind answers what was asked last, not the stale command."""

    def answer(self, request):
        text = request['input'][-1]['content'][0]['text']
        heard = text.rsplit('Сейчас прозвучало: ', 1)[-1]
        if heard.startswith('Распознано: '):
            readings = [self.read(part) for part in heard[len('Распознано: '):].split(' / ')]
            asked = [m for m in readings if m is not None and m[0] in ('q', 'fix')]
            if asked:
                return asked[-1][1].answer()
        return super().answer(request)


class Rehearsal(A.Stand):
    def __init__(self, spec, seed, *, flags=None, mutant=None):
        self.spec, self.mutant = spec, mutant
        profile = {**A.profile_of(seed), **spec.flags, **(flags or {})}
        self.earm, self.asked, self.rot = Ear(), [], 0
        self.down = self.ear_dead = self.cloud_dead = False
        self.cancelled, self.lines = {}, []                   # id of a question -> when «неважно» began
        super().__init__(seed, length=spec.minutes * 60.0, profile=profile, cloud=(0, 0), faults=True)
        self.rng = random.Random(f'{spec.name}-{seed}')
        self.mind = Mind()
        self._light()
        self.out.profile = dict(profile, rehearsal=spec.name)
        self._schedule()

    def _light(self):
        """``World.client``/``advance`` without the list of the frames they caused: the World scans all its frames on every call to make it, so an hour of
        conversation cost the square of its length (40 min: 78 s against 16 s for 20). The stand reads ``w.cues``, never that list. Same calls to the wire."""
        w = self.w

        def client(event):
            w.version += 1
            w.run(w.wire.client(event))
            w.settle()

        def advance(seconds, step=0.5):
            w.version += 1
            left = float(seconds)
            while left > 1e-9:
                piece = min(step, left)
                w.clock.advance(piece)
                left -= piece
                w.run(w.wire.tick())
                w.settle()
        w.client, w.advance = client, advance

    # -- the script of the line ------------------------------------------------------------------------------------------------------
    def _schedule(self):
        s, r = self.spec, self.rng
        if s.orate:
            t = r.uniform(3, 15)
            while t < self.length:
                self.later(t, self.other, call=None)
                t += r.expovariate(s.orate / 60.0)
        for kind, at in s.faults:
            self.later(at, lambda kind=kind, at=at: self.fault(kind, at), call=None)
        if s.burst:
            n, span = s.burst
            for k in range(n):
                self.later(2.0 + k * span / n, lambda: self.speak('question', None), call=None)

    def fault(self, kind, at):
        self.lines.append((round(self.now(), 2), f'FAULT {kind}'))
        if kind.startswith('drop') or kind == 'restart':
            gap = float(kind[4:]) if kind.startswith('drop') else 3.0
            self.down = True
            self.out.reconnects.append(round(self.now(), 2))

            def back():
                self.down = False
                self.reconnect()
                self.later(self.now() + self.rng.uniform(0.5, 2.0), self.decide)
            self.later(self.now() + gap, back, call=None)
        elif kind == 'call2':
            self.reconnect()
            self.later(self.now() + self.rng.uniform(1.0, 3.0), self.decide)
        elif kind == 'live':
            self.cloud_dead = True
            self.later(at + 30.0, lambda: setattr(self, 'cloud_dead', False), call=None)
        elif kind == 'eardead':
            self.ear_dead = True

    def window(self, kind, length):
        return any(k == kind and at <= self.now() < at + length for k, at in self.spec.faults)

    # -- what is asked ----------------------------------------------------------------------------------------------------------------
    def question(self, last=None):
        s, r = self.spec, self.rng
        if s.rotate:
            family = s.ask[(len(self.asked) // 3) % len(s.ask)]
        else:
            family = r.choice(s.ask)
        if last is not None and last.family in ('money', 'verb') and family in ('money', 'verb') and r.random() < 0.35:
            q = A.ask(random.Random(r.random()), last)
        elif family in ('money', 'mult', 'verb', 'year', 'article'):
            q = classic(r, family)
        elif family == 'compound':
            (q1, a1), (q2, a2) = r.sample(P.BANK['op09'] + P.BANK['tax'], 2)
            q = P.Fact('compound', (q1, q2), f'{q1[:-1]}, и ещё: {q2[0].lower()}{q2[1:]}', f'{a1} {a2}')
        else:
            text, reply = r.choice(P.BANK[family])
            q = P.Fact(family, (text,), text, reply)
        if isinstance(q, P.Fact):
            q = longer(q, s.long)
        self.asked.append(q)
        return q

    # -- the people ----------------------------------------------------------------------------------------------------------------------
    def decide(self):
        s, r, now = self.spec, self.rng, self.now()
        if s.pause and s.pause[1] <= now < s.pause[1] + s.pause[0]:
            self.later(max(s.pause[1] + s.pause[0], now + 0.1), self.decide)
            return
        if s.chat and s.chat[1] <= now < s.chat[1] + s.chat[0] * 60:
            self.later(max(s.chat[1] + s.chat[0] * 60, now + 0.1), self.decide)          # never at «now»: the clock is a float
            return
        if s.first is not None and not self.said:
            self.later(max(now + 0.1, s.first), lambda: self.speak('question', None))
            return
        if self.faults and r.random() < 0.01 and now > 10 and not s.faults:
            self.reconnect()
            self.later(now + r.uniform(1.0, 3.0), self.decide)
            return
        cue = self.last_cue()
        playing = self.w.open is not None and not self.w.open.diagnostic
        if playing and r.random() > s.barge:
            self.later(now + 0.2, self.decide)
            return
        last = self.said[-1] if self.said else None
        asked = next((u for u in reversed(self.said) if u.kind == 'question' and u.who == 'friend'), None)
        if asked is not None and now - asked.offset < WAIT_S and not any(c.t - self.zero > asked.onset for c in self.w.cues if not c.diagnostic) \
                and r.random() < 0.9 and not getattr(asked, 'lost', False):
            self.later(now + 0.5, self.decide)                                  # a question asked: they wait for the answer (one in ten does not)
            return
        if asked is not None and getattr(asked, 'lost', False) and now - asked.offset > 4.0 and not any(c.t - self.zero > asked.onset for c in self.w.cues if not c.diagnostic) \
                and not getattr(asked, 'again', False):
            asked.again = True                                                  # Р055: not heard, so asked again
            self.later(now + 0.3, lambda: self.speak('question', None))
            return
        fresh = cue is not None and (last is None or cue.t - self.zero > last.offset) and self.following and not self.stopped
        table = STOPPED if self.stopped else s.user if fresh else s.idle
        kinds = [k for k, w in table.items() if w > 0]
        kind = r.choices(kinds, [table[k] for k in kinds])[0]
        if kind == 'fix' and (self.current is None or self.current.family not in ('money', 'mult')):
            kind = 'question'
        if kind in ('stutter', 'own', 'more', 'self', 'follow', 'object', 'cancel', 'back') and self.current is None:
            kind = 'question'
        if kind == 'silence':
            self.later(now + r.uniform(2.0, 9.0), self.decide)
            return
        onset = max(now + (r.uniform(0.3, 1.2) if fresh and not playing else r.uniform(0.0, 0.6)), self.free)
        self.later(onset, lambda: self.speak(kind, cue if fresh else None, barge=playing))

    def stuttered(self, text, style):
        r, words = self.rng, text.split()
        if not words:
            return text
        k = r.randrange(len(words))
        if style == 'first':
            return f'{words[0][:2]}... {text}'
        if style == 'mid':
            k = len(words) // 2
            return ' '.join(words[:k] + ['э-э', words[k][:3] + '...'] + words[k:])
        if style == 'last':
            return ' '.join(words[:-1] + [words[-1][:3] + '...', words[-1]])
        if style == 'num':
            nums = [i for i, w in enumerate(words) if re.search(r'\d', w)]
            k = nums[0] if nums else k
            return ' '.join(words[:k] + [words[k][:1] + '...'] + words[k:])
        if style == 'filler':
            return ' '.join(words[:k] + [r.choice(('ну', 'это', 'как его', 'короче'))] + words[k:])
        if style == 'stretch':
            w = words[k]
            vowel = next((i for i, ch in enumerate(w) if ch.lower() in 'аеиоуыэюя'), None)
            return ' '.join(words[:k] + ([w[:vowel] + w[vowel] * 4 + w[vowel + 1:]] if vowel is not None else [w]) + words[k + 1:])
        if style == 'cut':
            return ' '.join(words[:-1] + [words[-1][:max(2, len(words[-1]) // 2)]])
        if style == 'restart':
            return ' '.join(words[:2]) + '... ' + text
        if style == 'skip' and len(words) > 2:
            return ' '.join(words[:k] + words[k + 1:])
        if style == 'swap' and len(words) > 2:
            k = min(k, len(words) - 2)
            return ' '.join(words[:k] + [words[k + 1], words[k]] + words[k + 2:])
        if style == 'more':
            chunks = list(getattr(self.last_cue(), 'snap', {}).get('chunks') or ())
            index = (getattr(self.last_cue(), 'snap', {}) or {}).get('index') or 0
            after = chunks[index + 1].split()[:3] if index + 1 < len(chunks) else []
            return ' '.join(words + after)
        if style == 'own':
            swaps = {'это': 'значит', 'налог': 'налоги', 'организации': 'фирмы', 'рублей': 'рубля', 'бывают': 'есть'}
            return ' '.join(swaps.get(w.lower(), w) for w in words)
        return text

    def speak(self, kind, cue, barge=False):
        """Who says what. The friend: ``question fix doubt follow object cancel back newq``; the user: a repeat of the cue (``repeat partial wrong stutter
        own more self``) or a command; ``other``: someone else (``OTHERS``), the meaning of it is the mind's only for a passer-by's question."""
        r, s = self.rng, self.spec
        meaning, who = None, 'user'
        if kind == 'stutter':
            style = r.choice(s.stutter)
            if cue is None:
                kind = 'question'
            else:
                barge = barge or style == 'closed'
                text = self.stuttered(cue.text, 'mid' if style == 'closed' else style)
        if kind in ('question', 'newq'):
            if self.spec.lostq and self.current is not None and any(getattr(u, 'again', False) and u.meaning[1] is self.current for u in self.said[-3:]):
                q = self.current                                        # Р055: not heard, asked again
            else:
                q = self.question(self.current)
            text, meaning, who = q.text, ('q', q), 'friend'
            if s.intro and r.random() < s.intro or not s.intro and r.random() < 0.1:
                text = (r.choice(P.INTROS) if s.intro else r.choice(A.CHATTER[:3])) + ' ' + text
            kind = 'question'
        elif kind == 'fix' and (self.current is None or self.current.family not in ('money', 'mult')):
            return self.speak('question', cue, barge)
        elif kind == 'fix':
            q = self.current
            a, b = q.params
            new = a + r.choice((10, 20, -10)) if a > 20 else a + 10
            q2 = Q(q.family, (new, b), q.text.replace(str(a), str(new), 1))
            text, meaning, who = f'Нет, не {a}, а {new}.', ('fix', q2), 'friend'
        elif kind in ('doubt', 'follow', 'object'):
            text = r.choice({'doubt': A.DOUBTS, 'follow': ('А подробнее?', 'А почему так?', 'Поясни.'), 'object': ('Нет, это не так.', 'Я думаю, ты ошибаешься.')}[kind])
            meaning, who, kind = ('doubt', None), 'friend', 'doubt'
        elif kind == 'cancel':
            text, who = r.choice(('А, неважно, проехали.', 'Ладно, неважно.')), 'friend'
            self.cancelled.setdefault(id(self.current), round(self.now(), 2))
        elif kind == 'back':
            older = [q for q in self.asked[:-1] if q is not self.current]
            if older:
                q = r.choice(older)
                text, meaning, who, kind = 'Вернёмся к прошлому вопросу. ' + q.text, ('q', q), 'friend', 'question'
            else:
                return self.speak('question', cue)
        elif kind == 'self':
            text = ' '.join(self.current.answer().split()[:5])
        elif kind == 'own':
            text = self.stuttered(cue.text, 'own') if cue else r.choice(A.CHATTER)
            kind = 'stutter'
        elif kind == 'more':
            text = self.stuttered(cue.text, 'more') if cue else r.choice(A.CHATTER)
            kind = 'stutter'
        elif kind in A.COMMANDS:
            text, meaning = r.choice(A.COMMANDS[kind]), ('cmd', kind)
        elif kind in ('repeat', 'partial', 'wrong') and cue is not None:
            words = cue.text.split()
            if kind == 'repeat':
                text = cue.text
            elif kind == 'partial':
                text = ' '.join(words[:max(1, min(2, len(words) - 1))])
            else:
                text = re.sub(r'\d+', lambda m: str(int(m.group()) + 7), cue.text, count=1) if re.search(r'\d', cue.text) else ' '.join(words[:-1] + ['капуста'])
        elif kind != 'stutter':
            kind, text = 'chatter', r.choice(A.CHATTER)
        self.utter(kind, text, meaning, who, cue, barge)
        gap = r.uniform(0.2, 2.5) if r.random() < 0.8 else r.uniform(3.0, 8.0)
        if who != 'other':
            self.later(self.said[-1].offset + gap, self.decide)

    def other(self):
        """Someone else speaks: a stranger, the television, a laugh, a door, an aside, an argument, a passer-by's own question, another's «повторите» or «стоп»."""
        r, s = self.rng, self.spec
        if not s.over and (self.now() < self.free or self.speaking is not None):
            self.later(max(self.now(), self.free) + r.uniform(0.2, 1.0), self.other, call=None)
            return
        kinds = list(s.others)
        kind = r.choices(kinds, [s.others[k] for k in kinds])[0]
        meaning = None
        if kind == 'passer':
            text, reply = r.choice(P.BANK['out'])
            q = P.Fact('out', (text,), text, reply)
            text, meaning = 'Извините, а ' + text[0].lower() + text[1:], ('q', q)
        elif kind == 'answer_other':
            text = self.current.answer() if self.current is not None else r.choice(OTHERS['chatter'])
        elif kind == 'again_other':
            text, meaning = r.choice(OTHERS[kind]), ('cmd', 'again')
        elif kind == 'stop_other':
            text, meaning = r.choice(OTHERS[kind]), ('cmd', 'stop')
        else:
            text = r.choice(OTHERS[kind])
        self.utter('other', text, meaning, kind, None, self.w.open is not None)

    def utter(self, kind, text, meaning, who, cue, barge):
        r = self.rng
        ear = self.heard_by_ear(text, kind) if text else ''
        if meaning:
            for said in {text, ear, meaning[1].text if meaning[0] == 'q' else text}:
                self.mind.learn(said, meaning)
                self.mind.learn(self.heard_by_ear(said, kind, exact=True), meaning)
        now = self.now()
        tempo = self.spec.tempo or r.uniform(2.0, 3.0)
        length = 0.3 if not text else max(0.35, len(text.split()) / tempo * r.uniform(0.85, 1.15))
        u = A.Said(len(self.said) + 1, kind, text, ear, round(now, 2), round(now + length, 2), meaning=meaning,
                   cue=cue and (cue.text, cue.snap.get('revision'), cue.snap.get('index')), barge=barge, call=self.call)
        u.who = who
        u.lost = bool(kind == 'question' and self.spec.lostq and r.random() < self.spec.lostq)
        u.cancelled = False
        self.said.append(u)
        if who != 'other' or (meaning and meaning[0] == 'cmd'):
            if kind in ('question', 'fix'):
                self.current, self.stopped, self.following = meaning[1], False, True
            elif kind == 'stop' or meaning == ('cmd', 'stop'):
                self.stopped = True
            elif kind in ('again', 'resume') or meaning == ('cmd', 'again'):
                self.stopped = False
        if who != 'other':
            self.free = u.offset + 0.15
        self._utter(u)

    def heard_by_ear(self, text, kind, exact=False):
        if exact:
            return super().heard_by_ear(text, kind, exact=True)
        r = self.rng
        heard = self.earm.hear(r, text, self.spec.noise)
        if r.random() < 0.7:
            heard = ' '.join(A.spell(int(w)) if w.isdigit() and len(w) < 10 else w for w in heard.split())
        return heard

    def _utter(self, u):
        """The ear's onset, end and text; the cloud's turn: created, words, the final (12_LATENCY_CHAIN), sometimes lost; sometimes the cloud's own answer."""
        r, s = self.rng, self.spec
        uid = f'u{u.n}'
        box = {}
        if self.down:
            return

        def onset():
            if not (self.down or self.ear_dead):
                self.steps.append(('onset', box))

        def offset():
            if not (self.down or self.ear_dead):
                self.steps.append(('end', box))

        def text():
            if box.get('ear') is not None and not (self.down or self.ear_dead) and not u.lost:
                u.ear_at = round(self.now(), 2)
                self.worker.heard(box['ear'], u.ear)

        self.later(u.onset, onset)
        self.later(u.offset, offset)
        if u.text:
            self.later(u.offset + max(0.05, lognormal(r, 0.15, 0.34)), text)
        if not u.text and r.random() < 0.7:
            return                                                             # a door: the cloud makes nothing of it
        words = (u.text or 'м').split()
        if r.random() < 0.9:
            created = u.onset + r.uniform(0.2, 1.0)

            def created_now():
                u.created_at = round(self.now(), 2)
                head = self.ms(u.onset) // 200 * 200
                self._feed({'type': 'turn.created', 'turn': {'id': uid, 'role': 'user', 'transcript': words[0], 'start_ms': head, 'end_ms': head + 200}})
            self.later(created, created_now)
            for n, word in enumerate(words[1:]):
                at = created + (u.offset - created) * (n + 1) / len(words)
                self.later(at, lambda word=word, n=n: self._feed({**A.S.turn_delta(uid, ' ' + word, 0), **self.span(u, n + 1, len(words))}))
        lost = 0.04 + (0.04 if s.noise == 'snr5' else 0.0)
        if r.random() > lost and not u.lost:
            late = lognormal(r, 2.35, 3.48) if u.kind in ('question', 'fix') else lognormal(r, 1.95, 2.44) if u.kind in ADVANCING else lognormal(r, 1.89, 6.08)
            if any(k == 'cold' for k, _ in s.faults) and u.n <= 2:
                late += 1.5
            final = max(u.offset + min(late, 15.0), self.last_final + 0.05)
            self.last_final = final

            def done():
                u.final_at = round(self.now(), 2)
                d = A.S.turn_done(uid, 'user', u.text or 'м')
                d['turn'].update(start_ms=self.ms(u.onset) // 200 * 200, end_ms=-(-self.ms(u.offset) // 200) * 200)
                self._feed(d)
            self.later(final, done)
            if r.random() < 0.5:
                aid = f'a{u.n}'
                reply = u.meaning[1].answer() if u.meaning and u.meaning[0] in ('q', 'fix') and r.random() < 0.5 else r.choice(A.CHATTER_OF_THE_CLOUD)
                at = final + r.uniform(0.1, 2.5)
                self.later(at, lambda: self._feed(A.S.turn_created(aid, 'assistant', '')))
                self.later(at + r.uniform(0.3, 2.0), lambda: self._feed(A.S.turn_done(aid, 'assistant', reply)))

    def _feed(self, event):
        if self.down or self.cloud_dead:
            return
        super()._feed(event)

    def _packet(self):
        if self.down:
            return
        super()._packet()

    # -- the model -----------------------------------------------------------------------------------------------------------------------
    def _born(self, job, thread):
        run = A.Run(job, thread, self.now())
        self.runs[id(job.request)] = run
        answer = self.mind.answer(job.request)
        r = self.rng
        first = TAIL_S + r.uniform(0, 1) if r.random() < TAIL_P else lognormal(r, 1.2, 3.0)
        if any(k == 'cold' for k, _ in self.spec.faults) and len(self.out.jobs) < 2:
            first *= 2
        fail = r.random() < FAIL_P
        if self.window('silent12', 60):
            first = 12.0
        if self.window('429', 40):
            first, fail = 0.3, True
        text = job.request['input'][-1]['content'][0]['text']
        if self.window('search', 60) and answer != '—' and r.random() < 0.5:
            fail = True
        heard = text.rsplit('Сейчас прозвучало: ', 1)[-1]
        readings = [self.mind.read(part) for part in heard[len('Распознано: '):].split(' / ')] if heard.startswith('Распознано: ') else []
        parts = heard[len('Распознано: '):].split(' / ') if readings else []
        inside = len(parts) == 2 and any(key in normalize(parts[0]) for key, meaning in self.mind.meant.items() if key and meaning == readings[1])
        mixed = len(readings) == 2 and None not in readings and readings[0] != readings[1] and not inside
        self.out.jobs.append({'at': round(self.now(), 2), 'heard': text[-160:], 'answer': answer, 'first': round(first, 2), 'fail': fail, 'mixed': mixed})
        pieces = [answer] if len(answer) < 12 or r.random() < 0.4 else self._pieces(answer)
        at = self.now() + first
        for piece in pieces:
            self.later(at, lambda piece=piece: run.say(piece), call=None)
            at += r.uniform(0.05, 0.4)
        self.later(at, lambda: run.end(fail), call=None)


# =====================================================================================================================================
# broken controllers: the stand must go red on them (tests/test_w9_rehearsal.py)
# =====================================================================================================================================

def _mute(cm):
    """Says nothing: every list of actions the controller returns (to the provider's events, the ticks, the ear, the fast channel) is dropped."""
    for name in ('provider', 'tick', 'ear_heard', 'ear_piece', 'ear_onset', 'fast_feed', 'fast_stable', 'fast_lost', 'partial_quiet', 'answer_diagnosed',
                 'grounding', 'delivery_sent', 'no_search', 'no_source'):
        method = getattr(cm, name, None)
        if method is None:
            continue

        def wrapped(*a, _method=method, **k):
            out = _method(*a, **k)
            return [] if isinstance(out, list) else out
        setattr(cm, name, wrapped)


def _stale(cm):
    """Keeps the first answer: every later user turn of a new question is dropped once an answer is on (an old answer after a new question, a missed one)."""
    provider, heard = cm.provider, cm.ear_heard

    def answering():
        s = cm.state() or {}
        return bool(s.get('chunks')) and not s.get('completed')

    def stale_provider(event, *a, **k):
        turn = event.get('turn') or {}
        if turn.get('role') == 'user' and answering() and '?' in (turn.get('transcript') or turn.get('text') or ''):
            return []
        return provider(event, *a, **k)
    cm.provider = stale_provider
    cm.ear_heard = lambda record, *a, **k: [] if answering() else heard(record, *a, **k)


MUTANTS = {'mute': _mute, 'stale': _stale}


def play(spec, seed, *, flags=None, mutant=None, keep_log=True, stand=None):
    """One rehearsal of one seed: the record (``Outcome``) with the stand's invariants, the controller's log lines (seconds, text) and the stand's own lines.
    ``stand``: the class that plays it (default ``Rehearsal``; ``tools.rehearsal.shrink`` plays a recorded or a scripted one)."""
    from tools.replay.stand import check
    lines, box = [], {}

    class Catch(logging.Handler):
        def emit(self, record):
            st = box.get('stand')
            if st is not None and hasattr(st, 'zero'):
                lines.append((round(st.now(), 2), record.getMessage()[:200]))
                if len(lines) > 4000:
                    del lines[:2000]
    handler, root = Catch(level=logging.INFO), logging.getLogger()
    level = root.level
    if keep_log:
        root.addHandler(handler)
        root.setLevel(logging.INFO)
    original = A.Stand.__init__

    def init(self, *a, **k):
        box['stand'] = self
        original(self, *a, **k)
    A.Stand.__init__ = init
    try:
        st = (stand or Rehearsal)(spec, seed, flags=flags, mutant=mutant)
    finally:
        A.Stand.__init__ = original
    try:
        if mutant:
            MUTANTS[mutant](st.w.controller)
            attach = st._attach

            def again():
                before = st.w.controller
                attach()
                if st.w.controller is not before:
                    MUTANTS[mutant](st.w.controller)
            st._attach = again
        try:
            st.play()
        except Exception as error:                     # noqa: BLE001 - a crash of the chain is a finding
            import traceback
            st.out.crash = ''.join(traceback.format_exception(error))[-1500:]
            st.out.violations.append(('A0', round(st.now(), 2), f'{type(error).__name__}: {error}'[:300]))
            st._collect()
    finally:
        st.close()
        if keep_log:
            root.removeHandler(handler)
            root.setLevel(level)
    out = st.out
    out.violations += check(out)
    out.ctl = lines
    out.stand_lines = st.lines
    out.cancelled = {u.n: st.cancelled[id(u.meaning[1])] for u in out.said if u.kind == 'question' and id(u.meaning[1]) in st.cancelled}
    return out

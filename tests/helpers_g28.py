"""g28-guards: a scene of the owner's call, step by step, through the real chain of the stand (tools/replay/stand.py).

REAL: ControlledMedia, the shadow ear in act mode, the fast text channel with its threads, the classifier, the engine.
SCRIPTED: what the listener says and when, what the ear and the cloud make of it and how late, the text model (``Mind``: a table of
replies by the words it is given, '—' otherwise) and the cloud's own replies. Nothing random: the same scene gives the same record.
"""
import re

from tools.replay import stand as A
from echo_sync.textutil import normalize

FLAGS = {'local_ear': 'act', 'prompt_tempo': 'ear', 'fast_text': 'on', 'ear_release': 'on', 'quick_math': 'on', 'two_witnesses': 'on'}


class Mind:
    """The text model of a scene: ``replies`` maps words to the reply given to a request whose heard text contains them (the longest key
    wins); the rest is «—». ``seen`` keeps what each job was given."""

    def __init__(self, replies=None):
        self.replies = {normalize(k): v for k, v in (replies or {}).items()}
        self.seen = []
        self.meant = {}

    def learn(self, text, meaning):
        pass

    def read(self, text):
        return None

    def heard(self, request):
        text = request['input'][-1]['content'][0]['text']
        return text.rsplit('Сейчас прозвучало: ', 1)[-1]

    def answer(self, request):
        heard = normalize(self.heard(request))
        self.seen.append(heard)
        keys = [k for k in self.replies if k and k in heard]
        return self.replies[max(keys, key=len)] if keys else '—'


class Scene(A.Stand):
    def __init__(self, replies=None, *, job_late=0.6, flags=None, **keywords):
        super().__init__(0, length=1e9, profile={**FLAGS, **(flags or {})}, faults=False, **keywords)
        self.mind = Mind(replies)
        self.job_late = job_late
        self.n = 0

    # the model: one piece, ``job_late`` seconds after the job began
    def _born(self, job, thread):
        run = A.Run(job, thread, self.now())
        self.runs[id(job.request)] = run
        answer = self.mind.answer(job.request)
        self.out.jobs.append({'at': round(self.now(), 2), 'heard': self.mind.heard(job.request), 'answer': answer, 'first': self.job_late, 'fail': False, 'mixed': False})
        at = self.now() + self.job_late
        self.later(at, lambda: run.say(answer), call=None)
        self.later(at + 0.05, lambda: run.end(False), call=None)

    def say(self, at, text, *, ear=None, late=0.8, lost=False, ear_lost=False, reply=None, reply_late=0.4, kind='talk'):
        """The listener says ``text`` from ``at`` (0.33 s a word). The ear writes ``ear`` (default: lower case, no punctuation) 0.2 s after
        the end; the cloud's final comes ``late`` s after the end (``lost``: never); ``reply``: what the cloud itself answers then."""
        self.n += 1
        words = text.split()
        u = A.Said(self.n, kind, text, ear if ear is not None else ' '.join(re.findall(r'[\w-]+', text.lower())), round(at, 2), round(at + max(0.4, 0.33 * len(words)), 2))
        uid = f'u{u.n}'
        box = {}
        self.said.append(u)
        self.later(u.onset, lambda: self.steps.append(('onset', box)))
        self.later(u.offset, lambda: self.steps.append(('end', box)))

        def heard():
            if box.get('ear') is not None and not ear_lost:
                u.ear_at = round(self.now(), 2)
                self.worker.heard(box['ear'], u.ear)
        self.later(u.offset + 0.2, heard)
        created = u.onset + 0.3

        def created_now():
            u.created_at = round(self.now(), 2)
            head = self.ms(u.onset) // 200 * 200
            self._feed({'type': 'turn.created', 'turn': {'id': uid, 'role': 'user', 'transcript': words[0], 'start_ms': head, 'end_ms': head + 200}})
        self.later(created, created_now)
        for n, word in enumerate(words[1:]):
            self.later(created + (u.offset - created) * (n + 1) / len(words), lambda word=word, n=n: self._feed({**A.S.turn_delta(uid, ' ' + word, 0), **self.span(u, n + 1, len(words))}))
        if not lost:
            final = max(u.offset + late, self.last_final + 0.05)
            self.last_final = final

            def done():
                u.final_at = round(self.now(), 2)
                event = A.S.turn_done(uid, 'user', u.text)
                event['turn'].update(start_ms=self.ms(u.onset) // 200 * 200, end_ms=-(-self.ms(u.offset) // 200) * 200)
                self._feed(event)
            self.later(final, done)
            if reply is not None:
                aid = f'a{u.n}'
                self.later(final + reply_late, lambda: self._feed(A.S.turn_created(aid, 'assistant', '')))
                self.later(final + reply_late + 0.5, lambda: self._feed(A.S.turn_done(aid, 'assistant', reply)))
        return u

    def until(self, t):
        while self.now() < t:
            while self.agenda and self.agenda[0][0] <= self.now() + 1e-9:
                _, _, call, action = A.heapq.heappop(self.agenda)
                if call is None or call == self.call:
                    action()
            self._packet()
            self.w.advance(A.TICK, step=A.TICK)
            self._sample()
        return self

    # observation
    def cues(self, after=0.0):
        return [c.text for c in self.w.cues if not c.diagnostic and c.t - self.zero >= after - 1e-9]

    def state(self):
        return self.w.controller.state() or {}

    def last_cue(self):
        cues = self.cues()
        return cues[-1] if cues else None

    def repeat(self, at, **keywords):
        """The listener repeats the cue that is played last, word for word."""
        cue = self.last_cue()
        return self.say(at, cue, kind='repeat', **keywords)

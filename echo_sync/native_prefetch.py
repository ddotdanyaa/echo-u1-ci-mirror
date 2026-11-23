"""Bounded evidence prefetch over the existing lookup; never authorizes audio.

Only the same turn and narrow canonical question match can adopt preparation.
Existing RU numeric/reference formatting is accepted; other lexical surfaces,
negation, codes and word order remain protected. a3-search: another wording of the same question adopts it too (``search_identity.same_meaning``, numbers/«не» protected); no embeddings.
"""
import asyncio
import inspect
import re
import unicodedata

from .search_identity import same_meaning
from .timer_policy import EARLY_LOOKUP_STABLE_SECONDS


def question_key(text):
    text=unicodedata.normalize('NFC',str(text)).casefold().replace('ё','е')
    text=re.sub(r'\s+',' ',text).strip().rstrip('?!。.! ').strip()
    try:
        from .ru_alignment import _canonical,_lemma,_NUMBERS,_ORDINALS,_UNITS
        from razdel import tokenize
        # Reuse the existing ordered RU token/number/unit grammar. No fuzzy
        # threshold, synonyms, discarded negation or mutation of a generator.
        reference=bool(re.search(r'\b(?:стать\w*|пункт\w*|глав\w*)\b',text))
        reference_words={'статья','пункт','глава','кодекс','конституция','закон','гражданский','налоговый','уголовный','трудовой','семейный','административный','российский','федерация'} if reference else set()
        # Lemmas alone erase tense and grammatical roles (Ивану/Ивана).
        # Permit inflection only inside the narrow reference vocabulary;
        # retain the surface of every other lexical token, in order.
        lexical=[]
        for token in tokenize(text):
            word=token.text
            if not word.isalpha():continue
            lemma=_lemma(word)
            if lemma not in _NUMBERS and lemma not in _ORDINALS and lemma not in _UNITS and lemma not in reference_words:
                lexical.append(word)
        return ('ru',_canonical(text,()),tuple(lexical))
    except ImportError:return ('exact',text)


class EarlyLookup:
    def __init__(self,fetch,trace,*,enabled=False):
        self.fetch=fetch;self.trace=trace;self.enabled=enabled
        self.stable_seconds=EARLY_LOOKUP_STABLE_SECONDS
        self.signature=None;self.question='';self.changed_at=0
        self.started={};self.task=None;self.task_question='';self.task_signature=None;self.tasks=set()
        self.confirmed={};self.closed=False
        self.request_counts={}
        # Q1 / B9: ``source``: whose text the signature is ('partial': the cloud's, 'ear': the local ear's, see ``observe_ear``); ``ear_fed``: the turns the ear prepared for (one request more each).
        self.source='partial';self.ear_fed={}

    def observe(self,turn_id,question,*,now):
        if self.closed or turn_id in self.confirmed:return
        signature=(turn_id,question_key(question)) if turn_id and question else None
        if signature==self.signature:return
        self.signature=signature;self.question=question or '';self.changed_at=now;self.source='partial'
        if self.task and signature!=self.task_signature and not self.task.done() and self.task_signature[0] not in self.confirmed:self.task.cancel()

    def observe_ear(self,turn_id,question,*,now):
        """Q1 / B9: the local ear's text of the utterance the cloud's open turn ``turn_id`` holds: a whole utterance, so the search starts on the next tick and does not wait for it to settle as a partial does.
        Preparing only, as always. One preparation a turn whoever's text starts it; the turn has one request more for it (``_fetch``), so that a preparation for other words never takes the place of the
        final's request or of one restart of it."""
        if self.closed or not self.enabled or not turn_id or not question or turn_id in self.confirmed or turn_id in self.started:return
        self.ear_fed[turn_id]=True
        while len(self.ear_fed)>64:self.ear_fed.pop(next(iter(self.ear_fed)))
        self.observe(turn_id,question,now=now);self.source='ear'      # the same signature as the cloud's partial: ``observe`` changes nothing and the ear confirms it, no wait

    async def _fetch(self,question,turn_id):
        if self.closed:raise asyncio.CancelledError()
        count=self.request_counts.get(turn_id,0)
        if count>=(3 if turn_id in self.ear_fed else 2):
            await self.trace('lookup_budget_exhausted')
            raise RuntimeError('lookup_budget_exhausted')
        self.request_counts[turn_id]=count+1
        while len(self.request_counts)>64:self.request_counts.pop(next(iter(self.request_counts)))
        value=self.fetch(question)
        return await value if inspect.isawaitable(value) else value

    async def _prepare(self,question,turn_id):
        try:
            value=await self._fetch(question,turn_id)
            await self.trace('prefetch_result_ready',source_count=len(value) if isinstance(value,list) else 0)
            return value
        except Exception as error:      # a cancel is not an ``Exception``: it goes through
            await self.trace('prefetch_failure',error_type=type(error).__name__)
            return None

    async def tick(self,*,now):
        if self.closed or not self.enabled or not self.signature or (self.source!='ear' and now-self.changed_at<self.stable_seconds):return
        tid,_=self.signature
        if tid in self.started or tid in self.confirmed:return
        self.started[tid]=True
        while len(self.started)>64:self.started.pop(next(iter(self.started)))
        self.task_signature=self.signature;self.task_question=self.question
        # Bind task, question and signature before yielding to diagnostics.
        self.task=asyncio.create_task(self._prepare(self.question,tid));self.tasks.add(self.task)
        self.task.add_done_callback(self.tasks.discard)
        await self.trace('speculation_started',stable_ms=round((now-self.changed_at)*1000),kind='existing_public_lookup',source=self.source)

    async def resolve(self,turn_id,question):
        if self.closed:raise asyncio.CancelledError()
        signature=(turn_id,question_key(question))
        task,task_signature=self.task,self.task_signature
        self.confirmed[turn_id]=True
        while len(self.confirmed)>64:self.confirmed.pop(next(iter(self.confirmed)))
        # a3-search: the same turn and the same meaning (another way of saying it, numbers in their order and every «не» with its word agreeing) adopts the preparation too
        if task and task_signature!=signature and task_signature[0]==turn_id and not task.cancelled() and same_meaning(question,self.task_question):signature=task_signature
        if task and task_signature==signature and not task.cancelled():
            await self.trace('prefetch_adopted',result_already_ready=task.done())
            try:value=await task
            except asyncio.CancelledError:
                # External cancellation must not start a replacement lookup.
                if self.closed or asyncio.current_task().cancelling():raise
                value=None
            if value:return value
        elif task and not task.done():
            task.cancel()
            await self.trace('prefetch_discarded',reason='question_or_turn_changed')
        return await self._fetch(question,turn_id)

    async def close(self):
        self.closed=True
        tasks=list(self.tasks)
        for task in tasks:
            if not task.done():task.cancel()
        if tasks:await asyncio.gather(*tasks,return_exceptions=True)

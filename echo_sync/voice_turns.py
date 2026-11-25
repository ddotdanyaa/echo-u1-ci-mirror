"""Bounded in-memory conversation map for Conduit's subscription wire.

Created/delta/done share turn IDs; input_transcript.added IDs identify single
fragments instead. Never infer speaker ownership from callback arrival order.
This ledger provides data, not permission to advance a cursor or speak.
"""
from copy import deepcopy
import math
import re

REUSED_MIN_WORDS=6          # D1: a final of a turn already final is another utterance only when BOTH texts have this many words: a refinement of a shorter speech («15» -> «50», a corrected word) is never told apart from it
REUSED_MAX_SHARED=1/5       # ... and share at most this part of the shorter text's words: a refined transcript of the same speech keeps its words
_WORDS=re.compile(r'\w+')
_DIGIT=re.compile(r'\d')
def _another_speech(old,new,old_span=None,new_span=None):
    """D1: is ``new`` a different utterance than ``old``, said under a turn id the provider numbered again (the microphone was re-opened)? Not when it carries a sign of a refinement: the same span of the input audio, or words turned into figures («двести сорок пять тысяч» -> «245 000»)."""
    if old_span is not None and old_span==new_span:return False
    if bool(_DIGIT.search(old))!=bool(_DIGIT.search(new)):return False
    a,b=_WORDS.findall(old.lower()),_WORDS.findall(new.lower())
    if min(len(a),len(b))<REUSED_MIN_WORDS:return False
    return len(set(a)&set(b))<=REUSED_MAX_SHARED*min(len(set(a)),len(set(b)))

class FramelessTurns:
    def __init__(self,*,max_turns=64,max_chars=4000,keep=None,sink=None):
        """``keep``: optional callable returning the ids of turns its owner is still working on.

        The map stays bounded by evicting the OLDEST turn, but never one of those: the question being answered and the
        assistant turn that streams its answer are old by arrival order long before they are finished (every ACK is a
        turn), and a controller that loses them stops for good. Only finished history is evicted.
        """
        self.max_turns=max(1,int(max_turns));self.max_chars=max(1,int(max_chars))
        self._keep=keep;self._sink=sink      # U14-S4: ``sink(tid, text, revisions)`` hears each final of the listener's words (a refined one again); a failing sink costs nothing
        self._turns={};self._sequence=0

    def apply(self,event):
        if not isinstance(event,dict):return None
        kind=event.get('type')
        if kind not in {'turn.created','turn.delta','turn.done'}:return None
        raw=event.get('turn') if kind!='turn.delta' else None
        if kind=='turn.delta':
            tid=event.get('turn_id')
            if not isinstance(tid,str):return None
            turn=self._turns.get(tid)
            text=event.get('delta')
            if turn is None or turn['final'] or not isinstance(text,str) or not text:return None
            span=(event.get('start_ms'),event.get('end_ms'))
            key=(*span,text) if all(type(x) in (int,float) for x in span) else None
            if key is not None and not all(math.isfinite(x) and x>=0 for x in span):return None
            if key is not None and key in turn['_seen']:return None
            if key is not None:
                if len(turn['_seen'])<self.max_chars:turn['_seen'].add(key)
                else:turn['truncated']=True
            joined=turn['text']+text
            turn['truncated']=turn['truncated'] or len(joined)>self.max_chars
            turn['text']=joined[:self.max_chars]
            if type(event.get('end_ms')) in (int,float):turn['end_ms']=event['end_ms']
        else:
            if not isinstance(raw,dict):return None
            tid,role,text=raw.get('id'),raw.get('role'),raw.get('transcript','')
            if not isinstance(tid,str) or not tid or len(tid)>200 or not isinstance(role,str) or role not in {'user','assistant'} or not isinstance(text,str):return None
            if any(name in raw and (type(raw[name]) not in (int,float) or not math.isfinite(raw[name]) or raw[name]<0) for name in ('start_ms','end_ms')):return None
            if kind=='turn.created' and tid in self._turns:return None
            chain=self._chain(tid)
            if len(chain)>1 and any(self._turns[key]['text']==text and self._turns[key]['role']==role and self._turns[key]['final'] for key in chain):return None      # the retransmit of any speech of this id
            tid=chain[-1];turn=self._turns.get(tid)      # D1: the LAST speech under the id is the one a final is compared with
            if turn is not None and kind=='turn.done' and turn['final'] and turn['role']==role=='user' and text!=turn['text'] and _another_speech(turn['text'],text,self._span(turn),self._span(raw)):
                # D1: the id came again with other speech after the first was final: a new turn of its own (ids number from the start once the microphone is re-opened), never a clarification of the first
                n=len(chain)+1
                while f'{chain[0]}~{n}' in self._turns:n+=1
                tid=f'{chain[0]}~{n}';turn=None
            if turn is not None and turn['final'] and text==turn['text'] and role==turn['role']:return None
            # A second, different final of a USER turn is the provider's refined transcript of the same speech: the turn is updated
            # and stays eligible (DEF-STATE-03: a permanent conflict muted the call). Nothing is taken as new speech by that: the
            # owner of the ledger acts once per turn id. A change of role, or a rewritten answer, is a conflict for good.
            revised=bool(turn and kind=='turn.done' and turn['final'] and turn['role']==role=='user' and text.strip() and text!=turn['text'])
            if turn is not None and turn['final'] and turn['role']==role=='user' and text!=turn['text'] and not revised:return None
            conflict=bool(turn and (turn['role']!=role or (turn['final'] and text!=turn['text'] and not revised)))
            if turn is None:
                self._sequence+=1
                turn={'id':tid,'role':role,'_sequence':self._sequence,'_seen':set(),'conflicted':False,'revisions':0}
                self._turns[tid]=turn
            turn.update(text=text[:self.max_chars],final=kind=='turn.done',truncated=len(text)>self.max_chars,
                        conflicted=turn['conflicted'] or conflict,revisions=turn['revisions']+bool(revised))
            for name in ('start_ms','end_ms'):
                if type(raw.get(name)) in (int,float):turn[name]=raw[name]
            if self._sink and kind=='turn.done' and role=='user' and turn['text'].strip():
                try:self._sink(tid,turn['text'],turn['revisions'])
                except Exception:pass
        while len(self._turns)>self.max_turns:
            needed=self._keep() if self._keep else ()
            finished=[t for t in self._turns.values() if t['id'] not in needed]
            if not finished:break  # everything is still needed: the owner's call, never an endless loop
            del self._turns[min(finished,key=lambda turn:turn['_sequence'])['id']]      # the oldest by arrival: a turn of ours has no ``start_ms``, ``_order`` puts it first of all (level1-a, question 17: the new job's own turn went)
        return self.snapshot(tid)

    @staticmethod
    def _span(item):
        start,end=item.get('start_ms'),item.get('end_ms')
        return (start,end) if type(start) in (int,float) and type(end) in (int,float) else None

    def _chain(self,tid):
        """The turn under ``tid`` and the later speeches the provider gave the same id (``<id>~2``, ``~3``), oldest first; ``[tid]`` when there is none."""
        found=[tid];n=2
        while f'{tid}~{n}' in self._turns:found.append(f'{tid}~{n}');n+=1
        return found

    def effective(self,tid):
        """The id of the LAST speech given under ``tid``: what the controller keeps its records of (the transport asks it for the events of a reused id)."""
        return self._chain(tid)[-1] if isinstance(tid,str) else tid

    @staticmethod
    def _order(turn):return (turn.get('start_ms',-1),turn['_sequence'])

    def snapshot(self,tid):
        turn=self._turns.get(tid)
        if turn is None:return None
        value={key:deepcopy(item) for key,item in turn.items() if not key.startswith('_')}
        value['valid']=not value['conflicted'] and not value['truncated']
        return value

    def latest_user(self,*,require_final=False):
        users=[turn for turn in self._turns.values() if turn['role']=='user']
        if not users:return None
        value=self.snapshot(max(users,key=self._order)['id'])
        return None if require_final and not value['final'] else value

    def history(self):return [self.snapshot(turn['id']) for turn in sorted(self._turns.values(),key=self._order)]

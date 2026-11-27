"""w9-search (N123, N124, Ст8): the search and the job without a source run side by side; a draft is released only if the source confirmed its numbers.
Pure and off by default (``enabled``): nothing here is wired into ``controlled_media.py`` (the patch is in the report). ``says_a_number`` is the same check the engine already makes:
a number the question does not have must come from a source. ``QueryCache``: per call (memory) and on disk with the day it was fetched on; a source of another day is never given back;
only hashed keys and public sources are stored, a private question is not stored at all."""
import asyncio
import hashlib
import json
import os
import re
import time
from collections import OrderedDict
from datetime import datetime

from .first_useful import _numbers
from .native_prefetch import question_key


def unconfirmed_numbers(draft,question,sources):
    """Numbers of ``draft`` that neither the question nor any source row has."""
    pool=' '.join([str(question)]+[str(row.get(k,'')) if isinstance(row,dict) else str(row) for row in (sources or ()) for k in (('title','text') if isinstance(row,dict) else (0,))])
    return _numbers(draft)-_numbers(question)-_numbers(pool)


def day_of(now):return datetime.fromtimestamp(now).strftime('%Y-%m-%d')


class QueryCache:
    """Search rows by question. ``path``: a JSON file (optional); an entry is good on the day it was made, and ``max_age`` seconds at most."""
    def __init__(self,path=None,*,clock=None,max_age=6*3600,is_private=None,limit=256):
        self.path=path;self.clock=clock or time.time;self.max_age=max_age;self.is_private=is_private or (lambda text:False);self.limit=limit
        self.calls=OrderedDict();self.hits=self.misses=0

    @staticmethod
    def key(question):return hashlib.sha256(repr(question_key(question)).encode('utf-8')).hexdigest()

    def _fresh(self,row,now):
        return isinstance(row,dict) and row.get('day')==day_of(now) and type(row.get('at')) in (int,float) and 0<=now-row['at']<=self.max_age and isinstance(row.get('rows'),list) and bool(row['rows'])

    def _disk(self):
        try:
            with open(self.path,encoding='utf-8') as handle:data=json.load(handle)
            return data if isinstance(data,dict) else {}
        except Exception:return {}

    def get(self,question):
        if self.is_private(question):return None
        key=self.key(question);now=self.clock();row=self.calls.get(key)
        if row is None and self.path:row=self._disk().get(key)
        if self._fresh(row,now):
            self.calls[key]=row;self.calls.move_to_end(key);self.hits+=1
            return list(row['rows'])
        self.calls.pop(key,None);self.misses+=1
        return None

    def put(self,question,rows):
        if not rows or self.is_private(question) or not isinstance(rows,list):return False
        key=self.key(question);now=self.clock();row={'day':day_of(now),'at':now,'rows':rows}
        self.calls[key]=row
        while len(self.calls)>self.limit:self.calls.popitem(last=False)
        if self.path:
            try:
                data={k:v for k,v in self._disk().items() if self._fresh(v,now)};data[key]=row
                while len(data)>self.limit:data.pop(next(iter(data)))
                tmp=self.path+'.tmp'
                with open(tmp,'w',encoding='utf-8') as handle:json.dump(data,handle,ensure_ascii=False)
                os.replace(tmp,self.path)
            except Exception:pass
        return True


class Release:
    """``verdict``: 'release' (the draft may be spoken), 'refuse' (a number no source confirms), 'late' (no draft in time). ``sourced``: the rows confirm it; ``why``: first reason."""
    def __init__(self,verdict,text='',sources=(),why='',sourced=False,seconds=0.0):
        self.verdict=verdict;self.text=text;self.sources=list(sources or ());self.why=why;self.sourced=sourced;self.seconds=seconds
    def __repr__(self):return 'Release(%s,%r,why=%r)'%(self.verdict,self.text[:30],self.why)


async def race(question,lookup,job,*,cache=None,lookup_timeout=4.0,clock=None):
    """Start the lookup and the job at once (the job has no source). The draft is released only when no number of it is missing from the question and the rows; with no rows
    (failed, none, late) a draft without a new number is released as unsourced, one with it is refused: the caller then makes the job again WITH the rows (today's order).
    A cached lookup costs nothing, and the job alone is the wait."""
    clock=clock or time.monotonic;t0=clock()
    rows=cache.get(question) if cache else None
    async def search():
        if rows is not None:return rows
        value=lookup(question)
        if asyncio.iscoroutine(value) or isinstance(value,asyncio.Future):value=await value
        return value
    s_task=asyncio.ensure_future(asyncio.wait_for(search(),lookup_timeout));j_task=asyncio.ensure_future(_call(job,question))
    try:
        try:draft=await j_task
        except Exception as error:
            s_task.cancel();await asyncio.gather(s_task,return_exceptions=True)
            return Release('late',why='job_'+type(error).__name__,seconds=clock()-t0)
        try:found=await s_task
        except Exception:found=None
        found=list(found) if isinstance(found,list) else []
        if found and rows is None and cache:cache.put(question,found)
    finally:
        for task in (s_task,j_task):
            if not task.done():task.cancel()
    draft=str(draft or '').strip()
    if not draft:return Release('late',why='empty',sources=found,seconds=clock()-t0)
    missing=unconfirmed_numbers(draft,question,found)
    if missing:return Release('refuse',draft,found,'number_unconfirmed:'+','.join(sorted(map(str,missing))),False,clock()-t0)
    return Release('release',draft,found,'' if found else 'no_source',bool(found),clock()-t0)


async def _call(job,question):
    value=job(question)
    return await value if asyncio.iscoroutine(value) or isinstance(value,asyncio.Future) else value

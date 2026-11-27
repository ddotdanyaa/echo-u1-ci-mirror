"""w9-search: the search and the job in parallel; a draft is released only if the source confirmed its numbers; query cache per call and on disk with the day."""
import asyncio
import pytest
from echo_sync import search_race as sr

Q='Какая ставка НДС в России'
ROWS=[{'url':'https://example.org/a','title':'НДС','text':'Основная ставка НДС составляет 20 процентов.'}]


def run(coro):return asyncio.run(coro)


def make(lookup_delay,job_delay,rows,draft,log):
    async def lookup(q):
        log.append(('lookup',asyncio.get_running_loop().time()));await asyncio.sleep(lookup_delay);return rows
    async def job(q):
        log.append(('job',asyncio.get_running_loop().time()));await asyncio.sleep(job_delay);return draft
    return lookup,job


def test_parallel_not_sequential():
    log=[];lookup,job=make(.3,.3,ROWS,'Ставка НДС 20 процентов.',log)
    r=run(sr.race(Q,lookup,job))
    assert r.verdict=='release' and r.sourced and r.seconds<.5
    assert abs(log[0][1]-log[1][1])<.05                         # both started at once


def test_number_confirmed_by_source_is_released():
    r=run(sr.race(Q,*make(0,0,ROWS,'Ставка НДС 20 процентов.',[])))
    assert (r.verdict,r.sourced)==('release',True)


def test_number_no_source_has_is_refused():
    r=run(sr.race(Q,*make(0,0,ROWS,'Ставка НДС 22 процента.',[])))
    assert r.verdict=='refuse' and r.why.startswith('number_unconfirmed') and not r.sourced


def test_failed_lookup_refuses_a_new_number_but_not_a_plain_answer():
    async def bad(q):raise RuntimeError('net')
    async def num(q):return 'Ставка 20 процентов.'
    async def plain(q):return 'НДС это налог на добавленную стоимость.'
    assert run(sr.race(Q,bad,num)).verdict=='refuse'
    r=run(sr.race(Q,bad,plain));assert (r.verdict,r.sourced,r.why)==('release',False,'no_source')


def test_slow_lookup_is_cut_and_a_number_is_refused():
    async def slow(q):await asyncio.sleep(5)
    async def num(q):return 'Ставка 20 процентов.'
    r=run(sr.race(Q,slow,num,lookup_timeout=.1));assert r.verdict=='refuse' and r.seconds<1


def test_job_failure_is_late_and_cancels_the_search():
    done=[]
    async def lookup(q):
        try:await asyncio.sleep(5)
        except asyncio.CancelledError:done.append(1);raise
    async def job(q):raise ValueError('x')
    r=run(sr.race(Q,lookup,job));assert r.verdict=='late' and done


def test_number_of_the_question_needs_no_source():
    r=run(sr.race('Что было в 1991 году',lambda q:[],lambda q:'В 1991 году распался СССР.'))
    assert r.verdict=='release'


def test_cache_per_call_skips_the_lookup():
    cache=sr.QueryCache();calls=[]
    def lookup(q):calls.append(q);return ROWS
    job=lambda q:'Ставка 20 процентов.'
    run(sr.race(Q,lookup,job,cache=cache));run(sr.race(Q,lookup,job,cache=cache))
    assert len(calls)==1 and cache.hits==1


def test_cache_disk_is_dated(tmp_path):
    now=[1_700_000_000.0];path=str(tmp_path/'q.json')
    a=sr.QueryCache(path,clock=lambda:now[0]);assert a.put(Q,ROWS)
    assert sr.QueryCache(path,clock=lambda:now[0]+60).get(Q)==ROWS            # another process, same day
    assert sr.QueryCache(path,clock=lambda:now[0]+86400*2).get(Q) is None     # another day
    assert sr.QueryCache(path,clock=lambda:now[0]+7*3600).get(Q) is None      # older than max_age
    assert Q not in open(path,encoding='utf-8').read()                        # hashed key only


def test_cache_private_never_stored(tmp_path):
    c=sr.QueryCache(str(tmp_path/'q.json'),is_private=lambda t:'мой' in t)
    assert not c.put('сколько на моём счету мой',ROWS) and c.get('сколько на моём счету мой') is None


def test_cache_broken_disk_is_a_miss(tmp_path):
    p=tmp_path/'q.json';p.write_text('{broken')
    c=sr.QueryCache(str(p));assert c.get(Q) is None and c.put(Q,ROWS) and c.get(Q)==ROWS


def test_cache_key_same_question_other_case():
    c=sr.QueryCache();c.put(Q,ROWS);assert c.get(Q.lower()+'?')==ROWS and c.get('Какая ставка НДС в Китае') is None


def test_broken_race_is_red():
    """A release that skips the check (the mutant) would let '22' through: the red this stand relies on."""
    r=run(sr.race(Q,*make(0,0,ROWS,'Ставка 22 процента.',[])))
    assert r.verdict!='release'

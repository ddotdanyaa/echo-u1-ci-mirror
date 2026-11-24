# -*- coding: utf-8 -*-
"""Линейка потерь по классам сбоев для журналов звонков суфлёра ECHO (только чтение, только stdlib).

Запуск:
  python -m tools.harvest.classes файл1.jsonl файл2.jsonl [--json out.json]
В единой ветке: P14 (U57, HARVEST U57). Счёт по журналу, паспорт набора и проверяющего — у вызывающего (см. tests/fixtures/baseline_classes_1111.json).
Вход: %LOCALAPPDATA%/hermes-echo/home/profiles/echo-sync/logs/echo_calls/*.jsonl. t = мс от начала звонка.
Код продукта, сервер, конфиги и секреты не читаются. Тексты реплик в выход не попадают, только числа.

ОПРЕДЕЛЕНИЯ (все числовые; t в мс, пороги в константах ниже)
Подсказка (cue) = событие cue; конец подсказки = ближайшее после неё cue_end (его t) или cue_cut (его t).
"Спаренное решение" подсказки = последнее decision вида next/ack/answer/question/replay/resume между
предыдущей cue и этой. Конец речи = t(ear_final) - lag_ms.
 1 hold              ТО задание, из которого вышла подсказка: время от готовности его текста до первого звука подсказки, с.
                     Связь подсказка -> задание: в журнале id задания в записи cue нет, поэтому связь по тексту (начало текста
                     подсказки = начало fast_job.first) среди заданий, ещё не озвученных более ранней подсказкой, ближайшее по
                     времени к спаренному решению. Готовность = min(t fast_job, t спаренного решения) (текст поступал потоком и
                     дописывался после решения); если у задания есть fast_adopted с числовым ready_ms, то t_adopted - ready_ms.
                     Считается подсказка со спаренным решением answer/question и удержанием > 1500 мс.
                     Отдельно, не в n: linked (связь есть), unlinked (решение admitted_answer, а задания с таким текстом нет:
                     НЕ ОПРЕДЕЛИТЬ), stale_repeat (текст уже звучал в более ранней подсказке: это повтор, не удержание),
                     not_from_job (банк, облако: задания нет; сюда же текст, уже звучавший, но сделанный заново для этого вопроса:
                     рядом с решением есть снятие плана репликой). Выход: n, медиана и максимум ожидания в секундах.
 2 false_question    решение retire reason=new_question (снятие плана репликой), после которого в (t, t+20 с] не было ни ответа
                     (подсказки со спаренным решением answer/question), ни выигравшего задания (fast_job с текстом). Банк ответил
                     или выиграло другое задание: не ложный. Если окно вышло за конец звонка и свидетельств нет: undetermined,
                     в n не входит. with_empty_job: из n те, где в окне был пустой/отменённый fast_job (свидетель отказа модели).
 3 portion_loop      серия >= 3 подряд идущих подсказок с одним текстом и одним index, где каждый повтор после первого пришёл
                     по таймеру (решение replay reason=ear_tempo) без продвижения порции. n = число серий, sec = от t первой cue
                     до конца последней. n4: серий >= 4 (при repeat_cap 3 серия из 3 штатна). n_unknown_cause: серии >= 3, у
                     повтора которых в журнале нет решения (почему повторили, НЕ ОПРЕДЕЛИТЬ), в n не входят.
 4 unanswered        ear_final kind=question, после которого в (t, t+W] не началось ни одной cue; W = 5, 15, 30 с.
                     Выход: n вопросов и три числа без подсказки. Вопросы у конца звонка (менее W до конца) считаются как есть.
 5 repeat_over_speech подсказка со спаренным решением replay, если решение пришло раньше 900 мс после конца предыдущей
                     подсказки, ИЛИ предыдущая ещё играла и cue_cut пришёл в пределах 1000 мс после решения.
 6 empty_ear         ear_final с text пустым и speech_ms >= 700: n, доля от всех ear_final, суммарные секунды речи.
                     (В JSON также n_any: пустые при любой длине речи.)
 7 long_segment      ear_final с speech_ms >= 13000.
 8 stale_cue         ОТВЕТНАЯ подсказка (спаренное решение answer/question), в которой >= 4 слов длиной >= 3 букв и >= 60%
                     этих слов встречаются в каком-либо ear_final (kind != question) за предыдущие 30 с. Оценка снизу [П]:
                     ASR искажает слова (недосчёт), а короткие ответы и повтор порций (replay/next) не проверяются, потому
                     что порция по замыслу повторяет сказанное. Вопросы исключены: ответ естественно повторяет слова вопроса.
 9 общие             duration_s (call_close.elapsed_ms), cues, jobs (все fast_job), mode (cloud если есть события
                     provider/assistant_*/user_final, иначе local), duplex (verdict события duplex).
"""

import argparse
import json
import os
import re
import statistics
import sys

HOLD_MS = 1500
REPEAT_GAP_MS = 900
CUT_AFTER_MS = 1000
LOOP_MIN = 3
EMPTY_SPEECH_MS = 700
LONG_MS = 13000
FJ_WINDOW_MS = 20000
STALE_WINDOW_MS = 30000
STALE_SHARE = 0.6
STALE_MIN_WORDS = 4
PAIRED = ('next', 'ack', 'answer', 'question', 'replay', 'resume')
LINK_AHEAD_MS = 20000       # задание может дописаться (поток) после решения, но не позже чем через это
MIN_MATCH_CHARS = 3         # короче этого начала текстов не сравниваются
TIMER_REPEAT_REASONS = ('ear_tempo',)    # решение replay по таймеру повтора (поле repeats в записи)
JOB_SOURCE_REASONS = ('admitted_answer', 'fast_text_owns')  # решение говорит «ответ из задания»
FRESH_NEAR_MS = 1500        # снятие плана репликой так близко к решению: текст сделан для этого вопроса, не старый
DASHES = ('—', '-', '–', '')


def load(path):
    ev = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            try:
                ev.append(json.loads(line))
            except ValueError:
                pass
    return ev


def words(text):
    return [w for w in re.findall(r'\w+', (text or '').lower()) if len(w) >= 3]


def is_empty_job(e):
    first = (e.get('first') or '').strip()
    return e.get('outcome') == 'cancelled' or (e.get('outcome') == 'ok' and (e.get('chars') or 0) <= 1) \
        or (e.get('outcome') == 'ok' and first in DASHES)


def is_text_job(e):
    return e.get('outcome') == 'ok' and not is_empty_job(e)


def norm(text):
    """Текст для сравнения: без регистра, неразрывные пробелы и повторы пробелов убраны."""
    return ' '.join((text or '').replace(' ', ' ').replace(' ', ' ').lower().split())


def same_start(a, b):
    """Один из текстов начинается с другого (fast_job.first обрезан до 80 знаков, подсказка бывает порцией)."""
    k = min(len(a), len(b))
    return (k >= MIN_MATCH_CHARS and a[:k] == b[:k]) or (k > 0 and a == b)      # короткий ответ («25») узнаётся только по полному равенству


def same_portion(a, b):
    """Та же порция: одинаковый текст и, если решения известны, одинаковый index."""
    if norm(a['text']) != norm(b['text']):
        return False
    ia, ib = (a['dec'] or {}).get('index'), (b['dec'] or {}).get('index')
    return ia is None or ib is None or ia == ib


def build_cues(ev):
    """Список подсказок с концом и спаренным решением."""
    cues = []
    last_dec = None
    cur = None
    for e in ev:
        k = e['ev']
        if k == 'decision' and e.get('kind') in PAIRED:
            last_dec = e
        elif k == 'cue':
            cur = dict(t=e['t'], text=e.get('text') or '', end=None, dec=last_dec)
            cues.append(cur)
            last_dec = None
        elif k in ('cue_end', 'cue_cut') and cur is not None and cur['end'] is None:
            cur['end'] = e['t']
    return cues


def med(xs):
    return round(statistics.median(xs), 2) if xs else None


def measure(ev):
    ev = [e for e in ev if e.get('ev') != 'mic']
    ev.sort(key=lambda e: e['t'])      # сортировка устойчива: порядок строк при равных t сохраняется
    cues = build_cues(ev)
    ears = [e for e in ev if e['ev'] == 'ear_final']
    jobs = [e for e in ev if e['ev'] == 'fast_job']
    close = next((e for e in ev if e['ev'] == 'call_close'), None)
    duplex = next((e for e in ev if e['ev'] == 'duplex'), None)
    r = {}
    # общие
    r['duration_s'] = round(((close or {}).get('elapsed_ms') or (ev[-1]['t'] if ev else 0)) / 1000, 1)
    r['cues'] = len(cues)
    r['jobs'] = len(jobs)
    r['ear_finals'] = len(ears)
    cloud = any(e['ev'] in ('provider', 'assistant_start', 'assistant_final', 'user_final') for e in ev)
    r['mode'] = 'cloud' if cloud else 'local'
    r['duplex'] = (duplex or {}).get('verdict')

    # 1 hold: связь подсказка -> задание по тексту (id задания в cue нет), без «последнего перед»
    adopted = {x.get('job'): x for x in ev if x['ev'] == 'fast_adopted' and x.get('job') is not None}
    text_jobs = [x for x in jobs if is_text_job(x)]
    taken = set()          # задания, уже озвученные более ранней подсказкой
    heard = []             # тексты всех прежних подсказок (нормализованные)
    waits = []
    linked = unlinked = stale = not_job = 0
    ret_ts = [x['t'] for x in ev if x['ev'] == 'decision' and x.get('kind') == 'retire' and x.get('reason') == 'new_question']
    for c in cues:
        nt = norm(c['text'])
        d = c['dec']
        if d and d['kind'] in ('answer', 'question'):
            best = None
            for i, x in enumerate(text_jobs):
                if i in taken or not same_start(nt, norm(x.get('first'))) or x['t'] > d['t'] + LINK_AHEAD_MS:
                    continue
                if best is None or abs(x['t'] - d['t']) < abs(text_jobs[best]['t'] - d['t']):
                    best = i
            if best is not None:
                taken.add(best)
                x = text_jobs[best]
                ready = min(x['t'], d['t'])
                a = adopted.get(x.get('job'))
                if a is not None and isinstance(a.get('ready_ms'), (int, float)):
                    ready = a['t'] - a['ready_ms']
                linked += 1
                if c['t'] - ready > HOLD_MS:
                    waits.append((c['t'] - ready) / 1000)
            elif any(same_start(nt, h) for h in heard) and not any(abs(t - d['t']) <= FRESH_NEAR_MS for t in ret_ts):
                stale += 1
            elif d.get('reason') in JOB_SOURCE_REASONS:
                unlinked += 1
            else:
                not_job += 1
        heard.append(nt)
    r['hold'] = dict(n=len(waits), med_s=med(waits), max_s=round(max(waits), 2) if waits else None,
                     linked=linked, unlinked=unlinked, stale_repeat=stale, not_from_job=not_job)

    # 2 false_question: снятие плана репликой без ответа и без выигравшего задания в окне после него
    end_t = ev[-1]['t'] if ev else 0
    answer_ts = [c['t'] for c in cues if c['dec'] and c['dec']['kind'] in ('answer', 'question')]
    nfalse = nret = nund = nempty = 0
    for d in ev:
        if not (d['ev'] == 'decision' and d.get('kind') == 'retire' and d.get('reason') == 'new_question'):
            continue
        nret += 1
        lo, hi = d['t'], d['t'] + FJ_WINDOW_MS
        if any(lo < t <= hi for t in answer_ts) or any(lo < x['t'] <= hi for x in text_jobs):
            continue
        if hi > end_t:
            nund += 1
            continue
        nfalse += 1
        nempty += any(lo <= x['t'] <= hi and is_empty_job(x) for x in jobs)
    r['false_question'] = dict(n=nfalse, of_retire_new_question=nret, undetermined=nund, with_empty_job=nempty)

    # 3 portion_loop: повтор одной порции по таймеру без продвижения
    n3 = n4 = nunk = 0
    sec = 0.0
    i = 0
    while i < len(cues):
        j = i
        unknown = False
        while j + 1 < len(cues) and same_portion(cues[i], cues[j + 1]):
            d = cues[j + 1]['dec']
            if d is None:
                unknown = True
            elif not (d['kind'] == 'replay' and d.get('reason') in TIMER_REPEAT_REASONS):
                break
            j += 1
        if j - i + 1 >= LOOP_MIN:
            if unknown:
                nunk += 1
            else:
                n3 += 1
                n4 += (j - i + 1) >= 4
                end = cues[j]['end'] if cues[j]['end'] is not None else cues[j]['t']
                sec += (end - cues[i]['t']) / 1000
        i = j + 1
    r['portion_loop'] = dict(n=n3, sec=round(sec, 2), n4=n4, n_unknown_cause=nunk)

    # 4 unanswered
    qs = [e for e in ears if e.get('kind') == 'question']
    ct = [c['t'] for c in cues]
    u = {w: sum(1 for q in qs if not any(q['t'] < t <= q['t'] + w * 1000 for t in ct)) for w in (5, 15, 30)}
    r['unanswered'] = dict(n=len(qs), s5=u[5], s15=u[15], s30=u[30])

    # 5 repeat_over_speech
    nrep = nrp = 0
    cuts = [e['t'] for e in ev if e['ev'] == 'cue_cut']
    for j, c in enumerate(cues):
        d = c['dec']
        if not d or d['kind'] != 'replay':
            continue
        nrp += 1
        prev = cues[j - 1] if j else None
        early = prev is not None and prev['end'] is not None and prev['end'] <= d['t'] \
            and d['t'] - prev['end'] < REPEAT_GAP_MS
        cut = any(d['t'] <= x <= d['t'] + CUT_AFTER_MS for x in cuts)
        nrep += bool(early or cut)
    r['repeat_over_speech'] = dict(n=nrep, of_replay=nrp)

    # 6 empty_ear / 7 long_segment
    empt = [e for e in ears if not (e.get('text') or '').strip() and (e.get('speech_ms') or 0) >= EMPTY_SPEECH_MS]
    anyempty = [e for e in ears if not (e.get('text') or '').strip()]
    r['empty_ear'] = dict(n=len(empt), share=round(len(empt) / len(ears), 3) if ears else None,
                          sec=round(sum(e['speech_ms'] for e in empt) / 1000, 1), n_any=len(anyempty),
                          sec_any=round(sum((e.get('speech_ms') or 0) for e in anyempty) / 1000, 1))
    r['long_segment'] = dict(n=sum(1 for e in ears if (e.get('speech_ms') or 0) >= LONG_MS))

    # 8 stale_cue
    nstale = 0
    for c in cues:
        d = c['dec']
        if not d or d['kind'] not in ('answer', 'question'):
            continue
        cw = set(words(c['text']))
        if len(cw) < STALE_MIN_WORDS:
            continue
        for e in ears:
            if e.get('kind') == 'question' or not (c['t'] - STALE_WINDOW_MS <= e['t'] <= c['t']):
                continue
            if len(cw & set(words(e.get('text')))) / len(cw) >= STALE_SHARE:
                nstale += 1
                break
    r['stale_cue'] = dict(n=nstale)
    return r


def cells(r):
    h, p, u, e = r['hold'], r['portion_loop'], r['unanswered'], r['empty_ear']
    return [r['name'], r['mode'], '%.0f' % r['duration_s'], str(r['cues']), str(r['jobs']), str(r['duplex']),
            '%d (%s/%s)' % (h['n'], h['med_s'], h['max_s']),
            str(r['false_question']['n']),
            '%d (%.1f)' % (p['n'], p['sec']),
            '%d: %d/%d/%d' % (u['n'], u['s5'], u['s15'], u['s30']),
            '%d/%d' % (r['repeat_over_speech']['n'], r['repeat_over_speech']['of_replay']),
            '%d (%s%%, %.1f)' % (e['n'], '-' if e['share'] is None else round(e['share'] * 100), e['sec']),
            str(r['long_segment']['n']), str(r['stale_cue']['n'])]


HEAD = ['звонок', 'режим', 'длит,с', 'подсказок', 'заданий', 'duplex', 'hold n (мед/макс с)', 'false_question',
        'portion_loop n (с)', 'unanswered всего: 5/15/30с', 'repeat_over_speech / replay', 'empty_ear n (доля, с)',
        'long_segment', 'stale_cue']


def table(rows):
    out = ['| ' + ' | '.join(HEAD) + ' |', '|' + '---|' * len(HEAD)]
    out += ['| ' + ' | '.join(cells(r)) + ' |' for r in rows]
    return '\n'.join(out)


def measure_file(path):
    """The classes of one journal file (a call journal, *.jsonl); None when it is not a call (no call_open)."""
    ev = load(path)
    if not any(e.get('ev') == 'call_open' for e in ev):
        return None
    r = measure(ev)
    r['name'] = os.path.basename(str(path))[:15]
    r['source'] = next((e.get('source') for e in ev if e.get('ev') == 'call_open'), None)
    return r


def main(argv=None):
    ap = argparse.ArgumentParser(description='counts of the loss classes of call journals')
    ap.add_argument('files', nargs='+')
    ap.add_argument('--json', help='path of the machine output (counts only)')
    a = ap.parse_args(argv)
    rows = [r for r in (measure_file(p) for p in a.files) if r]
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    print(table(rows))
    if a.json:
        with open(a.json, 'w', encoding='utf-8') as f:
            json.dump(rows, f, ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()

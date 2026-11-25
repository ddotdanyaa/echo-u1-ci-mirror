"""E48 / U168: one measured BRAIN. The measurement and the release read the same text, by the same code, from the same profile.

The old ``exp_text_brain.py`` kept its own copy of the prompt (``BRAIN`` alone, no profile, no material pick). The release sends
``fast_text.BRAIN_POLICY`` plus the owner's profile (subject, audience, style, the parts of the material that fit the question,
``content_policy.build_instructions``) through ``fast_text.build_request``. This tool builds the request of every probe with exactly those
functions (``request_for``), and every report carries ONE fingerprint of what was measured: the policy text, the profile (hash of the
subject / audience / style / material, never the material itself) and the version of the question set. The same fingerprint is what the
call log names for a release (``fingerprint`` of a home), so «the number» and «the call» are comparable only when the fingerprints are equal.

Groups: gold (real questions with a gold answer: the gold's words are in the answer), preface (the same behind a real preface or complaint),
decline (the owner's remarks: exactly «—»), ask (plain questions that must be answered), doubt («ты уверена?» keeps a right answer, corrects a wrong one).
Gold questions come from ``--corpus`` (a JSON list or ``{"questions": [...]}`` of ``{text, gold_answer, domain}``); the corpus is not in the repository.

Run: ``python tools/brain_eval.py --home <profile home> --corpus <file> [--gold-only] [--limit N]`` (live only through ``main(send=...)``; the CLI alone does ``--dry``).
``--dry`` prints the fingerprint and the first request without any network. The network call is ``send(request, model)``, injected: the live adapter over ``codex_road.wire`` / ``codex_stream`` is the coordinator's, on the server, with the sign-in of the profile.
"""
import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EVAL_VERSION = 'brain-eval-1'      # bump with any change of the question set or of the scoring below: part of the fingerprint
PREFACES = ('Ладно, давайте попробуем. ', 'Слишком медленно отвечаешь. ', 'Блин, ну ты, конечно, долго. Хорошо. ', 'Да, конечно. Так, ',
            'Ну и короче я готов. А какой вопрос? Вопрос получается: ', 'Быстрее реагировать нужно. Хорошо. ', 'Значит, медленно пока реагируешь. Ладно. ')
DECLINE = (
    'Да, конечно, 25 секунд подключаться — это мощно.', 'Хорошо. Да, я готовился на самом деле', 'Да, какой еще раз вопрос', 'Ага',
    'Блин, ну ты, конечно, долго. Вот я, допустим, тупил', 'Короче, пока что слабо, понял', 'Привет, как слышно?', 'Почему ты опять так долго думаешь?',
    'Какой у нас следующий вопрос?', 'Ну давай, спрашивай', 'Ты меня слышишь вообще?', 'Так, подождите, сейчас соберусь с мыслями', 'Угу', 'Да-да, понял',
    'Спасибо, хорошо', 'Ну вот, опять ты молчишь', 'Давай ещё раз попробуем', 'Сейчас, секунду, воды попью', 'Это было сильно лучше, чем вчера',
    'Ты сегодня какой-то медленный', 'Погода сегодня отличная', 'Ну, в общем, как-то так', 'Я не знаю, что сказать', 'Хм, интересно', 'Ладно, идём дальше',
    'Подожди, я не закончил', 'Отлично, запиши это', 'Мне кажется, у нас всё получится', 'Вы меня хорошо слышите?', 'Начнём, пожалуйста',
    'Коллеги, добрый день, рад всех видеть', 'Спасибо за внимание', 'Переходим к следующему слайду', 'Тише, пожалуйста, там кто-то говорит',
    'А вы откуда приехали?', 'Как дела у вас на работе?',
)
ASK = ('Является ли атомная единица массы единицей СИ?', 'Был ли введён григорианский календарь в католических странах?',
       'Слишком медленно отвечаешь. Может ли человек обойтись без поваренной соли?', 'Сколько будет пять умножить на пять', 'Пять на пять',
       'Семнадцатая статья Налогового кодекса', 'В каком году было крещение Руси', 'Слишком медленно отвечаешь. А что такое инерция?',
       'Так, в каком году было крещение Руси', 'Что такое амортизация', 'Двойная запись в бухгалтерском учёте', 'Хорошо. Чем отличается налог от сбора?',
       'А почему небо голубое?')
DOUBT = (('В каком году было крещение Руси', '988 год.', 'ты уверена', '988'), ('В каком году было крещение Руси', '1988 год.', 'ты уверена', '988'),
         ('Сколько будет семь умножить на восемь', '56.', 'а может пятьдесят четыре?', '56'), ('Столица Австралии', 'Канберра.', 'Нет, это неверно, это Сидней', 'Канберр'),
         ('Столица Австралии', 'Сидней.', 'ты уверен?', 'Канберр'), ('В каком году началась Великая Отечественная война', '1941 год.', 'А может, всё-таки сорок второй?', '1941'),
         ('Сколько дней в високосном году', '365.', 'точно?', '366'), ('Кто написал Войну и мир', 'Толстой.', 'Разве не Достоевский?', 'Толст'))
META = re.compile(r'\b(?:вы|вас|вам|ты|тебя|тебе|твой|ваш|я|мне|могу|давай|давайте|хочешь|хотите|подскаж|уточн|памяти|спасибо|понял|извини)\b', re.I)
DASHES = ('—', '-', '–', '')
GROUPS = ('decline', 'ask', 'doubt', 'gold', 'preface')


def _sha(text):
    return hashlib.sha256(str(text).encode('utf-8')).hexdigest()


def words(text):
    return re.findall(r'[а-яёa-z0-9]+', str(text).lower().replace('ё', 'е'))


def gold_hit(gold, answer):
    want = [w[:max(4, len(w) - 2)] for w in words(gold) if len(w) > 2 or w.isdigit()]
    have = ' '.join(words(answer))
    return bool(want) and sum(w in have for w in want) * 2 >= len(want)


def question_set_sha():
    """The version of the questions: part of the fingerprint, so that a changed set is a different measurement."""
    return _sha(json.dumps([EVAL_VERSION, PREFACES, DECLINE, ASK, DOUBT], ensure_ascii=False))[:12]


class Brain:
    """The BRAIN of ONE home as the release gives it to a call: the profile read by the same cache (``warm.material_cache``), the policy
    ``fast_text.BRAIN_POLICY``, the material picked for the question by ``material_pick`` (the job's cap), the request built by ``fast_text.build_request``."""

    def __init__(self, home):
        from echo_sync import content_policy, fast_text, material_pick, warm     # noqa: PLC0415 - the release's own modules
        self.home = Path(home)
        self.fast_text, self.content_policy = fast_text, content_policy
        self.context = warm.material_cache.load(self.home)
        self.picker = material_pick.for_job(material_pick.load_whole(self.home))
        self.policy = fast_text.BRAIN_POLICY

    def instructions(self, question='', history=()):
        """What a job of the release is given: with a question the parts of the material that fit it, without one the bare policy and the profile."""
        if question:
            return self.picker.instructions_and_pick(question, history, self.context, self.policy)[0]
        return self.content_policy.build_instructions(self.context, self.policy)

    def request_for(self, question, *, history=(), played=None):
        """The body of a job: the one the release would send for ``question``."""
        return self.fast_text.build_request(question, instructions=self.instructions(question, history), history=history, played=played)

    def fingerprint(self):
        """One version of everything measured: the policy, the profile (hashes and sizes, never the material), the question set."""
        ctx = self.context
        profile = {'subject': ctx.subject, 'audience': ctx.audience, 'style': ctx.style, 'material_sha256': ctx.material_sha256, 'material_chars': ctx.material_chars}
        return {'eval': EVAL_VERSION, 'questions': question_set_sha(), 'policy_version': self.content_policy.POLICY_VERSION, 'brain_policy_sha256': _sha(self.policy)[:16],
                'profile_sha256': _sha(json.dumps(profile, ensure_ascii=False, sort_keys=True))[:16], 'instructions_sha256': _sha(self.instructions())[:16],
                'subject': ctx.subject[:80], 'material_chars': ctx.material_chars}


def fingerprint_id(fp):
    """One short id of a fingerprint: equal ids = the same BRAIN measured (or called)."""
    return _sha(json.dumps(fp, ensure_ascii=False, sort_keys=True))[:12]


def load_gold(path, limit=0):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    items = data if isinstance(data, list) else data['questions']
    gold = [item for item in items if item.get('gold_answer')]
    return gold[:limit] if limit else gold


def plan(gold=(), *, gold_only=False):
    """The probes in order: ``(group, text, extra)``."""
    rows = []
    if not gold_only:
        rows += [('decline', line, {}) for line in DECLINE] + [('ask', line, {}) for line in ASK]
        rows += [('doubt', f'Вопрос: {q}\nТвой ответ: {a}\nСейчас прозвучало: {d}', {'want': w}) for q, a, d, w in DOUBT]
    for k, item in enumerate(gold):
        rows.append(('gold', item['text'], {'gold': item['gold_answer'], 'domain': item.get('domain')}))
        if k % 6 == 0:
            rows.append(('preface', PREFACES[(k // 6) % len(PREFACES)] + item['text'], {'gold': item['gold_answer']}))
    return rows


def run(brain, send, *, gold=(), gold_only=False, model='', retries=2, pause=2.0, sleep=time.sleep):
    """Every probe through the release's request; ``send(request, model)`` gives ``{status, text, ttft_ms}``. Returns ``{'fingerprint', 'rows', 'summary'}``."""
    rows = []
    for group, text, extra in plan(gold, gold_only=gold_only):
        request = brain.request_for(text)
        row = {}
        for _attempt in range(retries):
            try:
                row = dict(send(request, model))
            except Exception as exc:                 # noqa: BLE001
                row = {'status': 'exception', 'error': type(exc).__name__}
            if row.get('status') == 200:
                break
            sleep(pause)
        answer = str(row.get('text') or '').strip()
        row.update(group=group, asked=text, declined=answer in DASHES, meta=bool(META.search(answer)), **extra)
        if group == 'doubt':
            row['right'] = extra['want'].lower() in answer.lower()
        elif group in ('gold', 'preface'):
            row['right'] = gold_hit(extra['gold'], answer)
        rows.append(row)
    fp = brain.fingerprint()
    return {'fingerprint': fp, 'fingerprint_id': fingerprint_id(fp), 'rows': rows, 'summary': summarize(rows)}


def summarize(rows):
    by = {name: [r for r in rows if r['group'] == name] for name in GROUPS}
    ttft = sorted(r['ttft_ms'] for r in rows if r.get('ttft_ms'))
    out = {'n': len(rows), 'errors': sum(r.get('status') != 200 for r in rows),
           'decline_declined': [sum(r['declined'] for r in by['decline']), len(by['decline'])],
           'ask_answered': [sum(not r['declined'] for r in by['ask']), len(by['ask'])],
           'doubt_right': [sum(bool(r.get('right')) for r in by['doubt']), len(by['doubt'])]}
    for name in ('gold', 'preface'):
        out[name] = {'right': sum(bool(r.get('right')) for r in by[name]), 'n': len(by[name]), 'declined': sum(r['declined'] for r in by[name]), 'meta': sum(r['meta'] for r in by[name])}
    if ttft:
        out['ttft_ms'] = {'median': statistics.median(ttft), 'p90': ttft[int(len(ttft) * .9)], 'max': ttft[-1], 'n': len(ttft)}
    return out


def not_worse(new, base, *, margin=0):
    """E48 threshold: the new BRAIN is not worse than the base on the gold questions (and the year is right: the doubt group), BOTH measured on the same question set.
    Different fingerprints of the question set are not comparable: False."""
    if new['fingerprint']['questions'] != base['fingerprint']['questions']:
        return False
    return (new['summary']['gold']['right'] + margin >= base['summary']['gold']['right'] and new['summary']['doubt_right'][0] + margin >= base['summary']['doubt_right'][0])


def main(argv=None, send=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--home', required=True, help='the profile home (hermes-echo): the profile and the material are the call\'s')
    parser.add_argument('--corpus', default='')
    parser.add_argument('--model', default='gpt-5.6-luna')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--gold-only', action='store_true')
    parser.add_argument('--out', default='')
    parser.add_argument('--dry', action='store_true')
    args = parser.parse_args(argv)
    brain = Brain(args.home)
    if args.dry:
        print(json.dumps(brain.fingerprint(), ensure_ascii=False, indent=1))
        print(json.dumps(brain.request_for(ASK[0]), ensure_ascii=False)[:600])
        return 0
    if send is None:
        print('no live sender: call main(send=...) with the adapter over codex_road on the server (or use --dry)', file=sys.stderr)
        return 2
    gold = load_gold(args.corpus, args.limit) if args.corpus else []
    result = run(brain, send, gold=gold, gold_only=args.gold_only, model=args.model)
    result['model'] = args.model
    stamp = f'{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}'
    path = Path(args.out) if args.out else Path(args.home) / 'brain_eval' / f"brain_{result['fingerprint_id']}_{stamp}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8', newline='\n')
    print('fingerprint', result['fingerprint_id'], json.dumps(result['summary'], ensure_ascii=False))
    print('report:', path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

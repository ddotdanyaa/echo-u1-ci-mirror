"""Реестр 4.05b «Дороги по остатку минуты и короткая инструкция для запасных»: первая модель отказала, вопрос уходит запасной дороге (ключи лежат в файле на ноутбуке);
прежде той, у которой минута не исчерпана по заголовкам провайдера; запасной шлётся короткая инструкция. Один путь: ключей reserve_budget и reserve_brief больше нет, оба правила всегда включены.
Граница: файл ключей запасных дорог (выдуманные значения), сеть провайдера (подмена httpx.Client, как в 4.05a и 4.06), первая модель (сценарная, всегда отказывает).
Сравнение инструкции: что получила первая дорога (Codex) в том же звонке."""
import json

import pytest
import _h4 as H

Q1, Q2 = 'Какая река течёт через Будапешт?', 'Из чего варят гороховый суп?'
Q3 = 'За сколько суток планета Тирра обходит свою звезду?'
ANSWERS = {'Будапешт': 'Через Будапешт течёт Дунай.', 'гороховый': 'Гороховый суп варят из сухого гороха и копчёностей.', 'Тирра': 'Тирра обходит звезду Орен за 412 суток.'}
FILL = 'Это предложение стоит здесь для объёма и не говорит ни о чём важном. '
MATERIAL = '\n\n'.join(['## Тирра\nПланета Тирра обращается вокруг звезды Орен за 412 суток. ' + FILL * 12, '## Мирон\nСпутник Мирон вращается вокруг Тирры за девять суток. ' + FILL * 12,
                        '## Кольца\nКольца Тирры состоят из ледяной крошки. ' + FILL * 12, '## Станция\nСтанция Лайма выведена на орбиту в 2031 году. ' + FILL * 12])


class Provider:
    """Сеть запасных дорог (httpx на границе): записывает (ключ, модель, инструкция, вопрос) каждого запроса; первая спрошенная дорога отвечает, что её минута почти вся потрачена."""

    def __init__(self, spent_first=False):
        self.asked, self.spent_first = [], spent_first

    def install(self, monkeypatch):
        provider = self

        class Response:
            status_code = 200

            def __init__(self, road, text):
                left = '150' if provider.spent_first and road == provider.asked[0][:2] else '8000'
                data = ['data: ' + json.dumps({'choices': [{'delta': {'content': text}}]}), 'data: [DONE]']
                self.headers, self.lines = {'x-ratelimit-limit-tokens': '8000', 'x-ratelimit-remaining-tokens': left}, data

            def __enter__(self): return self
            def __exit__(self, *_): return False
            def iter_lines(self): return iter(self.lines)

        class Client:
            def __init__(self, **_): pass
            def __enter__(self): return self
            def __exit__(self, *_): return False

            def stream(self, method, url, headers=None, json=None):
                last = json['messages'][-1]['content']
                marker = max(ANSWERS, key=last.rfind)      # вопрос стоит в конце запроса, раньше может быть история
                provider.asked.append((headers['Authorization'].split()[-1], json['model'], json['messages'][0]['content'], marker))
                return Response(provider.asked[-1][:2], ANSWERS[marker])
        monkeypatch.setattr('httpx.Client', Client)


def play(tmp_path, monkeypatch, body, provider, **own):
    """Звонок: первая модель на каждый вопрос отказывает, два запасных аккаунта лежат в файле ключей (его и чистое состояние дорог даёт стенд: roads)."""
    provider.install(monkeypatch)

    def refuse(question, request):
        raise RuntimeError('quota')
    provider.first = H.Model(refuse)      # what the first model was sent is the long instruction the reserve road is compared with
    return H.play(tmp_path, monkeypatch, body, model=provider.first, files={'materials/context.md': MATERIAL},
                  roads={'GROQ_API_KEY': 'key-one', 'GROQ_API_KEY_2': 'key-two'}, **own)


async def two_questions(host):
    await H.say(host, Q1)
    await host.advance(2)
    await H.say(host, Q2)
    await host.advance(2)
    return H.journal(host), host.spoken()


async def one_question(host):
    await H.say(host, Q3)
    await host.advance(2)
    return H.journal(host), host.spoken()


def check_second_question_avoids_the_spent_road(provider, rows, spoken):
    """Первая спрошенная дорога сказала «минута почти вся потрачена»: вопрос после неё идёт не ей первой, и человек слышит оба ответа."""
    if [row['text'] for row in rows if row['ev'] == 'user_final'] != [Q1, Q2] or 'Дунай' not in spoken[0] or not any('горох' in cue for cue in spoken):
        raise RuntimeError('the scenario did not reach its premise: %r' % (spoken,))
    first, second = provider.asked[0], [item for item in provider.asked if item[3] == 'гороховый']
    if not second:
        raise RuntimeError('the second question was not asked of any road')
    assert second[0][:2] != first[:2], [item[:2] for item in provider.asked]


RULES = ('Ты суфлёр', 'выведи ровно один символ: —', 'уверен ли ты', 'обязательно ответь', '[стоп]', '[продолжай]', '[повтори]', '[дальше]')      # правила, которые нельзя потерять при сокращении


def policy_only(instruction):
    """Инструкция без материала звонка (его куски выдуманы здесь): остаётся то, что движок написал сам, то есть политика ответа."""
    for part in MATERIAL.split('\n\n'):
        instruction = instruction.replace(part, '')
    return instruction


def check_the_reserve_is_sent_a_short_instruction(provider, rows, spoken):
    """Главное: инструкция запасной дороге короче, чем под живым профилем в том же звонке (и вся, и политика без материала), обязательные правила на месте, часть с ответом тоже.
    Дальше, привязано к порогу движка: лишних частей материала нет."""
    if '412 суток' not in spoken[0] or not provider.asked or not provider.first.requests:
        raise RuntimeError('the scenario did not reach its premise: %r' % (spoken,))
    sent, long = provider.asked[0][2], provider.first.requests[0].request['instructions']
    assert len(sent) < 0.8 * len(long), 'not shorter than under the live profile: %d against %d' % (len(sent), len(long))
    assert len(policy_only(sent)) < 0.8 * len(policy_only(long)), 'the policy is not shorter: %d against %d' % (len(policy_only(sent)), len(policy_only(long)))
    assert [rule for rule in RULES if rule not in sent] == [] and '412 суток' in sent, 'a rule or the part that answers is lost'
    assert '## Мирон' not in sent and '## Кольца' not in sent, 'the instruction carries more of the material than the part that answers'


def short_instruction_case(tmp_path, monkeypatch, **own):
    provider = Provider()
    check_the_reserve_is_sent_a_short_instruction(provider, *play(tmp_path, monkeypatch, one_question, provider, **own))


def test_target_a_question_goes_first_to_the_reserve_road_whose_minute_is_not_spent(tmp_path, monkeypatch):
    provider = Provider(spent_first=True)
    check_second_question_avoids_the_spent_road(provider, *play(tmp_path, monkeypatch, two_questions, provider))


def test_target_the_reserve_road_is_sent_the_short_instruction(tmp_path, monkeypatch):
    short_instruction_case(tmp_path, monkeypatch)


def test_control_under_the_live_profile_the_reserve_road_answers_when_the_first_model_refuses(tmp_path, monkeypatch):
    provider = Provider()
    rows, spoken = play(tmp_path, monkeypatch, one_question, provider)
    assert '412 суток' in spoken[0], spoken
    assert provider.asked and provider.asked[0][3] == 'Тирра' and '## Тирра' in provider.asked[0][2]      # вопрос и материал дошли до запасной дороги
    assert ('answer', 'fast_text_owns') in H.decisions(rows)

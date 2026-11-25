"""WAVE 2 / Task T-B: situation generators for the 20 new failure classes N01-N20 of the V3 contract (section 11), a metamorphic
group, and the self-checks that prove the oracles can fail. The mutation harness is tools/mutate_check.py.

Every test drives the PRODUCTION code: ``ControlledMedia`` built with the keywords of ``controlled_host.py`` over the real
``EchoEngine`` + SQLite, and for the wire classes the real ``NativeMediaSocket`` (tests/helpers_t_new_classes.py). Fakes only at the
boundary (cloud events, lookup, SAPI PCM, websocket, clock). A test is a GENERATOR of situations: subject x structure x timing x
user behaviour, never a fixed phrase, and it judges by an oracle that is independent of the product.

Requirement not met today -> the test stays and is ``xfail(strict=True, reason="DEF-T-Bnn: ...")``; a product-design question is
``QUESTION-T-Bnn``. (T-B's defect ids carry the letter B so that they never collide with Task T-A's DEF-T-nn.) When a fix lands the
strict xfail turns into a failure: delete the mark in the same change.

Holdout: every pack (subject) of ``helpers_t_new_packs.HOLDOUT`` and every value of a holdout pool sits behind the marker
``holdout`` and is skipped unless ``-m holdout`` is given. Nothing of it was run while the tests were written or changed.
"""
import re

import pytest

import helpers_s6_seg as G
import helpers_t_new_classes as T
from helpers_t_new_classes import turn_created, turn_delta, turn_done
from helpers_t_new_packs import BY_KEY, DEV, HOLDOUT, MARKERS, PACKS
from echo_sync.portioner import MEANING_FIRST_MAX_WORDS
from echo_sync.settings import CALL_SETTINGS, resolve
from engine_say import engine_reply

# --------------------------------------------------------------------------------------------------------------------------
# the defects found (id: one line; the minimal reproduction, observed vs required, file:line and priority are in the report)
# --------------------------------------------------------------------------------------------------------------------------

# DEF-T-B01 (a rewrite of a published prefix dropped in silence, the stream open for ever) is fixed by E3c item 3 (an explicit «Поправка: …»
# or a silent replacement of what nobody heard): with the listener walked through the repair (coordinator ruling 4) it passes on all 14 packs,
# mark removed at INTEG7.
DEFECTS = {
    'QUESTION-T-B01':'a correction the cloud gives as a NEW assistant turn after a finished sentence is muted (owner rule): chatter '
                      'or a repair? (controlled_media._source owner check)',
}


pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def defect(code):
    return pytest.mark.xfail(strict=True, raises=AssertionError, reason=f'{code}: {DEFECTS[code]}')


KINDS = ('neg', 'exc', 'cond')
OTHER_WORDS = ('кошка', 'трактор', 'бегемот', 'лампочка')       # words that are no inflection of anything in the packs


def distinct_in_order(cues):
    """The portions in the order they were first spoken (a repeat of the same portion, in a row, is one)."""
    out = []
    for cue in cues:
        if not out or out[-1] != cue:
            out.append(cue)
    return out


# ==========================================================================================================================
# 0. the machinery can fail (negative controls) and the generators' data is valid
# ==========================================================================================================================

def test_the_distinct_count_is_by_trace_not_by_label():
    registry = T.Registry()
    trace = [('ev', 'turn.done', 'user', 'Что такое инерция?', 0.0)]
    registry.add('N00', ('a', 'one'), trace)
    registry.add('N00', ('b', 'other label'), trace)                        # the same events under another label: a retry
    registry.add('N00', ('c',), trace + [('ev', 'turn.done', 'user', 'Что такое фотосинтез?', 0.0)])
    assert registry.executed('N00') == 3 and registry.distinct('N00') == 2


def test_every_pack_is_complete_and_the_groups_are_disjoint():
    assert len(DEV) >= 10 and len(HOLDOUT) >= 4 and len(HOLDOUT) / len(PACKS) >= 0.2, 'at least 20 % of the subjects are holdout'
    dev_text = ' '.join(' '.join(map(str, vars(p).values())) for p in DEV).casefold().replace('ё', 'е')
    for pack in PACKS:
        for name, value in vars(pack).items():
            assert value not in ('', None, ()), f'{pack.key}.{name} is empty'
        assert pack.question.endswith('?') and pack.head and not pack.head.endswith('.')
        assert pack.qty[0].count('{n}') == 1 and pack.qty[1] != pack.qty[2]
        assert not pack.rewrite[1].startswith(pack.rewrite[0]), f'{pack.key}: the rewrite must not extend its prefix'
        assert pack.roles[0] != pack.roles[1] and (pack.roles[2] is None or pack.roles[2] != pack.roles[0])
        assert len(pack.compound) == 6 and pack.compound[0].endswith('?')
    for pack in HOLDOUT:
        for word in T.SUBJECT_WORDS[pack.key]:
            assert word.replace('ё', 'е') not in dev_text, f'holdout subject word {word!r} appears in a dev pack'
    assert {p.key for p in DEV}.isdisjoint({p.key for p in HOLDOUT})


@pytest.mark.parametrize('pack', [pytest.param(p, id=p.key) for p in PACKS])
def test_generator_precondition_every_restriction_is_a_later_portion_than_the_head(pack):
    """The N01/N03 generators assume: the claim is cut into 4+ portions, the marker is in a portion that is not the first, and the
    head alone carries no marker. Checked on the production plan only (no controller, so a holdout pack can be validated unseen: the data of every pack, holdout
    included, is checked on every run; what the product DOES with a holdout pack is not run)."""
    T.REGISTRY.add_unit('META', (pack.key, 'plan'), [pack.key])
    for kind in KINDS:
        claim = pack.claim(kind)
        plan = T.portions_of(claim)
        marker = MARKERS[kind]
        assert len(plan) >= 4, (pack.key, kind, plan)
        first = next(i for i, p in enumerate(plan) if marker in T.words_of(p))
        assert first >= 1 or kind == 'neg', (pack.key, kind, plan)
        assert marker not in T.words_of(pack.head)
        assert G.lossless_problem(claim, plan) is None


@pytest.mark.parametrize('pack', [pytest.param(p, id=p.key) for p in PACKS])
def test_generator_precondition_the_data_fits_what_the_generators_assume(pack):
    """Pure data checks (no controller), so that a pack nobody has run can be validated unseen:
    a role clause is one first cue (at most 4 words and 14 spoken syllables: the profile's 8 plus the first cue's slack of 6); the compound answer, the claims and the dictations that
    take one transform per portion are long enough; the restrictions leave something to say after a marker is dropped."""
    T.REGISTRY.add_unit('META', (pack.key, 'data'), [pack.key])
    for clause in (pack.roles[0], pack.roles[1], pack.roles[2] or pack.roles[0]):
        assert len(T.words_of(clause)) <= 4 and T.vowel_syllables(clause) <= 14, (pack.key, clause, T.vowel_syllables(clause))
    assert pack.rewrite[0].startswith('Да,') and len(pack.rewrite[0].split()) >= 4
    assert len(T.portions_of(' '.join(pack.compound[1:4]))) >= 6, 'the compound answer must have enough portions to correct in the middle'
    assert len(T.portions_of(pack.claim('cond') + ' ' + pack.tail + ' ' + pack.qty[0].format(n=pack.qty[1]) + '.')) >= 10
    assert any(ch.isdigit() for ch in pack.qty[0].format(n=pack.qty[1])) and 'не' in T.words_of(pack.claim('neg'))
    assert all(len(pack.claim(kind).split()) >= 8 for kind in KINDS)
    for kind in KINDS:
        plan = T.portions_of(pack.claim(kind))
        portion = plan[marker_portion(plan, MARKERS[kind])]
        variants = n03_variants(portion, MARKERS[kind], kind)
        assert all(heard and heard != portion for _, heard in variants), (pack.key, kind, portion, variants)
    assert pack.topic[0] and pack.topic[2].split()[0] in ('о', 'об', 'обо')


def test_generator_precondition_every_verified_parent_needs_the_lookup():
    from echo_sync.generator import route_need
    for question, _, group in PARENTS:
        T.REGISTRY.add_unit('META', (question, 'verified'), [question])
        assert route_need(question), question
    for _, text, _ in N09_ELLIPTICAL:
        assert not route_need(text), 'an elliptical child is not verified by its own words: ' + text


def test_the_portion_oracles_catch_what_they_are_for():
    assert T.dangling_ends(['Налог не']) == ['Налог не'] and T.dangling_ends(['Налог не взимается', 'кроме']) == ['кроме']
    assert T.dangling_ends(['Налог не взимается.', 'если']) == ['если'] and T.dangling_ends(['Это всё.']) == []
    assert T.restarts(['Тело сохраняет', 'свою скорость', 'Тело сохраняет']) == [2]
    assert T.restarts(['Вода кипит', 'Вода замерзает', 'Вода плавится']) == [2]
    assert T.restarts(['Тело сохраняет', 'свою скорость']) == []
    assert T.covers('Налог не взимается с пенсионеров', 'Налог не взимается') and not T.covers('Налог взимается', 'Налог не взимается с пенсионеров')
    assert not T.covers('если доход ниже минимума', 'доход ниже минимума и если')
    # W1F-A (b): a head made of the question's own words may be left out - the rest, in order, may not
    bridge = 'Когда построен мост Сильверн?'
    assert T.answers_with('в 1873 году.', 'Мост Сильверн построен в 1873 году.', bridge)
    assert not T.answers_with('в 1921 году.', 'Мост Сильверн построен в 1873 году.', bridge)
    assert not T.answers_with('в 1873 году.', 'Мост Сильверн построен в 1873 году.', 'Когда открыли мост?')
    assert not T.answers_with('построен', 'Мост Сильверн построен в 1873 году.', bridge)
    assert T.vowel_syllables('Электроэнцефалография') == 10 and T.vowel_syllables('22 июня') == T.vowel_syllables('двадцать два июня')
    assert G.lossless_problem('Тело сохраняет скорость', ['Тело', 'скорость']) is not None


def test_the_splice_oracle_accepts_the_explicit_correction_and_nothing_else_that_mixes_the_texts():
    """INTEG7 ruling 3: «<early head> Поправка: <final>» is the sanctioned revision; every other mix of the two texts is a hybrid."""
    w = T.words_of
    early, final = w('Да, трение всегда тормозит движение тел.'), w('Нет, трение иногда ускоряет движение, например у колёс.')
    assert not spliced(w('Да, трение Поправка: Нет, трение иногда ускоряет движение, например у колёс.'), early, final)
    assert not spliced(w('Поправка: Нет, трение иногда ускоряет движение'), early, final)
    assert not spliced(w('Да, трение всегда'), early, final) and not spliced(w('трение иногда ускоряет'), early, final)
    assert spliced(w('Да, трение иногда ускоряет движение'), early, final), 'the old head glued to the new tail'
    assert spliced(w('Да, трение Поправка: тормозит движение тел'), early, final), 'the old text after the word'
    assert spliced(w('Да, трение Поправка: Нет, трение иногда ускоряет движение тел'), early, final), 'the new text ends in the old tail'
    assert spliced(w('Да, трение Нет, трение иногда ускоряет Поправка:'), early, final), 'the word after the new text'
    assert spliced(w('Да, трение Поправка: Нет, трение Поправка: иногда ускоряет'), early, final), 'the word twice'
    assert spliced(w('Да, трение Поправка:'), early, final), 'the word with no new text'


# ==========================================================================================================================
# N01  the restriction came late (not / except / only if) after an early partial
# ==========================================================================================================================

N01_SHAPES = (('neg', 'whole'), ('cond', 'whole'), ('neg', 'words'), ('neg', 'split:5'), ('exc', 'split:5'), ('cond', 'split:5'))


def n01_run(sc, claim, shape):
    """Deliver ``claim`` in ``shape``; the listener repeats whatever is spoken, waiting for the rest of a late answer."""
    if shape.startswith('split:'):
        words = re.findall(r'\s*\S+', claim)
        head, rest = ''.join(words[:int(shape[6:])]), ''.join(words[int(shape[6:]):])
        tid = sc.tid('a')
        sc.feed(turn_created(tid, 'assistant', head))
        spoken_before = len(sc.cues)
        for _ in range(6):
            if sc.current() is None:
                break
            sc.say(sc.current())
        sc.elapse(2.5)                                       # the restriction comes late: after the listener caught up with the head
        sc.feed(turn_delta(tid, rest, 1))
        sc.feed(turn_done(tid, 'assistant', claim))
        return spoken_before
    sc.answer(claim, shape=shape, delta_gap=0.05 if shape == 'words' else 0.0)
    return 0


@pytest.mark.parametrize('pack', T.pack_params())
def test_n01_a_restriction_that_comes_late_still_reaches_the_listener_after_its_head(pack):
    """Whatever the delivery (whole, word by word, restriction after a gap), the listener who repeats every portion hears the head
    and then the restriction, in order, once each, and the answer is complete only when the restriction was confirmed."""
    violations = []
    for kind, shape in N01_SHAPES:
        name = f'{pack.key}/{kind}/{shape}'
        with T.ctl('N01', pack.key, kind, shape, group=pack.group) as sc:
            claim = pack.claim(kind)
            sc.ask(pack.question)
            n01_run(sc, claim, shape)
            sc.walk()
            issued = distinct_in_order(sc.cues)
            problem = G.lossless_problem(claim, issued)
            if problem:
                T.collect(violations, name, f'what was spoken is not the answer: {problem}')
            if not sc.completed:
                T.collect(violations, name, f'the dictation did not complete (portion {sc.idx} of {len(sc.chunks)}, cues {len(sc.cues)})')
            marker = MARKERS[kind]
            marker_at = next((i for i, p in enumerate(issued) if marker in T.words_of(p)), None)
            if marker_at is None:
                T.collect(violations, name, f'the restriction word «{marker}» never reached the listener')
            elif not T.covers(' '.join(issued[:marker_at + 1]), pack.head):
                T.collect(violations, name, f'the restriction «{marker}» was spoken before the head it restricts')
            if T.dangling_ends(issued):
                T.collect(violations, name, f'a portion ends on a word that needs the next one: {T.dangling_ends(issued)}')
    T.assert_none(violations, 'N01 late restriction')


@pytest.mark.parametrize('pack', T.pack_params())
def test_n01_a_rewritten_prefix_is_repaired_or_was_never_published(pack):
    """The cloud first says the head of the claim and then its final text, which does NOT continue the head but flips it. Required
    (V3 N01): the wrong head is not published, or the listener gets an explicit repair (the corrected words, or at least a signal)."""
    violations = []
    for confirmed in (False, True):
        name = f'{pack.key}/rewrite/confirmed={confirmed}'
        with T.ctl('N01', pack.key, 'rewrite', f'confirmed={confirmed}', group=pack.group) as sc:
            early, final = early_head(pack), pack.rewrite[1]
            sc.ask(pack.question)
            tid = sc.tid('a')
            sc.feed(turn_created(tid, 'assistant', early))
            published = len(sc.cues)
            if confirmed and sc.current():
                sc.say(sc.current())
            before = len(sc.cues)
            actions = sc.feed(turn_done(tid, 'assistant', final))
            actions += sc.tick(12)
            sc.walk()          # INTEG7 ruling 4: a portioned repair says one portion at a time - the listener repeats what is dictated
            repair = ' '.join(sc.cues[before:])
            signalled = any(a['type'] == 'unanswered' for a in actions)
            if published and not (T.covers(repair, final.split('.')[0]) or signalled):
                state = sc.state()
                T.collect(violations, name, f'the head «{early}» was published ({published} cue) and the final text «{final[:40]}…» was '
                                            f'dropped without a word: streaming={state.get("streaming")}, waiting={state.get("stream_waiting_next")}, '
                                            f'nothing spoken for 12 s')
    T.assert_none(violations, 'N01 rewrite of a published prefix')


def early_head(pack):
    """The cloud's early text as a whole sentence. F1 (wave F): a call publishes a meaning portion - a sentence or a clause - where it
    published a 2-word head of the open text before; the head must be published (and confirmable) for these scenarios to test anything."""
    return pack.rewrite[0].rstrip('.') + '.'


def spans_of(words, text_words):
    return any(text_words[i:i + len(words)] == words for i in range(len(text_words) - len(words) + 1))


CORRECTION_WORD = 'поправка'


def spliced(spoken, early, final):
    """Is ``spoken`` (words, in order) a hybrid of the early and the final text? A stretch of either one is not. Nor is the explicit
    correction V3 sanctions after publication (coordinator ruling 3 at INTEG7): a stretch of the early text, then «поправка» (said by the
    product, before the new text), then a stretch of the final text - nothing of the old text after the word. Anything else that mixes them is."""
    if spans_of(spoken, early) or spans_of(spoken, final):
        return False
    if spoken.count(CORRECTION_WORD) == 1 and CORRECTION_WORD not in early + final:
        at = spoken.index(CORRECTION_WORD)
        head, tail = spoken[:at], spoken[at + 1:]
        return not (tail and spans_of(head, early) and spans_of(tail, final))
    return True


@pytest.mark.parametrize('pack', T.pack_params())
def test_n01_a_rewrite_is_never_spliced_onto_the_head_that_was_published(pack):
    """Whatever the product does with a rewritten answer, it never speaks a hybrid: the words spoken, in order, are a stretch of the early
    text or a stretch of the final text (a head of the old claim glued to the tail of the new one is the worst of the outcomes), or the
    explicit correction «<early head> Поправка: <final>» (``spliced``, coordinator ruling 3 at INTEG7). Two rewrites: a different text, and
    the same text with its first word flipped for a word of the same length («Да,» -> «Не,») and another last word, where the cut of the
    published prefix falls exactly on a word boundary of the new text."""
    violations = []
    early = early_head(pack)
    assert early.startswith('Да,'), 'generator precondition: the early text starts with «Да,»'
    flipped = ' '.join(('Не,' + early[3:]).split()[:-1] + [OTHER_WORDS[PACKS.index(pack) % len(OTHER_WORDS)]])
    for kind, final in (('other_text', pack.rewrite[1]), ('same_shape_flip', flipped)):
        for confirmed in (False, True):
            with T.ctl('N01', pack.key, 'rewrite-guard', kind, f'confirmed={confirmed}', group=pack.group) as sc:
                sc.ask(pack.question)
                tid = sc.tid('a')
                sc.feed(turn_created(tid, 'assistant', early))
                if confirmed and sc.current():
                    sc.say(sc.current())
                sc.feed(turn_done(tid, 'assistant', final))
                sc.tick(4)
                sc.walk(limit=8)
                spoken = [w for cue in distinct_in_order(sc.cues) for w in T.words_of(cue)]
                if spoken and spliced(spoken, T.words_of(early), T.words_of(final)):
                    T.collect(violations, f'{pack.key}/{kind}/confirmed={confirmed}', f'a hybrid was spoken: {" ".join(distinct_in_order(sc.cues))!r}')
    T.assert_none(violations, 'N01 rewrite splice')


@pytest.mark.parametrize('pack', T.pack_params())
@defect('QUESTION-T-B01')
def test_n01_an_explicit_repair_turn_after_the_head_was_confirmed_reaches_the_listener(pack):
    """The cloud's head is complete and confirmed; a LATER assistant turn says «Поправка: …» (the restriction). Required: the listener
    hears it (V3 N01: «явный repair»). Today the owner rule mutes every assistant turn that follows a repeat of a finished sentence."""
    violations = []
    with T.ctl('N01', pack.key, 'repair-turn', group=pack.group) as sc:
        sc.ask(pack.question)
        sc.answer(pack.head + '.')
        for _ in range(6):
            if sc.current() is None:
                break
            sc.say(sc.current())
        before = len(sc.cues)
        correction = 'Поправка' + pack.cond[1:] + '.'
        sc.feed(turn_done('repair-1', 'assistant', correction))
        sc.tick(4)
        if len(sc.cues) == before and sc.current() is None:
            T.collect(violations, pack.key, f'the repair «{correction[:50]}…» was dropped silently')
    T.assert_none(violations, 'N01 repair turn')


# ==========================================================================================================================
# N02  the subject changed without a restart: the follow-up and the model must use the LAST subject
# ==========================================================================================================================

# Verified questions (the lookup route) of subjects that have nothing to do with the packs: the "old subject" of a switch.
# (question, stem of its subject word, group)
PARENTS = (
    ('Какая ставка налога на прибыль?', 'ставк', 'dev'),
    ('Какой штраф за превышение скорости?', 'штраф', 'dev'),
    ('Что устанавливает статья 228 Уголовного кодекса?', 'статья', 'dev'),
    ('Какой курс доллара сегодня?', 'курс', 'dev'),
    ('Какая стоимость патента для предпринимателя?', 'стоимост', 'holdout'),
    ('Какой размер штрафа за нарушение тишины?', 'штраф', 'holdout'),
)
PARENT_ANSWER = 'Это значение установлено законом и действует для большинства организаций. Оно пересматривается каждый год.'


def parent_for(pack):
    pool = [p for p in PARENTS if p[2] == pack.group]
    return pool[PACKS.index(pack) % len(pool)]


SWITCH_RECOGNISED = (('give_acc', 'Давайте теперь про {acc}.'), ('lets_better_prep', 'Давайте лучше {prep}.'), ('new_question', '{question}'))
SWITCH_SILENT = (('talk_prep', 'Теперь поговорим {prep}.'), ('other_topic', 'Другая тема — {nom}.'),
                 ('next_block', 'Следующий блок: {nom}.'), ('switch_to', 'Переключаемся на {acc}.'))
N02_FOLLOW_UPS = ('Почему так?', 'Приведи пример', 'Что это значит?')


def n02_check(pack, forms, violations):
    parent, old_stem, _ = parent_for(pack)
    new_stem = T.stem5(T.words_of(pack.topic[0])[0])
    for number, (form_name, form) in enumerate(forms):
        follow = N02_FOLLOW_UPS[(PACKS.index(pack) + number) % len(N02_FOLLOW_UPS)]
        name = f'{pack.key}/{form_name}/{follow}'
        with T.ctl('N02', pack.key, form_name, follow, group=pack.group) as sc:
            sc.ask(parent)
            sc.answer(PARENT_ANSWER)
            sc.say(sc.chunks[0])
            switch = form.format(nom=pack.topic[0], acc=pack.topic[1], prep=pack.topic[2], question=pack.question)
            sc.ask(switch, ground=False)
            _, actions = sc.ask(follow, ground=False)
            for query in [a['lookup_question'] for a in actions if a['type'] == 'lookup']:
                words = T.words_of(query)
                old_there = any(w.startswith(old_stem) for w in words)
                new_there = any(w.startswith(new_stem) for w in words)
                if old_there and not new_there:
                    T.collect(violations, name, f'«{follow}» after «{switch}» was looked up with the OLD subject: {query!r}')
                elif old_there:
                    T.collect(violations, name, f'the lookup carries both subjects: {query!r}')
    return violations


@pytest.mark.parametrize('pack', T.pack_params())
def test_n02_a_recognised_subject_switch_moves_the_follow_up_to_the_new_subject(pack):
    T.assert_none(n02_check(pack, SWITCH_RECOGNISED, []), 'N02 recognised switch')


DEFECTS['DEF-T-B02'] = ('a subject switch said as a statement («Теперь поговорим о …», «Другая тема — …», «Следующий блок: …», '
                        '«Переключаемся на …») is silent: the next «Почему так?» is looked up with «Тема:» of the OLD subject '
                        '(user_intents.topic_change knows a few verb forms only; controlled_media.py:761-764)')


@pytest.mark.parametrize('pack', T.pack_params())
@defect('DEF-T-B02')
def test_n02_a_subject_switch_said_as_a_statement_moves_the_follow_up_too(pack):
    T.assert_none(n02_check(pack, SWITCH_SILENT, []), 'N02 statement switch')


def pair_params():
    pairs = list(zip(PACKS, PACKS[1:] + PACKS[:1]))
    return [pytest.param(pair, id=f'{pair[0].key}-to-{pair[1].key}',
                         marks=T.HOLD if 'holdout' in (pair[0].group, pair[1].group) else ()) for pair in pairs]


def pair_group(a, b):
    return 'holdout' if 'holdout' in (a.group, b.group) else 'dev'


@pytest.mark.parametrize('pair', pair_params())
def test_n02_the_engine_asks_the_model_with_the_material_of_the_current_subject(pair, tmp_path):
    """Classic route: the SAME definition question after the subject (the material) changed must reach the model with the new
    material and must not be served from the answer given under the old one (answer reuse keys on the material)."""
    from echo_sync.engine import EchoEngine
    a, b = pair
    material = {'now': f'Предмет: {a.subject}. {a.claim("neg")}'}
    answers = {f'Предмет: {p.subject}. {p.claim("neg")}': p.claim('neg') + ' ' + p.tail for p in PACKS}
    calls = []

    def generate(question, history, context, request, model):
        calls.append(context)
        return answers[context]

    engine = EchoEngine(tmp_path / 's.sqlite3', generate, context=lambda: material['now'])
    question = 'Что такое ' + a.subject + '?'
    first = engine_reply(engine, session_id='s', turn_id='t1', text=question, request={}, model='m')
    material['now'] = f'Предмет: {b.subject}. {b.claim("neg")}'
    second = engine_reply(engine, session_id='s', turn_id='t2', text=question, request={}, model='m')
    T.REGISTRY.add_unit('N02', (a.key, b.key, 'engine'), [question, material['now']], pair_group(a, b))
    assert len(calls) == 2 and calls[1].startswith(f'Предмет: {b.subject}'), 'the model was not asked with the new material (reuse across subjects)'
    assert T.words_of(second)[0] == T.words_of(b.head)[0] and T.words_of(first)[0] == T.words_of(a.head)[0], (first, second)


@pytest.mark.parametrize('pair', pair_params())
def test_n02_replacing_the_materials_leaves_nothing_of_the_old_subject(pair, tmp_path):
    """The real material import: after the second import the context is the new subject's text only, the manifest lists only the new
    source, and the old text is nowhere in it (the old copy is kept as a backup file, not in the context)."""
    from echo_sync import materials
    a, b = pair
    home = tmp_path / 'home'
    file_a, file_b = tmp_path / 'a.txt', tmp_path / 'b.txt'
    file_a.write_text(f'{a.subject}. {a.claim("neg")} {a.claim("cond")} {a.tail}', encoding='utf-8')
    file_b.write_text(f'{b.subject}. {b.claim("exc")} {b.tail}', encoding='utf-8')
    first = materials.import_materials([file_a], home)
    second = materials.import_materials([file_b], home)
    T.REGISTRY.add_unit('N02', (a.key, b.key, 'materials'), [a.subject, b.subject], pair_group(a, b))
    context = materials.read_material_context(second['path'])
    assert b.claim('exc') in context and a.head not in context and a.tail not in context
    assert [s['source_name'] for s in second['manifest']['sources']] == ['b.txt']
    assert second['manifest']['sources'][0]['material_id'] != first['manifest']['sources'][0]['material_id']
    assert second['backup'] is not None and a.head in second['backup'].read_text(encoding='utf-8')


# ==========================================================================================================================
# N03  the listener repeated the pretty part and skipped the logically mandatory condition
# ==========================================================================================================================

REPLACEMENT = {'neg': 'ни', 'exc': 'помимо', 'cond': 'когда'}
JOIN_GAP = 11.0          # longer than ACK_JOIN_SECONDS (10 s): an earlier failed attempt can never be joined with the next one


def marker_portion(chunks, marker):
    return next(i for i, chunk in enumerate(chunks) if marker in T.words_of(chunk))


def n03_variants(portion, marker, kind):
    """What a listener might say instead of the portion that carries the restriction: only the pretty part, without the marker,
    with the marker replaced by a look-alike."""
    words = portion.split()
    at = next(i for i, w in enumerate(words) if T.words_of(w) == [marker])
    pretty = words[:at] if at else words[at + 1:]
    return [('pretty_prefix', ' '.join(pretty)), ('drop_marker', ' '.join(words[:at] + words[at + 1:])),
            ('replace_marker', ' '.join(words[:at] + [REPLACEMENT[kind]] + words[at + 1:]))]


@pytest.mark.parametrize('pack', T.pack_params())
def test_n03_a_repeat_without_the_condition_never_closes_the_slot(pack):
    """The restriction portion («не» / «кроме» / «если»…) is skipped three ways: only the words around it, the words without it,
    and with a look-alike word. None of them is the portion: the cursor stays, the answer is not complete, nothing is spoken; the
    correct repeat then moves on exactly one portion and the dictation completes."""
    violations = []
    for kind in KINDS:
        marker = MARKERS[kind]
        with T.ctl('N03', pack.key, kind, group=pack.group) as sc:
            claim = pack.claim(kind) + ' ' + pack.tail
            sc.ask(pack.question)
            sc.answer(claim)
            target = marker_portion(sc.chunks, marker)
            for i in range(target):
                sc.say(sc.chunks[i])
            portion = sc.chunks[target]
            for behaviour, heard in n03_variants(portion, marker, kind):
                name = f'{pack.key}/{kind}/{behaviour}'
                assert heard and heard != portion, (name, portion, heard)
                state = (sc.idx, sc.revision, len(sc.cues))
                sc.say(heard, gap=JOIN_GAP)
                if (sc.idx, sc.revision, len(sc.cues)) != state or sc.completed:
                    T.collect(violations, name, f'«{heard}» for «{portion}» moved the dictation: cursor {state[0]}->{sc.idx}, '
                                                f'revision {state[1]}->{sc.revision}, cues {state[2]}->{len(sc.cues)}')
                sc.checkpoint(behaviour)
            sc.say(portion, gap=JOIN_GAP)
            if sc.idx != target + 1:
                T.collect(violations, f'{pack.key}/{kind}/correct', f'the correct repeat of «{portion}» did not move one portion ({sc.idx})')
            sc.walk()
            if not sc.completed or G.lossless_problem(claim, distinct_in_order(sc.cues)):
                T.collect(violations, f'{pack.key}/{kind}/finish', f'completed={sc.completed}, {G.lossless_problem(claim, distinct_in_order(sc.cues))}')
    T.assert_none(violations, 'N03 skipped condition')


# ==========================================================================================================================
# N04  the portions that were really issued, put together, are the answer: whole, in order, no start over, no cut condition
# ==========================================================================================================================

N04_SHAPES = (('neg', 'whole'), ('cond', 'words'))


@pytest.mark.parametrize('pack', T.pack_params())
def test_n04_the_issued_portions_concatenate_to_the_answer(pack):
    """Wire level: the frames the phone received (response.audio_transcript.delta of each response), joined, are the answer that the
    cloud gave: nothing lost, nothing twice, in order, no portion starts the answer over, none ends on a word that needs the next."""
    violations = []
    for kind, shape in N04_SHAPES:
        name = f'{pack.key}/{kind}/{shape}'
        with T.wire('N04', pack.key, kind, shape, group=pack.group) as w:
            claim = pack.claim(kind) + ' ' + pack.tail
            w.ask(pack.question)
            w.answer(claim, shape='whole' if shape == 'whole' else 'words')
            for _ in range(40):
                current = w.current()
                if current is None:
                    break
                w.say(current)
            issued = [c.text for c in w.portions]
            if G.lossless_problem(claim, issued):
                T.collect(violations, name, f'issued text is not the answer: {G.lossless_problem(claim, issued)}')
            if T.restarts(issued):
                T.collect(violations, name, f'a portion starts the answer over: {T.restarts(issued)}')
            if T.dangling_ends(issued):
                T.collect(violations, name, f'a portion ends on a word that needs the next: {T.dangling_ends(issued)}')
            if len(set(issued)) != len(issued):
                T.collect(violations, name, 'a portion was issued twice without being asked to')
            if not w.completed or w.w.violations:
                T.collect(violations, name, f'completed={w.completed}, wire violations={w.w.violations[:1]}')
    T.assert_none(violations, 'N04 issued concatenation')


DEFECTS['DEF-T-B04'] = ('the abbreviation table of the settings expands an abbreviation into ONE fixed (nominative) form: «рост ВВП» is spoken '
                        '«рост валовой внутренний продукт», «о ВВП» «о валовой внутренний продукт» (portioner._expand has no case agreement)')
N04_ABBREVIATIONS = (
    ('ВВП', {'nomn': 'валовой внутренний продукт', 'gent': 'валового внутреннего продукта', 'loct': 'валовом внутреннем продукте',
             'ablt': 'валовым внутренним продуктом'}),
    ('МРОТ', {'nomn': 'минимальный размер оплаты труда', 'gent': 'минимального размера оплаты труда',
              'loct': 'минимальном размере оплаты труда', 'ablt': 'минимальным размером оплаты труда'}),
)
N04_CONTEXTS = (('nomn', '{A} вырос за год.'), ('gent', 'Рост {A} замедлился за год.'), ('loct', 'Эксперты говорят о {A} каждый год.'),
                ('ablt', 'Эксперты занимаются {A} каждый год.'))


def n04_cases(nominative):
    return [pytest.param((abbr, forms, case, template), id=f'{abbr}-{case}')
            for abbr, forms in N04_ABBREVIATIONS for case, template in N04_CONTEXTS if (case == 'nomn') == nominative]


def n04_spoken(abbr, forms, case, template):
    settings = {'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2, 'abbreviations': {abbr: forms['nomn']}}
    T.REGISTRY.add_unit('N04', (abbr, case, 'abbreviation'), [template, abbr])
    return ' '.join(T.portions_of(template.format(A=abbr), settings)).casefold()


@pytest.mark.parametrize('case', n04_cases(True))
def test_n04_an_abbreviation_in_its_own_case_is_expanded_whole(case):
    abbr, forms, wanted, template = case
    assert forms['nomn'] in n04_spoken(abbr, forms, wanted, template)


@pytest.mark.parametrize('case', n04_cases(False))
@defect('DEF-T-B04')
def test_n04_the_expanded_abbreviation_agrees_with_the_case_of_its_phrase(case):
    abbr, forms, wanted, template = case
    spoken = n04_spoken(abbr, forms, wanted, template)
    assert forms[wanted] in spoken, f'«{abbr}» in the {wanted} context was spoken as «{spoken}»'


# ==========================================================================================================================
# N05  a subtle change of the subject: who does what to whom
# ==========================================================================================================================

def role_portion(pack, sc):
    """Ask, give the role sentence (+ the tail) as the answer, and require that the first portion carries both roles."""
    base = pack.roles[0]
    sc.ask(pack.question)
    sc.answer(base + '. ' + pack.tail)
    portion = sc.chunks[0]
    assert portion.rstrip('.,') == base, f'generator precondition: {portion!r} is not the role clause {base!r}'
    return portion


@pytest.mark.parametrize('pack', T.pack_params())
def test_n05_swapped_or_replaced_roles_are_not_the_portion_and_the_exact_repeat_is(pack):
    base, swapped, _ = pack.roles
    other = swapped.split()[0]
    violations = []
    with T.ctl('N05', pack.key, 'lexical-and-order', group=pack.group) as sc:
        portion = role_portion(pack, sc)
        for behaviour, heard in (('lexical_swap', ' '.join([other] + base.split()[1:])), ('order_swap', swapped)):
            before = (sc.idx, len(sc.cues))
            sc.say(heard, gap=JOIN_GAP)
            if (sc.idx, len(sc.cues)) != before:
                T.collect(violations, f'{pack.key}/{behaviour}', f'«{heard}» was taken for «{portion}» (cursor {before[0]}->{sc.idx})')
            sc.checkpoint(behaviour)
        sc.say(portion, gap=JOIN_GAP)
        if sc.idx != 1:
            T.collect(violations, f'{pack.key}/exact', f'the exact repeat of «{portion}» did not move the cursor ({sc.idx})')
    T.assert_none(violations, 'N05 roles')


DEFECTS['DEF-T-B05'] = ('the ACK matcher compares LEMMAS in order, so a repeat that swaps the roles only by case endings («Банка кредитует клиент» '
                        'for «Банк кредитует клиента») is a full, correct repeat: false NEXT on a role inversion (ru_alignment._atoms, _word_item)')


@pytest.mark.parametrize('pack', T.pack_params([p.key for p in PACKS if p.roles[2]]))
@defect('DEF-T-B05')
def test_n05_roles_swapped_only_by_case_endings_are_not_the_portion(pack):
    inplace = pack.roles[2]
    violations = []
    with T.ctl('N05', pack.key, 'inplace-case', group=pack.group) as sc:
        portion = role_portion(pack, sc)
        sc.say(inplace, gap=JOIN_GAP)
        if sc.idx != 0:
            T.collect(violations, pack.key, f'«{inplace}» (the roles of «{portion}» reversed by endings) advanced the cursor 0->{sc.idx}')
    T.assert_none(violations, 'N05 in-place case swap')


# ==========================================================================================================================
# N06  the source is fresh but the quotation belongs to another edition: the version of the source decides what may be spoken
# ==========================================================================================================================

def parents_params():
    return [pytest.param(p, id=f'parent{i}', marks=T.HOLD if p[2] == 'holdout' else ()) for i, p in enumerate(PARENTS)]


N06_MOMENTS = ('before_the_lookup_result', 'sources_found_not_yet_delivered', 'after_delivery')


@pytest.mark.parametrize('parent', parents_params())
def test_n06_an_answer_written_before_the_sources_were_delivered_is_never_spoken(parent):
    """The cloud may answer at any moment. Only text that came AFTER the sources reached it may be dictated (V3: an old basis is
    not the basis of the new claim); the same answer after the delivery is spoken."""
    question, _, group = parent
    violations = []
    for moment in N06_MOMENTS:
        with T.ctl('N06', question, moment, group=group) as sc:
            sc.ask(question, ground=False)
            assert any(a['type'] == 'lookup' for a in sc.actions), 'generator precondition: the question must need a lookup'
            if moment != 'before_the_lookup_result':
                sc.ground(deliver=False)
            if moment == 'after_delivery':
                sc.deliver()
            sc.answer(PARENT_ANSWER)
            spoken = bool(sc.cues)
            if spoken != (moment == 'after_delivery'):
                T.collect(violations, f'{question}/{moment}', f'the answer was {"spoken" if spoken else "muted"}, cues={sc.cues[:2]}')
            if moment != 'after_delivery':               # the cloud answers again once the sources are there: that one is spoken
                if moment == 'before_the_lookup_result':
                    sc.ground(deliver=False)
                sc.deliver()
                sc.answer(PARENT_ANSWER + ' Это важно знать.')
                if not sc.cues:
                    T.collect(violations, f'{question}/{moment}/second', 'the answer given after the delivery was not spoken either')
    T.assert_none(violations, 'N06 source fence')


@pytest.mark.parametrize('parent', parents_params())
def test_n06_a_lookup_result_of_an_older_question_never_grounds_a_newer_one(parent):
    """Question 1 waits for its sources; question 2 replaces it - a verified one (its own result not back yet, or already back but not
    delivered), a model-memory one, or «стоп». Then the lookup of question 1 returns and its sources are reported delivered. Neither
    may touch question 2: not its grounding, not its delivery flag, and question 2's own sources still work."""
    question, _, group = parent
    violations = []
    for second in ('verified-waiting', 'verified-grounded', 'direct', 'stop'):
        with T.ctl('N06', question, 'stale-' + second, group=group) as sc:
            sc.ask(question, ground=False)
            old_epoch = sc.c.epoch
            if second.startswith('verified'):
                sc.ask('Какая ставка налога на имущество?', ground=False)
            elif second == 'direct':
                sc.ask(PACKS[0].question, ground=False)
            else:
                sc.say('стоп')
            if second == 'verified-grounded':
                sc.ground(deliver=False)                              # question 2 is grounded and its sources are not delivered yet
            contexts = len(sc.contexts)
            stale = sc.ground(epoch=old_epoch, deliver=False)
            if stale or len(sc.contexts) != contexts or (sc.c.grounded and second != 'verified-grounded'):
                T.collect(violations, f'{question}/{second}', f'a result of epoch {old_epoch} grounded epoch {sc.c.epoch}: {[a["type"] for a in stale]}')
            if sc.deliver(epoch=old_epoch) or sc.c.delivery_ready:
                T.collect(violations, f'{question}/{second}', 'the delivery of an older epoch was taken for the sources of the current question')
            if second.startswith('verified'):
                if second == 'verified-waiting':
                    fresh = sc.ground(deliver=False)
                    if [a['type'] for a in fresh] != ['context']:
                        T.collect(violations, f'{question}/{second}', f'the current question could not be grounded after the stale result: {fresh}')
                sc.answer(PARENT_ANSWER)
                if sc.cues:
                    T.collect(violations, f'{question}/{second}', 'an answer was dictated before the sources of the CURRENT question were delivered')
                sc.deliver()
                sc.answer(PARENT_ANSWER + ' Это важно знать.')
                if not sc.cues:
                    T.collect(violations, f'{question}/{second}', 'the answer after the real delivery was not dictated')
    T.assert_none(violations, 'N06 stale epoch')


DEFECTS['DEF-T-B06'] = ('public_sources() copies only url/text/title/source_receipt: the revision, edition, locator (page, clause) and date of '
                        'application of a source never reach the model or the stored state, so a claim cannot be tied to the edition it was '
                        'quoted from (controlled_media.py:85-112)')
N06_FIELDS = (('revision', '2019-03'), ('edition', 'пятое издание'), ('locator', 'пункт 4, абзац 2'), ('effective_date', '2024-01-01'),
              ('page', '117'), ('retrieved_at', '2026-11-02'))


@pytest.mark.parametrize('parent', parents_params())
@defect('DEF-T-B06')
def test_n06_the_revision_locator_and_date_of_a_source_reach_the_model(parent):
    question, _, group = parent
    violations = []
    for field_name, value in N06_FIELDS:
        with T.ctl('N06', question, 'provenance', field_name, group=group) as sc:
            rows = [{'url': 'https://example.org/law/' + field_name, 'text': 'Норма действует в редакции, указанной в источнике.', field_name: value}]
            sc.ask(question, rows=rows)
            sent = sc.contexts[-1]['sources'][0] if sc.contexts else {}
            if sent.get(field_name) != value:
                T.collect(violations, f'{question}/{field_name}', f'«{field_name}» = {value!r} did not reach the model (sent keys: {sorted(sent)})')
    T.assert_none(violations, 'N06 provenance fields')


# ==========================================================================================================================
# N07  two people talk in turn: similar words of the other voice must not confirm a portion that was not repeated
# ==========================================================================================================================

@pytest.mark.parametrize('pack', T.pack_params())
def test_n07_words_of_another_voice_that_are_not_the_current_portion_never_advance(pack):
    """The other voice repeats the PREVIOUS portion (it has been confirmed, the cursor has moved on), and a near copy of the current one
    (one word of it changed). Neither is the current portion."""
    violations = []
    with T.ctl('N07', pack.key, 'other-voice', group=pack.group) as sc:
        sc.ask(pack.question)
        sc.answer(pack.claim('neg') + ' ' + pack.tail)
        first, second = sc.chunks[0], sc.chunks[1]
        sc.say(first)
        for behaviour, heard in (('quote_of_the_previous_portion', first), ('near_copy', ' '.join(second.split()[:-1] + [OTHER_WORDS[PACKS.index(pack) % len(OTHER_WORDS)]]))):
            before = (sc.idx, len(sc.cues))
            sc.say(heard, gap=JOIN_GAP)
            if (sc.idx, len(sc.cues)) != before:
                T.collect(violations, f'{pack.key}/{behaviour}', f'«{heard}» advanced the dictation (cursor {before[0]}->{sc.idx})')
            sc.checkpoint(behaviour)
    T.assert_none(violations, 'N07 other voice')


DEFECTS['DEF-T-B07'] = ('a user turn that ends with the exact portion is a confirmation even when another user turn is still open (two voices '
                        'at once): the controller does not look at overlapping turns, so the interlocutor can confirm for the owner '
                        '(controlled_media._accept_user)')


@pytest.mark.parametrize('pack', T.pack_params())
@defect('DEF-T-B07')
def test_n07_two_voices_speaking_at_once_never_confirm_the_portion(pack):
    """The owner's turn is open (speaking); a second turn begins and ends with the exact words of the portion. Two voices at once is
    doubt: V3 says HOLD, and a false NEXT is worse than a pause."""
    violations = []
    with T.ctl('N07', pack.key, 'overlap', group=pack.group) as sc:
        sc.ask(pack.question)
        sc.answer(pack.claim('cond') + ' ' + pack.tail)
        first = sc.chunks[0]
        sc.elapse(1.0)
        sc.start_speaking('owner')
        sc.elapse(0.3)
        sc.start_speaking('other')
        sc.elapse(0.5)
        sc.feed(turn_done('other', 'user', first))
        if sc.idx != 0:
            T.collect(violations, pack.key, f'«{first}» from the second voice, while the first turn was still open, advanced the cursor to {sc.idx}')
        sc.feed(turn_done('owner', 'user', 'ну подожди'))
    T.assert_none(violations, 'N07 overlapping voices')


def test_n07_nothing_the_product_sends_claims_who_spoke():
    """The wire has no speaker evidence; the product must not invent it: no key of any action or frame names a speaker."""
    with T.wire('N07', 'identity-claims') as w:
        w.ask(PACKS[0].question)
        w.answer(PACKS[0].claim('neg'))
        w.say(w.current())
        w.say('кто-то другой сказал это')
        blob = repr(w.w.frames) + repr(w.c.state())
        assert not re.search(r'speaker|owner_id|identity|voiceprint', blob.casefold()), 'a speaker claim in the product output'


# ==========================================================================================================================
# N08  the owner speaks while the TTS is still being played: the system's own voice never confirms itself
# ==========================================================================================================================

N08_VOICED = (0.8, 1.5, 2.5)
MARGIN = 0.3                       # controlled_media.CUE_TAIL_SECONDS
# There is no drop of an echo (ledger ruling of 2 Nov: the iPhone cancels our playback with its voice processing and a fast listener begins to
# repeat INSIDE the cue, so a drop rejected genuine repeats; the overlap is logged as ``own_voice_suspect`` and accepted - pinned by F16 of Task T-A).
# What is pinned here is the other side, with the timing a real echo has:
# the provider announces the cue heard back no sooner than ECHO_FLOOR s after the cue's first audio (the microphone has to hear it, the provider has
# to transcribe it: candidate review of 2 Nov, 0.9-2.3 s from the start of its probe audio, never under 1.26 s), inside the window in which the
# cue can be heard back (the voice + MARGIN). Speech announced sooner than that cannot be the cue: it is the listener, over the cue.
ECHO_FLOOR = 1.0
N08_STARTS = (('at_the_first_frame', lambda d: 0.0, 'echo'), ('mid_voice', lambda d: d / 2, 'echo'), ('last_moment_of_voice', lambda d: d - 0.1, 'echo'),
              ('fast_repeat_after_the_margin', lambda d: d + MARGIN + 0.25, 'genuine'), ('slow_repeat_after_the_pcm_tail', lambda d: d + 0.78 + 0.6, 'genuine'))
N08_LAGS = (0.0, 0.5, 1.2, None)       # seconds between the real start of speech and the provider's announcement (turn.created); None: never announced
N08_PACKS = (DEV[0], DEV[1], DEV[2], HOLDOUT[0])


def n08_run(pack, voiced, name, start_fn, lag):
    """The portion is in the ear for ``voiced`` s; somebody says exactly its words, starting ``start_fn(voiced)`` s after the first frame,
    announced ``lag`` s later (the provider's turn.created), or never announced. True when the cursor moved."""
    with T.ctl('N08', pack.key, f'D={voiced}', name, f'lag={lag}', group=pack.group, play=False) as sc:
        sc.ask(pack.question)
        sc.answer(pack.claim('neg') + ' ' + pack.tail)
        cue = [a for a in sc.actions if a['type'] == 'speak'][-1]
        begin = sc.clock()
        sc.cue_in_flight(cue, voiced)
        real_start = start_fn(voiced)
        if lag is not None:
            sc.clock.t = begin + real_start + lag
            sc.start_speaking('speech')
        sc.clock.t = begin + real_start + voiced + (lag or 0.0)
        sc.feed(turn_done('speech', 'user', cue['text']))
        return sc.idx == 1, cue['text']


def n08_cases(truth, announced_in_window=None):
    """(pack, D, start name, start fn, lag) for one kind of speech, one pack per combination (round robin).
    ``truth == 'echo'``: speech that starts inside the voice and is announced the way an echo is, from ECHO_FLOOR s after the cue's first audio;
    ``announced_in_window`` True keeps those announced before the window ends, False those announced after it or never.
    ``truth == 'early'``: the same starts, announced SOONER than an echo can be (< ECHO_FLOOR): not the cue heard back, but somebody speaking over it.
    ``truth == 'genuine'``: the repeat begins after the voice and its margin."""
    cases, number = [], 0
    for voiced in N08_VOICED:
        for name, fn, kind in N08_STARTS:
            if kind != ('genuine' if truth == 'genuine' else 'echo'):
                continue
            for lag in N08_LAGS:
                number += 1
                if truth != 'genuine':
                    announced = None if lag is None else fn(voiced) + lag
                    if announced is not None and announced < ECHO_FLOOR:
                        category = 'early'
                    elif announced is not None and announced <= voiced + MARGIN:
                        category = 'in_window'
                    else:
                        category = 'late'
                    if category != ('early' if truth == 'early' else 'in_window' if announced_in_window else 'late'):
                        continue
                pack = N08_PACKS[number % len(N08_PACKS)]
                cases.append(pytest.param((pack, voiced, name, fn, lag), id=f'{pack.key}-D{voiced}-{name}-lag{lag}',
                                          marks=T.HOLD if pack.group == 'holdout' else ()))
    return cases


@pytest.mark.parametrize('case', n08_cases('early'))
def test_n08_speech_announced_sooner_than_an_echo_can_be_is_the_listeners_even_with_the_guard_on(case):
    """The other side of the window: nothing is announced less than a second after the cue's first audio can be the cue heard back, so a listener
    who begins to repeat over the cue (fast speakers do) is accepted, whatever the guard."""
    pack, voiced, name, fn, lag = case
    advanced, portion = n08_run(pack, voiced, name, fn, lag)
    assert advanced, f'the repeat of «{portion}» ({name}, D={voiced}s, announced {fn(voiced) + lag:.2f}s after the cue began) was dropped as an echo'


@pytest.mark.parametrize('case', n08_cases('genuine'))
def test_n08_a_genuine_repeat_after_the_voice_is_accepted_whatever_the_announcement_lag(case):
    pack, voiced, name, fn, lag = case
    advanced, portion = n08_run(pack, voiced, name, fn, lag)
    assert advanced, f'the repeat of «{portion}» by the listener ({name}, D={voiced}s, lag {lag}) was dropped as an echo'


# ==========================================================================================================================
# N09  a clarification is a part of the old question, not a new subject
# ==========================================================================================================================

N09_RECOGNISED = (('why_so', 'А почему так?'), ('example', 'Приведи пример'), ('what_means', 'Что это значит?'), ('why', 'Почему так?'))
# 'А в прошлом году?' was the child 'last_year': since the route merge of 16.11 (generator.route_need) a phrase that holds «в прошлом году» is a time-bound datum and
# needs a source by its OWN words (CHANGES), so it is no longer an elliptical child that waits for its parent; replaced by one that really is (REDB).
N09_ELLIPTICAL = (('for_banks', 'А для банков?', 'dev'), ('small_org', 'А если организация малая?', 'dev'), ('exceptions', 'А исключения?', 'dev'),
                  ('pensioners', 'А для пенсионеров?', 'dev'), ('how_much', 'Сколько?', 'dev'), ('children_goods', 'А для детских товаров?', 'dev'),
                  ('individuals', 'А для физических лиц?', 'holdout'), ('under_what', 'А при каких условиях?', 'holdout'),
                  ('who_exempt', 'А кто освобождается?', 'holdout'))


def n09_follow_up(parent, child_text, group, name, violations, tag):
    question, old_stem, _ = parent
    with T.ctl('N09', question, tag, name, group=group) as sc:
        sc.ask(question)
        sc.answer(PARENT_ANSWER)
        sc.say(sc.chunks[0])
        _, actions = sc.ask(child_text, ground=False)
        lookups = [a['lookup_question'] for a in actions if a['type'] == 'lookup']
        if not lookups:
            T.collect(violations, f'{question}/{name}', f'«{child_text}» about a sourced question went to the model\'s memory ({[a["type"] for a in actions]})')
        elif not any(w.startswith(old_stem) for w in T.words_of(lookups[0])):
            T.collect(violations, f'{question}/{name}', f'the lookup for «{child_text}» does not carry the parent topic: {lookups[0]!r}')


@pytest.mark.parametrize('parent', parents_params())
def test_n09_a_recognised_clarification_of_a_sourced_question_is_looked_up_with_its_parent(parent):
    violations = []
    for name, text in N09_RECOGNISED:
        n09_follow_up(parent, text, parent[2], name, violations, 'recognised')
    T.assert_none(violations, 'N09 recognised clarification')


DEFECTS['DEF-T-B09'] = ('an elliptical clarification of a SOURCED question («А для банков?», «А если …?», «А исключения?», «Сколько?») does not inherit '
                        'the parent: it goes to the model\'s memory without a lookup, or is looked up without the parent topic '
                        '(generator.route_need and controlled_media._CONTEXT_FOLLOWUP list a few phrasings only)')


@pytest.mark.parametrize('parent', parents_params())
@defect('DEF-T-B09')
def test_n09_an_elliptical_clarification_of_a_sourced_question_keeps_its_parent(parent):
    violations = []
    for name, text, group in N09_ELLIPTICAL:
        if group == parent[2]:
            n09_follow_up(parent, text, group, name, violations, 'elliptical')
    T.assert_none(violations, 'N09 elliptical clarification')


# DEF-T-B10 (a clarification retired the old answer for good: no «продолжай» / «дальше» / «вернёмся к вопросу») is fixed by CL2 (NEXT, RESUME,
# the conversation map): strict XPASS on all 14 packs, mark removed at INTEG7.
N09_RETURNS = (('continue', 'продолжай'), ('next', 'дальше'), ('go_back', 'вернёмся к вопросу'))


@pytest.mark.parametrize('pack', T.pack_params())
def test_n09_after_a_clarification_the_listener_can_return_to_the_unspoken_part(pack):
    violations = []
    for name, phrase in N09_RETURNS[:2]:
        with T.ctl('N09', pack.key, 'return', name, group=pack.group) as sc:
            sc.ask(pack.question)
            answer = pack.claim('neg') + ' ' + pack.tail
            sc.answer(answer)
            parent_chunks = list(sc.chunks)
            # c23-final(B): c22-merge (G15, cloud_context/reports/c22-merge.md п.1, intended) cues the first sentence whole while it fits 9 words: medicine's answer is two portions now,
            # «Антибиотик подавляет размножение бактерий, но не действует на вирусы.» one of them. Two said, nothing was left unspoken: one is said, the last stays unspoken.
            told = min(2, len(parent_chunks) - 1)
            for chunk in parent_chunks[:told]:
                sc.say(chunk)
            sc.ask('Приведи пример', ground=False)
            sc.answer(pack.compound[3])
            sc.walk()
            before = len(sc.cues)
            sc.say(phrase)
            sc.tick(2)
            spoken = ' '.join(sc.cues[before:])
            if not T.covers(spoken, parent_chunks[told]):
                T.collect(violations, f'{pack.key}/{name}', f'after «{phrase}» the unspoken «{parent_chunks[told]}» was not resumed (cues: {sc.cues[before:]})')
    T.assert_none(violations, 'N09 return to the unclosed part')


# ==========================================================================================================================
# N10  «неправильно» is somebody else's comment, not an objection
# ==========================================================================================================================

WHO_DEV = ('преподаватель', 'оппонент', 'рецензент', 'коллега')
WHO_HOLDOUT = ('мой сосед', 'автор статьи')
N10_PACKS = ('physics', 'tax', 'biology', 'finance', 'history', 'medicine', 'ornithology', 'music')


def who_for(pack):
    pool = WHO_HOLDOUT if pack.group == 'holdout' else WHO_DEV
    return pool[PACKS.index(pack) % len(pool)]


def n10_retired(pack, utterances, name, kind):
    """Dictate to the middle of the claim, say ``utterances`` (a list of user turns), return whether the answer was retired."""
    with T.ctl('N10', pack.key, kind, name, group=pack.group) as sc:
        sc.ask(pack.question)
        sc.answer(pack.claim('neg') + ' ' + pack.tail)
        sc.say(sc.chunks[0])
        revision, cursor = sc.revision, sc.idx
        for number, text in enumerate(utterances):
            sc.say(text, gap=0.7 if number else JOIN_GAP)
        return sc.revision != revision or sc.idx != cursor


def n10_forms(pack, who):
    why = pack.head.split()[0].lower() + ' не так'
    return {
        'bare': ['Это неверно'], 'with_reason': [f'Нет, это неправильно, потому что {why}'],
        'colon_quote': [f'{who.capitalize()} говорит: это неправильно'], 'metalinguistic': ['Слово «неправильно» пишется слитно'],
        'said_that': [f'{who.capitalize()} сказал, что это неверно'], 'tail_reported': [f'Это неверно, сказал {who}'],
        'lead_reported': [f'Неправильно, говорит {who}, надо иначе'], 'split_quote': [f'{who.capitalize()} говорит', 'это неправильно'],
    }


def n10_params():
    return T.pack_params(N10_PACKS)


@pytest.mark.parametrize('pack', n10_params())
def test_n10_a_real_objection_retires_the_answer(pack):
    violations = []
    for name in ('bare', 'with_reason'):
        if not n10_retired(pack, n10_forms(pack, who_for(pack))[name], name, 'active'):
            T.collect(violations, f'{pack.key}/{name}', 'an objection to the answer did not retire it')
    T.assert_none(violations, 'N10 active objection')


@pytest.mark.parametrize('pack', n10_params())
def test_n10_a_quoted_word_that_is_not_the_start_of_an_objection_leaves_the_answer_alone(pack):
    violations = []
    for name in ('colon_quote', 'metalinguistic'):
        if n10_retired(pack, n10_forms(pack, who_for(pack))[name], name, 'quote-ok'):
            T.collect(violations, f'{pack.key}/{name}', 'the answer was retired by a quotation')
    T.assert_none(violations, 'N10 quotation')


DEFECTS['DEF-T-B11'] = ('somebody else\'s comment that contains «неверно/неправильно» retires the answer in progress: «X сказал, что это неверно» is read '
                        'as a question («что» within the first three words), «Это неверно, сказал X» and «Неправильно, говорит X …» as an '
                        'objection (user_intents.disagreement is anchored at the start and ignores a reporting verb), and the second half of a split '
                        'quote («X говорит» | «это неправильно») is an objection (classifier._trigger, user_intents._DISAGREEMENT)')


@pytest.mark.parametrize('pack', n10_params())
@defect('DEF-T-B11')
def test_n10_a_reported_objection_does_not_retire_the_answer(pack):
    violations = []
    for name in ('said_that', 'tail_reported', 'lead_reported', 'split_quote'):
        if n10_retired(pack, n10_forms(pack, who_for(pack))[name], name, 'reported'):
            T.collect(violations, f'{pack.key}/{name}', f'«{" | ".join(n10_forms(pack, who_for(pack))[name])}» retired the answer in progress')
    T.assert_none(violations, 'N10 reported objection')


# ==========================================================================================================================
# N11  the cancel coincides with the first PCM: a fence at the very boundary of sending, and nothing stale after it
# ==========================================================================================================================

N11_CAUSES = ('client_cancel', 'client_clear', 'provider_speech_started', 'new_question')
N11_STEPS = tuple(range(0, 11)) + (13,)       # event-loop iterations between "the cue is issued" and "the cancel": one iteration is one frame
N11_PACKS = (DEV[0], DEV[1], DEV[2], HOLDOUT[0])


def n11_inject(w, cause):
    if cause == 'client_cancel':
        w.client({'type': 'response.cancel'})
    elif cause == 'client_clear':
        w.client({'type': 'input_audio_buffer.clear'})
    elif cause == 'provider_speech_started':
        w.feed({'type': 'input_audio_buffer.speech_started'})
    else:
        w.feed(turn_created('nq', 'user', 'Что'))
        w.feed(turn_done('nq', 'user', N11_PACKS[3].question))


def n11_check(w, cause, before, violations, name):
    """After a cancel (and everything it started) has settled: nothing of the cancelled response goes to the phone after the fence."""
    wire = w.w
    if wire.violations:
        T.collect(violations, name, wire.violations[0].splitlines()[0])
    if wire.open is not None:
        T.collect(violations, name, f'a response is still open after the cancel: {wire.open.text!r}')
    for cue in wire.cues:
        if not (cue.done or cue.cleared):
            T.collect(violations, name, f'a response ended neither done nor cleared: {cue.text!r}')
    frames = [f for _, _, f in wire.frames]
    last_clear = max((i for i, f in enumerate(frames) if f.get('type') == 'output_audio_buffer.clear'), default=None)
    if last_clear is None:
        T.collect(violations, name, 'no output_audio_buffer.clear reached the phone')
    else:
        stale = [f['type'] for f in frames[last_clear + 1:] if f.get('type') in ('response.audio.delta', 'response.created', 'response.done')]
        if stale:
            T.collect(violations, name, f'frames after the fence: {stale[:3]}')
    if cause != 'new_question' and (w.state().get('revision'), w.idx) != before:
        T.collect(violations, name, f'the cancel moved the cursor {before} -> {(w.state().get("revision"), w.idx)}')


def n11_slots():
    return [pytest.param((cause, slot), id=f'{cause}-{N11_PACKS[slot].key}', marks=T.HOLD if N11_PACKS[slot].group == 'holdout' else ())
            for cause in N11_CAUSES for slot in range(len(N11_PACKS))]


@pytest.mark.parametrize('case', n11_slots())
def test_n11_a_cancel_at_every_point_of_the_send_path_leaves_nothing_stale(case):
    """The cue is issued; the loop is stepped ``n`` iterations (one send step each: synthesis, the first frame, the middle, the last frame,
    response.done); then the cancel arrives. Whatever ``n`` is: the response is cut off or finished, never both open, no frame follows the
    clear. The steps are shared out among the subjects (step k goes to subject k mod 4)."""
    cause, slot = case
    pack = N11_PACKS[slot]
    violations = []
    for steps in N11_STEPS[slot::len(N11_PACKS)]:
        with T.wire('N11', cause, f'steps={steps}', pack.key, group=pack.group) as w:
            w.ask(pack.question)
            w.feed(turn_done('a1', 'assistant', pack.claim('neg') + ' ' + pack.tail), settle=False)
            step_loop(w.w.loop, steps)
            w.trace.append(('step', steps))
            before = (w.state().get('revision'), w.idx)
            n11_inject(w, cause)
            w.w.settle()
            n11_check(w, cause, before, violations, f'{cause}/steps={steps}/{pack.key}')
    T.assert_none(violations, 'N11 cancel interleavings')


def step_loop(loop, iterations):
    """Run exactly ``iterations`` iterations of the event loop (one send step of the paced sender each)."""
    for _ in range(iterations):
        loop.call_soon(loop.stop)
        loop.run_forever()


@pytest.mark.parametrize('case', n11_slots())
def test_n11_a_cancel_that_arrives_while_the_synthesis_is_pending_leaves_no_audio_at_all(case):
    """Cancel after await: the cue is waiting for its PCM, the cancel comes, the PCM arrives later. The cancelled cue sends nothing."""
    cause, slot = case
    pack = N11_PACKS[slot]
    with T.wire('N11', cause, 'synthesis-held', pack.key, group=pack.group) as w:
        w.w.hold_synthesis()
        w.ask(pack.question)
        w.answer(pack.claim('exc') + ' ' + pack.tail)
        assert not w.w.cues, 'generator precondition: nothing is audible while the synthesis is held'
        n11_inject(w, cause)
        w.w.release_synthesis()
        audio = [f for f in w.frames('response.audio.delta')]
        created = [f for f in w.frames('response.created')]
        assert not audio and not created, f'a cancelled cue sent {len(created)} response(s) / {len(audio)} audio frames after its synthesis finished'
        assert not w.w.violations


def n11_engine_cases():
    return [pytest.param((pack, kind), id=f'{pack.key}-{kind}', marks=T.HOLD if pack.group == 'holdout' else ())
            for pack in N11_PACKS for kind in ('new_question', 'stop', 'correction')]


@pytest.mark.parametrize('case', n11_engine_cases())
def test_n11_a_late_answer_of_a_superseded_question_is_discarded_by_the_engine(case, tmp_path):
    """Classic route, real threads: the model's answer to question 1 arrives AFTER question 2 / «стоп» / a correction was accepted."""
    import threading
    from echo_sync.engine import EchoEngine
    pack, kind = case
    started, release = threading.Event(), threading.Event()
    late = pack.claim('neg') + ' ' + pack.tail
    fresh = pack.claim('cond') + ' ' + pack.tail

    def generate(question, history, context, request, model):
        if question == pack.question:
            started.set()
            assert release.wait(20), 'the test never released the first generation'
            return late
        return fresh

    engine = EchoEngine(tmp_path / 'e.sqlite3', generate)
    results = {}
    worker = threading.Thread(target=lambda: results.setdefault('first', engine_reply(engine, session_id='s', turn_id='t1', text=pack.question, request={}, model='m')))
    worker.start()
    assert started.wait(20), 'the first generation never started'
    follow = {'new_question': 'Что такое ' + pack.subject + ' на практике?', 'stop': 'стоп', 'correction': 'Нет, я имел в виду ' + pack.topic[1]}[kind]
    engine_reply(engine, session_id='s', turn_id='t2', text=follow, request={}, model='m')
    during = engine.state('s')
    release.set()
    worker.join(20)
    T.REGISTRY.add_unit('N11', (pack.key, kind, 'engine'), [pack.question, follow], pack.group)
    after = engine.state('s')
    assert not worker.is_alive()
    assert after['revision'] == during['revision'] and after['answer'] == during['answer'], 'the late answer of question 1 overwrote the state'
    assert late not in (after['answer'], results.get('first')), 'the late answer was spoken'


# ==========================================================================================================================
# N12  the network came back: what the new call may and may not do with the stored session
# ==========================================================================================================================

N12_CUTS = ('after_the_question', 'after_the_first_cue', 'after_one_confirmation', 'after_two_confirmations', 'in_the_middle_of_a_stream', 'after_the_end')
N12_PACKS = (DEV[0], DEV[1], DEV[3], HOLDOUT[0])


def n12_run(w, pack, cut):
    claim = pack.claim('cond') + ' ' + pack.tail
    w.ask(pack.question)
    if cut == 'after_the_question':
        return claim
    if cut == 'in_the_middle_of_a_stream':
        # F1 (wave F): the first cue of a stream is a meaning portion, published once its clause ends - the stream stops one word after
        # the first comma (at least the 6 words it always had), so that a portion is stored when the call drops
        words = claim.split()
        k = next(i for i, word in enumerate(words) if word.endswith(',')) + 2
        w.feed(turn_created('a1', 'assistant', ' '.join(words[:max(6, k)])))
        # c23-final(B): c22-merge (G15, cloud_context/reports/c22-merge.md п.1/3, intended) holds a first cue at a comma while the next clause may fit its 9 words: the stream goes on
        # word by word until the first portion is stored, still in the middle of the stream (the case under test: a reconnect with a portion stored and the answer streaming)
        for number, word in enumerate(words[max(6, k):-1], 1):
            if (w.state().get('chunks') or [None])[0]:
                break
            w.feed(turn_delta('a1', ' ' + word, number))
        assert w.state().get('chunks') and w.state().get('streaming'), 'precondition: a portion is stored in the middle of the stream'
        return claim
    w.answer(claim)
    steps = {'after_the_first_cue': 0, 'after_one_confirmation': 1, 'after_two_confirmations': 2, 'after_the_end': 99}[cut]
    for _ in range(steps):
        if w.current() is None:
            break
        w.say(w.current())
    return claim


def n12_cases():
    return [pytest.param((cut, pack), id=f'{cut}-{pack.key}', marks=T.HOLD if pack.group == 'holdout' else ()) for cut in N12_CUTS for pack in N12_PACKS]


@pytest.mark.parametrize('case', n12_cases())
def test_n12_a_reconnect_at_any_point_changes_nothing_by_itself_and_the_dictation_can_go_on(case):
    cut, pack = case
    violations = []
    if True:
        name = f'{cut}/{pack.key}'
        with T.wire('N12', cut, pack.key, group=pack.group) as w:
            claim = n12_run(w, pack, cut)
            before_state, before_cues = dict(w.state()), len(w.w.cues)
            w.w.reconnect()
            w.trace.append(('reconnect',))
            after_state = w.state()
            if len(w.w.cues) != before_cues:
                T.collect(violations, name, 'the reconnect itself spoke')
            changed = {k for k in ('revision', 'chunk_index', 'chunks', 'completed', 'answer') if before_state.get(k) != after_state.get(k)}
            closed_stream = bool(before_state.get('streaming') and not after_state.get('streaming'))
            if changed and not (closed_stream and changed <= {'chunk_index', 'completed'}):
                T.collect(violations, name, f'the reconnect changed the stored session: {sorted(changed)}')
            if cut == 'after_the_question':
                w.answer(claim)
                if not w.w.cues:
                    pass                                       # a reopened call stays quiet until the listener asks (quiet_reopen)
                w.say('повтори')
            elif not w.completed:
                w.say('повтори')
                if not w.w.cues or w.w.cues[-1].text != w.current():
                    T.collect(violations, name, f'«повтори» after the reconnect did not speak the stored portion {w.current()!r}')
            before_walk = len(w.w.cues)
            for _ in range(40):
                if w.current() is None:
                    break
                w.say(w.current())
            issued = [c.text for c in w.portions[before_walk:]]
            if not w.completed and w.state().get('streaming'):
                T.collect(violations, name, f'the dictation cannot finish after the reconnect (portion {w.idx} of {len(w.chunks)}, streaming)')
            if len(set(issued)) != len(issued):
                T.collect(violations, name, f'a portion was spoken twice after the reconnect: {issued}')
            if w.w.violations:
                T.collect(violations, name, w.w.violations[0].splitlines()[0])
    T.assert_none(violations, 'N12 reconnect')


DEFECTS['QUESTION-T-B12'] = ('every phone call of the product uses ONE session id («live-native-controlled-user-v1»): a new call about another subject '
                             'resumes the stored answer of the old one; the Conduit protocol has no subject hash for a server to compare — what '
                             'must identify the subject / voice route of a call? (controlled_host.controller_session_id)')


@defect('QUESTION-T-B12')
def test_n12_a_call_about_another_subject_does_not_resume_the_stored_conversation():
    from echo_sync import controlled_host
    first = controlled_host.controller_session_id({'subject_hash': 'aaaa'})
    second = controlled_host.controller_session_id({'subject_hash': 'bbbb'})
    T.REGISTRY.add_unit('N12', ('session-id',), ['aaaa', 'bbbb'])
    assert first != second, 'two calls about different subjects share the persisted session'


# ==========================================================================================================================
# N13  after 40 minutes of talk: the protected words of an early statement survive, verbatim, with their provenance
# ==========================================================================================================================

N13_FILLERS = (0, 4, 9)
N13_PACKS = (DEV[0], DEV[4], DEV[6], HOLDOUT[1])


def protected_fields(text):
    """The words and numbers of a statement that a summary must not lose: negations, conditions, numbers."""
    return {w for w in T.words_of(text) if w in ('не', 'ни', 'кроме', 'если', 'только', 'без', 'нет', 'нельзя') or w[0].isdigit()}


def protected_lost(original, compressed):
    return sorted(protected_fields(original) - protected_fields(compressed))


@pytest.mark.parametrize('pack', [pytest.param(p, id=p.key, marks=T.HOLD if p.group == 'holdout' else ()) for p in N13_PACKS])
def test_n13_an_early_statement_keeps_its_protected_words_after_a_long_conversation(pack):
    violations = []
    for fillers in N13_FILLERS:
        with T.ctl('N13', pack.key, f'fillers={fillers}', 'streamed' if fillers != 4 else 'whole', group=pack.group) as sc:
            thesis = pack.claim('neg') + ' ' + pack.qty[0].format(n=pack.qty[1]) + '.'
            sc.ask(pack.question)
            sc.answer(thesis, shape='words' if fillers != 4 else 'whole', delta_gap=0.05)
            sc.walk()
            for number in range(fillers):
                sc.elapse(180)                                  # three minutes of conversation between two questions
                other = PACKS[(PACKS.index(pack) + 1 + number) % len(PACKS)]
                sc.ask(f'Что такое {other.subject} на практике?')
                sc.answer(f'Это понятие {number + 1} описано в учебнике.')
                sc.walk()
            history = sc.state().get('history', [])
            early = history[0]['answer'] if history else ''
            lost = protected_lost(thesis, early)
            name = f'{pack.key}/fillers={fillers}'
            if early != thesis or lost:
                T.collect(violations, name, f'the early statement is no longer verbatim in the stored history; lost {lost}')
            if len(history) != fillers + 1:
                T.collect(violations, name, f'history has {len(history)} entries for {fillers + 1} answered questions')
            qid = sc.c.question_id
            if qid and (sc.c.ledger.snapshot(qid) is None):
                T.collect(violations, name, 'the ledger lost the question being answered')
            sc.checkpoint()
    T.assert_none(violations, 'N13 long context')


def test_n13_the_protected_field_check_catches_a_lossy_summary():
    original = 'Налог не взимается с пенсионеров, кроме тех, чей доход выше 30 тысяч, если они работают.'
    assert protected_lost(original, original) == []
    assert protected_lost(original, 'Налог взимается с пенсионеров, чей доход выше 30 тысяч.') == ['если', 'кроме', 'не']
    assert protected_lost(original, 'Налог не взимается с пенсионеров, кроме тех, чей доход выше тысяч, если они работают.') == ['30']
    T.REGISTRY.add_unit('N13', ('oracle',), [original])


# ==========================================================================================================================
# N14  looks short, is hard to say: syllables, rare terms, dates and the listener's pace decide, not the word count
# ==========================================================================================================================

def heavy_sentences(pack):
    return [pack.hard, pack.qty[0].format(n=pack.qty[1]) + '.']


@pytest.mark.parametrize('pack', T.pack_params())
def test_n14_no_issued_portion_is_heavier_than_the_listener_can_repeat(pack):
    """Every issued portion of a short but heavy statement has at most the call profile's words and syllables (F1, wave F: a meaning
    portion of up to 9 words / 26 syllables; it was 12 syllables of the short-cue profile, aim 8) unless it is one indivisible unit (one
    word, a number with its unit); a heavy statement over those caps is never one portion. Syllables are counted by an independent
    oracle (vowels; numbers as the spoken number), not by the production counter."""
    caps = resolve(CALL_SETTINGS)
    violations = []
    for number, sentence in enumerate(heavy_sentences(pack)):
        with T.ctl('N14', pack.key, f'sentence={number}', group=pack.group) as sc:
            sc.ask(pack.question)
            sc.answer(sentence)
            sc.walk()
            issued = distinct_in_order(sc.cues)
            for portion in issued:
                words = T.words_of(portion)
                unit = len(words) == 1 or (len(words) == 2 and any(w[0].isdigit() for w in words))
                if (T.vowel_syllables(portion) > caps['max_syllables'] or len(words) > caps['max_words']) and not unit:
                    T.collect(violations, f'{pack.key}/{number}', f'«{portion}» has {T.vowel_syllables(portion)} spoken syllables in {len(words)} words')
            heavy = T.vowel_syllables(sentence) > caps['max_syllables'] or len(T.words_of(sentence)) > caps['max_words']
            if heavy and len(issued) < 2 and len(T.words_of(sentence)) >= 3:
                T.collect(violations, f'{pack.key}/{number}', f'a heavy statement ({T.vowel_syllables(sentence)} syllables) is ONE portion: {issued}')
            if not sc.completed:
                T.collect(violations, f'{pack.key}/{number}', 'the dictation of the heavy statement did not complete')
    T.assert_none(violations, 'N14 portion load')


DEFECTS['DEF-T-B14'] = ('the portion size never adapts to the listener: after 3 or 5 failed repeats of one portion the portions still to come are cut '
                        'exactly as before (V3 5G: a future tail must follow the difficulty, with hysteresis; one stumble changes nothing). The '
                        'plan is fixed once per answer (engine.reply, portions(answer, cfg))')
N14_KINDS = (('partial', lambda portion: ' '.join(portion.split()[:1])), ('did_not_hear', lambda portion: 'не расслышал'))


def n14_tail_load(sc):
    return sum(T.vowel_syllables(c) for c in sc.chunks[sc.idx + 1:]) / max(1, len(sc.chunks[sc.idx + 1:]))


def n14_run(pack, fails, kind):
    with T.ctl('N14', pack.key, 'adapt', f'fails={fails}', kind[0], group=pack.group) as sc:
        sc.ask(pack.question)
        sc.answer(pack.claim('neg') + ' ' + pack.tail + ' ' + pack.hard)
        sc.say(sc.chunks[0])
        current, baseline = sc.chunks[sc.idx], n14_tail_load(sc)
        for _ in range(fails):
            sc.say(kind[1](current), gap=JOIN_GAP)
        return sc.chunks[sc.idx] == current, baseline, n14_tail_load(sc)


@pytest.mark.parametrize('case', [pytest.param((p, k), id=f'{p.key}-{k[0]}', marks=T.HOLD if p.group == 'holdout' else ())
                                  for p in (DEV[0], DEV[3], HOLDOUT[1]) for k in N14_KINDS])
def test_n14_one_stumble_changes_nothing_and_the_current_portion_never_changes(case):
    pack, kind = case
    stable, baseline, after = n14_run(pack, 1, kind)
    assert stable, 'the portion the listener is working on changed under their feet'
    assert after == baseline, f'one stumble already changed the plan of the tail ({baseline} -> {after} syllables per portion)'


@pytest.mark.parametrize('case', [pytest.param((p, k), id=f'{p.key}-{k[0]}', marks=T.HOLD if p.group == 'holdout' else ())
                                  for p in (DEV[0], DEV[3], HOLDOUT[1]) for k in N14_KINDS])
@defect('DEF-T-B14')
def test_n14_repeated_failure_shortens_the_portions_still_to_come(case):
    pack, kind = case
    for fails in (3, 5):
        stable, baseline, after = n14_run(pack, fails, kind)
        assert stable, 'the portion the listener is working on changed under their feet'
        assert after < baseline, f'{fails} failed repeats and the tail is still {after} syllables per portion (was {baseline})'


# ==========================================================================================================================
# N15  an exact fact nobody can know is replaced by a plausible one: the independent source oracle sees it, UNKNOWN stays visible
# ==========================================================================================================================

# (nominative, «в» + prepositional, group): places that exist in no model
ENTITIES = (('посёлок Верхние Тополи', 'в посёлке Верхние Тополи', 'dev'), ('деревня Нижний Увал', 'в деревне Нижний Увал', 'dev'),
            ('город Каменный Брод', 'в городе Каменный Брод', 'dev'), ('станция Малые Сосны', 'на станции Малые Сосны', 'dev'),
            ('село Светлый Ключ', 'в селе Светлый Ключ', 'holdout'), ('хутор Дальний Лог', 'на хуторе Дальний Лог', 'holdout'))


def entity_params():
    return [pytest.param(e, id=f'place{i}', marks=T.HOLD if e[2] == 'holdout' else ()) for i, e in enumerate(ENTITIES)]


def test_n15_the_support_oracle_sees_a_made_up_basis_and_not_a_formatting_difference():
    rows = [{'url': 'https://example.org/a', 'text': 'Население посёлка Верхние Тополи — 4 312 человек, основан в 1887 году.'}]
    question = 'Сколько жителей в посёлке Верхние Тополи?'
    assert T.unsupported_specifics('В посёлке Верхние Тополи живёт 4312 человек.', rows, question) == []
    assert T.unsupported_specifics('В посёлке живёт 4 312 человек, он основан в 1887 году.', rows, question) == []
    assert T.unsupported_specifics('В посёлке Верхние Тополи живёт 5 120 человек.', rows, question) == [('num', '5120')]
    assert ('num', '1901') in T.unsupported_specifics('Он основан в 1901 году.', rows, question)
    assert T.unsupported_specifics('Главой был Иванов.', rows, question) == [('name', 'иванов')]
    assert T.unsupported_specifics('Это известно.', rows, question) == []
    T.REGISTRY.add_unit('N15', ('oracle',), [question])


# DEF-T-B15 (the model's own delegation on the model-knowledge route was never served: «Нет ответа» after 8 s) is fixed by E3c item 4
# (``ControlledMedia.without_source`` 'delegated'): strict XPASS on all 6 entities, mark removed at INTEG7.


@pytest.mark.parametrize('entity', entity_params())
def test_n15_a_delegation_requested_by_the_model_is_served_with_a_lookup(entity):
    name, locative, group = entity
    violations = []
    for form_name, form in (('population', 'Сколько жителей {loc}?'), ('founded', 'Когда был основан {nom}?')):
        question = form.format(loc=locative, nom=name)
        with T.ctl('N15', name, 'delegation', form_name, group=group) as sc:
            tid, actions = sc.ask(question, ground=False)
            if any(a['type'] == 'lookup' for a in actions):
                continue                                          # the router already sends it to the sources: nothing to ask for
            actions = sc.feed({'type': 'delegation.created', 'item': {'id': 'd1', 'target': 'client', 'user_bidi_turn_id': tid}})
            actions += sc.tick(3.0)
            if not any(a['type'] in ('lookup', 'context') for a in actions):
                T.collect(violations, f'{name}/{form_name}', f'the model asked for sources for «{question}» and got none ({[a["type"] for a in actions]})')
    T.assert_none(violations, 'N15 delegation on the direct route')


DEFECTS['DEF-T-B16'] = ('a specific the sources do not carry (a number or a name the model made up) is dictated as a source-backed answer: '
                        'retrieval_status is «source_backed» because sources were SUPPLIED, not because the answer is supported by them '
                        '(controlled_media._source, generator.StreamingAnswer)')


@pytest.mark.parametrize('parent', parents_params())
def test_n15_an_answer_that_the_sources_support_is_dictated(parent):
    question, _, group = parent
    rows = [{'url': 'https://example.org/norm', 'text': 'Норматив составляет 25 процентов и действует с 2025 года.'}]
    with T.ctl('N15', question, 'supported', group=group) as sc:
        sc.ask(question, rows=rows)
        sc.answer('Норматив составляет 25 процентов. Он действует с 2025 года.')
        sc.walk()
        assert T.unsupported_specifics(' '.join(sc.cues), rows, question) == [] and sc.completed
        assert sc.state().get('retrieval_status') == 'source_backed'


@pytest.mark.parametrize('parent', parents_params())
@defect('DEF-T-B16')
def test_n15_a_specific_that_no_source_carries_is_not_dictated_as_source_backed(parent):
    question, _, group = parent
    rows = [{'url': 'https://example.org/norm', 'text': 'Норматив составляет 25 процентов и действует с 2025 года.'}]
    violations = []
    for variant, answer in (('number', 'Норматив составляет 31 процент. Он действует с 2025 года.'),
                            ('name', 'Норматив составляет 25 процентов. Его утвердил министр Воронцов в 2025 году.')):
        with T.ctl('N15', question, 'fabricated', variant, group=group) as sc:
            sc.ask(question, rows=rows)
            sc.answer(answer)
            sc.walk()
            made_up = T.unsupported_specifics(' '.join(sc.cues), rows, question)
            if made_up and sc.state().get('retrieval_status') == 'source_backed':
                T.collect(violations, f'{question}/{variant}', f'{made_up} was dictated and stored as source_backed')
    T.assert_none(violations, 'N15 unsupported specifics')


# ==========================================================================================================================
# N16  a faster first sound that made the useful answers slower: a guardrail over the FULL denominator
# ==========================================================================================================================

def A(outcome, pcm, useful):
    return T.Attempt(outcome, pcm, useful)


def test_n16_failures_stay_in_the_denominator_of_every_percentile():
    ten = [A('useful', 1.0 + i / 10, 3.0 + i / 10) for i in range(8)] + [A('silent', None, None), A('echo', 0.8, None)]
    report = T.latency_report(ten)
    assert report['n'] == 10 and report['useful_rate'] == 0.8
    assert report['useful_p90'] == T.INF, 'two failures in ten: the 90th percentile of the USEFUL answer is "never", not 3.7 s'
    assert report['first_pcm_p90'] < T.INF and report['first_pcm_p50'] < 2, 'the first SOUND of an echo counts as a sound: that is the headline number'
    assert T.latency_report(ten[:8])['useful_p90'] < 4, 'the same successes alone would look fine: that is the cheat'
    assert T.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, T.INF], 90) == 9 and T.percentile([1, 2, 3, 4, 5, 6, 7, 8, T.INF, T.INF], 90) == T.INF
    T.REGISTRY.add_unit('N16', ('report',), [len(ten)])


def test_n16_the_guardrail_rejects_what_a_faster_first_sound_pays_for():
    baseline = T.latency_report([A('useful', 2.0, 3.0 + i / 20) for i in range(20)])
    faster_but_worse = T.latency_report([A('useful', 0.6, 4.5 + i / 20) for i in range(20)])
    faster_but_rarer = T.latency_report([A('useful', 0.6, 3.0) for _ in range(17)] + [A('stall', 0.6, None)] * 3)
    cheat = T.latency_report([A('useful', 0.6, 3.0) for _ in range(17)])
    genuinely_better = T.latency_report([A('useful', 0.6, 2.5 + i / 20) for i in range(20)])
    assert faster_but_worse['first_pcm_p50'] < baseline['first_pcm_p50'], 'the trap: the headline number improved'
    assert 'useful_p90' in T.guardrail(baseline, faster_but_worse) and 'useful_p50' in T.guardrail(baseline, faster_but_worse)
    assert 'useful_rate' in T.guardrail(baseline, faster_but_rarer) and 'useful_p90' in T.guardrail(baseline, faster_but_rarer)
    assert 'denominator' in T.guardrail(baseline, cheat), 'a report with fewer attempts than the baseline is not comparable'
    assert T.guardrail(baseline, genuinely_better) == []
    T.REGISTRY.add_unit('N16', ('guardrail',), [1, 2, 3, 4, 5])


N16_STYLES = (('content', 'Времена года меняются из-за наклона земной оси. Поэтому полушария получают разное тепло.'),
              ('restates_only', 'Времена года меняются.'), ('stall_only', 'Сейчас проверю.'), ('silent', None),
              ('late_content', 'Времена года меняются из-за наклона земной оси. Поэтому полушария получают разное тепло.'))


def n16_attempt(style, text, group='dev'):
    """One real attempt through the production controller: the question, the cloud's behaviour, an ideal listener who repeats every cue
    0.8 s after it. Outcome by an independent reading of what was spoken."""
    question = 'Почему меняются времена года?'
    with T.ctl('N16', style, group=group) as sc:
        sc.ask(question)
        t_final = sc.clock()
        if style == 'late_content':
            sc.tick(5.0)
        if text:
            sc.answer(text, shape='words', delta_gap=0.2)
        diagnostics = sc.tick(10.0) if not sc.cues else []          # nobody to repeat: the watchdog speaks (a repeating listener never waits 10 s)
        sc.walk(limit=8)
        asked = {T.stem5(w) for w in T.words_of(question)}
        first_pcm = first_useful = None
        for stamp, cue, _, _ in sc.cue_log:
            if first_pcm is None:
                first_pcm = stamp - (t_final - sc.t0)
            if first_useful is None and any(T.stem5(w) not in asked and len(w) >= 4 for w in T.words_of(cue)):
                first_useful = stamp - (t_final - sc.t0)
        said = any(a['type'] == 'unanswered' for a in diagnostics + sc.actions)
        outcome = 'useful' if first_useful is not None else 'diagnostic' if said else 'echo' if first_pcm is not None else 'silent'
        return T.Attempt(outcome, first_pcm, first_useful)


def test_n16_real_attempts_keep_every_failure_in_the_report():
    attempts = [n16_attempt(style, text) for style, text in N16_STYLES]
    by_style = dict(zip([s for s, _ in N16_STYLES], attempts))
    assert by_style['content'].outcome == 'useful' and by_style['late_content'].outcome == 'useful'
    assert by_style['late_content'].first_useful > by_style['content'].first_useful + 4.0, (by_style, 'the late answer was measured as late')
    assert by_style['silent'].outcome == 'diagnostic', 'the question the cloud never answered ends in the spoken "no answer", never in silence'
    report = T.latency_report(attempts)
    assert report['n'] == 5 and report['useful_rate'] < 1.0 and report['useful_p90'] == T.INF
    assert T.latency_report([a for a in attempts if a.outcome == 'useful'])['useful_p90'] != T.INF, 'the cheating report would have looked finite'
    assert T.guardrail(report, T.latency_report([a for a in attempts if a.outcome == 'useful'])) != []


# ==========================================================================================================================
# N17  the judge and the implementation share a wrong premise: a blind gold and planted errors decide
# ==========================================================================================================================

FACTS = (
    T.Fact('toys', 'Какой налог на игрушки в стране Эльдория?', 'Налог на игрушки в стране Эльдория составляет 7 процентов.',
           ('Налог на игрушки в стране Эльдория составляет 12 процентов.',)),
    T.Fact('bridge', 'Когда построен мост Сильверн?', 'Мост Сильверн построен в 1873 году.', ('Мост Сильверн построен в 1921 году.',)),
    T.Fact('mount', 'Какова высота горы Тарвиль?', 'Высота горы Тарвиль составляет 2140 метров.', ('Высота горы Тарвиль составляет 3150 метров.',)),
    T.Fact('river', 'Куда впадает река Ольмара?', 'Река Ольмара впадает в озеро Лимар.', ('Река Ольмара впадает в море Кальвен.',)),
    T.Fact('law', 'Каков срок давности по закону Берана?', 'Срок давности по закону Берана составляет четыре года.',
           ('Срок давности по закону Берана составляет десять лет.',)),
    T.Fact('clinic', 'Сколько коек в клинике Арнис?', 'В клинике Арнис шестьдесят коек.', ('В клинике Арнис двести коек.',)),
)
HOLDOUT_FACT_KEYS = ('law', 'clinic')


def fact_params():
    return [pytest.param(f, id=f.key, marks=T.HOLD if f.key in HOLDOUT_FACT_KEYS else ()) for f in FACTS]


def shared_premise_judge(fact):
    """A judge that has the implementation's wrong belief: it accepts what contains the wrong statement."""
    return lambda answer: T.covers(answer, fact.wrong[0]) or not T.covers(answer, 'нет такого слова')


def independent_judge(fact):
    return lambda answer: T.covers(answer, fact.truth) and not T.covers(answer, fact.wrong[0])


@pytest.mark.parametrize('fact', fact_params())
def test_n17_the_gold_decides_when_the_judge_shares_the_implementations_error(fact):
    group = 'holdout' if fact.key in HOLDOUT_FACT_KEYS else 'dev'
    for implementation, wrong in (('wrong', True), ('right', False)):
        with T.ctl('N17', fact.key, implementation, group=group) as sc:
            sc.ask(fact.question)
            sc.answer(fact.wrong[0] if wrong else fact.truth)
            sc.walk()
            spoken = ' '.join(distinct_in_order(sc.cues))
            judge = shared_premise_judge(fact)(spoken)
            verdict = T.final_verdict(spoken, fact, judge)
            if wrong:
                assert verdict['verdict'] == 'FAIL' and judge is True, 'the shared-premise judge must have been fooled for this test to mean something'
                assert verdict['disagreement'] is True and verdict['verdict'] == 'FAIL', 'a gold FAIL is never turned into a pass by the judge; the clash is recorded'
            else:
                assert verdict['verdict'] == 'PASS'


def test_n17_a_judge_is_trusted_only_when_it_catches_the_planted_errors_including_its_own_premise():
    planted = [f.wrong[0] for f in FACTS]
    assert not T.trusted(shared_premise_judge(FACTS[0]), planted), 'the shared-premise judge accepts the planted error that matches its premise'
    assert T.judge_sensitivity(shared_premise_judge(FACTS[0]), planted) == 0.0
    assert T.judge_sensitivity(independent_judge(FACTS[0]), [FACTS[0].wrong[0]]) == 1.0
    sloppy = lambda answer: len(answer) > 5
    assert T.judge_sensitivity(sloppy, planted) == 0.0 and not T.trusted(sloppy, planted)
    assert T.trusted(lambda a: any(T.covers(a, f.truth) for f in FACTS), planted)
    T.REGISTRY.add_unit('N17', ('judge',), planted)


# ==========================================================================================================================
# N18  a short correction fixed the fact but forgot a question with three parts: the open obligations before and after the revision
# ==========================================================================================================================

DEFECTS['DEF-T-B18'] = ('a recognised correction retires the whole answer including the parts that were not spoken yet; the corrected short answer covers '
                        'only the corrected part and its confirmation completes the question: the unclosed sub-questions are dropped silently '
                        '(engine.reply STOP/QUESTION branches keep no obligation map; controlled_media._accept_user)')


@pytest.mark.parametrize('pack', T.pack_params())
@defect('DEF-T-B18')
def test_n18_a_correction_does_not_close_a_question_whose_other_parts_are_still_owed(pack):
    question, s1, s2, s3, correction, fixed = pack.compound
    violations = []
    for confirmed in (1, 2):
        with T.ctl('N18', pack.key, f'confirmed={confirmed}', group=pack.group) as sc:
            sc.ask(question)
            sc.answer(' '.join((s1, s2, s3)))
            assert len(sc.chunks) > confirmed + 1, 'generator precondition'
            for i in range(confirmed):
                sc.say(sc.chunks[i])
            revision = sc.revision
            sc.say(correction, gap=1.0)
            assert sc.revision == revision + 1, 'generator precondition: the correction must be recognised'
            sc.answer(fixed)
            sc.walk()
            spoken = ' '.join(sc.cues)
            missing = [name for name, sentence in (('fixed part', fixed), ('part 2', s2), ('part 3', s3)) if not T.covers(spoken, sentence)]
            if missing:
                T.collect(violations, f'{pack.key}/confirmed={confirmed}', f'the question was closed (completed={sc.completed}) with {missing} never spoken')
    T.assert_none(violations, 'N18 obligations after a correction')


@pytest.mark.parametrize('pack', T.pack_params())
def test_n18_a_correction_stops_the_old_audio_and_starts_the_new_revision_at_its_first_portion(pack):
    question, s1, s2, s3, correction, fixed = pack.compound
    with T.ctl('N18', pack.key, 'fresh-revision', group=pack.group) as sc:
        sc.ask(question)
        sc.answer(' '.join((s1, s2, s3)))
        sc.say(sc.chunks[0])
        old = set(sc.chunks)
        sc.say(correction, gap=1.0)
        assert sc.pending is None and sc.current() is None, 'nothing of the old answer may be waiting'
        sc.answer(fixed)
        assert sc.idx == 0 and sc.cues[-1] in sc.chunks and sc.cues[-1] not in old - set(T.portions_of(fixed)), 'the new revision starts at its first portion'


# ==========================================================================================================================
# N19  automatic repeats and the acoustic loop: bounded, no model, and the system's own voice never closes the loop
# ==========================================================================================================================

N19_PACKS = (DEV[0], DEV[3], DEV[6], HOLDOUT[2])


IDEMPOTENCY_PATTERNS = ('repeated_at_once', 'late_retransmit', 'stable_partial_then_final_twice')


REPEATING_UNITS = ('Раз, два, три.', 'Да, это важно.', 'Всё было верно.', 'Так бывает редко.', 'Время пошло.', 'Тихо и ясно.')   # (a sentence of function words only gets no cue)


def repeating_answer(pack):
    """An answer whose portions are identical (a short sentence said four times): only the turn id can tell a retransmitted confirmation
    from a second one."""
    return ' '.join([REPEATING_UNITS[PACKS.index(pack) % len(REPEATING_UNITS)]] * 4)


@pytest.mark.parametrize('pack', T.pack_params())
def test_n19_a_retransmitted_final_is_one_confirmation(pack):
    """The same user turn (same id, same words) delivered again - at once, three times, after the next cue was spoken, after its stable
    partial was accepted - moves the cursor exactly once; a NEW turn with the same words moves it again."""
    violations = []
    for pattern in IDEMPOTENCY_PATTERNS:
        with T.ctl('N19', pack.key, 'idempotency', pattern, group=pack.group) as sc:
            sc.ask(pack.question)
            sc.answer(repeating_answer(pack))
            portion = sc.chunks[0]
            assert len(set(sc.chunks)) == 1 and len(sc.chunks) >= 3, f'generator precondition: identical portions, got {sc.chunks}'
            sc.elapse(0.8)
            sc.start_speaking('c1')
            if pattern == 'stable_partial_then_final_twice':
                sc.feed(T.turn_delta('c1', portion, 1))
                sc.tick(0.4)
            event = turn_done('c1', 'user', portion)
            sc.feed(event)
            copies = {'repeated_at_once': 2, 'late_retransmit': 1, 'stable_partial_then_final_twice': 1}[pattern]
            if pattern == 'late_retransmit':
                sc.elapse(2.0)
            for _ in range(copies):
                sc.feed(dict(event))
            if sc.idx != 1:
                T.collect(violations, f'{pack.key}/{pattern}', f'one confirmation moved the cursor to {sc.idx}, not 1')
            if len(sc.cues) != 2:
                T.collect(violations, f'{pack.key}/{pattern}', f'one confirmation made {len(sc.cues) - 1} further cue(s), not 1')
            sc.say(portion, gap=2.5)
            if sc.idx != 2:
                T.collect(violations, f'{pack.key}/{pattern}', f'a second, NEW confirmation with the same words did not move the cursor to 2 ({sc.idx})')
    T.assert_none(violations, 'N19 idempotency')


@pytest.mark.parametrize('pack', T.pack_params())
def test_n19_the_engine_answers_a_retried_turn_id_without_moving_the_cursor_again(pack, tmp_path):
    from echo_sync.engine import EchoEngine
    engine = EchoEngine(tmp_path / 'e.sqlite3', lambda *a: repeating_answer(pack), settings={'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2})
    engine_reply(engine, session_id='s', turn_id='q1', text=pack.question, request={}, model='m')
    portion = engine.state('s')['chunks'][0]
    replies = [engine_reply(engine, session_id='s', turn_id='ack-1', text=portion, request={}, model='m') for _ in range(4)]
    T.REGISTRY.add_unit('N19', (pack.key, 'engine-retry'), [pack.key, portion], pack.group)
    assert engine.state('s')['chunk_index'] == 1, 'a retried turn id moved the cursor more than once'
    assert replies[0] == portion and all(r == portion for r in replies[1:]), replies
    engine_reply(engine, session_id='s', turn_id='ack-2', text=portion, request={}, model='m')
    assert engine.state('s')['chunk_index'] == 2


@pytest.mark.parametrize('pack', T.pack_params())
def test_n19_after_the_repeat_cap_the_wait_is_visible_in_the_log_and_nothing_more_is_said(pack, caplog):
    import logging
    caplog.set_level(logging.INFO, logger='echo-sync')
    with T.ctl('N19', pack.key, 'silence-cap', group=pack.group) as sc:
        sc.ask(pack.question)
        sc.answer(pack.claim('exc') + ' ' + pack.tail)
        cap = sc.c.max_auto_repeats                       # a profile value (3 by default; Task UX-trace changes the default): the test follows it
        sc.tick(60.0)
        assert len(sc.cues) == 1 + cap, f'{len(sc.cues)} cues in 60 s of silence (one cue + {cap} automatic repeats are the cap)'
        sc.tick(60.0)
        assert len(sc.cues) == 1 + cap and sc.idx == 0
    assert any('auto_repeat_cap' in r.getMessage() for r in caplog.records), 'the owner cannot tell from the log why the phone went quiet'


# ==========================================================================================================================
# N20  the fast path must not depend on the words of a subject it was written on
# ==========================================================================================================================

def test_n20_no_production_module_carries_a_lexicon_of_the_test_subjects():
    import ast
    from pathlib import Path
    import echo_sync
    folded = lambda s: s.casefold().replace('ё', 'е')
    words = [folded(w) for group in T.SUBJECT_WORDS.values() for w in group]
    found = []
    for path in sorted(Path(echo_sync.__file__).parent.glob('*.py')):
        if path.name.startswith('kb_'):
            continue                       # G2: published reference tables (article and account titles) are data, not behaviour
        tree = ast.parse(path.read_text(encoding='utf-8'))
        docs = {id(n.body[0].value) for n in ast.walk(tree) if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.body and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], 'value', None), ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                hit = [w for w in words if w in folded(node.value)]
                if hit:
                    found.append(f'{path.name}:{node.lineno} {hit} in {node.value[:50]!r}')
    T.REGISTRY.add_unit('N20', ('static',), [len(words)])
    assert not found, 'subject vocabulary in production code:\n  ' + '\n  '.join(found)


@pytest.mark.parametrize('pack', T.pack_params())
def test_n20_the_same_program_holds_its_invariants_on_every_subject(pack):
    """One program, no knowledge of the subject: question, answer, dictation, a new question in the middle, «стоп». The invariants are
    the product's own promises, none of them mentions a word."""
    violations = []
    shapes = ('whole', 'words') if pack.group == 'holdout' or pack.key in ('physics', 'tax', 'finance', 'construction') else ('whole',)
    for shape in shapes:
        with T.ctl('N20', pack.key, shape, group=pack.group) as sc:
            claim = pack.claim('exc') + ' ' + pack.tail
            sc.ask(pack.question)
            sc.answer(claim, shape=shape, delta_gap=0.05 if shape == 'words' else 0.0)
            name = f'{pack.key}/{shape}'
            if not sc.cues:
                T.collect(violations, name, 'no first cue')
                continue
            first = sc.cues[0]
            # F1 (wave F): the first cue is a meaning portion of up to MEANING_FIRST_MAX_WORDS words (WAVE 2 / L2 had up to 5)
            if len(T.words_of(first)) > MEANING_FIRST_MAX_WORDS or T.words_of(first) == T.words_of(pack.question):
                T.collect(violations, name, f'the first cue is {len(T.words_of(first))} words or the question read back: {first!r}')
            sc.say(sc.chunks[0])
            sc.say(sc.chunks[1])
            old = list(sc.chunks)
            sc.ask('Что такое ' + BY_KEY['physics' if pack.key != 'physics' else 'tax'].subject + '?', partial=True)
            sc.answer(BY_KEY['physics' if pack.key != 'physics' else 'tax'].claim('neg'))
            if sc.cues[-1] in old[2:] and sc.cues[-1] not in sc.chunks:
                T.collect(violations, name, 'an old portion was spoken after the new question')
            spoken_before_the_stop = len(sc.cues)
            sc.say('стоп')
            sc.tick(8)
            # «стоп» either wipes the answer (completed: the contract of master 75c8db2) or pauses it (Task CL2: the plan and the cursor are kept, nothing is
            # spoken until the listener asks): in both shapes the answer is no longer dictated and no audio follows the stop.
            stopped = sc.completed or bool(sc.state().get('paused'))
            if len(sc.cues) != spoken_before_the_stop or not stopped:
                T.collect(violations, name, f'«стоп» did not end the answer (cues {spoken_before_the_stop}->{len(sc.cues)}, completed={sc.completed}, '
                                            f'paused={sc.state().get("paused")})')
            if any(len(T.words_of(c)) > 8 for c in sc.cues):
                T.collect(violations, name, f'a cue longer than eight words: {max(sc.cues, key=len)!r}')
    T.assert_none(violations, 'N20 subject independence')


# ==========================================================================================================================
# MM  the metamorphic group: the meaning stays -> the verdict stays; cause / number / negation / subject changes -> the verdict changes
# ==========================================================================================================================

MM_INVARIANT = (
    ('lower_case', lambda p: p.lower()),
    ('upper_case', lambda p: p.upper()),
    ('no_punctuation', lambda p: re.sub(r'[^\w\s-]', '', p)),
    ('leading_filler', lambda p: 'ну ' + p),
    ('trailing_filler', lambda p: p + ' ну'),
    ('hesitation_first', lambda p: 'э-э ' + p),
    ('double_spaces', lambda p: p.replace(' ', '  ')),
    ('ellipsis_end', lambda p: p.rstrip('.,;:!?') + '...'),
)


def mm_insert_before_last(word):
    return lambda p: ' '.join(p.split()[:-1] + [word] + p.split()[-1:])


MM_SENSITIVE = (
    ('number_changed', lambda p: bool(re.search(r'\d', p)), lambda p: re.sub(r'\d+', lambda m: str(int(m.group()) + 1), p, count=1)),
    ('negation_dropped', lambda p: 'не' in T.words_of(p), lambda p: T.drop_word(p, 'не')),
    ('negation_inserted', lambda p: len(p.split()) >= 2, mm_insert_before_last('не')),
    ('quantifier_inserted', lambda p: len(p.split()) >= 2, mm_insert_before_last('все')),
    ('last_word_replaced', lambda p: len(p.split()) >= 2, lambda p: ' '.join(p.split()[:-1] + [OTHER_WORDS[len(p) % 4]])),
    ('first_word_replaced', lambda p: len(p.split()) >= 2, lambda p: ' '.join([OTHER_WORDS[len(p) % 3]] + p.split()[1:])),
    ('words_swapped', lambda p: len(set(p.split()[:2])) == 2, lambda p: ' '.join(p.split()[1::-1] + p.split()[2:])),
    ('modality_prefixed', lambda p: True, lambda p: 'возможно ' + p),
)


@pytest.mark.parametrize('pack', T.pack_params())
def test_mm1_a_repeat_with_the_same_meaning_in_another_surface_form_advances_exactly_once(pack):
    violations = []
    with T.ctl('MM1', pack.key, group=pack.group) as sc:
        sc.ask(pack.question)
        # F1 (wave F): meaning portions - the heavy statement and the three compound sentences make the answer long enough again
        sc.answer(pack.claim('cond') + ' ' + pack.tail + ' ' + pack.qty[0].format(n=pack.qty[1]) + '. ' + pack.hard + ' '
                  + ' '.join(pack.compound[1:4]))
        assert len(sc.chunks) >= len(MM_INVARIANT) + 1, 'generator precondition: the answer is long enough for one transform per portion'
        for name, transform in MM_INVARIANT:
            portion = sc.current()
            heard = transform(portion)
            before, cues = sc.idx, len(sc.cues)
            sc.say(heard)
            if sc.idx != before + 1:
                T.collect(violations, f'{pack.key}/{name}', f'«{heard}» for «{portion}» was not taken (cursor {before}->{sc.idx})')
            sc.checkpoint(name)
    T.assert_none(violations, 'MM1 invariance')


@pytest.mark.parametrize('pack', T.pack_params())
def test_mm2_a_repeat_whose_meaning_changed_never_advances(pack):
    violations = []
    with T.ctl('MM2', pack.key, group=pack.group) as sc:
        sc.ask(pack.question)
        sc.answer(pack.qty[0].format(n=pack.qty[1]) + '. ' + pack.claim('neg') + ' ' + pack.tail)
        for name, applicable, transform in MM_SENSITIVE:
            target = next((i for i in range(sc.idx or 0, len(sc.chunks)) if applicable(sc.chunks[i])), None)
            assert target is not None, f'generator precondition: no portion for {name}'
            while sc.idx < target:
                sc.say(sc.current(), gap=JOIN_GAP)
            portion = sc.current()
            heard = transform(portion)
            assert T.words_of(heard) != T.words_of(portion), (name, portion, heard)
            before, cues = sc.idx, len(sc.cues)
            sc.say(heard, gap=JOIN_GAP)
            if (sc.idx, len(sc.cues)) != (before, cues):
                T.collect(violations, f'{pack.key}/{name}', f'«{heard}» for «{portion}» moved the dictation (cursor {before}->{sc.idx})')
            sc.checkpoint(name)
        sc.say(sc.current(), gap=JOIN_GAP)
        if sc.idx == 0:
            T.collect(violations, f'{pack.key}/exact', 'the exact repeat after all the failed attempts was not taken')
    T.assert_none(violations, 'MM2 sensitivity')


def mm3_pairs(pack):
    head = pack.head[0].lower() + pack.head[1:]
    base = f'Правда ли, что {head}?'
    words = head.split()
    number_q = f'Верно ли, что {pack.qty[0].format(n=pack.qty[1])[0].lower() + pack.qty[0].format(n=pack.qty[1])[1:]}?'
    wrong_q = number_q.replace(pack.qty[1], pack.qty[2], 1)
    same = [('lower', base, base.lower()), ('upper', base, base.upper()), ('no_mark', base, base.rstrip('?')),
            ('spaces', base, '  '.join(base.split())), ('yo', base, base.replace('е', 'ё', 0))]
    differ = [('negation', base, f'Правда ли, что {words[0]} не {" ".join(words[1:])}?'), ('number', number_q, wrong_q),
              ('subject', base, f'Правда ли, что {OTHER_WORDS[len(head) % 4]} {" ".join(words[1:])}?'),
              ('order', base, f'Правда ли, что {" ".join([words[1], words[0]] + words[2:])}?'),
              ('not_a_question_about_it', base, f'Правда, что {head}.'),
              ('cause_and_effect_swapped', f'Верно ли, что {" ".join(words[:3])} из-за того, что {" ".join(words[3:])}?',
               f'Верно ли, что {" ".join(words[3:])} из-за того, что {" ".join(words[:3])}?')]
    return same, differ


@pytest.mark.parametrize('pack', T.pack_params())
def test_mm3_the_lookup_key_ignores_formatting_and_never_ignores_meaning(pack):
    """``native_prefetch.question_key`` decides whether a prefetched lookup may serve a question: the same words in another surface
    form are the same key; a changed negation, number, subject, word order or sentence type is another key."""
    from echo_sync.native_prefetch import question_key
    same, differ = mm3_pairs(pack)
    violations = []
    for name, a, b in same:
        T.REGISTRY.add_unit('MM3', (pack.key, name), [a, b], pack.group)
        if question_key(a) != question_key(b):
            T.collect(violations, f'{pack.key}/{name}', f'«{a}» and «{b}» are different keys')
    for name, a, b in differ:
        T.REGISTRY.add_unit('MM3', (pack.key, name), [a, b], pack.group)
        if question_key(a) == question_key(b):
            T.collect(violations, f'{pack.key}/{name}', f'«{a}» and «{b}» are the same key')
    T.assert_none(violations, 'MM3 question key')


MM4_FORMS = (
    ('canonical', 'Что такое {nom}?', True), ('explain', 'Объясни, что такое {nom}', True), ('tell_me', 'Расскажи мне про {acc}', True),
    ('mean', 'А что значит {nom}?', True), ('could_you', 'Можешь объяснить, что такое {nom}?', True), ('what_is_it', '{nom} — что это такое?', True),
    ('need_to_understand', 'Мне нужно понять, что такое {nom}', True), ('curious', 'Интересно, зачем нужен {nom}', True),
    ('please_describe', 'Пожалуйста, опиши {acc}', True), ('bare_term', '{nom}?', True),
    # the speaker's own need to understand (coordinator ruling at INTEG7: «мне/нам нужно|надо|необходимо|хочется|хотелось бы понять|узнать|…»)
    ('need_to_learn_about', 'Мне необходимо узнать про {acc}', True), ('would_like_to_figure_out', 'Нам хотелось бы разобраться, что такое {nom}', True),
    ('want_to_know', 'Хочу узнать про {acc}', False), ('do_not_understand', 'Не совсем понимаю, как работает {nom}', False),
)
DEFECTS['DEF-T-B20'] = ('a question put as an indirect request («Не совсем понимаю, как работает …») is silent: the classifier needs a question word among '
                        'the first three words, an imperative, «?» or one of the indirect-request openers it learnt (classifier._trigger; same family as the '
                        'seed F01 of Task T-A, whose forms - and «Хочу узнать про …» here - Task E3a fixed on master)')


def mm4_check(pack, expect_asked):
    violations = []
    with T.ctl('MM4', pack.key, 'asked' if expect_asked else 'indirect', group=pack.group) as sc:
        sc.ask('Что такое инерция?')
        sc.answer('Свойство тела сохранять скорость. Это важно.')
        sc.say(sc.chunks[0])
        for name, form, asked in MM4_FORMS:
            if asked != expect_asked:
                continue
            text = form.format(nom=pack.topic[0], acc=pack.topic[1])
            _, actions = sc.ask(text, ground=False)
            if not any(a['type'] in ('route', 'lookup') for a in actions):
                T.collect(violations, f'{pack.key}/{name}', f'«{text}» was not taken for a question ({[a["type"] for a in actions]})')
            sc.checkpoint(name)
    return violations


@pytest.mark.parametrize('pack', T.pack_params())
def test_mm4_a_question_said_in_another_way_is_still_a_question(pack):
    T.assert_none(mm4_check(pack, True), 'MM4 paraphrases')


@pytest.mark.parametrize('pack', T.pack_params())
@defect('DEF-T-B20')
def test_mm4_a_question_put_as_an_indirect_request_is_still_a_question(pack):
    T.assert_none(mm4_check(pack, False), 'MM4 indirect requests')


@pytest.mark.parametrize('pack', T.pack_params([p.key for p in PACKS if p.key in ('physics', 'tax', 'biology', 'finance', 'history', 'ornithology', 'music')]))
def test_mm5_a_revision_of_an_older_turn_never_touches_the_answer_that_is_being_dictated(pack):
    """ASR corrects what it heard of QUESTION 1 while question 2 is being dictated: only the claims linked to question 1 are its business;
    the answer to question 2 keeps its revision, its cursor and its audio."""
    other = PACKS[(PACKS.index(pack) + 1) % len(PACKS)]
    with T.ctl('MM5', pack.key, 'older-turn', group=pack.group) as sc:
        first, _ = sc.ask(pack.question)
        sc.answer(pack.claim('neg') + ' ' + pack.tail)
        sc.walk()
        sc.ask(other.question)
        sc.answer(other.claim('cond') + ' ' + other.tail)
        sc.say(sc.chunks[0])
        state, cues = (sc.revision, sc.idx), len(sc.cues)
        sc.feed(turn_done(first, 'user', 'Что такое ' + other.subject + ' и почему?'))
        sc.tick(2)
        assert (sc.revision, sc.idx) == state and len(sc.cues) == cues, 'a revision of an older question disturbed the current answer'


DEFECTS['DEF-T-B19'] = ('the provider\'s refined (second) final of an ALREADY accepted question is dropped even when ASR changed its meaning: '
                        'the answer to the OLD words keeps being dictated and the new words are never asked (controlled_media._accept_user '
                        'returns for ``tid in self.seen``; voice_turns keeps the revised text only)')


@pytest.mark.parametrize('pack', T.pack_params([p.key for p in PACKS if p.key in ('physics', 'tax', 'biology', 'finance', 'history', 'ornithology', 'music')]))
def test_mm5_a_surface_only_revision_of_the_final_asks_nothing_new(pack):
    with T.ctl('MM5', pack.key, 'surface', group=pack.group) as sc:
        tid, _ = sc.ask(pack.question)
        sc.answer(pack.claim('neg') + ' ' + pack.tail)
        revision, cues = sc.revision, len(sc.cues)
        sc.feed(turn_done(tid, 'user', pack.question.lower().rstrip('?')))
        assert sc.revision == revision and len(sc.cues) == cues, 'a re-punctuated final of the same question must change nothing'


@pytest.mark.parametrize('pack', T.pack_params([p.key for p in PACKS if p.key in ('physics', 'tax', 'biology', 'finance', 'history', 'ornithology', 'music')]))
@defect('DEF-T-B19')
def test_mm5_a_revision_of_the_final_that_changes_the_meaning_asks_the_new_words(pack):
    other = PACKS[(PACKS.index(pack) + 1) % len(PACKS)]
    with T.ctl('MM5', pack.key, 'meaning', group=pack.group) as sc:
        tid, _ = sc.ask(pack.question)
        sc.answer(pack.claim('neg') + ' ' + pack.tail)
        revision = sc.revision
        actions = sc.feed(turn_done(tid, 'user', 'Что такое ' + other.subject + '?'))
        assert sc.revision == revision + 1 or any(a['type'] in ('lookup', 'route') for a in actions), (
            f'ASR revised «{pack.question}» into «Что такое {other.subject}?» and the product went on with the old words')


# ==========================================================================================================================
# the count of what was really executed
# ==========================================================================================================================

def test_zz_the_scenarios_are_distinct_and_counted(request):
    """Runs last. A scenario is distinct by the trace of events it fed to the production code; a label that repeats is a retry.
    Prints the count of what was executed (a holdout run prints its own) and, with T_B_SCENARIO_LOG=<path>, writes every scenario there."""
    import os
    holdout_run = 'holdout' in (request.config.getoption('markexpr') or '')
    rows = [r for r in T.REGISTRY.rows if r[0] != 'META']
    by_class = {}
    for cls, key, digest, group in rows:
        by_class.setdefault(cls, set()).add((digest, group))
    unit = len({(c, h) for c, k, h, g in rows if k and k[0] == 'unit'})
    distinct = len({(c, h) for c, k, h, g in rows})
    print('\nT_B_SUMMARY ' + ' '.join(f'{c}={len(v)}' for c, v in sorted(by_class.items())) +
          f' | executed={len(rows)} distinct={distinct} (integration {distinct - unit}, unit {unit}) '
          f'dev={len({(c, h) for c, k, h, g in rows if g == "dev"})} holdout={len({(c, h) for c, k, h, g in rows if g == "holdout"})}')
    if os.environ.get('T_B_SCENARIO_LOG'):
        T.REGISTRY.dump(os.environ['T_B_SCENARIO_LOG'])
    if len(rows) < 200 and not holdout_run:
        pytest.skip('a partial selection was run: no count to check')
    if not holdout_run:
        assert not [r for r in T.REGISTRY.rows if r[3] == 'holdout'], 'a holdout scenario ran in the default run: the gate leaks'
    assert T.REGISTRY.labels_distinct() == [], f'the same scenario label ran twice (a retry): {T.REGISTRY.labels_distinct()[:3]}'
    assert distinct == len(rows), f'{len(rows) - distinct} scenarios fed the production code the same events as another one'

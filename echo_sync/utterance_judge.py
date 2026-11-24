"""U15: the judge of an utterance. S3: the verdicts of ``fast_text.meaning_guard`` and what a caller does with an unsure one."""
import re
SAME = 'same'              # the two texts say one thing (fillers, garbled endings aside)
DIFFERS = 'differs'        # a number, «не», a unit, a role, the kind of question or an object is another
UNKNOWN = 'unknown'        # one text lacks an atom the other has: it may be a drop of the ear, it may be the meaning
VERDICTS = (SAME, DIFFERS, UNKNOWN)

# What a caller does with UNKNOWN: today's behaviour is kept (nothing is cancelled, nothing is adopted) and the doubt is logged.
UNKNOWN_POLICY = 'keep_and_log'

UNKNOWN_ADDRESSED = 'listen'      # U15-S9: a final that may be read aloud and is not clearly asked is listened to (QUIET, nothing opened); it never answers on a doubt


READ_STOP_SHARE = 0.2      # Fable 10.11 (К13): below this share of function words a long breath is written text read aloud (a task from a sheet: 0.08, 0.14 in the calls), not talk (0.26-0.59 in 36 long remarks of 23 calls)
# The closed class of English function words (articles, prepositions, pronouns, auxiliaries, conjunctions): what ``STOPWORDS`` is for Russian. A grammatical class, not a list of phrases.
EN_FUNCTION_WORDS = frozenset('''a an the and or but so if then than that this these those there here it its is are was were be been being am do does did have has had will would can could
shall should may might must i you he she we they me him her us them my your his our their of in on at to from by with about as for into over under up down out off not no yes
just like okay ok well kind sort really very too also again what which who when where why how'''.split())


def reads_text(text):
    """Is ``text`` written language read aloud: almost no function words among its words? A quantity (``READ_STOP_SHARE``), the same for both languages."""
    from .textutil import STOPWORDS, norm_words
    words = norm_words(text)
    return bool(words) and sum(word in STOPWORDS or word in EN_FUNCTION_WORDS for word in words) < READ_STOP_SHARE * len(words)


def asks_in(part_words, raw):
    """Does this stretch of speech carry an ask feature: a '?', a question word or an imperative of asking? The one feature of 'a question', for the gate of U15-S9 and for the tail of B."""
    from .classifier import IMPERATIVE, QUESTION_WORDS
    return '?' in raw or any(word in QUESTION_WORDS for word in part_words) or bool(IMPERATIVE.search(' '.join(part_words)))


def asks_in_tail(text, tail_words=None):
    """An ask feature in the last ``tail_words`` words of ``text`` (``ASK_TAIL_WORDS`` by default)."""
    from . import settings as cfg
    from .textutil import norm_words
    tail_words = cfg.ASK_TAIL_WORDS if tail_words is None else tail_words
    return asks_in(norm_words(text)[-tail_words:], ' '.join(str(text).split()[-tail_words:]))


def asked_tail(text, tail_words=None):
    """B: the question at the end of a long remark, or ``''``. Where it stands is a COUNT: the last ``tail_words`` words (``ASK_TAIL_WORDS``). In them an ask feature (a question word, an
    imperative of asking) or a sum the code works out (``quick_math``: «семь умножить на восемь» asks no word and is asked all the same). The question is the clause the feature stands in,
    to the end of the remark; a sum, the longest stretch of the tail that is one. No feature in the tail: the remark asks nothing."""
    from . import settings as cfg
    from .quick_math import answer as worked_out
    from .textutil import norm_words
    tail_words = cfg.ASK_TAIL_WORDS if tail_words is None else tail_words
    words = str(text).split()
    base = max(0, len(words) - tail_words)
    start = next((i for i in range(base, len(words)) if worked_out(' '.join(words[i:]))), None)
    if start is None:
        mark = next((i for i in range(base, len(words)) if asks_in(norm_words(words[i]), words[i])), None)
        if mark is None:
            mark = base if asks_in_tail(text, tail_words) else None      # an imperative of asking is a phrase: it stands somewhere in the tail
        if mark is None:
            return ''
        start = mark
        while start > 0 and words[start - 1][-1:] not in ',.;:!?…':start -= 1      # the clause it stands in
    return ' '.join(words[start:])


PRESENTING = frozenset({'вот', 'смотри', 'посмотри', 'слушай', 'видишь', 'знаешь', 'говорится'})      # a word that presents what follows: the «что» after it joins a clause, it asks nothing
_DISCOURSE_WHAT = re.compile(r'(?:^|\s)что\s+(?:ж|же)\s*(?:[,.!…;:]|$)')      # «ну что ж, ...»: the speaker takes the floor, no ask


DOUBT_WINDOW_LINES = 2      # harvest11 #6 (BRAIN V1-V13): a bare doubt word counts as a doubt of the answer in play only while at most this many lines (itself included) were said after that answer; later it is other people's talk


def doubtful_what(raw, waiting=False):
    """U47/U59 «doubt does not break»: ``True`` when the ONLY ask feature of ``raw`` is a «что» that asks nothing: the discourse «что ж,» (anywhere), or, while a portion ``waiting`` is in hand, the
    «что» that a presenting word (``PRESENTING``) leads into a clause («так вот что я хотел сказать»). A '?', another question word, an imperative of asking, «что такое / значит / означает»: it asks."""
    from .classifier import IMPERATIVE, QUESTION_WORDS
    from .textutil import norm_words
    words = norm_words(re.sub(r'\bкак\s+говорится\b', 'говорится', str(raw).lower()))      # the saying «как говорится» asks no «как»
    asking = [i for i, word in enumerate(words) if word in QUESTION_WORDS]
    if '?' in raw or len(asking) != 1 or words[asking[0]] != 'что' or IMPERATIVE.search(' '.join(words)) or words[asking[0] + 1:asking[0] + 2] in (['такое'], ['значит'], ['означает']):
        return False
    return bool(_DISCOURSE_WHAT.search(str(raw).lower())) or bool(waiting and asking[0] and words[asking[0] - 1] in PRESENTING)


def not_addressed(text, sources, *, share=None, min_words=None, long_words=None, tail_words=None):
    """U15-S9: ``None`` when ``text`` may be a question, else ``('read', share)`` (most of its significant words are in ``sources``, the cues played lately or
    the listener's earlier words) or ``('long', None)`` (long and nothing in it asks). An ask feature in the last ``tail_words`` words (a question word, an
    imperative of asking, '?') always passes. Quantities only; the thresholds are those of settings."""
    from . import settings as cfg
    from .textutil import STOPWORDS, norm_words, stem
    share = cfg.READ_SHARE if share is None else share
    min_words = cfg.READ_MIN_WORDS if min_words is None else min_words
    long_words = cfg.LONG_READ_WORDS if long_words is None else long_words
    words = norm_words(text)
    if asks_in_tail(text, tail_words):
        return None
    heard = [stem(word) for word in words if word not in STOPWORDS]
    held = {stem(word) for source in sources for word in norm_words(source)}
    if len(heard) >= min_words and held and sum(word in held for word in heard) / len(heard) >= share:
        return 'read', sum(word in held for word in heard) / len(heard)
    if len(words) >= long_words and not asks_in(words, str(text)) and not reads_text(text):      # a sheet read aloud is a task: the job's verdict on it stands
        return 'long', None
    return None


ASK_ANSWER_STEMS, ASK_ANSWER_WORDS = 3, 8      # U35 (a): a long breath with no form is a task when the model's reply is a reply of substance (this many words) that carries this many significant words of it
ANSWER_STEMS, ANSWER_WORDS = 2, 4              # U117: a remark of somebody else answers the question asked when it is no shorter than this and says this many of the question's own significant words; «хороший вопрос» is a remark about it


def shares(asked, said, *, stems, words):
    """U35 (a) and U117, one count: do ``said`` (at least ``words`` words) and ``asked`` have at least ``stems`` significant words in common? Quantities only. U117 reads it with 'asks nothing itself' (``asks_in``): the narrowest reading,
    an answer that shares nothing with its question («Восемь.», «Да.») is not recognized and a prompt that was not needed is still given."""
    from .textutil import STOPWORDS, norm_words, stem
    heard = norm_words(said or '')
    return len(heard) >= words and len({stem(word) for word in norm_words(asked) if word not in STOPWORDS} & {stem(word) for word in heard if word not in STOPWORDS}) >= stems


# B: the kind of an utterance has ONE owner: the judge (``ControlledMedia._accept_user``), or this module where there is none (the plugin). The engine carries out the verdict it is given.
COMMAND_REASONS = {'ack': 'ack_ru_canonical', 'stop': 'stop_command', 'repeat': 'repeat_command'}      # what the engine wrote of a portion said back, «стоп», «повтори» (classifier.py)


def command_ruling(kind, reason=None, text=None):
    """B: the verdict of a command the controller gives as text (a portion as the listener's confirmation, «стоп», «повтори»), with the reason the classifier gave it. The ONE place that builds a verdict for the controller's
    rules: ``reason`` and ``text`` name the verdict of a rule of the judge (``remark_ruling``, ``answered_elsewhere``)."""
    from .classifier import Decision
    return Decision(kind, reason or COMMAND_REASONS[kind], text, None)


def going_verdict(decision, plan):
    """B: what going on does to the kind (CL2 ruling 4 + amendment A, once written in ``EchoEngine.reply``): ``plan`` is that of ``engine.going_on``."""
    from .classifier import QUESTION, REPEAT, RESUME
    if plan == 'question':
        return decision._replace(kind=QUESTION, reason=decision.reason + ':nothing_to_resume')
    if plan is not None and decision.kind == QUESTION:
        return decision._replace(kind=RESUME, reason='resume_topic')
    if plan == 'restore' and decision.kind == REPEAT:
        return decision._replace(kind=RESUME, reason='resume_abandoned')      # c8b: «повтори» after an abandoned portion
    return decision


def going_plan(engine, state, decision, heard=None):
    """B: the one place that asks the engine what going on means for a verdict (``(plan, target)`` of ``engine.going_on``): the judge's row ``going_on`` and a host with no controller (``plain_ruling``) both read it here."""
    from .engine import going_on, resume_window
    return going_on(state, decision, now=engine.clock(), window_s=resume_window(decision), heard=heard)


def plain_ruling(engine, session_id, text, *, bank=None, settings=None):
    """B: the verdict for a host with no controller (the plugin): the engine's former own reading of the text, the same classifier and the same going on, as the arguments of ``EchoEngine.reply``."""
    from .classifier import analyze
    from .settings import resolve
    state = engine.state(session_id)
    cfg = resolve(settings if settings is not None else engine.settings)
    decision = analyze(str(text or '').strip(), state, engine.bank if bank is None else bank, cfg)
    plan, target = going_plan(engine, state, decision)
    return {'decided': going_verdict(decision, plan), 'going': (plan, target) if plan is not None else None,
            'basis': (state['revision'], None) if state else None}


# U15-S1 / M1: the judge of one final in ``ControlledMedia._accept_user``. A pure carrier: ``JUDGE_RULES`` is the ordered table of ROWS, one ``Rule`` per kind verdict; ``ControlledMedia._judge`` walks it and decides nothing itself.
from dataclasses import dataclass, field
from typing import Callable, NamedTuple


class Rule(NamedTuple):
    """One row of the judge. ``fn(ctx)`` reads the context (``ctx.cm`` is the controller it runs in) and either returns a verdict (a ``Decision``; the walker writes it and names the row) or rewrites ``ctx`` itself
    (``ctx.decision`` + ``ctx.spoke(name)``) and returns None. ``pos_examples`` / ``neg_examples`` are scenes: ``(said_before..., text)`` where the row speaks / does not speak; ``tests/test_m1_rules.py`` drives
    every one through the real ``ControlledMedia``. ``after``: a feature or veto of the final verdict, run after the table (the table's own first match is taken before it)."""
    name: str
    fn: Callable
    pos_examples: tuple = ()
    neg_examples: tuple = ()
    after: bool = False
    first: bool = False      # a row of the first stage: it runs on the final BEFORE the bookkeeping of the final (``seen``, the candidate, the hearing flag) and may take the final whole (``c.taken``); the walker is the same, the stage is the call (``_judge(c, take=True)``)


def _method(name):
    """The body of a row that lives in the controller's family module (``ControlledMedia._rule_<name>``): late-bound, so a row is added by adding a ``Rule`` here, never by editing the walker."""
    def row(ctx):
        return getattr(type(ctx.cm), '_rule_' + name)(ctx.cm, ctx)
    row.__name__ = 'row_' + name
    return row


def _row(name, pos=(), neg=(), after=False, first=False):
    return Rule(name, _method(name), tuple(pos), tuple(neg), after, first)


# U15-S7 / follow-up class: a short turn with no topic of its own after discourse particles («ну пример», «а вот пример», «так, пример») continues the question before it exactly as «а пример» does.
# Decided by structure: the leading words are a closed GRAMMATICAL class of particles (``FOLLOW_LEADS``), what is left (at most ``FOLLOW_MAX_WORDS`` words) is the follow-up of ``followup.is_followup`` with the one canonical lead.
FOLLOW_LEADS = frozenset({'а', 'и', 'ну', 'так', 'вот', 'же', 'значит', 'слушай', 'э', 'эм', 'хм', 'тогда'})
FOLLOW_MAX_WORDS = 3


def followup_lead(c):
    """Row ``followup_lead``: the base left a follow-up silent (``mismatch_policy_silent``) only because its lead was not «а» or «и»: with the lead normalised it is the question before it, asked on. Returns the verdict or None."""
    from .classifier import QUESTION, QUIET
    decision = c.decision
    if c.tail or c.utterance or decision is None or decision.kind != QUIET or decision.reason != 'mismatch_policy_silent':
        return None
    from .engine import asked_of
    from .followup import is_followup
    from .textutil import norm_words
    words = norm_words(c.text)
    lead = 0
    while lead < len(words) and words[lead] in FOLLOW_LEADS:
        lead += 1
    core = words[lead:]
    asked = asked_of(c.state)
    if not lead or not core or len(core) > FOLLOW_MAX_WORDS or not asked or not is_followup(' '.join(['а'] + core), asked, strict=True):
        return None
    return command_ruling(QUESTION, 'short_contextual_followup', ' '.join(['а'] + core))


_Q = 'Что такое инерция?'      # the question in play of most scenes
_ASK = 'Какая ставка налога на доходы физических лиц?'      # the question of the dictating rig
# Scene kinds (``tests/test_m1_rules.py`` runs each one through the real ControlledMedia; the row is asserted to speak, or not, for the LAST thing said):
#   ('call', before, text[, extras])   helpers_night_memory.Call: ``before`` are finals said first; extras: 'profile' (settings), 'set' (attributes of the controller set before the last final)
#   ('rig', state, texts)              tools.replay.repeat_scenes rig, the answer to ``_ASK`` in flight ('dict': dictating, its first portion said; 'talk'); ``texts`` are the utterances, the last one is judged
#   ('corpus', row_id)                 a row of tests/fixtures/brain_eval_n2.json, its speech context said first
#   ('test', 'file::name')             a state the row needs (the ear, a veto, coalescing) is built by that test through the real controller; it is part of this packet's narrow run
JUDGE_RULES = (
    _row('recall', pos=[('call', (_Q,), 'повтори мои последние двадцать слов')], neg=[('call', (), 'повтори мои последние двадцать слов')]),
    _row('early_tail', pos=[('test', 'tests/test_ear_act.py::test_a_stop_said_after_the_repeat_in_the_same_breath_is_still_acted_on')], neg=[('call', (), _Q)]),
    # kind-accept (16.11, wave 3): the two finals that were taken in front of the judge (``_accept_user`` before its bookkeeping) are rows of the first stage: the final of a try the ear went on from; the repeat that goes on with other words
    _row('try_final', pos=[('test', 'tests/test_c22_repeat_wiring.py::test_the_cloud_final_of_a_try_the_ear_went_on_from_moves_nothing_more')],
         neg=[('test', 'tests/test_go_on_property.py::test_a_question_the_ear_heard_is_no_try_at_the_portion')], first=True),
    _row('head_repeat', pos=[('test', 'tests/test_split_repeat.py::test_the_live_split_repeat_is_one_confirmation')],
         neg=[('test', 'tests/test_split_repeat.py::test_a_whole_repeat_after_an_attempt_advances_exactly_once')], first=True),
    # kind-accept (16.11): the final that a path of its own takes whole (``c.taken``: the actions it left; the walker stops at the row that took it) is a row of the table, no branch of ``_accept_user`` before it
    _row('speech_opens', pos=[('test', 'tests/test_h6.py::test_a_command_opens_the_speech_as_the_plan')], neg=[('test', 'tests/test_h6.py::test_with_no_mode_a_material_and_no_question_say_nothing')]),
    _row('plan_back', pos=[('test', 'tests/test_h6.py::test_the_words_of_the_portion_bring_the_old_plan_back')], neg=[('test', 'tests/test_h6.py::test_r4_a_try_does_not_take_a_stopped_plan_back')]),
    _row('no_to_the_cue', pos=[('rig', 'talk', ('не так',)), ('corpus', 'b2_DS_003')], neg=[('rig', 'talk', ('ага',))]),
    _row('base', pos=[('call', (), _Q)], neg=[('call', (_Q,), 'повтори мои последние двадцать слов')]),
    _row('remark_form', pos=[('call', (_Q,), 'но ведь это не так'), ('call', (_Q,), 'дай переслушать')], neg=[('call', (_Q,), 'это так')]),
    Rule('followup_lead', followup_lead, (('call', (_Q,), 'ну пример'), ('call', (_Q,), 'а вот пример')), (('call', (_Q,), 'ну ладно'), ('call', (), 'ну пример'))),
    _row('long_talk', pos=[('corpus', 'b2_CH_042')], neg=[('call', (), _Q)]),
    _row('doubt', pos=[('rig', 'talk', ('Ну что ж, давайте продолжим',))], neg=[('rig', 'talk', ('что такое сила',))]),
    _row('cloud_admitted', pos=[('test', 'tests/test_g1_admit.py::test_the_reply_to_a_long_sentence_is_the_answer_and_the_waiting_portion_retires')],
         neg=[('test', 'tests/test_g1_admit.py::test_a_reply_cut_by_the_next_turn_admits_nothing')]),
    _row('bank_question', pos=[('test', 'tests/registry/test_fn_2_12.py::test_bank_question_after_a_long_talk')],
         neg=[('test', 'tests/registry/test_fn_2_04.py::test_4_a_slip_in_the_number_is_a_wrong_repeat_even_with_a_row_in_the_bank')]),
    _row('dispute', pos=[('corpus', 'b2_CH_009')], neg=[('call', (), _Q)]),
    _row('tempo_help', pos=[('test', 'tests/test_c24_a2.py::test_the_late_final_of_a_try_the_ear_helped_with_goes_on_under_the_rule')],
         neg=[('test', 'tests/test_go_on_property.py::test_a_question_the_ear_heard_is_no_try_at_the_portion')]),
    _row('landmark_said', pos=[('test', 'tests/test_c24_landmark_wiring.py::test_from_the_word_includes_it')],
         neg=[('test', 'tests/test_c24_landmark_wiring.py::test_a_word_of_the_next_portion_jumps_over_nothing')]),
    _row('gate_talk', pos=[('call', (), 'Миша, ты зарядку не видел?'), ('call', (), 'Ну что, давайте задавайте любой вопрос')], neg=[('call', (_Q,), 'Миша, ты зарядку не видел?')]),
    _row('read_again', pos=[('rig', 'dict', (_ASK,)), ('rig', 'dict', ('какая ставка налога на доходы физических лиц тринадцать процентов?',))], neg=[('rig', 'dict', ('Что такое налоговый вычет?',))]),
    _row('asked_again_unheard', pos=[('test', 'tests/test_c24_a2.py::test_the_question_asked_again_before_its_answer_was_heard_is_the_same_request')],
         neg=[('test', 'tests/test_c24_question_again.py::test_a_changed_question_is_a_new_question')]),
    _row('joined_repeat', pos=[('test', 'tests/test_split_repeat.py::test_a_repeat_torn_into_several_pieces_is_joined')],
         neg=[('test', 'tests/test_split_repeat.py::test_fragments_in_the_wrong_order_are_not_a_confirmation')]),
    _row('past_the_veto', pos=[('test', 'tests/test_c24_a2.py::test_p11_the_next_portion_said_after_its_cue_sounded_is_where_the_owner_is')],
         neg=[('test', 'tests/test_c24_a2.py::test_p11_the_next_portion_said_with_no_cue_of_it_heard_takes_no_step')]),
    _row('went_to_the_answer', pos=[('call', (_Q,), 'дальше', {'set': {'fast_mark': {'uid': 'u9', 'word': 'стоп', 'job': None, 'at': 0.0}}})],
         neg=[('call', (_Q,), 'Что такое сила?', {'set': {'fast_mark': {'uid': 'u9', 'word': 'стоп', 'job': None, 'at': 0.0}}})]),
    _row('joined_question', pos=[('corpus', 'b2_RH_048')], neg=[('call', (), _Q)]),
    _row('request_goes_on', pos=[('test', 'tests/test_w1f_command_fragments.py::test_the_fragments_of_one_return_never_retire_the_answer_it_restored')],
         neg=[('test', 'tests/test_w1f_command_fragments.py::test_a_real_question_after_a_local_request_is_still_a_question')]),
    _row('answered_elsewhere', pos=[('test', 'tests/test_u117_answered_by_other.py::test_a_question_another_person_answered_gets_no_prompt')],
         neg=[('test', 'tests/test_u117_answered_by_other.py::test_an_answer_not_known_to_be_another_voice_withholds_nothing')]),
    _row('not_addressed', pos=[('rig', 'talk', ('Какая основная ставка налога на доходы составляет 13 процентов пособие по беременности не облагается налогом',))],
         neg=[('rig', 'talk', ('Что такое налоговый вычет?',))], after=True),
    _row('ear_number_veto', pos=[('test', 'tests/test_ear_number_veto.py::test_989_heard_by_the_ear_blocks_the_stable_partial_988_of_the_cloud')],
         neg=[('test', 'tests/test_ear_number_veto.py::test_precondition_the_portion_under_test_waits')], after=True),
    _row('going_on', pos=[('call', (_Q,), 'дальше')], neg=[('call', (_Q,), 'повтори')], after=True),
    _row('own_voice', pos=[('test', 'tests/test_own_voice_guard.py::test_in_shadow_mode_a_suspect_final_advances_and_is_logged_as_suspect')], neg=[('call', (), _Q)], after=True),
    _row('held', pos=[('test', 'tests/test_h6.py::test_a_mark_waits_while_the_speech_goes_on_and_a_question_takes_it_away'), ('test', 'tests/test_c25_a_veto.py::test_a_repeat_asked_after_a_newer_question_is_no_old_answer')],
         neg=[('call', (_Q,), 'повтори')], after=True))
RULE_NAMES = tuple(rule.name for rule in JUDGE_RULES)


@dataclass
class AcceptCtx:
    turn: dict
    boundary: str
    tail: bool
    whole: str
    utterance: bool
    admitted: bool
    gated: bool
    tid: object
    text: str
    state: object
    decision: object = None
    pieces: tuple = ()
    disputed: bool = False
    local: object = None                    # U14-S6: the answer a rule already has (the recall's verbatim words), given to ``_open_question``
    cause: object = None                    # X-TURN: why this final is judged (the name the turn record keeps)
    going: object = None                    # B: ``(plan, target)`` of ``engine.going_on`` for the verdict (a feature of the verdict, worked out by ``_rule_going_on``; None: not about going on)
    analyses: int = 0                       # calls of ``analyze`` the judge made for this final
    early: bool = False                     # the final is that of a turn the stable partial or the ear has already taken: the row ``early_tail`` judges it and settles it
    actions: object = None                  # the actions a row has already taken for the final (a settled final: the walker goes no further); None: none taken
    evidence: object = None                 # the witness that the final is our own cue heard back (row ``own_voice``): a feature, never a drop
    taken: object = None                    # kind-accept: the actions of a row that took this final whole (the prepared speech opened, the suspended plan taken back); None: no row did
    hold: object = None                     # kind-accept: what the verdict says of this final's step, not its kind: 'stop_waits' (a stop waits for the ear's silence), 'repeat_waits' (a repeat after a newer question is nobody's)
    cm: object = None                       # M1: the controller the rows run in (set by ``_judge``)
    chain: list = field(default_factory=list)   # the rules that changed the verdict or the text, in the order they did
    steps: list = field(default_factory=list)   # U15-S11: what each of them left behind: (rule, decision, text, turn, state, pieces)

    def spoke(self, rule):
        """A rule changed the verdict (or the text it is made of)."""
        self.chain.append(rule)
        self.steps.append((rule, self.decision, self.text, self.turn, self.state, self.pieces))

    @property
    def rule(self):
        return self.chain[-1] if self.chain else 'base'

    def line(self):
        """The one ``judge`` log line of the final."""
        decision = self.decision
        return 'echo-sync judge tid=%s kind=%s reason=%s rule=%s chain=%s analyses=%s' % (
            self.tid, getattr(decision, 'kind', None), getattr(decision, 'reason', None), self.rule, '>'.join(self.chain) or '-', self.analyses)


def first_match(ctx):
    """U15-S11: the ordered rule table, first match by priority: the step of the first rule of ``JUDGE_RULES`` that spoke with a verdict
    (a rule that spoke before the base had run has none: skipped), else ``None`` (the base verdict stands). ``not_addressed`` is no step of the table: it is a terminal veto applied after it."""
    for step in ctx.steps:
        if step[1] is not None and step[0] != 'not_addressed':
            return step
    return None


# X-TURN (U15 S5): ONE record per utterance (tid). U14 takes ``final_rev`` from it, U20's OrderLedger takes ``epoch``. It decides nothing by itself.
# The first decision stands: an untyped second one is refused and counted; a typed one is a new ``final_rev`` of the same record.
from .reasons import REVISE_CAUSES, is_revise_cause, known      # M1: the closed registry of names (a later look at the same words, named: exactly seven)
RESOLUTION_KEEP = 256


class Resolutions:
    def __init__(self, keep=RESOLUTION_KEEP):
        self.keep = keep
        self.records = {}          # tid -> record, in the order they came
        self.untyped = 0           # second decisions with no named cause
        self.unknown_kinds = 0     # verdict kinds that are not in ``reasons.KINDS``

    def resolve(self, tid, *, resolution, cause=None, epoch=None, onset=None, rule=None, reason=None, revision=None, going=None):
        """Record the decision on ``tid``. Returns ``(record, outcome)``; outcome: 'new', 'same' (the very same decision again), 'revised' (typed),
        'untyped' (a second decision with no named cause: refused). B: the record also keeps why (``reason``), the engine revision the verdict was made on (with ``epoch``:
        the key a verdict is checked against) and the plan of going on that goes with it."""
        if not known('kind', resolution):
            self.unknown_kinds += 1      # M1: a kind outside the closed registry is refused and counted, never recorded
            return self.records.get(tid) or {'tid': tid, 'final_rev': 0, 'resolution': resolution, 'cause': cause, 'void_by': None, 'answered': False, 'epoch': epoch}, 'unknown_kind'
        old = self.records.get(tid)
        if old is None:
            rec = {'tid': tid, 'final_rev': 1, 'resolution': resolution, 'cause': cause, 'void_by': None, 'answered': False, 'epoch': epoch, 'onset': onset, 'rule': rule,
                   'reason': reason, 'revision': revision, 'going': going}
            self.records[tid] = rec
            while len(self.records) > self.keep:
                self.records.pop(next(iter(self.records)))
            return rec, 'new'
        if old['resolution'] == resolution and old['cause'] == cause:
            return old, 'same'
        if is_revise_cause(cause):
            old.update(final_rev=old['final_rev'] + 1, resolution=resolution, cause=cause, rule=rule, reason=reason, revision=revision, going=going)
            if epoch is not None:
                old['epoch'] = epoch
            return old, 'revised'
        self.untyped += 1
        return old, 'untyped'

    def get(self, tid):
        return self.records.get(tid)

    def line(self, rec, outcome):
        return 'echo-sync resolution tid=%s final_rev=%s resolution=%s cause=%s outcome=%s epoch=%s void_by=%s' % (
            rec['tid'], rec['final_rev'], rec['resolution'], rec['cause'], outcome, rec['epoch'], rec['void_by'])


# U118: an objection («но ведь это не так», «ты путаешь»), a clarification («в смысле», «что ты имеешь в виду») and a repeat are three remarks about the answer in play. The classifier tells the plain ones apart; these are the forms
# it left silent or took for a question of its own. Whole-remark forms over normalized words (a stray «не так» inside a longer sentence is no objection). The rule rewrites only QUIET (mismatch_policy_silent) and QUESTION (question_word).
import re as _re
OBJECTION_FORMS = _re.compile(r'(?:(?:но|а|нет)\s+)*(?:(?:ведь|же)\s+)*(?:это|так)\s+(?:совсем\s+|вовсе\s+)?не\s+так|ты\s+(?:что-то\s+|опять\s+|снова\s+)?(?:путаешь|врёшь|врешь|ошибаешься)')
CLARIFICATION_FORMS = _re.compile(r'(?:а\s+)?в\s+смысле|(?:а\s+)?что\s+(?:ты\s+)?(?:имеешь\s+в\s+виду|хочешь\s+сказать)|(?:то\s+есть\s+)?как\s+это\s+понимать|то\s+есть\s+как(?:\s+это)?')
RELISTEN_FORMS = _re.compile(r'(?:(?:ну|а|так|и|пожалуйста|можно|можешь|давай|дай|хочу|хотел|хотела|бы|я|мне|нужно|надо)\s+)*(?:еще\s+раз\s+)?(?:(?:пере|про|по)слуша(?:ть|ю|ем)|слушать|с\s+начала|сначала)(?:\s+(?:еще|раз|разок|снова|заново|ответ|его|это|последнюю|часть|пожалуйста))*')      # U153: a request to hear the answer again (a listening verb, or «с начала»): not a question, not a new one
COMPLAINT_FORMS = _re.compile(r'(?:ну\s+)?(?:как\s+же\s+ты\s+надоел|что\s+ты\s+нес[её]шь|что\s+за\s+(?:ерунда|чушь|бред|ахинея)|сколько\s+можно)')      # U108 (5): a complaint with an ask WORD in it and no ask: the plan stands
REMARK_REASONS = {'mismatch_policy_silent', 'question_word', 'not_a_question', 'modal_request'}      # the base verdicts a form may rewrite


def remark_form(text):
    """'objection', 'clarification', 'complaint', 'relisten' or None: the whole remark is one of the forms."""
    from .textutil import norm_words
    said = ' '.join(norm_words(text))
    if OBJECTION_FORMS.fullmatch(said):
        return 'objection'
    if RELISTEN_FORMS.fullmatch(said):
        return 'relisten'
    if COMPLAINT_FORMS.fullmatch(said):
        return 'complaint'
    return 'clarification' if CLARIFICATION_FORMS.fullmatch(said) else None


def remark_ruling(text):
    """U118, U108 (5): the verdict of a remark that is one of the forms (None when it is none): an objection is a correction of the answer, a clarification asks about it, a complaint is no question (the plan begun stays)."""
    from .classifier import CORRECTION, QUESTION, QUIET, REPEAT
    form = remark_form(text)
    if form == 'complaint':
        return command_ruling(QUIET, 'complaint_no_ask')
    if form == 'relisten':
        return command_ruling(REPEAT)      # U153: asked to hear it again: the portion said again, no new generation
    return command_ruling(*{'objection': (CORRECTION, 'objection_form'), 'clarification': (QUESTION, 'clarification_request')}[form], text) if form else None

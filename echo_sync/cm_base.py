"""The module level of the former ``controlled_media.py``: imports, constants and helpers the family mixins and ``ControlledMedia`` read."""
# cm-split: the module level of the former controlled_media.py, verbatim; controlled_media re-exports every name of it
import collections
import ipaddress
import json
import logging
import re
import sys
import threading
import uuid
import time
from difflib import SequenceMatcher
from urllib.parse import urlsplit

from .classifier import CLOSED, OPEN, ACK, QUESTION, CORRECTION, Decision, GREETING, STOP, QUIET, REPLAY, REPEAT, QUESTION_WORDS, _NOT_THIS_BUT, ATTEMPT_REASONS
from .engine import EchoEngine,PublicationRefused,SILENT
from . import search_identity
from .ru_alignment import match_current,whole_portions,without_repeats,_OPTIONAL_LEADING,_lemma,_ABBREVIATIONS,_UNITS
from .flow_ahead import FlowAhead,progress as tail_progress
from .local_ear import PauseLearner
from .generator import StreamingAnswer,CHANGES,hedged,route_need,unhedged
from .portioner import stable_prefix
from .settings import CALL_SETTINGS,resolve
from .timer_policy import ANSWER_GRACE_SECONDS,CONFIRM_SECONDS,WRONG_REPEAT_SECONDS,MERGE_PATIENCE_SECONDS,SEGMENT_IDLE_SECONDS
from .timer_policy import EAR_ASK_HOLD_SECONDS, EAR_SPEECH_SECONDS, OWNER_SILENCE_S      # EAR_ASK_HOLD_SECONDS: defined once, in timer_policy (E43)
from .timer_policy import ABANDON_SECONDS, CONTEXT_AGE_S, FIGURE_HEAD_SECONDS, FIGURE_STILL_SECONDS, NO_AFTER_CUE_SECONDS, PLAN_BACK_SECONDS, PLAYED_FRESH_S, READ_USER_WINDOW_S, SPLIT_JOIN_SECONDS, WITNESS_SLACK_SECONDS      # the ages: defined once, in timer_policy
from .utterance_judge import AcceptCtx,JUDGE_RULES,REMARK_REASONS,Resolutions,remark_ruling,ANSWER_STEMS,ANSWER_WORDS,ASK_ANSWER_STEMS,ASK_ANSWER_WORDS,asked_tail,asks_in,command_ruling,doubtful_what,first_match,going_verdict,not_addressed,reads_text,shares
from .reserve_text import REFUSAL
from .timer_policy import Stamped,STAMPED_SLOTS,stale_slots,ACK_JOIN_SECONDS,HEARING_SECONDS,ACK_STABLE_SECONDS,PARTIAL_STABLE_SECONDS      # one-timers: these three deadlines are defined once, in the registry
from .pace import Pace
from .input_state import InputMeter,OTHER_LANGUAGE
from .lang_hint import TurnLang,ear_foreign,counts as lang_counts
from .stumble_place import place as stumble_place
from .repeat_rule import gate,silence,DICTATION_START_SECONDS,DictationPace,landmark,landmark_command,verdict as rule_verdict,written_to
from .voice_turns import FramelessTurns
from .conversation_ledger import BACK,ConversationLedger
from .timer_policy import CONVERSATION_GAP_S,LOOKUP_TIMEOUT_S,ONSET_HOLD_MAX_S
from .timer_policy import CUE_TAIL_SECONDS,CUE_SYNTHESIS_SECONDS,ECHO_MIN_LAG_SECONDS,INPUT_CLOCK_SLACK_MS      # defined once, in timer_policy
from .timer_policy import ANSWER_WAIT_SECONDS,LOOKUP_WAIT_SECONDS,LOOKUP_ANSWER_WAIT_SECONDS,ANSWER_CAP_SECONDS,REFUSE_BEFORE_DROP_SECONDS,FIRST_HOLD_CAP_SECONDS,HANDED_BACK_WAIT_SECONDS      # the answer waits: defined once, in timer_policy
from .recall import parse as recall_parse,resolve as recall_resolve
from pathlib import Path
from .textutil import about_itself,strip_process_prefix,drop_process_sentences,definition_body,talks_about_itself
from .personal_volatile import personal_volatile,honest_reply
from .abbrev_state import Abbreviations
from .gate_text import TALK as GATE_TALK,decide as gate_decide
from .cm_probes import probe
from .stable_text import _protected as _protected_word
from .fast_text import HISTORY_EXCHANGES,_atoms,_protected,_values,COMMAND_SAID,FIRST_TEXT_S,reads_out,adds_nothing,answer_keeps,caught_up,ear_disputes,ends_like,most_said,said_share,brain_answer,brain_command,doubts,asks_again,of_the_answer,revises,said_within,same_question,same_start,unmarked,wide_refusal
from .native_prefetch import question_key
from .reference_kb import lookup as reference_lookup,preload as reference_preload
from .first_useful import asks_for_more,compact_opening,first_cue,says_a_number
from .question_lead import lead,splice as lead_splice,trace_row as lead_row
from .quick_math import answer as quick_answer,asked as quick_asked,stated as quick_stated
from . import instant
from . import why_journal
from .textutil import FUNCTION_WORDS,NUMBER_WORDS,STOPWORDS,WORDS,destutter,norm_words,normalize,stem
from .user_intents import HESITATION_WORDS,fold_asr,hearing_repair,is_confirmation_tag,is_repeat_request,pause_split
# CL2 (rulings 4 and 5): going on and the spoken progress for the model (the block at the end of ControlledMedia).
from .classifier import NEXT,RESUME
from .followup import QuestionMap,TOPIC_MARK,complete as complete_followup,is_followup
from .diagnostics import reason_of
from . import privacy_gate
from . import two_witnesses
from . import answer_witness as witness_rule
from . import answer_conditions
from .ear_command import early_command
from .engine import UNASKED, asked_of, call_history, conversation_map, going_on, new_call_plan, resume_window, state_age, unfinished, unfinished_at, answered_after, plan_entry, resumable
from .progress_notes import progress_note, reconnect_note

_SERVICE=re.compile(r'^(?:да[,!\s]+|хорошо[,!\s]+|сейчас\b|уточню\b|проверю\b|ищу\b|отправляю\b|принято\b|гермес\b)',re.I)
logger=logging.getLogger('echo-sync')
# c25-b: a word problem, a sum told as a condition: «если у меня было 60 рублей и я потратил 90 рублей, сколько денег осталось». Its «у меня» is no private affair, and the ear,
# which hears no comma nor «?», may open its job (``_ear_opens_job``): it starts with «если», names two numbers or more, and asks «сколько … осталось / стало / получится» at its end
_WORD_PROBLEM_END=re.compile(r'\bсколько(?:\s+\w+){0,3}?\s+(?:осталось|останется|остаётся|остается|стало|станет|получилось|получится|будет|всего|вместе)(?:\s+\w+){0,2}\s*[?.!…]*\s*$',re.I)
def word_problem(text):
    text=str(text or '')
    return bool(re.match(r'\s*если\b',text,re.I) and len(_values(_atoms(text)))>=2 and _WORD_PROBLEM_END.search(text.replace('ё','е').replace('Ё','Е')))
_ENDS_SENTENCE=re.compile(r'[.!?…][»”"\)]*\s*$')
# The end of the old sentence whose rest opens a new answer's first segment (see ControlledMedia._interrupted_head); «3.5» is no end.
_HEAD_TERMINATOR=re.compile(r'(?<!\d)[.!?…]+(?!\d)[»”"\)]*')

# G5: how many times ONE unconfirmed portion is re-spoken on its own while the listener says nothing. The listener's
# repeat, «повтори» or a new question resume normally; after the cap the prompter waits instead of repeating for ever.
MAX_AUTO_REPEATS=3
# u18: the owner talks by themselves: this many utterances of other speech in a row at one portion (``tempo_others``) make its hold last MONOLOGUE_QUIET_SECONDS of quiet instead of TEMPO_HOLD_SECONDS (``_hold_s``).
MONOLOGUE_OTHERS=2
MONOLOGUE_QUIET_SECONDS=15.0
ABANDON_SHARE=0.30
ABANDON_FINALS=1
_MOVED_ON=frozenset({'unrelated_speech','weak_question_ignored','speech_too_long_for_an_attempt','remark_to_prompter'})
# Wave G (the owner's call 04.11 09:41: «48 умножить на 10» -> silent while the cloud answered «Четыреста восемьдесят.»): the closed grammar does
# not decide what is a question, the cloud model does. A final with one of these verdicts - the classifier has no evidence either way - stays a
# CANDIDATE (``_take_candidate``): no try at the portion, no command, no remark to the prompter, no small talk, no own voice, no pause. It is
# ADMITTED by the first of: the reference base has its answer, the model delegates it, the model's own reply holds a sentence of substance.
_NO_EVIDENCE=frozenset({'not_a_question','unrelated_speech','mismatch_policy_silent','speech_too_long_for_an_attempt','weak_question_ignored'})
# H2 (rule 2): with the text channel on, the job judges these too: speech the arbiter does not act on, and no try at the portion.
_LEAD_PREPOSITION=re.compile(r'\s*(в|во|на|с|со|к|ко|по|за|до|от|из|о|об|у)\s+',re.IGNORECASE)     # H2: the job's answer in the form of the question leaves it out: «988 году.»
_HYPHENS=re.compile(r"[-’']")      # F3: «из-за» is «из» «за» when the recognizer cuts it
_OPTIONAL_STEMS=frozenset(stem(word) for word in _OPTIONAL_LEADING)      # F4: the connectors a repeat may leave out (ru_alignment._OPTIONAL_LEADING)
_STALLS=re.compile(r'(?<![\w-])(?:значит|короче|типа|как бы|в общем|это самое|так сказать)(?![\w-])')      # F5: what people lean on while they look for the next word
_SIGNS=re.compile(r'[%‰°₽$€£¥]')      # F6: the sign of a unit is no word
_FOR_THE_BRAIN=_NO_EVIDENCE|frozenset({'remark_to_prompter','rhetorical_exclamation','clarification_without_answer','ambiguous_repair_policy_silent','dispute_of_the_portion'})
FAST_TURN='fast-'       # the id of a job's turn in the ledger, with its number
_SPOKEN_SENTENCE=re.compile(r'[^.!?…]+[.!?…]+(?=\s|$)')
CALL_QUESTIONS=3     # how many questions of THIS call the reference base and the prepared answers see (a follow-up «а 27-я?» takes the code from them): the one window, the selector is ``call_exchanges``
# W1F-B (class C2, W1 groups G2/G5): the provider splits ONE utterance into several user turns at its short pauses («…четыре на пять
# метров» | « Нет» | «, подождите. Комната пять на шесть метров»; «Как называется наука, которая изучает» | « грибы»). A user turn that
# BEGAN within ``coalesce_seconds`` of the previous final of the question's utterance goes on with it (``_continuation``): it is judged
# with the joined utterance, never against a portion of the answer to the unfinished question. It joins when it is at most
# UTTERANCE_TAIL_WORDS words and, alone, nothing the controller acts on; a longer one (at most UTTERANCE_FIX_WORDS) only when it corrects
# the question (a self-correction opener, «не X, а Y», or two of the question's own content words said again).
UTTERANCE_TAIL_WORDS=5
UTTERANCE_FIX_WORDS=12
# Alone, these say that the question is about to be corrected, and nothing else: «Нет», «Ой, подождите», «Вернее», «Я ошибся».
_FIX_OPENER=r'(?:нет|ой|подожди(?:те)?|постой(?:те)?|погоди(?:те)?|обожди(?:те)?|секунд(?:у|очку)|минут(?:у|ку)|вернее|точнее|то есть|не так|' \
            r'я ошиб(?:ся|лась)|ошиб(?:ся|лась)|неверно|неправильно)'
_FIX_ONLY=re.compile(r'^(?:'+_FIX_OPENER+r'\s*)+$')
_FIX_START=re.compile(r'^'+_FIX_OPENER+r'(?:\s|$)')
# W1F-B (C4): the verdicts that are a real try at the waiting portion (classifier: by alignment, by shared stems about as long as it, or
# mostly its words). An uncertain «а?» / «что?» (attempt_clarification) is not one: noise for the silence timer, nobody for the count.
_YES_NO_HEADS=frozenset('нужно надо можно нельзя следует должен должна должно должны правда верно значит получается'.split())      # c22-speed ``cloud_form``: a question these begin is a question only by its «?»


def _said_within(text,said):
    """g28: are the words of ``text`` (two at least, a number one of them: «шестьдесят второй счёт» is «#62 счет») said in a row in one of ``said``? ``adds_nothing`` wants two words
    besides the numbers; a number and its noun said back are the same echo."""
    try:
        heard=[atom.atom for atom in _atoms(text)]
        if len(heard)<2:return False
        for one in said:
            atoms=[atom.atom for atom in _atoms(one)]
            if any(atoms[at:at+len(heard)]==heard for at in range(len(atoms)-len(heard)+1)):return True
        return False
    except Exception:return False
MORE_DETAIL=re.compile(r'\b(?:по)?подробн|\bразверн[уи]т|\bрасскажи\s+больше\b',re.I)
TRY_FINAL_SECONDS=8.0     # g17: the cloud's final of a try the ear went on with comes this late at most: it is that try, not a word to the portion after it
# ACK-split (live, 02.11): the cloud may hear ONE repeat of a portion as several consecutive turns («свойство тела» |
# «сопротивляться изменению своего движения»). The speech since the portion started is matched with the fragments joined in
# order: not further apart than ACK_JOIN_SECONDS (counted between the arrivals of the finals), at most ACK_JOIN_FRAGMENTS
# pieces (the one that has just arrived included).
ACK_JOIN_FRAGMENTS=4
# The longest single producer turn the ledger keeps whole. An answer of any length is dictated, so this is far above what the model is
# asked to say (1-2 sentences); it only bounds the memory of a call (the old limit, 4000 characters, silently dropped a long answer).
MAX_TURN_CHARS=60000
# L1 latency: the provider's final transcript arrives ~0.8 s after its text is known, and 96 % of the ACK -> next portion wait is
# that. A partial transcript that fully matches the waiting portion (the same matcher: every content word, numbers and «не»/«ни»
# exact) and has not changed for this long is accepted as the confirmation; the final of the same utterance is then ignored
# (the turn is already taken), so it can never advance a second time.
# R-EAR-ACT (``local_ear`` = "act", ear_shadow.py; scripts/DUAL_SYSTEM_DESIGN.md §3.3): the local ear's confirmations, repeat requests, stops
# and «дальше» act at once, through the path a cloud final takes (``ear_heard``). Its speech detector ends an utterance after 300 ms of
# quiet, so a comma or a breath cuts ONE repeat into pieces (S1 bake-off: 20 % of the TTS phrases; its one false ACK was «Не а, …» cut
# after «не»): pieces each begun at most EAR_JOIN_GAP_SECONDS after the end of the one before, at most EAR_JOIN_PIECES of them, are judged
# as one. The ear takes the cloud's open turn of the same utterance - announced at most EAR_ANNOUNCE_SLACK_SECONDS before the ear heard
# the speech begin, and (when the provider says where its speech began) begun within the utterance, EAR_START_SLACK_MS of padding
# allowed - as the stable partial does, so that the turn never acts again. The cloud announces a turn 0.3-2.3 s after the speech began:
# a verdict that finds none waits EAR_BIND_SECONDS for it, then the cloud decides alone. After a take, a new turn of the cloud is a later
# piece of the same utterance (the cloud cuts where the ear did not) when the ear has heard nothing new since and it is announced within
# EAR_PIECE_SECONDS of the end of that utterance, and - when the provider says where its speech began - that was more than
# EAR_PIECE_GRID_MS (its 200 ms grid) before the end the ear heard.
EAR_JOIN_GAP_SECONDS=1.0
EAR_JOIN_PIECES=3
EAR_ANNOUNCE_SLACK_SECONDS=0.3
EAR_START_SLACK_MS=700
EAR_BIND_SECONDS=1.5
EAR_PIECE_SECONDS=2.0
EAR_PIECE_GRID_MS=200
# c9-numveto (the ear contradicting a confirmation of the CLOUD, for a number only; ``_ear_number_veto``): the ear's utterance is the one the
# cloud's turn holds when the turn was announced from EAR_ANNOUNCE_SLACK_SECONDS before to this long after the ear heard the speech begin
# (the cloud announces a turn 0.3-2.3 s after the speech began).
EAR_ANNOUNCE_MAX_SECONDS=2.5
# H3 (the owner's call of 4 Nov 20:34: «ты мне подсказываешь секунд через шесть, через семь»; the ear tempo, ear_shadow.for_call): the tempo of the prompter is kept by the local ear. The cloud's
# transcript came ~3 s after the ear's text, and its growth kept ``hearing`` alive long after the listener had stopped. While the ear runs, ``hearing`` is its detector, the silence timer starts from the end
# of a cue and what the ear hears decides at the offset of an utterance (``_tempo_heard``):
# - no speech: the portion again after ``repeat_seconds``, TEMPO_STEP_SECONDS more for each further automatic repeat of it (the cap is ``repeat_rule.repeat_cap``: ``max_auto_repeats`` unless the dictation cycle runs);
# - a start of the portion that stopped: what is missing, TEMPO_START_SECONDS after its offset with no cloud final; a start said twice, TEMPO_TWICE_SECONDS;
# - a hesitation (no content word at all, or noise of TEMPO_FRAGMENT_WORDS words at most, none of the portion's): the wait goes on, and the portion comes TEMPO_FILLER_SECONDS after it;
# - other speech, or a try or a command the cloud's final is to confirm: the timer does not fire (``tempo_hold``). That final, or the job's verdict on it, runs it again; TEMPO_HOLD_SECONDS when neither comes.
# H5 item 1 (n1_01 step 8: «Дальше задачка.» ended at a comma, the timer fired 0.03 s later over 15 s of question): whatever the timer says, nothing is replayed within TEMPO_FILLER_SECONDS of the ear's last offset, nor while it hears speech. A start that stopped keeps its times.
# The cloud's start of speech comes up to ~3 s late (53.3, 56.2 of the call: at the end of the utterance and after it): TEMPO_ANNOUNCE_SECONDS after the ear heard speech end it is news of that speech, it
# cuts no cue. The ear's text came 0.12-0.75 s after the offset in the call: TEMPO_TEXT_SECONDS with none means it has been dropped, and nobody knows what was said.
TEMPO_STEP_SECONDS=1.5
PACE_QUIET_SECONDS=0.3     # W5: the ear's detector ends an utterance 300 ms after the speech (its silence window): the last word ended that long before the offset
TEMPO_START_SECONDS=1.2
_LEDGERS=collections.OrderedDict()      # M1-e: (db path, session) -> the memory ledger of the session: a redial (a new controller) goes on with it; the newest LEDGERS_KEPT sessions only
LEDGERS_KEPT=4


class CallDictation:
    """c22-repeat / c24-c: THE one place that says whether the owner is dictating: said by voice only («диктуй медленно» / «хватит диктовать»: ``said``; no profile key); and the owner's tempo of writing (``pace``). Both outlive a reconnect of the same session: the session's ledger holds them (dictation-carry: its kind
    'dictation', ``ConversationLedger.KINDS``), as it holds the topic; the plan and the cursor outlive it in SQLite. The classifier only names the command (``analyze``),
    the controller only passes the reason here."""

    def __init__(self, ledger, clock):
        self.ledger, self.clock, self.said, self.pace = ledger, clock, None, DictationPace()
        kept = ledger.held('dictation', 'session', clock()) if ledger is not None else None
        if kept:
            self.said, self.pace.per_word, self.pace.seen = json.loads(kept)

    def on(self):
        return self.said is True

    def heard(self, reason):
        """The classifier's ``dictation_on`` / ``dictation_off``: the setting for the rest of the call. True when it was one."""
        if reason not in ('dictation_on', 'dictation_off'):
            return False
        if self.on() != (reason == 'dictation_on'):
            logger.info('echo-sync dictation=%s reason=said', reason[10:])
        self.said = reason == 'dictation_on'
        self.keep()
        return True

    def keep(self):
        """What the owner said of dictation and their tempo, for the next call of this session (the ledger's kind 'dictation', within its time)."""
        if self.ledger is None:
            return
        self.ledger.hold('dictation', 'session', None, json.dumps([self.said, self.pace.per_word, self.pace.seen]), self.clock())

REPEAT_SAID='повтори'      # c24-c: what a question read again while writing stands for (``_read_again``)
LANDMARK_SECONDS=0.3         # c24-c: «повтори со слова X» / «последнее записанное слово X»: asked for, said this soon after its end
TEMPO_TWICE_SECONDS=0.6
TEMPO_FILLER_SECONDS=1.5
_JOINS=frozenset({'а','и','но','то','ну','так','тогда','вот','да'})
_ORDER_SHAPE=re.compile(r'\w{3,}(?:ите|йте)|\w{4,}(?:ть|ти)')
TAIL_HEAD_WORDS=2      # h31: ``_reference_tail``
_NO_WORDS=frozenset({'нет','неа','не','то','так','неправильно','неверно','это','совсем'})
_NO_HEADS=frozenset({'нет','неа','не','неправильно','неверно'})
_NO_REAL=frozenset({'не','неправильно','неверно'})
NO_ANOTHER='Нет, это не так. Дай другой ответ.'
TEMPO_FRAGMENT_WORDS=2
TEMPO_BLANK_WORDS=5
TEMPO_PAUSE_SECONDS=4.0     # g25: «секунду», «сейчас», «дай вспомнить»: the owner asks for time (TEMPO_PAUSE): no cue into it and no job; this long after its end, the portion or what is missing of it
# H6 item 6: see HOLD_BOUNDS. No final EAR_FINAL_SECONDS after the speech: the job runs on the ear's text (the cloud's final came up to 3.7 s behind the ear on the phone), and its first text has FIRST_TEXT_S: so a hold after speech ends at TEMPO_HOLD_SECONDS.
EAR_FINAL_SECONDS=4.0
TEMPO_HOLD_SECONDS=EAR_FINAL_SECONDS+FIRST_TEXT_S
FIRST_HOLD_SECONDS=8.0
TEMPO_ANNOUNCE_SECONDS=4.0
TEMPO_TEXT_SECONDS=1.5
# What a hesitation is, by class and never by phrase. The word will not come (TEMPO_BLANK, up to TEMPO_BLANK_WORDS words): «не могу вспомнить», «вылетело из головы»: help is what they ask for, however long it is
# said. A question word is the job's however short («где», «сколько лет»), unless it looks for the word itself (TEMPO_SEEKING: «как там», «как его», «что там»).
TEMPO_BLANK=re.compile(r'(?<![\w-])(?:забыл\w*|забыт\w*|вылетел\w*|вспомн\w*|не\s+помн\w*|запамятова\w*)(?![\w-])')
TEMPO_SEEKING=frozenset({'там','его'})
# H4 (the owner's call of 4 Nov 20:34; ``fast_text`` = "on" and ``local_ear`` = "act"): on the phone the cloud's final came ~3 s after the ear's (59.0/56.4, 150.4/147.1, 244.8/241.7). Rule 1: a plain reference the base
# answers is opened from the ear's text, on the cloud's open turn, or when that is announced (EAR_BIND_SECONDS, as for a confirmation). Rule 2 (no key: fast_text on, ear acting): so is a question in a strong form (EAR_STRONG_FORMS),
# once the job prepared on it has given its first sentence and the ear's silence has lasted EAR_RELEASE_SILENCE_SECONDS, while what the cloud has of it so far agrees (``same_start``). The final then only says whether the ear
# heard right (``_ear_first_final``): it opens nothing twice, and when it disagrees it is judged as if the ear had not acted, the cue cut. A later piece of the cloud may come as late as its start of speech does
# (TEMPO_ANNOUNCE_SECONDS): the cue is playing by then. EAR_SAID_PIECES: what the ear keeps of a cloud turn that holds several of its utterances (143.7-150.4 of the call).
# H5 item 6 (n1_01 step 15: the cloud's final stopped at «… под двадцать», the ear between two pieces of one breath, the job's answer to that head was cued): an utterance is over when the ear's silence has lasted
# EAR_RELEASE_SILENCE_SECONDS and its text does not stop on an open tail (classifier.open_tail), which is evidence and no veto: EAR_TAIL_SILENCE_SECONDS of silence are an end all the same.
# H5 item 8: on the phone the cloud announced a turn 3.1-3.7 s after the onset: the wait of a reference opened from the ear is EAR_FIRST_BIND_SECONDS. A confirmation keeps EAR_BIND_SECONDS.
EAR_RELEASE_SILENCE_SECONDS=0.9
TURN_MAP_CAP,TURN_MAP_KEEP=256,64      # c24 P17: a map by turn longer than the cap keeps the ledger's turns and the newest TURN_MAP_KEEP others
EAR_TAIL_SILENCE_SECONDS=2.5
EAR_FIRST_BIND_SECONDS=4.0
EAR_PILE_SECONDS=8.0      # h28: of the speech nobody judged, what ended this close to the last words can be one question with them
_GROWS=frozenset(normalize('двадцать тридцать сорок пятьдесят шестьдесят семьдесят восемьдесят девяносто двадцати тридцати сорока пятидесяти шестидесяти семидесяти восьмидесяти девяноста '
                           'сто двести триста четыреста пятьсот шестьсот семьсот восемьсот девятьсот ста двухсот трехсот четырехсот пятисот тысяча тысячи тысяч миллион миллиона миллионов миллиард миллиарда миллиардов').split())


def _number_grows(text):
    """g14: does ``text`` end on a number another number word can still add to («счёт пятьдесят» | «два»)? A round ten, hundred, thousand."""
    words=norm_words(text or '')
    return bool(words) and (words[-1] in _GROWS or (words[-1].isdigit() and words[-1].endswith('0') and int(words[-1])>0))
PACE_HELP_SECONDS=(0.7,1.2)     # w10 item 16 (WAVE10): a stumble is helped 0.7-1.2 s after the listener's last word: the pace (``prompt_pace``) chooses inside, never earlier (a breath) nor later
EAR_STRONG_FORMS=frozenset({'question_word','question_explicit_prefix','question_imperative'})
# H6 item 2 (N4: in c14 all three plans a decline gave back were 71-172 s old, over newer answers): a plan goes on after a decline only when no newer answer was given since, it was cued less than PLAN_BACK_SECONDS ago and the listener was at it
# (``_resume_after_nothing``). Otherwise it waits in the history: «продолжай» or his own words at it bring it back. A timer's cue keeps a plan recent and proves nothing: the listener is at it when he said a word to it, or when only the first cue of it has been said.
LONG_TALK_WORDS=25      # h29 (the call of 20:29): a breath this long is talk: a form counts at its end only (``EAR_TAIL_WORDS``), «мы поговорили сколько, четырнадцать минут» in the middle of a remark opened a question
UNANSWERED_MIN_WORDS=4      # ROOT-2: shorter remarks are no context worth the tokens
UNANSWERED_KEPT=2           # ROOT-2: the last declined utterances the job is told
SAID_BACK_SHARE=0.7     # Fable 10.11: a reply this long against what was read is the task said back; shorter, it is a choice out of it (one option of four): an answer
STOOD_MORE_STEMS=3      # Fable 10.11 (20:54): this many new words in the final of a turn the ear stood in for are a new utterance, whenever that final comes
SAID_ALREADY_SHARE=0.7  # h29: this share of its words said before, and it is nothing new
ASKED_AGAIN_FEW_STEMS=3      # words of meaning of a short question that, all in an earlier question, make it that question asked again in few words (``_asked_before``)
ASKED_AGAIN_STEMS=3      # words of meaning of an old question that, all said again, make the question asked again (``_asked_again``)
# H6 item 3 (N5): a final that stops on an open tail waits this long for its rest before the job goes (n1_04 step 10: «… закон о» | 1.65 s | «бухгалтерском учёте»), unless the ear has been quiet that long already.
FAST_TAIL_SECONDS=1.5
# H6 item 5 (risk 4, R1): a command the job or a final found in speech that goes on waits for the ear's silence (``_utterance_over``), FAST_MARK_SECONDS at most (``fast_mark``); a new question takes it away.
FAST_MARK_SECONDS=8.0
# H6 item 6 (risk 5): every hold on the listener's speech and its bound, one table: no final, a stuck detector, a noisy room: a decision within 8 s of the end of speech. name -> (seconds, what happens at the bound).
# H5 item 2 against ONSET_HOLD_MAX_S: for a first cue H5 item 2 wins: it is new content and it waits for speech with content however long (the cap of a question, ``answer_cap_seconds``, bounds that), and FIRST_HOLD_SECONDS past the last such speech
# nothing holds it: a stuck detector and a noisy room hold it no longer. ONSET_HOLD_MAX_S is the hold of every other cue (a next portion, a replay): what the listener is in the middle of is that very plan.
RECORD_PAUSE_SECONDS=8.0      # u18-s4: the longest hold on a pause («секунду») while the owner is writing: the pen's wait (``DictationPace.wait``, 6 s at least) cut to this, within ANSWER_WAIT_SECONDS
HOLD_BOUNDS={
    'ear_text':(TEMPO_TEXT_SECONDS,'the text of an utterance never came: nobody knows what was said, the timer counts from the end of that speech'),
    'cloud_final':(EAR_FINAL_SECONDS,'no final: the job runs on the ear text and its verdict stands; the cloud came up to 3.7 s behind the ear on the phone'),
    'job_first_text':(FIRST_TEXT_S,'the job failed; on the ear text that is the end of it, on a final one more job with a wait of its own, then the cloud judged, then the failure said'),
    'speech_unjudged':(TEMPO_HOLD_SECONDS,'the timer, a plan given back and a first cue go on: the final and the first text of a job have had their time'),
    'ear_detector':(EAR_SPEECH_SECONDS,'one stretch with no offset and no word of the cloud for EAR_FINAL_SECONDS: the detector is stuck, the flag of speech is dropped'),
    'first_cue':(FIRST_HOLD_SECONDS,'past the last speech with content anybody heard: a stuck detector or a noisy room: the first cue plays'),
    'command':(FAST_MARK_SECONDS,'a mark of the job waited for silence: it is carried out'),
    'tail_before_job':(FAST_TAIL_SECONDS,'a final on an open tail got no rest: the job goes on what there is'),
    'tail_before_cue':(EAR_TAIL_SILENCE_SECONDS,'an open tail is evidence and no veto: the answer goes'),
    'cue_in_speech':(ONSET_HOLD_MAX_S,'timer_policy.ONSET_HOLD_MAX_S: a cue that is no first cue plays'),
    'no_final':(ANSWER_WAIT_SECONDS,'E43: the question the cue answers has no final of the cloud (an open turn, one never announced): the cue plays at the bound of the whole chain from the end of the speech'),
    'record_pause':(RECORD_PAUSE_SECONDS,'u18-s4: a pause asked for while the owner is writing waits for the pen (DictationPace.wait), then the portion or what is missing of its start'),
}
# H6 item 10 (ПОТ-1, always: no switch): the speaker follows a prepared text: with a material and no question nothing happened: the job said «—». «Начинаем», «поехали» (SPEECH_STARTS, with SPEECH_LEADS at most) or SPEECH_WORDS first words of the
# text said aloud open it as the plan, cut by the portioner, ACK as usual. A question in the middle is any question, and the speech goes on when its answer is over.
SPEECH_STARTS=frozenset(normalize('начинаем начнем начнём начинай начинайте начнемте поехали стартуем').split())
SPEECH_LEADS=frozenset(normalize('ну что давай давайте итак так все всё хорошо ладно можно').split())
SPEECH_WORDS=3
# H7 items 3 and 4 (``prepare_wide``): what is prepared, and how much. A partial of the cloud that has stood still for PARTIAL_STABLE_SECONDS with the ear silent, and every ear final of a breath (a pause of EAR_RELEASE_SILENCE_SECONDS ends it) that is no repeat, command or
# try gets a job: on the phone the text is there 1.06 s after the end of speech, the final at 2.23 s. A prepared job says nothing until it is adopted. PREPARE_MIN_WORDS as for a question the ear heard. PREPARE_WORDS: LiveKit's max_speech_duration in words: a minute of remark is
# not a job per piece: past this many words in one breath nothing is prepared, and the job on the final is the job, and a breath has fast_text.PREPARE_JOBS new jobs at most. A breath ends with a pause or with a final. A question the base answers needs no job, and a job with
# sources is never a prepared one: what the route would throw away is not asked.
PREPARE_MIN_WORDS=3
EAR_TAIL_WORDS=14      # c25-b case 1: the question at the end of a long breath is looked for in its last words only
LIVE_MIN_WORDS=2     # ``live_first``: «Счет 58»: two words of the cloud, three of the ear; 10 of 16 questions of the phone on 6 Nov had no job before the final
PREPARE_WORDS=40
FAST_HEAD_WORDS=24     # H5 skeptic: what the job ruled out and the breath went on: longer than this it is a remark of its own, not a question the cloud cut (``_fast_breath``)
EAR_SAID_PIECES=16
# A command (a repeat request, a stop, «дальше») is often only the start of an utterance («Повтори, | что ты сейчас сказал», «Не понял, |
# давай уточню»): the ear acts on one only when the quiet after it has lasted this long after the end its detector heard (300 ms of quiet
# already), and speech that begins meanwhile is judged with it. A replay or the next cue started in the middle of an utterance would also
# close the phone's microphone (open speaker, half duplex) and cut its rest off.
EAR_COMMAND_SETTLE_SECONDS=0.4
# F3 fix round 1: a call that opens this long after the last portion was spoken (the engine's wall clock) is the SAME conversation after a drop of the
# line, not a new one: ``begin_call`` keeps the waiting portion, and the listener's repeat or confirmation of it works (ACK passes the quiet reopen).
# Task E3c (the owner's call 35115fb1a8e5, 2 Nov) with amendment R2a: the listener's repeat cuts the model's speech, and after the
# listener's turn the model goes on in a new segment. That is the rest of the same sentence (« ног.», «ваются сильнее…», « Москве»),
# the model starting its answer again («Первое — в психологии, …»), the answer going on with a new sentence («Может быть полезным…»), or
# a reply to something else («Десять.»). Its first letter is a signal, never the verdict: every such segment except the rest of a word is
# weighed on what it says (ControlledMedia._weigh_segment / _restart_verdict) and is joined, aligned after what the listener has heard,
# corrected explicitly, or dropped. Bounds: a question takes at most MAX_RESTARTS restarts; a segment is weighed on at most
# RESTART_MAX_WORDS content words (and ``segment_idle_seconds`` of silence); what it retells of the text heard so far (F1 round 2:
# ``_retelling``, whatever the size of the portions) is found word after word with at most RESTART_ANCHOR_GAP other content words of
# the segment between two of them.
MAX_RESTARTS=3
RESTART_MAX_WORDS=60
RESTART_DECIDE_WORDS=3        # content words a new sentence needs before it is told from a reply to the listener (unless it ends first)
RESTART_ANCHOR_GAP=3
_OPENING_MARKS=re.compile(r'[\s«“„"\'(\[]*')
_LEADING_MARKS=re.compile(r'[\s,.;:!?…—–\-]*')
_AFTER_ANCHOR=re.compile(r'[\s,.;:!?…—–\-»”"\')\]]*')
_PROPER_NAME=frozenset({'Name','Surn','Patr','Geox','Orgn','Trad'})
# DEF-T-11: the words of a request that say nothing about its subject («Проверь, пожалуйста, что такое …», the lookup's «Тема:»).
_REQUEST_WORDS=frozenset(normalize(
    'проверь проверьте проверить пожалуйста скажи скажите подскажи подскажите расскажи расскажите объясни объясните найди найдите '
    'поищи поищите узнай узнайте посмотри посмотрите уточни уточните сверь сверьте приведи приведите назови назовите опиши опишите '
    'поясни поясните хочу хотел хотела хотелось знать узнать интересно значит означает называется вопрос тема').split())
_CYRILLIC=re.compile(r'[А-Яа-яЁё]')


def _proper_name(word):
    """Is ``word`` (Cyrillic, with a capital) a proper name pymorphy knows («Москве», «Иван», «Ньютон»), or a word it does not know at all?
    Russian writes a name with a capital inside a sentence too, never a common word; an unknown word gets the benefit of the doubt."""
    from . import ru_alignment as ru
    lower=word.casefold()
    ru._lemma(lower)                                   # initializes the shared analyzer behind its lock
    with ru._LOCK:
        if not ru._MORPH.word_is_known(lower):return True
        return any(_PROPER_NAME&parse.tag.grammemes for parse in ru._MORPH.parse(lower))


_QUOTE_START=re.compile(r'\s*[«“„"\']')
# R2a: a reply to the listener rather than the answer: every word of it one of these («Хорошо, продолжаем.», «Верно!»).
_CHATTER_WORDS=frozenset(normalize(
    'хорошо ладно отлично прекрасно замечательно верно правильно точно именно молодец умница спасибо пожалуйста продолжаем продолжим '
    'продолжайте продолжай давайте давай дальше идём идем слушаю понял поняла понятно ясно ага угу да ок окей так конечно повторите '
    'повторяйте повтори снова ещё еще раз итак вот мг мгм мм ммм хм наконец наконец-то').split())     # A1-F3: «Мг.» is a backchannel, no answer; c24-a1 (fuzz seed 730, the call of 4 Nov 20:34): nor «Ну наконец-то.»
_NO_SUBSTANCE=_CHATTER_WORDS|frozenset(normalize('нет рад рада рады помочь помогу договорились спасибо вопрос вопросы').split())
_MAY_ANSWER=frozenset(normalize('да нет верно правильно точно именно конечно').split())    # «Да.» answers «Вода мокрая?»; «Угу.» answers nothing
_INVERTS=frozenset(normalize('не ни нет наоборот').split())     # G3: words after a repeat that take it back («… но это не так», «… а наоборот нет»)
# G3 (``_answers_the_form``): what a question asks for, by its form, besides a number and a cause (``_ASKS_A_NUMBER``, ``_ASKS_A_CAUSE``).
_ASKS_A_PLACE=re.compile(r'(?:^|\s)(?:где|куда|откуда)(?=\s|$)',re.I)
_ASKS_A_PURPOSE=re.compile(r'(?:^|\s)(?:зачем|для\s+чего)(?=\s|$)',re.I)
_SAYS_A_PLACE=re.compile(r'\s*(?:в|во|на|у|за|под|при|около|возле)\s',re.I)
_SAYS_A_PURPOSE=re.compile(r'\s*(?:чтобы|для)\s',re.I)
# A question whose answer can be a bare number («Сколько…», «Когда…», «В каком году…»).
_ASKS_A_NUMBER=re.compile(r'(?:^|\s)(?:сколько|когда|скольк\w*|в\s+как\w+\s+(?:год|век|час)\w*|как\w+\s+(?:номер|год|число|процент)\w*|'
                          r'котор\w+\s+(?:час|год)\w*|какова?\s+(?:сумма|величина|ставка|температура|скорость|масса|длина|высота))',re.I)


def _segment_start(text,final=False,after=''):
    """How an assistant segment begins that follows a segment of the same answer cut without terminal punctuation (``after``): a SIGNAL
    of what it is, never the verdict (Task E3c, amendment R2a: a continuation may begin with a name, an abbreviation, a number, a formula
    or a quotation, and a restart in lower case; ``_restart_verdict`` decides on what the text says).

    ``'midword'``: the rest of the word ``after`` was cut in (letters or digits right after it, no change from lower to upper case).
    ``'continuation'``: a lower-case word, a digit or a mark. ``'name'``: a capital Russian also writes inside a sentence (a proper name,
    an abbreviation, another script, an opening quotation). ``'sentence'``: a capital on a common word: a new sentence. ``None`` while it
    cannot be told yet: nothing but spaces and marks, or a first word that may still grow («Пер» of «Первое» or «Пермь»)."""
    text=str(text or '')
    if not text:return None
    if after[-1:].isalnum() and text[0].isalnum() and not (after[-1].islower() and text[0].isupper()):return 'midword'
    rest=text[_OPENING_MARKS.match(text).end():]
    if not rest:return None
    if not (rest[0].isalpha() and rest[0].isupper()):return 'continuation'
    if _QUOTE_START.match(text):return 'name'
    word=WORDS.match(rest)
    if word and word.end()==len(rest) and not final:return None
    token=word.group() if word else rest[0]
    if len(token)>1 and token.isupper():return 'name'
    if not re.fullmatch(r'[А-ЯЁа-яё]+(?:-[А-ЯЁа-яё]+)*',token):return 'name'   # another script: not for Russian morphology to judge
    try:return 'name' if _proper_name(token) else 'sentence'
    except Exception:return 'sentence'


def _rest_end(text,final):
    """W1F-B (C5): where the rest of a cut sentence ends in a segment that goes on with it (``text``: the segment from where the answer
    goes on in it): after its first terminator, or before a capital on a common word - a new sentence the transcript did not punctuate
    (« воды Хорошо.»). ``None`` while neither has arrived; the whole text once it is final."""
    end=_HEAD_TERMINATOR.search(text)
    stop=end.end() if end else None
    for match in WORDS.finditer(text):
        if stop is not None and match.start()>=stop:break
        if match.start()==len(text)-len(text.lstrip()) or not match.group()[0].isupper():continue   # the segment's own first word
        if match.end()==len(text) and not final:break                                              # it may still grow
        if _segment_start(text[match.start():match.end()],final=True)=='sentence':
            stop=len(text[:match.start()].rstrip());break
    return len(text) if stop is None and final else stop


def _ends_in_number(text):
    """C7: does ``text`` stop at a number - digits or a number word («…составляет 60», «Шестьдесят»)?"""
    words=WORDS.findall(str(text or '').rstrip())
    if not words:return False
    last=normalize(words[-1])
    return last.isdigit() or last in NUMBER_WORDS


def _content(text):
    """``[(stem, start, end, negated, number)]`` of the words of ``text`` that carry content (function words, pronouns and the like
    left out): ``negated`` when «не»/«ни» stands before it, ``number`` for a number in digits or in words."""
    out=[];negated=False
    for match in WORDS.finditer(text):
        word=normalize(match.group())
        if word in ('не','ни'):
            negated=True;continue
        if not word or word in STOPWORDS:continue
        number=word.isdigit() or word in NUMBER_WORDS
        out.extend((stem(part),match.start(),match.end(),negated,number) for part in re.split(r"[-’'\s]",word) if part and part not in STOPWORDS)
        negated=False
    return out


def _stems(text):return {item[0] for item in _content(text)}


def _complete(text,final):
    """The part of a growing text whose words are complete: its last word may still grow unless the text is final."""
    if final or not text or not text[-1].isalnum():return text
    last=None
    for last in WORDS.finditer(text):pass
    return text[:last.start()] if last else text


def _valued(items,text):
    """F1 round 2: ``_content`` items of ``text`` with every run of number words merged into one item whose stem is the number's value as
    ru_alignment reads it: «8», «восемь», «восьми» are '#8', «девятьсот восемьдесят восемь» is '#988'; another value is another number
    (R2a). A run ru_alignment cannot read keeps its first stem."""
    out,i=[],0
    while i<len(items):
        if not items[i][4]:
            out.append(items[i]);i+=1;continue
        j=i
        while j+1<len(items) and items[j+1][4] and not text[items[j][2]:items[j+1][1]].strip():j+=1
        try:
            from .ru_alignment import _canonical
            values=[atom for atom in _canonical(text[items[i][1]:items[j][2]]) if atom.startswith('#')]
            value=re.sub(r'^#ord:','#',values[0]) if len(values)==1 else items[i][0]
        except Exception:
            value=items[i][0]
        out.append((value,items[i][1],items[j][2],items[i][3],True));i=j+1
    return out


def _by_value(text):
    """The comparison form of ``text`` with a number by its value alone: the digits of a year with no «года» after them and the ordinal it is said as are one."""
    from .ru_alignment import _canonical
    return [re.sub(r'^#ord:','#',atom) for atom in _canonical(text,())]


_SCALE_STEMS=('тысяч','миллион','миллиард')
_AFTER_SCALE=re.compile(r'(?<![\w])(тысяч[аиу]?|миллион(?:а|ов)?|миллиард(?:а|ов)?)\s+(?=[а-яё])',re.I)


def _like_a_try(text,portion):
    """c24 F1 (h5 n1_01 step 8, w3 scenes): is ``text`` a try at ``portion`` rather than speech of its own that shares a word or a number with it? Numbers alone are a try at the portion's
    number; otherwise a content word of the portion must be in it, and the portion's (its words, and no more numbers than it has) at least as many as the words of its own.
    «вклад ну сто тысяч рублей на два года» shares «рублей» and a number with «Купили материалы за 10 000 рублей:»: speech of its own."""
    word=lambda item:not item[4] and not item[0].startswith(_SCALE_STEMS)
    words=[item for item in _content(text) if word(item)];own={item[0] for item in _content(portion) if word(item)}
    heard=sum(1 for atom in _by_value(text) if atom.startswith('#'));has=sum(1 for atom in _by_value(portion) if atom.startswith('#'))
    if not words:return 0<heard<=has
    shared=sum(1 for item in words if item[0] in own)
    return shared>0 and shared+min(heard,has)>=len(words)-shared+max(0,heard-has)


def _holds_a_number(text):
    return any(atom.startswith('#') for atom in _by_value(text))


def _retelling(heard,words,first,from_start=False,to_end=False,strict=False):
    """F1 round 2 (E3c, size-independent): the run of a restart (``words``) that retells ``heard`` (the content items of the text heard
    so far, every portion of it - or of what nobody has heard yet): heard words one after another, none left out, each found in the
    restart after the one before with at most RESTART_ANCHOR_GAP other restart words between them; the run starts at the restart's first
    word (``first``) or at one of its first RESTART_ANCHOR_GAP + 1, at the first heard word when ``from_start``, and ends at the last
    heard word when ``to_end``. The longest run wins, then the one reaching further into the heard text. ``(pairs, conflict)``: the
    ``(heard index, restart index)`` pairs, and whether a retold word has another negation or a number another value (R2a); None when
    the restart retells nothing of it. ``strict``: a number retells only the same value (« 000 километров» is the rest of «300», not a
    retelling of it)."""
    same=(lambda a,b:a[0]==b[0]) if strict else (lambda a,b:a[0]==b[0] or (a[4] and b[4]))      # loosely the same content word: the same stem (or value), or a number for a number
    best=key=None
    for r0 in ([0] if first else range(min(len(words),RESTART_ANCHOR_GAP+1))):
        for h0 in ([0] if from_start else range(len(heard))):
            if not same(heard[h0],words[r0]):continue
            pairs=[(h0,r0)]
            while pairs[-1][0]+1<len(heard):
                h,r=pairs[-1]
                step=next((rr for rr in range(r+1,min(len(words),r+2+RESTART_ANCHOR_GAP)) if same(heard[h+1],words[rr])),None)
                if step is None:break
                pairs.append((h+1,step))
            if to_end and pairs[-1][0]!=len(heard)-1:continue
            if best is None or (len(pairs),pairs[-1][0])>key:best,key=pairs,(len(pairs),pairs[-1][0])
    if best is None:return None
    return best,any(heard[h][3]!=words[r][3] or heard[h][0]!=words[r][0] for h,r in best)


def _last_sentence_words(items,text):
    """How many of ``items`` (``_content`` of ``text``) stand in the last sentence of ``text``."""
    start=max((m.end() for m in re.finditer(r'[.!?…]+\s+(?=\S)',text)),default=0)
    return sum(1 for item in items if item[1]>=start)


def _retold_conflict(retold,said):
    """Does the part of a restart that retells what the listener heard (``_content`` items) say it otherwise (R2a): a word negated in
    the heard text and affirmed in the retelling or the other way round, or numbers where the heard text has others and none of them?"""
    polarity={}
    for item in said:polarity.setdefault(item[0],set()).add(item[3])
    if any(item[0] in polarity and item[3] not in polarity[item[0]] for item in retold):return True
    heard={item[0] for item in said if item[4]};mine={item[0] for item in retold if item[4]}
    return bool(heard and mine and not heard&mine)


def _chatter(text,question):
    """Is this new sentence a reply to the listener rather than the answer going on: a stall, praise or acknowledgement as a whole
    sentence («Хорошо, продолжаем.», «Понял.»), or a bare number to a question that does not ask for one («Десять.» to «А почему?»)?"""
    if not strip_process_prefix(text,question):return True
    words=norm_words(text)
    if words and all(word in _NO_SUBSTANCE and (word in _CHATTER_WORDS or word not in _MAY_ANSWER) for word in words):return True
    content=[word for word in words if word not in STOPWORDS]
    return bool(content) and all(word.isdigit() or word in NUMBER_WORDS for word in content) and not _ASKS_A_NUMBER.search(str(question))


_REQUEST_STEMS=frozenset(stem(word) for word in _REQUEST_WORDS|QUESTION_WORDS)
# INTEG7 (T-A C11): a question that asks for a cause, and a row that gives one (``_relevant``).
_ASKS_A_CAUSE=re.compile(r'(?:^|[^\w-])(?:почему|зачем|отчего|из-за\s+чего|по\s+какой\s+причине|причин[аеуы]\w*)(?![\w-])',re.I)
_GIVES_A_CAUSE=re.compile(r'(?:^|[^\w-])(?:потому\s+что|оттого\s+что|так\s+как|поскольку|из-за|вследствие|благодаря|поэтому|'
                          r'причин[аеуы]\w*)(?![\w-])',re.I)
# INTEG7 (T-A C11): a row whose leading clause - at its start, or after a heading that ends with «:» - has a third-person pronoun for its
# subject («Конспект: Оно происходит, когда…») speaks of something named elsewhere and names no subject of its own.
_UNNAMED_SUBJECT=re.compile(r'(?:[^.:;!?…\n]{1,60}:\s*)?[«“„"\'(]*(?:он|она|оно|они)(?![\w-])',re.I)
_CONDITION=re.compile(r'(?:^|[\s,])(?:если|при\s+условии|в\s+случае)\s+([^.!?;:]*)',re.I)


def _nouns(text):
    """The stems of the nouns of ``text`` (pymorphy's most likely reading); empty when the analyzer is not there."""
    try:
        from . import ru_alignment as ru
        out=set()
        for match in WORDS.finditer(text):
            word=normalize(match.group())
            if not word or word in STOPWORDS:continue
            ru._lemma(word)
            with ru._LOCK:parse=ru._MORPH.parse(word)[0]
            if parse.tag.POS=='NOUN':out.add(stem(word))
        return out
    except Exception:return set()


def _source_conflict(asked,items,query,text,by_value=False):
    """Why a source row is about something else although it may share the question's stems (amendment R2a), or None. ``asked`` and
    ``items``: ``_content`` of the question and of the row. ``number``: the row shares the question's words, but where the question names
    a number or a year the row names others and none of those; ``negation``: the question negates a word the row only affirms; ``subject``: the row shares the question's words but
    none of its nouns; ``condition``: the row has its own condition («если …») about the question's condition, with another predicate. ``by_value`` (H2, the call's 20:38:42: «двадцать
    первой» and «21» share no stem, every row went as another number and the answer came from memory): a number said in words is the same number as its digits."""
    mine={item[0] for item in items}
    words={item[0] for item in asked if not item[4]}&mine    # the same stems: only then is another number another claim
    numbers={item[0] for item in asked if item[4]};theirs={item[0] for item in items if item[4]}
    if words and numbers and theirs and not numbers&theirs and not (by_value and {atom for atom in _by_value(query) if atom.startswith('#')}&set(_by_value(text))):return 'number'
    for word in {item[0] for item in asked if item[3]}:
        uses=[item[3] for item in items if item[0]==word]
        if uses and not any(uses):return 'negation'
    nouns=_nouns(query)-_REQUEST_STEMS
    if mine&{item[0] for item in asked} and nouns and not nouns&mine:return 'subject'
    wanted=_CONDITION.search(query);given=_CONDITION.search(text)
    if wanted and given:
        wanted,given=_stems(wanted.group(1)),_stems(given.group(1))
        if wanted&given and not wanted<=given:return 'condition'
    return None


def public_sources(rows):
    result=[]
    for row in rows[:5] if isinstance(rows,list) else []:
        if not isinstance(row,dict):continue
        url=str(row.get('url') or '')
        text=str(row.get('text') or row.get('snippet') or row.get('description') or '')[:3000]
        try:
            parts=urlsplit(url);host=parts.hostname or ''
            # These are source references from the existing encrypted lookup,
            # not URLs fetched here. Its public-host contract includes HTTP
            # canonical government references (notably pravo.gov.ru).
            if parts.scheme not in {'https','http'} or '.' not in host or parts.username or parts.password:continue
            try:
                if not ipaddress.ip_address(host).is_global:continue
            except ValueError:
                if host.endswith(('.local','.localhost')):continue
        except ValueError:continue
        if text.strip():
            source={'url':url,'text':text}
            if isinstance(row.get('title'),str):source['title']=row['title'][:180]
            receipt=row.get('source_receipt')
            if isinstance(receipt,dict):
                meta={key:str(receipt[key])[:240] for key in ('policy','topic','publisher_basis','evidence','limitations') if key in receipt}
                # Publisher screening is not statement/effective-date proof.
                meta.update(statement_verification=False,applicability_verified=False,effective_date_verified=False)
                source['source_receipt']=meta
            result.append(source)
    return result

_HESITATES=frozenset({'hmm','mm','mhm','uh','um','er','ah','eh','хм','мм','ммм','э','ээ','эм','а-а'})      # Fable 10.11: sounds of hesitation the cloud writes down at the head of a turn
NUMBER_DOUBT={'ru':'Не расслышал число: {} или {}? Повторите.','en':'Which number: {} or {}? Say it again.'}
NUMBER_PREMISE={'ru':'Если {}: {}','en':'If {}: {}'}      # U36: the witnesses differ again: the answer names the number it stands on, the doubt stays audible until both hear one number
NUMBER_TRUSTS=1    # disagreements of the two witnesses within ``CONTEXT_AGE_S`` that go the cloud's way unasked (measured 10.11 on 181 numbered finals of the calls: the ear names another number in 30, a sixth, and the cloud is mostly the one that is right); the next one is asked about, the ones after it are answered with the premise: never a second bare answer, never a loop of questions      # Fable 10.11 (20:54, U36): two witnesses, two numbers: one exact question, never an answer on one of them
SOURCES_DIFFER='Источники расходятся, точно не знаю.'      # c22 (NC4): the one honest phrase when the bank and the law base answer one question differently (a wording of ``no_cloud.HONEST``: «не знаю»)

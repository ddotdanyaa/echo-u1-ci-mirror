"""Engine settings: defaults in code, an optional JSON file re-read on every turn.

``materials/echo_settings.json`` in the profile home may hold any subset of the
keys below. A missing file, broken JSON or a bad value never stops a session: the
default is used (and the problem is logged once). See SETTINGS.md.
"""
from __future__ import annotations

import json
import logging
import math
import os
import shutil
import tempfile
import unicodedata
import uuid
from pathlib import Path

from .textutil import normalize
from .timer_policy import SECONDS_PER_SYLLABLE

logger = logging.getLogger('echo-sync')
SETTINGS_FILE = 'echo_settings.json'

# The lesson the model is told about on the controlled route (CL1; content_policy.py writes it into the prompt of every call).
# Each is one clean line of plain text and may not grow past its cap, so a settings file cannot enlarge a prompt without bound.
TEXT_LIMITS = {'subject': 200, 'audience': 160, 'style': 160}

DEFAULT_FILLERS = ('так', 'ну', 'а', 'вот', 'итак', 'слушай', 'слушайте', 'скажи', 'скажите', 'подскажи',
                   'подскажите', 'пожалуйста', 'ладно', 'хорошо', 'окей', 'ок', 'эм', 'э', 'и')
# "Did not hear it": the same portion is spoken again. The phone handles Stop/End phrases (стоп, хватит,
# замолчи, тише, пока, до свидания, закончить разговор, это всё) itself and never sends them, so they are not here.
DEFAULT_CLARIFICATIONS = ('а', 'что', 'еще', 'еще раз', 'не понял', 'не поняла', 'не слышу', 'не слышно',
                          'не расслышал', 'не расслышала', 'не услышал', 'не услышала')

DEFAULTS = {
    'preset': None,                  # None or one of the named PRESETS below
    # --- how an answer is cut into portions
    'portion_mode': 'words',          # "words" | "syllables" | "meaning" (F1: sentence, clause, phrase - the preset 'meaning')
    'words_per_portion': 3,           # words mode: portion size
    'target_syllables': 8,            # syllables mode: preferred portion length
    'max_syllables': 12,
    'max_words': 5,
    'min_words': 1,
    'long_word_syllables': 6,         # a word this long may be a portion alone
    'abbreviations': {},              # {"ВВП": "валовой внутренний продукт"}: first occurrence only
    # --- how a heard utterance is understood
    'fillers': list(DEFAULT_FILLERS),
    'cancel_min_words': 3,            # a question word cancels a waiting answer only with this many words
    'question_window': 3,             # the question word must be among the first N words after fillers
    'bank_min_words': 4,              # a bank question this long may be found inside a longer utterance
    'repeat_cover': 0.8,              # share of a portion's words that makes a question look like a repeat; 0 = off
    'attempt_extra_words': 3,         # an attempt at a portion is at most this many words longer than the portion
    'ack_match': 'stem',              # "exact" | "stem" | "ru_aligned"
    'ack_garble': False,              # w8-repeat: ONE word the ear garbled into a non-word still counts as the portion's word (ru_aligned only)
    'on_mismatch': 'replay_if_attempt',   # "silent" | "replay_if_attempt"
    'clarifications': list(DEFAULT_CLARIFICATIONS),
    # --- only the controlled route (S1): the local ear in SHADOW mode - a local recognizer next to the cloud that only writes down
    # what the existing classifier would decide on its text (ear_shadow.py); it never acts, the cloud input is unchanged.
    # R-EAR-ACT: "act" (opt-in) - its confirmations, repeat requests, stops and «дальше» are applied at once (ControlledMedia.ear_heard)
    'local_ear': 'off',              # "off" | "shadow" | "act"
    # ear-early (C7): ms of silence after which the ear takes the recognizer's text so far (a partial, never acted on); 0 = off, else 100-400
    'ear_early_ms': 0,
    # ear-early (C6): "on" adds the plain words of the whole answer/material (no numbers, no «не») to the recognizer's bias; off until the laptop bake-off says so
    'ear_vocab': 'off',              # "off" | "on"
    # --- only the controlled route (H1): the fast text channel - the first words of an answer from the plain Codex text channel (fast_text.py)
    'fast_text': 'off',              # "off" | "on"
    # --- W12 (E59.1): how the text channel reaches the model: "http" (T1, CodexTransport) or "ws" (the Responses WebSocket, ws_transport.py; a refused or dropped socket puts the call on HTTP). Needs fast_text on.
    'text_transport': 'http',        # "http" | "ws"
    # --- only the controlled route (H3): who keeps the tempo of the prompter. "ear" (it needs local_ear on): the local ear's detector says when the listener speaks, its text what they
    # said (ControlledMedia, TEMPO_*); the silence auto-repeat then waits TEMPO_REPEAT_SECONDS unless the profile states its own repeat_seconds.
    'prompt_tempo': 'off',           # "off" | "ear"
    # --- only the controlled route (W5 w5-stumble): the wait of a start that stopped is this person's (echo_sync.pace): their pauses in this call, where they stopped, a filler at once. It needs prompt_tempo "ear".
    'prompt_pace': 'off',            # "off" | "on"
    # --- only the controlled route (H4): a question in a strong form opens on the ear's text, before the cloud's final, once the job prepared on it has given its first sentence (ControlledMedia, rule 2; a plain
    # reference the base answers does so with fast_text alone, rule 1). It needs fast_text on and local_ear "act"; apart from them so that it can be measured.
    'ear_release': 'off',            # "off" | "on"
    # --- only the controlled route (H7): the job starts earlier and what is ready is not thrown away: nothing changes when sound may start or what may be said, a prepared job says nothing until it is adopted (fast_text.py, ControlledMedia). Apart from
    # the rest so that it can be measured as a row of its own. It needs fast_text on and the local ear ("shadow" or "act": somebody has to say that the speaker has stopped).
    'prepare_wide': 'off',           # "off" | "on"
    # --- c16: the job of the ear's whole breath opens the question before the cloud's final, whatever the form of the words: the job says whether it is a question, and the cloud's open turn must read as the same question by the rule of an adoption (fast_text.wide_refusal). Needs prepare_wide, ear_release and two_witnesses
    'ear_job': 'off',                # "off" | "on"
    # --- the first cue of a question the base does not answer goes before the cloud's final: when the cloud's input text has caught up with the ear, the two agree on every number, code and «не», and the job on that text keeps them (controlled_media._live_stable). Needs prepare_wide, ear_release and two_witnesses
    'live_first': 'off',             # "off" | "on"
    # --- c22-speed, the job on the ear's text (``ear_job``): a number closed by «?»/«!» in the cloud's open turn does not wait for the final (``turn_mark``); an ear's breath without the form of a question
    # opens when the cloud's open turn asks (``cloud_form``: the ear hears no «?»). Numbers, «не», roles read as before. Need ear_job
    'turn_mark': 'off',              # "off" | "on"
    'cloud_form': 'off',             # "off" | "on"
    'ear_lookup': 'off',             # "off" | "on": c22-speed, a question of the search route opens on the same two witnesses (the ear, the cloud's open turn): the lookup and the job with its source start before the final
    # --- a number the job added against GPT-Live's reply, a third source (the bank, the law base, the material) decides; "shadow": one line of the call trace with the correction it would have said, nothing is said (answer_witness.py). Needs fast_text
    'answer_witness': 'off',         # "off" | "shadow"
    # --- only the controlled route (W5-lead): an answer from the model's knowledge opens at once with the question's own words («Первая мировая война началась»), question_lead.py; BRAIN goes on
    # after them with no word said twice. Not the first useful help (a journal line of its own). It needs fast_text on.
    'lead_cue': 'off',               # "off" | "on"
    # --- only the controlled route (H6 item 10): the prepared speech: the material of the call is the plan: «начинаем», «поехали» or its first words open it, it is cut by the portioner and prompted portion by portion, with no question asked
    'prepared_speech': 'off',        # "off" | "on"
    'material_pick': 'off',          # "off" | "on": w5-material, the parts of the material that fit the question instead of the first 12,000 characters
    'warm_start': 'off',             # w9-warm: "off" | "on": everything the first call loads is loaded when the server starts
    # --- only the controlled route (Q1): a plain expression of two numbers ("пять на пять", "10% от 200 000") is answered by code like a hit of the reference base (quick_math.py): at the cloud's final, and from the
    # ear's text before it where H4 opens a reference (fast_text + an acting ear). Off: every sum goes to the model as it did.
    'quick_math': 'off',             # "off" | "on"
    # --- only the controlled route (E76): the end of an answer is heard. The last word of the LAST portion is spoken a little lower (SSML <prosody pitch>
    # through the SAPI worker, sapi_worker.END_STYLES), so the voice falls where the answer ends and nowhere else. Nobody has listened to it yet: off.
    'end_intonation': 'off',          # "off" | "fall"
    # --- only the controlled route (W2): prepared answers without the model (prepared_answers.py): the owner's list of question-answer pairs (prepared_answers_file) and the long cache of settled answers. Always on; with no file the long cache alone.
    # --- only the controlled route (E87.1): the lookup prepared on the partial is adopted by another wording of the same question (search_identity.same_meaning). Off: only the exact key adopts it.
    'prefetch_same_meaning': 'off',  # "off" | "on"
    'prepared_answers_file': '',     # path of the pairs file (JSON or В:/О: blocks); empty: the cache only
    # --- only the controlled route (W5): the instant path (instant.py): every partial text of the ear is looked up in one index (bank, laws, chart of accounts, material); a unique hit releases the sound at once
    'instant': 'off',                # "off" | "on"
    # --- only the controlled route (c22-repeat, repeat_rule.py): the owner's rule of repeats: the last word of the portion or most of it said -> the next portion at once; a stumble -> on from its word; silence -> the portion again
    'repeat_rule': 'off',            # "off" | "on"
    # --- c22-repeat: dictation: the question said, the answer written by hand, the last words of each portion said; the silence timer waits for the hand (repeat_rule.DictationPace). Also said: «диктуй медленно» / «хватит диктовать»
    'dictation': 'off',              # "off" | "on"
    'dictation_cycle': 'off',        # "off" | "on": h25: while dictating silence repeats the portion every DICTATION_CYCLE_SECONDS up to DICTATION_CYCLE_REPEATS (off: once after the learned time of the hand)
    'resume_word': 'off',            # "off" | "on": G6 rule 3 reads where the listener stopped by ru_alignment.resume_word before ``_started``'s own reading; off: ``_started`` only
    'number_ranges': 'off',          # "off" | "on": U16 a written range («XIII–XV веках», «1941–1945») is read as its two ends (ru_alignment.set_ranges, the TTS century paradigm); off: as before
    'instant_rank': 'off',           # "off" | "on": W11/F5 the ranked path of the instant bank (instant.Ranker) besides the full match; off: the full match only
    'instant_rank2': 'off',          # "off" | "on": C24 the ranked path reads a spoken question kindly (chatter off, why-words one kind, «кто»/«кому» apart, a definition never answers «почему»); needs instant_rank "on"; off: the W11/F5 path as it was
    # --- only the controlled route (E86, w10 item 4): the ear's question opens on the cloud's open turn only when its STABLE piece (two_witnesses.py) agrees with the ear on every number, «не» and role; a disagreement cuts. Needs fast_text on and local_ear "act".
    'two_witnesses': 'off',          # "off" | "on"
    'fast_private': 'off',           # "off" | "on": G38 cut 3 (after G32), a personal question («у меня») the model's route takes is prepared before the final; the public search stays closed to it. Needs fast_text
    'stop_in_flight': 'off',         # "off" | "on": G38, the ear's «стоп» while the answer is on its way (a job, no portion yet) stops it; needs fast_text
    # --- only the controlled route (w8-admission): talk said to a person, chat, a remark is kept quiet by the text gate (gate_text.py) before any job is spent; «question»/«unknown» change nothing; always on for the talk to a person or the room, no key
    # --- only the controlled route (c22-nocloud, g37 «подключение»): each behind its flag, off = the behaviour of before, to the line
    'bank_atoms_first': 'off',       # "off" | "on": U21-S4 (C1), the ranked path scores the bank entries of the question's number before the cut of candidates ("статья 422" among 100 articles); not measured on the laptop
    'bank_rejoin': 'off',            # "off" | "on": U21-S5 (C3, C4), the ranked path joins a word the ear tore in two ("стимулиру ющая", REJOIN_MAX joins) and ranks the part after a self-correction when the question holds a word the bank never heard; not measured on the laptop
    'bank_cover_min': 0.6,           # 0..1: U21-S8 (C5, measure only), the share of the heard words (by IDF) a bank entry must hold; 0.6 = as it was; lower only after a measured run; not measured on the laptop
    'bank_rival_weight': 1.0,        # 0..1: U21-S6 (C2), how much the second best bank entry counts against the best in the margin (RANK_GAP); 1.0 = all of it, as it was; fitted on the dev half, grid 0, 0.2, 0.3, 0.45, 0.6; not measured on the laptop
    'brain_short': 'off',            # "off" | "on": w9-brain, the short BRAIN (brain_short.SHORT_POLICY, substance first) and a short history; needs fast_text on. Not measured on the model
    # --- only the controlled route (w8-donors N74, w10 item 11): «стоп»/«подожди» acts on the ear's text so far (ear_command.py), not after the end of the utterance. Needs fast_text on and local_ear "act".
    'ear_command_early': 'off',      # "off" | "on"
    'instant_bank_file': '',         # path of the bank (JSON list {q, alt, core, answer, source, subject, trust}), outside the repository
    'pcm_cache_dir': '',             # directory of the ready PCM of first portions (pcm_cache.py); empty: no cache
    'pcm_cache_mb': 200,             # size limit of that directory
    # --- U07 (L): the call's audio recorded on the laptop only, for replay (never sent anywhere). Off: no file. D4: switched on only by the owner's yes
    'pcm_record': 'off',             # "off" | "on"
    'pcm_record_calls': 20,          # the newest this many recorded calls stay, 1..200
    'pcm_record_mb': 2048,           # and at most this many MB in all, 64..20000
    'pcm_record_call_mb': 200,       # V5 step 0: and at most this many MB for ONE call (both channels together), 16..4000; 200 = as before (about 73 min of the microphone alone, 36 min with the cues)
    # --- V5 step 0, facts in the journal (call_trace.py). "off" = as before. "on": the arrival stamps and gaps of the microphone packets (mic_gap / mic_back / mic_facts), the rule or timer behind every hold and drop (why), one readiness verdict after the first cue (ready_verdict). Journal only, no decision changes
    'facts_journal': 'off',          # "off" | "on"
    'mic_gap_ms': 1500,              # no packet for longer than this while the call is open is a gap, 200..60000
    'mic_ring_s': 60,                # after the microphone line budget the last this many seconds are kept and written at the close (mic_tail), 5..600
    # --- V5 step 1a (v5_tap.py), ALWAYS ON (no switch): the entries of the controller go through ONE lock and the call's inputs and the actions it returned are written as a record of contract 1 next to the call journal (logs/echo_calls/*.v5tap.jsonl); nothing is decided differently
    'v5_tap_mb': 48,                 # the record of one call is a ring of at most this many MB (two halves), 8..500
    # --- V5 slice «answer gate» (v5_gate.py): "off" = as before, no gate. "shadow": the verdict of the gate next to every answer cue handed to the transport (journal, v5 record), nothing changes.
    # "on": a stale first portion is refused once per question and asked again; a hold by speech not known to be the owner's ends at the cap of v5_gate.COSTS
    'v5_answer_gate': 'off',         # "off" | "shadow" | "on"
    # --- the rule of «the same question» of that gate. "answers": a number/date not asked or a turned «не» forbids «the same»; otherwise the relation is unknown and the ANSWERS are compared by their numbers, dates and yes/no. "words": the old rule of content stems, kept to compare
    'v5_gate_same': 'answers',       # "answers" | "words"
    # --- U07 (L C3): a question that only misses words (rule 'words') may be adopted when at most this many of its words are missing, 0..2. 0 = as before. Excludes prepare_wide and keep_ready (one lever for the same refusals)
    'adopt_missing_words': 0,        # 0..2
    # --- U15-S4: a prepared job whose question differs only by a chatter prefix of the final (no number, «не» or question word in it) is kept. "shadow": only told (fast_keep), nothing changes. "on" sets adopt_missing_words to 0
    'keep_ready': 'off',             # "off" | "shadow" | "on"
    'keep_chatter_words': 2,         # 1..3, the longest chatter prefix in words
    # --- only the controlled route (w5-flow): the next portion is sent AHEAD, timed on the speaker's tempo to be heard 100-300 ms after the last word
    # of the repeat, its synthesis done at the cue, withdrawn when the repeat goes wrong; the length of the unsaid rest follows the speaker (flow_ahead.py)
    'flow_ahead': 'off',             # "off" | "on"
    # w5-near (near_voice.py): whose speech by loudness against the speaker's own level learned from what aligned with the prompt. "shadow": only numbers per utterance in the log; "act": the gate (needs the wiring patch)
    # --- W6 item 10: one spare audio helper started while the line is idle (helper_pool.SpareHelper): the next call takes it without the helper start (offer_ms 5-11 s after a pause)
    'spare_helper': 'off',           # "off" | "on"
    'near_voice': 'off',             # "off" | "shadow" | "act"
    # --- only the controlled route (w8-net): the wire's own holds on the audio (native_media_socket.py). Off by default; each is measured on the laptop first (report w8-net).
    'voice_gain': 1.0,               # 1.0 (as before) .. 4.0: software gain of everything sent to the phone, with a soft limiter (voice_boost.py); c22-voice
    'voice_presence': 0.0,           # 0 (off) .. 9 dB: lift of 2-4 kHz for clarity (voice_boost.py); c22-voice
    'audio_head_ms': 0,              # 0 (off) | 40..400: this much of a cue goes to the phone at once, the rest is paced that far ahead (Б11)
    'open_overlap': 'off',           # "off" | "on": the owner's material is read while the audio helper starts, not before it (N17)
    # --- optional extras
    'sec_per_syllable': SECONDS_PER_SYLLABLE,
    # --- only the controlled route (UX): the silence auto-repeat of a portion nobody has repeated. The owner's call of 2 Nov
    # («запоздалый диктофон с таймером») had 3 s and 3 repeats; the calm default is one repeat after 6 s of silence.
    'repeat_seconds': 6.0,            # seconds of silence after a portion before it is said again on its own (1..60)
    'max_auto_repeats': 1,            # how many times in a row it is said again on its own (0..10; 0 = never)
    # --- x-cap (repeat_rule.repeat_cap; not wired yet): the one cap of silent repeats
    'cycle_max_repeats': 15,          # 0..30: the cap while the dictation cycle runs (was the constant DICTATION_CYCLE_REPEATS)
    'repeat_scope': 'portion',        # "portion" | "answer": what the repeat counter counts
    'record_mode': 'off',             # "off" | "earned": the cap rises only while the owner is seen writing (record_on)
    'record_engage_k': 2,             # 1..5: advances that show the owner is writing
    # --- only the controlled route (UX): the local trace of a phone call, <profile>/logs/echo_calls/*.jsonl (never sent anywhere)
    'call_trace': 'on',               # "on" | "off"
    # --- only the controlled route (ControlledMedia): what to do with a repeat that may be the cue heard back from the speaker
    # --- the conversation map (CL2): what the listener has said of each answer
    # --- the lesson (one clean line each, see TEXT_LIMITS)
    'subject': '',                   # what the lesson or talk is about
    'audience': '',                  # who is listening
    'style': '',                     # a wish for the manner of speaking
    # --- only the controlled route (S0): the transport's own ear on the phone's microphone, which hears the START of speech
    'local_onset': 'shadow',          # "off" (not run) | "shadow" (run and log only) | "on" (holds the auto-repeat; a ready cue <= 1 s)
    # --- only the controlled route (R-VAD): what that ear (and the shadow ear's utterance cutting) tells speech from noise with
    'local_onset_engine': 'silero',   # "silero" (Silero VAD via sherpa-onnx; the energy rule when the model is missing) | "energy" (S0's rule)
    # --- only the controlled route (the owner's failed rehearsal of 06.11, 12:42/12:44): the laptop could not reach OpenAI
    # (TLS handshake timed out twice, 18 s each) and BOTH calls died after 36 s with ``controlled_upstream_unavailable``, although every
    # local source answered in 0.6-0.8 s the same morning. With this on, a call whose cloud channel cannot be opened does not close:
    # it opens in LOCAL mode (native_media_socket: the local ear hears, the bank / the law base / the chart of accounts / the owner's
    # material answer, SAPI speaks, portions and the go-on rules are the usual ones), the listener is told once, a question no local
    # source answers gets one honest line instead of silence, and the cloud is retried quietly in the background - when it comes back
    # the SAME call upgrades to the full path. Nothing of it is a second model: no network, no key, no new API.
    'local_fallback': 'off',          # "off" (as before: the call dies when the cloud is unreachable) | "on"
    # --- V6 slice «память» (v6_memory.py), ALWAYS ON (the owner's rule): the card of the model request is built from the ledger and replaces the history block, the recap and the carry of the request (only when it is not empty).
    # The ledger is the truth; the card is a rebuildable view of it. The three numbers are «стартовое»: nothing is measured yet
    'v6_memory_chars': 4000,         # the whole card is never longer than this, 1500..20000
    'v6_memory_step_min': 5,         # the outline of the call: one or two lines for every step of this many minutes, 1..60
    'v6_memory_lines': 4,            # earlier utterances retrieved by the words of the question, 0..20
    # --- U19 (language of the turn, B1; not wired yet): the language of the turn is a probe, always observed (the answer line and the voice follow it, no key); lang_turn only gates the Russian ear
    'input_state': 'shadow',          # U17-S4: "off" | "shadow" (the meter counts the microphone and the tick logs state= act=; nothing is held) | "on" (the repeat gate obeys it, U17-S5)
    'order_guard': 'shadow',           # U20-S5: "off" | "shadow" (a spoken refusal that breaks OrderLedger O1-O4 is logged as order_violation, still spoken) | "on" (and not spoken)
    'lang_turn': 'off',               # "off" | "shadow" (decide and log) | "on"
    'cross_script': 'off',            # "off" | "shadow" | "on": Cyrillic-vs-Latin comparison by transliteration; "on" needs lang_turn "on", "shadow" needs lang_turn not "off"
    'ear_en': 'off',                  # "off" | "on": the English ear (after the owner's D5 and a measurement); needs lang_turn "on"
}

# Portioning presets are intentionally small profiles. They only supply defaults;
# validated per-key values in the user's JSON take precedence.
PRESETS = {
    'strict_triples': {'portion_mode': 'words', 'words_per_portion': 3},
    'adaptive': {'portion_mode': 'syllables', 'target_syllables': 8, 'max_syllables': 12, 'max_words': 6},
    'slow': {'portion_mode': 'syllables', 'target_syllables': 5, 'max_syllables': 8, 'max_words': 3},
    # The same boundary-aware planner with explicit, reproducible load budgets.
    # These are deterministic heuristics, not semantic model calls or learning.
    'semantic_short': {'portion_mode': 'syllables', 'target_syllables': 10, 'max_syllables': 14, 'max_words': 6},
    'pronunciation_short': {'portion_mode': 'syllables', 'target_syllables': 6, 'max_syllables': 9, 'max_words': 4},
    # F1 (the owner's call of 3 Nov 09:55): portions by meaning - a sentence when it fits, else whole clauses, else phrases; never
    # across a sentence end, never inside a phrase (portioner._plan_meaning). A portion is at most 9 words / 26 syllables (a year
    # alone is ~9 of them), a comfortable one 8-18 syllables; fewer than 3 words only when the sentence itself is that short.
    'meaning': {'portion_mode': 'meaning', 'target_syllables': 13, 'max_syllables': 26, 'max_words': 9, 'min_words': 3},
}
PRESETS['fixed_3'] = dict(PRESETS['strict_triples'])
PRESETS['slow_assistive'] = dict(PRESETS['slow'])

# F1: the profile a phone call is to run on - meaning-sized portions, the Russian alignment of a repeat, silence (no replay) for a
# mismatch. A call takes ControlledMedia's own default settings (controlled_host passes none, and the profile's echo_settings.json is
# not read for portions or ACKs): that default was {'preset': 'slow_assistive', 'max_words': 4, 'min_words': 2, ...}, the 1-4-word
# portions of the owner's call of 3 Nov. The wave-F integration points ControlledMedia's default at this dict.
CALL_SETTINGS = {'preset': 'meaning', 'ack_match': 'ru_aligned', 'on_mismatch': 'silent'}


def controller_settings(profile_settings):
    """The ONE way a call's controller gets its settings, and it gets them BEFORE it is built (ROOT-1): the call's own profile
    (``CALL_SETTINGS``: its keys stay the call's) under every key the owner's profile CHANGED from its default. An unchanged key is
    the default either way (``resolve`` and every raw ``.get`` read agree on it), so no call changes unless the owner asked."""
    out = dict(CALL_SETTINGS)
    out.update({key: value for key, value in profile_settings.items() if key in DEFAULTS and key not in CALL_SETTINGS and value != DEFAULTS[key]})
    return out
READ_SHARE = 0.6               # U15-S9 (addressed_gate): the share of the significant words of a final that the cues played lately (or the listener's own words) hold, from which it is read aloud, not asked; unmeasured, calibrated in shadow
READ_MIN_WORDS = 6             # U15-S9: the fewest significant words the share is judged on
LONG_READ_WORDS = 25           # U15-S9: a final this long with no ask feature anywhere is talk, not a question
ASK_TAIL_WORDS = 8             # U15-S9: an ask feature in the last this many words always passes
READ_WINDOW_S = 120            # U15-S9: how far back the cues played count as the text that may be read aloud
READ_USER_WINDOW_S = 60        # U15-S9: and the listener's own earlier words
TEMPO_REPEAT_SECONDS = 2.0     # H3 rule 2: the default of ``repeat_seconds`` when the local ear keeps the tempo. H7 item 0: 3.5 until the owner's call of 5 Nov 10:27: «там ну максимум секунда две наверное должна быть перерыва»

_warned = set()


def environment(name, default=None):
    """The one place the process environment is read for a path or a file (the law base, the reserve keys file, the ear model, the profile home, the LOCALAPPDATA root): an empty value is none."""
    return os.environ.get(name) or default


class Settings(dict):
    """A validated settings dict; ``resolve`` returns it unchanged the second time."""


def _warn(message):
    if message not in _warned:
        _warned.add(message)
        logger.warning('echo-sync settings: %s', message)


def _number(value, default, low, high=None, *, integer):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return default
    if integer:
        if isinstance(value, float):
            if not value.is_integer():
                return default
            value = int(value)
    else:
        value = float(value)
    if value < low or (high is not None and value > high):
        return default
    return value


def _choice(value, default, options):
    return value if isinstance(value, str) and value in options else default


def _flag(value, default):
    return value if isinstance(value, bool) else default


def clean_line(value, limit):
    """``value`` as ONE line of plain text of at most ``limit`` characters.

    Control and invisible format characters are dropped (a zero-width or "tag" character can hide a sentence from the owner
    but not from the model), every run of white space becomes one space, and a too long text is cut between words.
    """
    kept = ''.join(' ' if ch in '\n\r\t' else ch for ch in str(value)
                   if ch in '\n\r\t' or unicodedata.category(ch) not in ('Cc', 'Cf'))
    text = ' '.join(kept.split())
    if len(text) > limit:
        cut = text[:limit]
        space = cut.rfind(' ')
        text = (cut[:space] if space > limit // 2 else cut).rstrip()
    return text


def _phrases(value, default):
    if not isinstance(value, list):
        return list(default)
    seen = []
    for item in value:
        phrase = normalize(item) if isinstance(item, str) else ''
        if phrase and phrase not in seen:
            seen.append(phrase)
    return seen


def _table(value):
    if not isinstance(value, dict):
        return {}
    return {key.strip(): full.strip() for key, full in value.items()
            if isinstance(key, str) and isinstance(full, str) and key.strip() and full.strip()}


def resolve(raw=None):
    """Merge ``raw`` (any subset of the keys) over the defaults, repairing bad values."""
    if isinstance(raw, Settings):
        return raw
    raw = raw if isinstance(raw, dict) else {}
    for key in raw:
        if key not in DEFAULTS:
            _warn(f'unknown key {key!r} ignored')
    for key, kind in (('fillers', list), ('clarifications', list), ('abbreviations', dict)):
        if key in raw and not isinstance(raw[key], kind):
            _warn(f'{key!r} must be a JSON {"array" if kind is list else "object"}; the default is used')
    d = DEFAULTS
    preset = raw.get('preset')
    if not (preset is None or (isinstance(preset, str) and preset in PRESETS)):
        _warn(f"invalid value for 'preset' replaced by the default None")
        preset = None
    profile = PRESETS.get(preset, {})
    effective = dict(profile)
    effective.update(raw)
    out = Settings()

    def pick(key, value):
        if key in raw and value == d[key] and raw[key] != d[key]:
            _warn(f'invalid value for {key!r} replaced by the default {d[key]!r}')
        out[key] = value

    out['preset'] = preset
    pick('portion_mode', _choice(effective.get('portion_mode', d['portion_mode']), profile.get('portion_mode', d['portion_mode']), ('words', 'syllables', 'meaning')))
    pick('words_per_portion', _number(effective.get('words_per_portion', d['words_per_portion']), profile.get('words_per_portion', d['words_per_portion']), 1, 30, integer=True))
    pick('target_syllables', _number(effective.get('target_syllables', d['target_syllables']), profile.get('target_syllables', d['target_syllables']), 1, 60, integer=True))
    pick('max_syllables', _number(effective.get('max_syllables', d['max_syllables']), profile.get('max_syllables', d['max_syllables']), 1, 60, integer=True))
    pick('max_words', _number(effective.get('max_words', d['max_words']), profile.get('max_words', d['max_words']), 1, 30, integer=True))
    pick('min_words', _number(effective.get('min_words', d['min_words']), profile.get('min_words', d['min_words']), 1, 30, integer=True))
    pick('long_word_syllables', _number(effective.get('long_word_syllables', d['long_word_syllables']), profile.get('long_word_syllables', d['long_word_syllables']), 1, 60, integer=True))
    out['abbreviations'] = _table(raw.get('abbreviations', {}))
    out['fillers'] = _phrases(raw.get('fillers', d['fillers']), d['fillers'])
    pick('cancel_min_words', _number(raw.get('cancel_min_words', d['cancel_min_words']), d['cancel_min_words'], 1, 30, integer=True))
    pick('question_window', _number(raw.get('question_window', d['question_window']), d['question_window'], 1, 10, integer=True))
    pick('bank_min_words', _number(raw.get('bank_min_words', d['bank_min_words']), d['bank_min_words'], 1, 30, integer=True))
    pick('repeat_cover', _number(raw.get('repeat_cover', d['repeat_cover']), d['repeat_cover'], 0.0, integer=False))
    pick('attempt_extra_words', _number(raw.get('attempt_extra_words', d['attempt_extra_words']), d['attempt_extra_words'], 0, 30, integer=True))
    pick('ack_match', _choice(raw.get('ack_match', d['ack_match']), d['ack_match'], ('exact', 'stem', 'ru_aligned')))
    pick('ack_garble', _flag(raw.get('ack_garble', d['ack_garble']), d['ack_garble']))
    pick('on_mismatch', _choice(raw.get('on_mismatch', d['on_mismatch']), d['on_mismatch'], ('silent', 'replay_if_attempt')))
    out['clarifications'] = _phrases(raw.get('clarifications', d['clarifications']), d['clarifications'])
    pick('local_ear', _choice(raw.get('local_ear', d['local_ear']), d['local_ear'], ('off', 'shadow', 'act')))
    early = _number(raw.get('ear_early_ms', d['ear_early_ms']), 0, 0, 400, integer=True)
    pick('ear_early_ms', early if early >= 100 else 0)
    pick('ear_vocab', _choice(raw.get('ear_vocab', d['ear_vocab']), d['ear_vocab'], ('off', 'on')))
    pick('fast_text', _choice(raw.get('fast_text', d['fast_text']), d['fast_text'], ('off', 'on')))
    pick('text_transport', _choice(raw.get('text_transport', d['text_transport']), d['text_transport'], ('http', 'ws')))
    pick('prompt_tempo', _choice(raw.get('prompt_tempo', d['prompt_tempo']), d['prompt_tempo'], ('off', 'ear')))
    if out['local_ear'] == 'off':
        out['prompt_tempo'] = 'off'
    pick('prompt_pace', _choice(raw.get('prompt_pace', d['prompt_pace']), d['prompt_pace'], ('off', 'on')))
    if out['prompt_tempo'] != 'ear':
        out['prompt_pace'] = 'off'
    pick('ear_release', _choice(raw.get('ear_release', d['ear_release']), d['ear_release'], ('off', 'on')))
    pick('quick_math', _choice(raw.get('quick_math', d['quick_math']), d['quick_math'], ('off', 'on')))
    pick('spare_helper', _choice(raw.get('spare_helper', d['spare_helper']), d['spare_helper'], ('off', 'on')))
    pick('near_voice', _choice(raw.get('near_voice', d['near_voice']), d['near_voice'], ('off', 'shadow', 'act')))
    if out['fast_text'] != 'on' or out['local_ear'] != 'act':
        out['ear_release'] = 'off'
    pick('voice_gain', _number(raw.get('voice_gain', d['voice_gain']), d['voice_gain'], 0.25, 4.0, integer=False))
    pick('voice_presence', _number(raw.get('voice_presence', d['voice_presence']), d['voice_presence'], 0, 9.0, integer=False))
    head = _number(raw.get('audio_head_ms', d['audio_head_ms']), d['audio_head_ms'], 0, 400, integer=True)
    pick('audio_head_ms', head if head >= 40 else 0)
    pick('open_overlap', _choice(raw.get('open_overlap', d['open_overlap']), d['open_overlap'], ('off', 'on')))
    pick('prepare_wide', _choice(raw.get('prepare_wide', d['prepare_wide']), d['prepare_wide'], ('off', 'on')))
    pick('ear_job', _choice(raw.get('ear_job', d['ear_job']), d['ear_job'], ('off', 'on')))
    pick('live_first', _choice(raw.get('live_first', d['live_first']), d['live_first'], ('off', 'on')))
    pick('answer_witness', _choice(raw.get('answer_witness', d['answer_witness']), d['answer_witness'], ('off', 'shadow')))
    if out['fast_text'] != 'on':
        out['answer_witness'] = 'off'                  # no job, nothing to compare
    if out['fast_text'] != 'on' or out['local_ear'] == 'off':
        out['prepare_wide'] = 'off'
    pick('lead_cue', _choice(raw.get('lead_cue', d['lead_cue']), d['lead_cue'], ('off', 'on')))
    if out['fast_text'] != 'on':
        out['lead_cue'] = 'off'
    pick('flow_ahead', _choice(raw.get('flow_ahead', d['flow_ahead']), d['flow_ahead'], ('off', 'on')))
    if out['local_ear'] != 'act':
        out['flow_ahead'] = 'off'         # the next portion is released on the ear's text so far: only an acting ear gives it (the one rule; the controller and the ear read the answer)
    pick('material_pick', _choice(raw.get('material_pick', d['material_pick']), d['material_pick'], ('off', 'on')))
    pick('end_intonation', _choice(raw.get('end_intonation', d['end_intonation']), d['end_intonation'], ('off', 'fall')))
    pick('prepared_speech', _choice(raw.get('prepared_speech', d['prepared_speech']), d['prepared_speech'], ('off', 'on')))
    pick('prefetch_same_meaning', _choice(raw.get('prefetch_same_meaning', d['prefetch_same_meaning']), d['prefetch_same_meaning'], ('off', 'on')))
    pick('instant', _choice(raw.get('instant', d['instant']), d['instant'], ('off', 'on')))
    if out['fast_text'] != 'on' or out['local_ear'] != 'act':
        out['instant'] = 'off'
    pick('resume_word', _choice(raw.get('resume_word', d['resume_word']), d['resume_word'], ('off', 'on')))
    pick('number_ranges', _choice(raw.get('number_ranges', d['number_ranges']), d['number_ranges'], ('off', 'on')))
    pick('repeat_rule', _choice(raw.get('repeat_rule', d['repeat_rule']), d['repeat_rule'], ('off', 'on')))
    pick('dictation', _choice(raw.get('dictation', d['dictation']), d['dictation'], ('off', 'on')))
    pick('dictation_cycle', _choice(raw.get('dictation_cycle', d['dictation_cycle']), d['dictation_cycle'], ('off', 'on')))
    pick('instant_rank', _choice(raw.get('instant_rank', d['instant_rank']), d['instant_rank'], ('off', 'on')))
    pick('instant_rank2', _choice(raw.get('instant_rank2', d['instant_rank2']), d['instant_rank2'], ('off', 'on')))
    pick('ear_command_early', _choice(raw.get('ear_command_early', d['ear_command_early']), d['ear_command_early'], ('off', 'on')))
    if out['fast_text'] != 'on' or out['local_ear'] != 'act':
        out['ear_command_early'] = 'off'
    for flag in ('bank_atoms_first', 'bank_rejoin'):
        pick(flag, _choice(raw.get(flag, d[flag]), d[flag], ('off', 'on')))
    pick('bank_rival_weight', _number(raw.get('bank_rival_weight', d['bank_rival_weight']), d['bank_rival_weight'], 0.0, 1.0, integer=False))
    pick('bank_cover_min', _number(raw.get('bank_cover_min', d['bank_cover_min']), d['bank_cover_min'], 0.0, 1.0, integer=False))
    pick('brain_short', _choice(raw.get('brain_short', d['brain_short']), d['brain_short'], ('off', 'on')))
    pick('two_witnesses', _choice(raw.get('two_witnesses', d['two_witnesses']), d['two_witnesses'], ('off', 'on')))
    if out['fast_text'] != 'on' or out['local_ear'] != 'act':
        out['two_witnesses'] = 'off'                   # the ear's text opens the answer as H4 rule 1 does: it needs both
    pick('fast_private', _choice(raw.get('fast_private', d['fast_private']), d['fast_private'], ('off', 'on')))
    if out['fast_text'] != 'on':
        out['fast_private'] = 'off'
    pick('stop_in_flight', _choice(raw.get('stop_in_flight', d['stop_in_flight']), d['stop_in_flight'], ('off', 'on')))
    if out['fast_text'] != 'on':
        out['stop_in_flight'] = 'off'                  # G38: only a job of the fast channel is an answer on its way
    if out['ear_release'] != 'on' or out['prepare_wide'] != 'on' or out['two_witnesses'] != 'on':
        out['ear_job'] = 'off'                         # no job on the ear, nobody to open on it, no second witness
        out['live_first'] = 'off'                      # the same three: no job on the cloud's text, nobody to open on it, no ear to say it has caught up
    for key in ('turn_mark', 'cloud_form', 'ear_lookup'):
        pick(key, _choice(raw.get(key, d[key]), d[key], ('off', 'on')))
        if out['ear_job'] != 'on':
            out[key] = 'off'                           # c22-speed: both read the job on the ear's text
    for key in ('prepared_answers_file', 'instant_bank_file', 'pcm_cache_dir'):
        value = raw.get(key, '')
        out[key] = value.strip()[:500] if isinstance(value, str) and '\n' not in value else ''
    pick('pcm_cache_mb', _number(raw.get('pcm_cache_mb', d['pcm_cache_mb']), d['pcm_cache_mb'], 1, 5000, integer=True))
    pick('pcm_record', _choice(raw.get('pcm_record', d['pcm_record']), d['pcm_record'], ('off', 'on')))
    pick('pcm_record_calls', _number(raw.get('pcm_record_calls', d['pcm_record_calls']), d['pcm_record_calls'], 1, 200, integer=True))
    pick('pcm_record_mb', _number(raw.get('pcm_record_mb', d['pcm_record_mb']), d['pcm_record_mb'], 64, 20000, integer=True))
    pick('pcm_record_call_mb', _number(raw.get('pcm_record_call_mb', d['pcm_record_call_mb']), d['pcm_record_call_mb'], 16, 4000, integer=True))
    pick('facts_journal', _choice(raw.get('facts_journal', d['facts_journal']), d['facts_journal'], ('off', 'on')))
    pick('mic_gap_ms', _number(raw.get('mic_gap_ms', d['mic_gap_ms']), d['mic_gap_ms'], 200, 60000, integer=True))
    pick('mic_ring_s', _number(raw.get('mic_ring_s', d['mic_ring_s']), d['mic_ring_s'], 5, 600, integer=True))
    pick('v5_tap_mb', _number(raw.get('v5_tap_mb', d['v5_tap_mb']), d['v5_tap_mb'], 8, 500, integer=True))
    pick('v5_answer_gate', _choice(raw.get('v5_answer_gate', d['v5_answer_gate']), d['v5_answer_gate'], ('off', 'shadow', 'on')))
    pick('v5_gate_same', _choice(raw.get('v5_gate_same', d['v5_gate_same']), d['v5_gate_same'], ('answers', 'words')))
    pick('warm_start', _choice(raw.get('warm_start', d['warm_start']), d['warm_start'], ('off', 'on')))
    pick('sec_per_syllable', _number(raw.get('sec_per_syllable', d['sec_per_syllable']), d['sec_per_syllable'], 0.0, integer=False))
    wait = TEMPO_REPEAT_SECONDS if out['prompt_tempo'] == 'ear' else d['repeat_seconds']
    pick('repeat_seconds', _number(raw.get('repeat_seconds', wait), wait, 1, 60, integer=False))
    pick('max_auto_repeats', _number(raw.get('max_auto_repeats', d['max_auto_repeats']), d['max_auto_repeats'], 0, 10, integer=True))
    cycle_max = raw.get('cycle_max_repeats', d['cycle_max_repeats'])
    if isinstance(cycle_max, int) and not isinstance(cycle_max, bool):
        cycle_max = max(0, min(30, cycle_max))           # x-cap: a too large cap is the largest one (99 -> 30), not the default
    pick('cycle_max_repeats', _number(cycle_max, d['cycle_max_repeats'], 0, 30, integer=True))
    pick('repeat_scope', _choice(raw.get('repeat_scope', d['repeat_scope']), d['repeat_scope'], ('portion', 'answer')))
    pick('record_mode', _choice(raw.get('record_mode', d['record_mode']), d['record_mode'], ('off', 'earned')))
    pick('record_engage_k', _number(raw.get('record_engage_k', d['record_engage_k']), d['record_engage_k'], 1, 5, integer=True))
    pick('call_trace', _choice(raw.get('call_trace', d['call_trace']), d['call_trace'], ('on', 'off')))
    for key, limit in TEXT_LIMITS.items():
        value = raw.get(key, d[key])
        if key in raw and not isinstance(value, str):
            _warn(f'invalid value for {key!r} replaced by the default {d[key]!r}')
        out[key] = clean_line(value, limit) if isinstance(value, str) else d[key]
    pick('local_onset', _choice(raw.get('local_onset', d['local_onset']), d['local_onset'], ('off', 'shadow', 'on')))
    pick('local_onset_engine', _choice(raw.get('local_onset_engine', d['local_onset_engine']), d['local_onset_engine'], ('energy', 'silero')))
    pick('local_fallback', _choice(raw.get('local_fallback', d['local_fallback']), d['local_fallback'], ('off', 'on')))
    pick('adopt_missing_words', _number(raw.get('adopt_missing_words', d['adopt_missing_words']), d['adopt_missing_words'], 0, 2, integer=True))
    pick('keep_ready', _choice(raw.get('keep_ready', d['keep_ready']), d['keep_ready'], ('off', 'shadow', 'on')))
    pick('keep_chatter_words', _number(raw.get('keep_chatter_words', d['keep_chatter_words']), d['keep_chatter_words'], 1, 3, integer=True))
    if out['prepare_wide'] == 'on' or out.get('keep_ready') == 'on':
        out['adopt_missing_words'] = 0                 # K1-M8: the three weaken the same rule 'words'; one at a time (U15-S4)
    pick('v6_memory_chars', _number(raw.get('v6_memory_chars', d['v6_memory_chars']), d['v6_memory_chars'], 1500, 20000, integer=True))
    pick('v6_memory_step_min', _number(raw.get('v6_memory_step_min', d['v6_memory_step_min']), d['v6_memory_step_min'], 1, 60, integer=True))
    pick('v6_memory_lines', _number(raw.get('v6_memory_lines', d['v6_memory_lines']), d['v6_memory_lines'], 0, 20, integer=True))
    pick('input_state', _choice(raw.get('input_state', d['input_state']), d['input_state'], ('off', 'shadow', 'on')))
    pick('order_guard', _choice(raw.get('order_guard', d['order_guard']), d['order_guard'], ('off', 'shadow', 'on')))
    pick('lang_turn', _choice(raw.get('lang_turn', d['lang_turn']), d['lang_turn'], ('off', 'shadow', 'on')))
    pick('cross_script', _choice(raw.get('cross_script', d['cross_script']), d['cross_script'], ('off', 'shadow', 'on')))
    pick('ear_en', _choice(raw.get('ear_en', d['ear_en']), d['ear_en'], ('off', 'on')))
    if out['lang_turn'] != 'on':
        out['ear_en'] = 'off'
        if out['cross_script'] == 'on' or out['lang_turn'] == 'off':
            out['cross_script'] = 'shadow' if (out['cross_script'] != 'off' and out['lang_turn'] == 'shadow') else 'off'
    # The maxima are the declared hard limits; the preferences give way to them.
    out['target_syllables'] = min(out['target_syllables'], out['max_syllables'])
    out['min_words'] = min(out['min_words'], out['max_words'])
    return Settings((key, out[key]) for key in d)


def timer_policy_check(resolved):
    """U20-S2: check the timer relations (timer_policy.RELATIONS) for these settings. Every violation is one log line (a hard one at
    ERROR, a soft one at WARNING); returns the rule names for the ``timer_violations`` field of call_open. Never raises, changes nothing."""
    try:
        from . import timer_policy      # noqa: PLC0415 - timer_policy reads the other modules; keep settings import-light
        found = timer_policy.validate(resolved)
    except Exception as error:
        logger.warning('echo-sync timer policy check unavailable: %s', type(error).__name__)
        return []
    for violation in found:
        logger.log(logging.ERROR if violation.hard else logging.WARNING, 'echo-sync timer relation %s %s: %s',
                   violation.rule, 'HARD' if violation.hard else 'soft', violation.text)
    return [violation.rule for violation in found]


def load(path):
    """Read the settings file. Never raises: any problem means the defaults."""
    if not path:
        return resolve(None)
    try:
        path = Path(path)
        if not path.exists():
            return resolve(None)
        raw = json.loads(path.read_text(encoding='utf-8-sig'))
    except Exception as exc:
        _warn(f'{SETTINGS_FILE} could not be read ({exc.__class__.__name__}); defaults are used')
        return resolve(None)
    if not isinstance(raw, dict):
        _warn(f'{SETTINGS_FILE} must contain a JSON object; defaults are used')
        return resolve(None)
    return resolve(raw)


def save_content_fields(path, fields):
    """Put ``subject`` / ``audience`` / ``style`` into the settings file at ``path`` and leave every other key as it is.

    An empty value removes its key (an old subject must not linger), a key not named in ``fields`` is not touched, and the
    file is replaced in one step. A file that is not a JSON object cannot be merged into: it is copied to ``<name>.<id>.bak``
    first and then replaced by a file with the content keys only (the loader had been ignoring it anyway).
    Returns ``{'path', 'backup', 'saved'}``; ``saved`` holds the cleaned values that were written.
    """
    unknown = sorted(str(key) for key in fields if key not in TEXT_LIMITS)
    if unknown:
        raise ValueError('Only ' + ', '.join(TEXT_LIMITS) + ' can be written here, not: ' + ', '.join(unknown))
    path = Path(path)
    stored, backup = {}, None
    if path.exists():
        try:
            parsed = json.loads(path.read_text(encoding='utf-8-sig'))
            if not isinstance(parsed, dict):
                raise ValueError(f'{SETTINGS_FILE} must contain a JSON object')
            stored = parsed
        except ValueError:
            backup = path.with_name(f'{path.name}.{uuid.uuid4().hex}.bak')
            shutil.copy2(path, backup)
    saved = {key: clean_line(value, TEXT_LIMITS[key]) if isinstance(value, str) else '' for key, value in fields.items()}
    for key, value in saved.items():
        if value:
            stored[key] = value
        else:
            stored.pop(key, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, pending = tempfile.mkstemp(prefix='.echo_settings-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(handle, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(stored, ensure_ascii=False, indent=2) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(pending, path)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    return {'path': path, 'backup': backup, 'saved': saved}

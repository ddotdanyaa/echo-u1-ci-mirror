"""U19-S8: the language acceptance over the journals. Text only, no controller: the cloud's user finals go through ``TurnLang`` (the language owner of lang_turn), the ear's finals through
``ear_unknown`` / ``ear_foreign`` (the gate's measure), the cues through ``lang_ssml`` and ``answer_instructions``, and each ear text against the cue before it through
``repeat_rule.verdict`` and the repeat rule's verdict of the ear (informational). The claims of the design (all Russian journals):
  L1  switches_to_en = 0: no turn of a Russian call is read as English (a switch would change the answer's language and the voice).
  L2  (PROXY: with the default lexicon every Cyrillic word is known and the journals hold no English, so it is 0 % by construction; only the strict corpus-lexicon share is informational) ear_unknown_share <= EAR_UNKNOWN_MAX over the ear's finals: the words of the ear that the gate would call foreign (Latin words, and words ``known`` does not have).
  L3  (PROXY: the request to the voice is the same; the PCM bytes themselves were not measured, SAPI is not run here: 'unknown') ru_pcm_same: no cue of a Russian call gets a language SSML, and the Russian instruction is empty, so the audio and the prompt of a Russian call are the plain ones.
``known`` is the controller's default lexicon (every Cyrillic word) unless given; ``main`` also prints the share against the words the corpus's own cloud finals and cues use (a stricter, informational proxy). Run: python -m tools.replay.lang_replay [folder]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from echo_sync import repeat_rule                                        # noqa: E402
from echo_sync.lang_hint import TurnLang, answer_instructions, ear_foreign, ear_unknown   # noqa: E402
from echo_sync.sapi_worker import lang_ssml                              # noqa: E402
from echo_sync.controlled_host import voice_key                          # noqa: E402

EAR_UNKNOWN_MAX = 0.02      # the design: ear_unknown_words <= 2 % of the Russian finals' words
USER = 'user'


def _known(word):
    """The controller's default ``ear_lexicon`` (None): every Cyrillic word is known to the ear, so only Latin words count as unknown."""
    return True


def call(fixture, known=_known):
    """The numbers of one fixture (a harvest journal)."""
    turns = TurnLang()
    finals = [row[3] for row in fixture.get('cloud', ()) if row[1] == USER and isinstance(row[3], str)]
    langs = [turns.observe(text) for text in finals]
    ears = [(float(row[0]), row[3]) for row in fixture.get('ear', ()) if isinstance(row[3], str) and row[3].strip()]
    unknown = total = foreign = 0
    for _, text in ears:
        u, t, _share = ear_unknown(text, known)
        unknown, total, foreign = unknown + u, total + t, foreign + ear_foreign(text, known)
    cues = [(float(row[0]), row[1]) for row in fixture.get('cues', ()) if isinstance(row[1], str)]
    ssml = sum(lang_ssml(text) is not None for _, text in cues)
    return {'turns': len(finals), 'switches_to_en': sum(lang == 'en' for lang in langs), 'ear_finals': len(ears), 'ear_words': total, 'ear_unknown_words': unknown,
            'ear_foreign_finals': foreign, 'cues': len(cues), 'cues_with_ssml': ssml, 'ru_instruction': answer_instructions('ru'), 'ear_next': ear_next(ears, cues),
            'cues_request_changed': sum(request(text) != RU_REQUEST for _, text in cues if not re.search('[a-z]', text, re.IGNORECASE))}


def request(text):
    """What reaches the voice for a cue, as ``controlled_host.synthesize`` decides it: (the lang flag, the PCM cache key's voice part, the SSML). The language of a cue is a rule of the call (no switch):
    for a Russian cue this must be ``RU_REQUEST``; equal requests are the proxy for equal PCM bytes (the bytes are not measured)."""
    lang = lang_ssml(text) is not None
    return lang, voice_key('sapi', None, lang, False), lang_ssml(text) if lang else None


RU_REQUEST = (False, voice_key('sapi', None, False, False), None)


def ear_next(ears, cues):
    """Informational: how many ear texts move the portion on by the repeat rule against the cue before them (the rule's verdict 'next'); no claim is made on it."""
    count = 0
    for at, heard in ears:
        cue = next((text for when, text in reversed(cues) if when <= at), None)
        count += cue is not None and repeat_rule.verdict(heard, cue) == 'next'
    return count


def acceptance(rows):
    """The sums of ``call`` rows and the checks."""
    keys = ('turns', 'switches_to_en', 'ear_finals', 'ear_words', 'ear_unknown_words', 'ear_foreign_finals', 'cues', 'cues_with_ssml', 'ear_next', 'cues_request_changed')
    total = {key: sum(row[key] for row in rows) for key in keys}
    share = total['ear_unknown_words'] / total['ear_words'] if total['ear_words'] else 0.0
    return dict(total, calls=len(rows), ear_unknown_share=round(share, 4), L1_no_switch=total['switches_to_en'] == 0, L2_ear_unknown=share <= EAR_UNKNOWN_MAX,
                L3_ru_pcm_same=total['cues_with_ssml'] == 0 and total['cues_request_changed'] == 0 and all(row['ru_instruction'] == '' for row in rows),
                L2_basis='proxy: by construction 0 with the default lexicon, no English in the journals', L3_basis='proxy: same request to the voice; PCM bytes unknown (SAPI not run)')


def corpus_lexicon(fixtures):
    """The words the cloud finals and the cues of the corpus use (lower case): a stricter ``known`` than the default."""
    from echo_sync.lang_hint import _words
    words = set()
    for fixture in fixtures:
        for text in [row[3] for row in fixture.get('cloud', ()) if row[1] == USER] + [row[1] for row in fixture.get('cues', ())]:
            words.update(w.lower() for _, _, w in _words(text))
    return words


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    folder = Path(argv[0]) if argv else ROOT / 'tests' / 'fixtures' / 'harvest'
    fixtures = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(folder.glob('2*.json'))]
    out = acceptance([call(fixture) for fixture in fixtures])
    lexicon = corpus_lexicon(fixtures)
    strict = acceptance([call(fixture, lexicon.__contains__) for fixture in fixtures])
    out['ear_unknown_share_vs_cloud_words'] = strict['ear_unknown_share']
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

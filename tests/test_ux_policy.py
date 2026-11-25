"""UX-trace, part 3: ONE line in the answer policy about an interruption by the speaker's repeat.

The owner's call of 2 Nov 21:46: the speaker repeated the first words of the answer, the cloud was cut, and it then RESTARTED its answer
(or answered the repeat itself, «Десять.»). The policy now says what to do. The model that reads this text is not part of the suite, so
the checks pin the RULE (by Russian word stems inside ONE paragraph, as tests/test_answer_policy.py does) and the size budget, not the
model's compliance - that stays NOT TESTED until the owner's next phone run.
"""
import re

from echo_sync import content_policy
from echo_sync.content_policy import ANSWER_POLICY, POLICY_VERSION, build_instructions, CallContext

POLICY_SIZE_CAP = 2500          # the same cap tests/test_answer_policy.py pins


def squash(text):
    return text.casefold().replace('ё', 'е')


def paragraphs():
    return [squash(block) for block in re.split(r'\n\s*\n', ANSWER_POLICY.strip()) if block.strip()]


def stated_together(*patterns):
    """True when ONE paragraph of the policy matches every pattern."""
    compiled = [re.compile(squash(p), re.DOTALL) for p in patterns]
    return any(all(c.search(block) for c in compiled) for block in paragraphs())


def test_the_policy_tells_the_model_to_go_on_from_where_it_stopped_when_the_speaker_interrupts_with_a_repeat():
    """Break: after the cut the cloud starts the whole answer again and the dictation restarts from the top."""
    assert stated_together(r'перебил|перебива|прерва', r'повтор',
                           r'продолж\w+', r'с\s+того\s+места|где\s+остановил|на\s+чём\s+остановил')


def test_the_model_is_told_never_to_start_the_answer_again_after_such_an_interruption():
    """The follow-up rule («заново не начинай», about a clarification) is another paragraph: the interruption rule has to say it itself."""
    assert stated_together(r'перебил|перебива|прерва',
                           r'не\s+начина\w+\s+(ответ\s+)?(заново|снова|сначала)|(заново|снова|сначала)\s+не\s+начина')


def test_the_model_is_told_never_to_answer_the_repeat_itself():
    """Break: «Десять.» - a reply to the speaker's repeat, glued into the dictation of the answer."""
    assert stated_together(r'не\s+отвечай\s+на\s+(сам\s+)?повтор|на\s+(сам\s+)?повтор\s+не\s+отвечай')


def test_the_rule_is_one_line_in_the_paragraph_about_repeats_not_a_new_theme():
    """The policy keeps ONE paragraph per theme: the repeats paragraph already says a repeat is no new question."""
    assert stated_together(r'не\s+нов\w+\s+вопрос', r'перебил|перебива|прерва', r'продолж\w+')


def test_the_policy_still_fits_its_budget_and_stays_plain_text():
    assert len(ANSWER_POLICY) <= POLICY_SIZE_CAP, f'{len(ANSWER_POLICY)} characters'
    assert '⟦' not in ANSWER_POLICY and '⟧' not in ANSWER_POLICY
    assert not re.search(r'[*#`]', ANSWER_POLICY)


def test_the_version_in_the_log_follows_the_rules():
    """«Changes whenever the rules change; written to the log of every call»: answer-v2 was the text without this line."""
    assert POLICY_VERSION != 'answer-v2'
    assert re.fullmatch(r'[a-z0-9.-]{3,30}', content_policy.POLICY_VERSION)


def test_the_call_gets_the_rule_first_and_the_owners_data_after_it():
    text = build_instructions(CallContext(subject='Физика'))
    assert text.startswith(ANSWER_POLICY) and text.index('Предмет занятия') > len(ANSWER_POLICY)

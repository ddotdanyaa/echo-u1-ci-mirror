"""Pure turn classifier: fillers, questions without '?', bank containment, noise, ACK, mismatch policy."""
import unittest

try:
    from echo_sync.prepared_answers import from_pairs
    from echo_sync.classifier import analyze, strip_fillers
except ImportError:
    analyze = strip_fillers = None

BANK_ITEMS = [
    {'question': 'Что такое финансовая система Российской Федерации?', 'answer': 'Финансовая система Российской Федерации представляет собой совокупность сфер.'},
    {'question': 'Что такое бюджет?', 'answer': 'Доходы покрывают наши расходы.'},
]
BANK = from_pairs(BANK_ITEMS)      # the classifier holds no bank of its own: it asks ``PreparedAnswers.lookup``, the lookup of the controlled route

def test_explicit_repeat_with_hearing_reason_is_not_a_negative_ack():
    for text in ('Повтори, я не расслышал.', 'Повторите, пожалуйста, я не услышала.', 'Я не расслышал, повтори.'):
        assert analyze(text,WAITING,[],{}).kind=='repeat'

def test_repeat_words_in_expected_quotation_keep_ack_precedence():
    expected=state(chunks=('Повтори я не расслышал','следующая часть'))
    assert analyze('Повтори я не расслышал',expected,[],{}).kind=='ack'
    partial=state(chunks=('Повтори я не расслышал название','следующая часть'))
    assert analyze('Повтори я не расслышал',partial,[],{}).kind=='silent'


def state(chunks=('Финансовая система Российской', 'Федерации представляет собой'), index=0, **extra):
    value = {'schema': 2, 'revision': 1, 'question': 'q', 'answer': ' '.join(chunks), 'chunks': list(chunks),
             'chunk_index': index, 'completed': False, 'pending_turn': None, 'history': []}
    value.update(extra)
    return value


WAITING = state()
FINISHED = state(completed=True)
GENERATING = state(completed=True, pending_turn='t1')


class ClassifierCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(analyze, 'Pure turn classifier has not been implemented')

    def kind(self, text, st=None, qa=BANK, settings=None, diagnose=True):
        decision = analyze(text, st, qa, settings, diagnose=diagnose)
        return decision.kind, decision.reason


class FillerTests(ClassifierCase):
    def test_leading_fillers_are_removed_but_the_question_word_stays(self):
        self.assertEqual(strip_fillers('Так что такое бюджет'), 'что такое бюджет')
        self.assertEqual(strip_fillers('ну а что такое бюджет'), 'что такое бюджет')
        self.assertEqual(strip_fillers('И вот что'), 'что')
        self.assertEqual(strip_fillers('Слушай, скажи, пожалуйста, что такое бюджет'), 'что такое бюджет')
        self.assertEqual(strip_fillers('Подскажите, как работает бюджет'), 'как работает бюджет')
        self.assertEqual(strip_fillers('итак ладно хорошо окей ок эм э так'), '')
        self.assertEqual(strip_fillers('Скажите, пожалуйста, ответьте что такое бюджет'), 'ответьте что такое бюджет')

    def test_fillers_inside_the_phrase_are_kept(self):
        self.assertEqual(strip_fillers('Что такое так называемый бюджет'), 'Что такое так называемый бюджет')

    def test_filler_list_is_configurable(self):
        self.assertEqual(strip_fillers('Короче что такое бюджет', {'fillers': ['короче']}), 'что такое бюджет')
        self.assertEqual(strip_fillers('Так что такое бюджет', {'fillers': ['короче']}), 'Так что такое бюджет')


class FieldPhraseTests(ClassifierCase):
    """What the real iPhone sent on 2026-10-21: no '?' and a natural filler in front."""

    def test_bank_question_after_a_filler_is_found(self):
        for st in (None, WAITING, FINISHED):
            kind, reason = self.kind('Так что такое финансовая система Российской Федерации', st)
            self.assertEqual(kind, 'question', st)
            self.assertIn('bank', reason)

    def test_unlisted_question_after_a_filler_is_a_question(self):
        for st in (None, WAITING, FINISHED):
            kind, reason = self.kind('Так что такое финансовая система', st)
            self.assertEqual(kind, 'question', (st, reason))
        self.assertEqual(analyze('Так что такое финансовая система', None, BANK).question, 'что такое финансовая система')

    def test_asking_to_answer_is_not_a_question(self):
        for st in (None, WAITING, FINISHED):
            self.assertEqual(self.kind('Ответь на мой вопрос', st)[0], 'silent', st)

    def test_plain_bank_question_still_matches_exactly(self):
        decision = analyze('Что такое финансовая система Российской Федерации', None, BANK)
        self.assertEqual(decision.kind, 'question')
        self.assertEqual(decision.prepared['answer'], BANK_ITEMS[0]['answer'])
        self.assertIn('bank', decision.reason)


class QuestionRuleTests(ClassifierCase):
    def test_question_word_must_be_within_the_first_three_words_after_fillers(self):
        self.assertEqual(self.kind('мы обсуждали как работает бюджет')[0], 'question')
        self.assertEqual(self.kind('мы вчера обсуждали как работает бюджет')[0], 'silent')
        self.assertEqual(self.kind('ну так вот скажите пожалуйста как работает бюджет')[0], 'question')

    def test_how_as_a_filler_is_not_a_question(self):
        self.assertEqual(self.kind('ну как бы да', WAITING)[0], 'silent')

    def test_explicit_question_prefix(self):
        for text in ('Вопрос: финансовая система', 'вопрос финансовая система', 'Новый вопрос бюджет', 'ну вопрос бюджет'):
            kind, reason = self.kind(text)
            self.assertEqual(kind, 'question', text)
            self.assertIn('explicit', reason)
        self.assertEqual(analyze('Вопрос: Объясни систему', None, []).question, 'Объясни систему')
        self.assertEqual(self.kind('Вопрос')[0], 'silent')

    def test_mentioning_the_word_question_later_is_not_the_prefix(self):
        self.assertEqual(self.kind('Ответь на мой вопрос о бюджете')[0], 'silent')

    def test_question_mark_and_imperative_list_still_count(self):
        self.assertEqual(self.kind('Бюджет сломался?')[0], 'question')
        self.assertEqual(self.kind('Нет, это неверно. Объясните иначе')[0], 'question')
        self.assertEqual(self.kind('Назовите состав финансовой системы')[0], 'question')

    def test_bank_question_is_found_in_the_question_as_it_was_said(self):
        for text in ('Что такое финансовая система Российской Федерации', 'Скажите пожалуйста что такое финансовая система российской федерации'):
            decision = analyze(text, WAITING, BANK)
            self.assertEqual(decision.kind, 'question')
            self.assertEqual(decision.reason, 'question_bank')
            self.assertEqual(decision.prepared['answer'], BANK_ITEMS[0]['answer'])

    def test_bank_question_inside_a_long_remark_is_not_taken(self):
        # strict (the one lookup of the controlled route): a question buried in a longer remark goes to the model, never to a stored answer
        for text, st in (('значит смотри что такое финансовая система российской федерации если коротко и вообще не мог бы ты рассказать', WAITING),
                         ('ну мне непонятно что такое бюджет в нашей компании', WAITING)):
            decision = analyze(text, st, BANK)
            self.assertIsNone(decision.prepared, text)
            self.assertNotIn('bank', decision.reason)
        exact = analyze('Что такое бюджет', None, BANK)
        self.assertEqual(exact.prepared['answer'], BANK_ITEMS[1]['answer'])
        self.assertEqual(exact.reason, 'question_bank')

    def test_a_time_sensitive_bank_question_is_never_stored(self):
        bank = from_pairs([{'question': 'Какой сегодня курс доллара к рублю', 'answer': 'Девяносто.'}])
        self.assertIsNone(analyze('Какой сегодня курс доллара к рублю', None, bank).prepared)

    def test_politeness_in_front_of_a_short_bank_question_still_finds_the_bank(self):
        for text in ('Скажите пожалуйста что такое бюджет', 'ну подскажи пожалуйста Что такое бюджет?'):
            decision = analyze(text, None, BANK)
            self.assertEqual(decision.prepared['answer'], BANK_ITEMS[1]['answer'], text)
            self.assertEqual(decision.reason, 'question_bank')

    def test_question_text_keeps_original_case_without_fillers_or_prefix(self):
        self.assertEqual(analyze('Новый вопрос: Как это применить?', None, []).question, 'Как это применить?')
        self.assertEqual(analyze('Ну а Что такое Бюджет', None, []).question, 'Что такое Бюджет')


class NoiseWhileWaitingTests(ClassifierCase):
    def test_short_noise_never_cancels_a_waiting_answer(self):
        # Exact "что это" is now a bounded follow-up; see test_short_followups.
        for text in ('да', 'угу', 'ага хорошо', 'как так', 'почему', 'где', 'объясни', 'что', 'ну'):
            kind, reason = self.kind(text, WAITING)
            self.assertNotEqual(kind, 'question', (text, reason))

    def test_question_word_with_three_words_cancels(self):
        self.assertEqual(self.kind('что такое налоги', WAITING)[0], 'question')
        self.assertEqual(self.kind('Как это работает', WAITING)[0], 'question')

    def test_cancel_threshold_is_configurable(self):
        self.assertEqual(self.kind('что такое налоги', WAITING, settings={'cancel_min_words': 4})[0], 'silent')
        self.assertEqual(self.kind('что это', WAITING, settings={'cancel_min_words': 2})[0], 'question')

    def test_explicit_signals_cancel_even_when_short(self):
        self.assertEqual(self.kind('Почему сломалось?', WAITING)[0], 'question')
        self.assertEqual(self.kind('вопрос бюджет', WAITING)[0], 'question')
        self.assertEqual(self.kind('Что такое бюджет', WAITING)[0], 'question')

    def test_long_talk_without_a_question_signal_is_noise(self):
        kind, reason = self.kind('мы вчера обсуждали совсем другую тему в офисе и она всем понравилась', WAITING)
        self.assertEqual(kind, 'silent', reason)

    def test_without_a_waiting_answer_short_questions_are_accepted(self):
        for st in (None, FINISHED):
            self.assertEqual(self.kind('Почему', st)[0], 'question', st)
            self.assertEqual(self.kind('что это', st)[0], 'question', st)
        # Bounded deictic follow-ups cannot attach to an unfinished generation.
        for text in ('почему так', 'что это'):
            self.assertEqual(self.kind(text, GENERATING)[0], 'silent', text)
        self.assertEqual(self.kind('Почему', GENERATING)[0], 'question')

    def test_sloppy_repeat_of_a_portion_with_a_question_word_is_not_a_new_question(self):
        waiting = state(chunks=('что позволяет планировать', 'расходы заранее'))
        kind, reason = self.kind('что позволяет планировать расходы', waiting)
        self.assertEqual(kind, 'replay', reason)
        self.assertEqual(self.kind('что позволяет планировать расходы', waiting, settings={'repeat_cover': 0})[0], 'question')
        # A genuinely new, longer question about something else still wins.
        self.assertEqual(self.kind('что такое налоги на прибыль организаций', waiting)[0], 'question')


class AckTests(ClassifierCase):







    def test_ack_has_priority_over_question_detection(self):
        waiting = state(chunks=('Что такое бюджет', 'это план'))
        self.assertEqual(self.kind('что такое бюджет', waiting, qa=[])[0], 'ack')

    def test_nothing_to_acknowledge_without_a_waiting_answer(self):
        # The words of the answer just given, heard back after it was complete, and anything said while it is being made: silence.
        for st in (FINISHED, GENERATING):
            self.assertEqual(self.kind('финансовая система российской', st)[0], 'silent', st)
        # Wave F / F2 ruling (the owner's call 03.11 09:55): with nothing said before, a bare named topic is a question, never an ack.
        self.assertEqual(self.kind('финансовая система российской', None)[0], 'question')


class MismatchPolicyTests(ClassifierCase):
    def test_related_wrong_repeat_is_an_attempt_and_replays_by_default(self):
        kind, reason = self.kind('финансовая система', WAITING)
        self.assertEqual(kind, 'replay')
        self.assertIn('attempt', reason)
        self.assertEqual(self.kind('российская', WAITING)[0], 'replay')

    def test_silent_policy_keeps_the_old_behaviour(self):
        for text in ('финансовая система', 'а', 'мы вчера обсуждали другую тему'):
            self.assertEqual(self.kind(text, WAITING, diagnose=False)[0], 'silent', text)

    def test_silent_policy_still_answers_an_explicit_request_to_hear_the_portion_again(self):
        # WAVE 2 / Task A (brief section 3, DEF-ACK-15): «не понял» / «что?» is a request, not a wrong repeat, so the
        # production profile (on_mismatch=silent) speaks the portion again at once. A bare «а» is still only noise.
        for text in ('не понял', 'не расслышал', 'Что?', 'а?'):
            self.assertEqual(self.kind(text, WAITING, diagnose=False)[0], 'replay', text)

    def test_short_clarifications_replay_the_same_portion(self):
        for text in ('а', 'что', 'ещё', 'Еще', 'не понял', 'не слышу', 'не расслышал', 'Что?', 'Не расслышал.', 'ну не понял'):
            kind, reason = self.kind(text, WAITING)
            self.assertEqual(kind, 'replay', (text, reason))
            self.assertIn('clarification', reason)

    def test_phrases_the_phone_handles_itself_are_not_clarifications(self):
        # Conduit intercepts them locally; if some other client does send them they must not replay a portion.
        for text in ('тише', 'закончить разговор', 'это всё'):
            self.assertEqual(self.kind(text, WAITING)[0], 'silent', text)
        # Wave F / F2 fix round 1 (ruling 4): farewells are small talk - still nothing replayed, nothing asked.
        for text in ('пока', 'до свидания'):
            self.assertEqual(self.kind(text, WAITING)[0], 'greeting', text)
        # WAVE 2 / Task A (brief section 3, DEF-ACK-18, QUESTION-ACK-04): in the native audio route the server receives
        # «хватит» and «замолчи» as transcripts, so they stop the dictation here as well. Still never a replay.
        for text in ('хватит', 'замолчи'):
            self.assertEqual(self.kind(text, WAITING)[0], 'stop', text)

    def test_clarification_list_is_configurable(self):
        self.assertEqual(self.kind('чего', WAITING)[0], 'silent')
        self.assertEqual(self.kind('чего', WAITING, settings={'clarifications': ['чего']})[0], 'replay')

    def test_repeat_commands_replay_under_any_policy(self):
        for text in ('повтори', 'Повторите', 'ну повтори', 'еще раз', 'ещё раз'):
            for diagnose in (False, True):
                self.assertEqual(self.kind(text, WAITING, diagnose=diagnose), ('repeat', 'repeat_command'), (text, diagnose))

    def test_long_talk_that_merely_uses_the_same_word_is_not_an_attempt(self):
        talk = 'я вчера читал что финансовая система нашей страны довольно сложная'
        kind, reason = self.kind(talk, WAITING)
        self.assertEqual((kind, reason), ('silent', 'speech_too_long_for_an_attempt'))
        self.assertEqual(self.kind(talk, WAITING, settings={'attempt_extra_words': 30})[0], 'replay')
        self.assertEqual(self.kind('финансовая система нашей страны', WAITING)[0], 'replay')

    def test_unrelated_longer_speech_is_silent(self):
        kind, reason = self.kind('мы вчера обсуждали совсем другую тему в офисе', WAITING)
        self.assertEqual(kind, 'silent')

    def test_function_words_do_not_make_noise_look_like_an_attempt(self):
        waiting = state(chunks=('на основании закона', 'о бюджете'))
        self.assertEqual(self.kind('на столе лежит книга', waiting)[0], 'silent')
        self.assertEqual(self.kind('закон', waiting)[0], 'replay')

    def test_common_words_of_three_or_more_letters_do_not_make_noise_look_like_an_attempt(self):
        waiting = state(chunks=('для расчёта налога', 'нужен калькулятор'))
        self.assertEqual(self.kind('для меня это совсем не важно', waiting)[0], 'silent')
        self.assertEqual(self.kind('при этом все было нормально', waiting)[0], 'silent')
        self.assertEqual(self.kind('расчёта', waiting)[0], 'replay')

    def test_one_stray_word_that_shares_a_stem_only_replays_never_cancels_or_advances(self):
        kind, _ = self.kind('система', WAITING)
        self.assertEqual(kind, 'replay')

    def test_numbers_count_as_content_even_when_short(self):
        waiting = state(chunks=('на 15 процентов', 'годовых'))
        self.assertEqual(self.kind('15', waiting)[0], 'replay')
        self.assertEqual(self.kind('на 16', waiting)[0], 'silent')

    def test_nothing_to_replay_without_a_waiting_answer(self):
        for st in (None, FINISHED, GENERATING):
            for text in ('а', 'не понял', 'финансовая система'):
                if st is None and text == 'финансовая система':
                    # Wave F / F2 ruling: with nothing said before, a bare named topic is a question (never a replay).
                    self.assertEqual(self.kind(text, st)[0], 'question', (text, st))
                    continue
                self.assertEqual(self.kind(text, st)[0], 'silent', (text, st))

    def test_empty_text_is_silent(self):
        for text in ('', '   ', '...', None):
            self.assertEqual(self.kind(text, WAITING)[0], 'silent')


class CommandTests(ClassifierCase):
    def test_commands_survive_fillers(self):
        self.assertEqual(self.kind('ну повтори', WAITING)[0], 'repeat')
        self.assertEqual(self.kind('так стоп', WAITING)[0], 'stop')
        self.assertEqual(self.kind('Стоп!', None)[0], 'stop')

    def test_stop_and_repeat_need_the_whole_utterance(self):
        self.assertNotEqual(self.kind('повтори пожалуйста что такое налоги', WAITING)[0], 'repeat')
        self.assertEqual(self.kind('не стоп а продолжай говорить дальше', WAITING)[0], 'silent')


class SettingsAreOptionalTests(ClassifierCase):
    def test_partial_and_missing_settings_use_defaults(self):
        self.assertEqual(self.kind('Что такое бюджет', None, BANK), self.kind('Что такое бюджет', None, BANK, {}))
        self.assertEqual(self.kind('Что такое бюджет', None, BANK)[0], 'question')
        self.assertEqual(self.kind('Что такое бюджет', None, None)[0], 'question')


if __name__ == '__main__':
    unittest.main()


def test_u16_own_number_range_portion_is_numeric():
    from echo_sync.classifier import _mismatch, norm_words, REPLAY
    cfg = {'diagnose': True, 'attempt_extra_words': 3}
    fillers = frozenset()
    heard, portion = norm_words('по пятнадцатый век'), norm_words('примерно в XIII–XV веках.')
    g28_heard, g28_portion = norm_words('пятьдесят девятый счёт это'), norm_words('расчётные счета организации в банке')
    got = _mismatch(cfg, True, heard, portion, fillers, '')
    assert (got.kind, got.reason) == (REPLAY, 'attempt_shared_stem')
    assert _mismatch(cfg, True, g28_heard, g28_portion, fillers, '').reason == 'unrelated_speech'

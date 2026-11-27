"""U19-S4: the language line of the brain prompt follows the turn (always, no key); Russian stays byte-identical."""
from echo_sync import fast_text as FT
from echo_sync.lang_hint import LANG_RULES, TurnLang
from echo_sync.settings import resolve

from test_h1_fast_text import FakeStream, Clock, manager


class Ctl:
    def __init__(self):
        self.turn_lang = TurnLang()
        self.fast_exchanges = lambda: []
        self.settings = {}
        self.ear_ended = 0
        self.source_segment_id = None
        self.refuse_deadline = self.decision_due = lambda *a: None      # no question open, no bound

    def fast_in_play(self):
        return None

    def fast_carry(self):
        return ''      # the memory of earlier calls (``for_call`` hands it to the channel)


def instructions_of(settings, question):
    ctl = Ctl()
    ctl.turn_lang.observe(question)
    channel = FT.for_call(resolve(settings), ctl, stream=FakeStream())
    return channel.lang_line(), ctl


def test_en_request_has_the_english_line_and_ru_is_byte_identical():
    en, _ = instructions_of({'fast_text': 'on'}, 'What is the capital of Canada?')
    assert en == LANG_RULES['en']['instruction']
    ru, _ = instructions_of({'fast_text': 'on'}, 'Что такое абсолютная ссылка в Excel')
    assert ru == ''
    fast, fake, clock = manager()
    job = fast._start('Что такое инерция')
    assert job.request['instructions'] == 'POLICY'                              # no channel line: byte-identical


def test_the_line_follows_the_turn_whatever_the_old_flags_say():      # one-input U19: answer_lang is gone, the line is not a mode
    for flags in ({}, {'lang_turn': 'off'}, {'lang_turn': 'shadow'}, {'lang_turn': 'on', 'answer_lang': 'ru'}):
        line, _ = instructions_of(dict(flags, fast_text='on'), 'What is the capital of Canada?')
        assert line == LANG_RULES['en']['instruction'], flags


def test_start_appends_the_line_to_the_instructions():
    fast, fake, clock = manager()
    fast.lang_line = lambda: 'LINE'
    job = fast._start('What is it')
    assert job.request['instructions'] == 'POLICY\n\nLINE'
    fast.lang_line = lambda: ''
    assert fast._start('x').request['instructions'] == 'POLICY'

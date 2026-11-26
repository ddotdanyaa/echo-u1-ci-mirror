"""Russian current-chunk donor adapter: morphology and protected values."""
import unittest
from echo_sync.classifier import analyze
from engine_say import engine_reply


import pytest
pytestmark = pytest.mark.usefixtures('no_lead')      # the lead is not the matter of these scenes (tests/conftest.py)


def waiting(text):
    return {'chunks':[text,'Следующая порция.'],'chunk_index':0,'completed':False,'pending_turn':None}


class RussianAlignmentTests(unittest.TestCase):
    settings={}

    def check(self,heard,expected,accepted):
        result=analyze(heard,waiting(expected),[],self.settings)
        self.assertEqual(result.kind=='ack',accepted,(heard,expected,result.kind,result.reason))

    def test_library_morphology_matches_irregular_forms_without_fuzzy_word_substitution(self):
        for heard,expected in [('люди платят налоги','человек платит налог'),
                               ('дети читают книги','ребенок читает книгу'),
                               ('российская федерация','Российской Федерации')]:
            with self.subTest(heard=heard):self.check(heard,expected,True)

    def test_spoken_values_and_display_symbols_have_equal_canonical_form(self):
        pairs=[('пятнадцать процентов','15 %'),('пять процентов','5%'),
               ('двадцать пять процентов','25 %'),('минус пятнадцать','−15'),
               ('плюс пять','+5'),('пятнадцатая статья','15-я статья'),
               ('два килограмма','2 кг'),('три миллиграмма','3 мг')]
        for a,b in pairs:
            with self.subTest(a=a,b=b):self.check(a,b,True);self.check(b,a,True)

    def test_protected_numeric_corpus_has_no_false_accepts(self):
        count=0
        for expected in range(25):
            for offset in (1,2,10,50):
                wrong=expected+offset
                for template in ('ставка {} процентов','статья {} кодекса'):
                    with self.subTest(expected=expected,wrong=wrong,template=template):
                        self.check(template.format(wrong),template.format(expected),False)
                        count+=1
        self.assertEqual(count,200)

    def test_negations_units_signs_and_similar_different_words_are_not_fuzzy_accepted(self):
        pairs=[('облагается налогом','не облагается налогом'),('нет налога','есть налог'),
               ('пятьдесят процентов','15%'),('пятнадцать','−15'),('минус пять','+5'),
               ('3 г','3 мг'),('до оплаты','после оплаты'),('налог уплачен','залог уплачен'),
               ('гипогликемия','гипергликемия'),('кот','собака'),('раз','два')]
        for a,b in pairs:
            with self.subTest(a=a,b=b):self.check(a,b,False)

    def test_partial_and_asr_typo_repeat_current_without_acceptance(self):
        for heard in ('Российской','Росийской Федерации'):
            d=analyze(heard,waiting('Российской Федерации'),[],self.settings)
            self.assertEqual(d.kind,'replay')

    def test_locality_never_accepts_the_next_chunk(self):
        self.assertNotEqual(analyze('Следующая порция',waiting('Первая часть ответа'),[],self.settings).kind,'ack')

    def test_unknown_math_symbols_are_not_silently_deleted(self):
        for heard,expected in [('1 2','1⁄2'),('a b','a ∈ b'),('a b','a ≠ b'),('1 2','1:2'),('a b','a ∈ ≠ b')]:
            with self.subTest(heard=heard,expected=expected):self.check(heard,expected,False)

    def test_empty_cyrillic_phonetic_keys_never_create_bonus(self):
        for heard,expected in [('абра','кадабра'),('налог','залог'),('...','!!!')]:
            with self.subTest(heard=heard,expected=expected):self.check(heard,expected,False)

    def test_missing_donor_dependency_does_not_fall_back_to_less_strict_match(self):
        from unittest.mock import patch
        with patch('echo_sync.ru_alignment._canonical',side_effect=ImportError('not installed')):
            self.check('Первый ответ','Первый ответ',False)

    def test_superscripts_subscripts_cannot_collapse_into_ordinary_digits(self):
        for heard,expected in [('12','1²'),('10','1⁰'),('12','1₂'),('x2','x²'),('3','³')]:
            with self.subTest(heard=heard,expected=expected):self.check(heard,expected,False)

    def test_math_grouping_and_cardinal_ordinal_meanings_are_protected(self):
        for heard,expected in [('1+2*3','(1+2)*3'),('a+b*c','(a+b)*c'),
                               ('один ответ','первый ответ'),('два раза','второй раз')]:
            with self.subTest(heard=heard,expected=expected):self.check(heard,expected,False)


    def test_duplicate_and_restart_keep_exactly_once_cursor_semantics(self):
        import tempfile
        from pathlib import Path
        from echo_sync.engine import EchoEngine
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'state.sqlite3'
            e=EchoEngine(path,lambda *a:'Ставка 15% применяется сегодня.',settings=self.settings)
            engine_reply(e, session_id='s',turn_id='q',text='Что это?',request={},model='offline')
            current=e.state('s')['chunks'][0]
            spoken=current.replace('15%','пятнадцать процентов')
            first=engine_reply(e, session_id='s',turn_id='ack',text=spoken,request={},model='offline')
            cursor=e.state('s')['chunk_index']
            restarted=EchoEngine(path,lambda *a:self.fail('unexpected generation'),settings=self.settings)
            self.assertEqual(engine_reply(restarted, session_id='s',turn_id='ack',text=spoken,request={},model='offline'),first)
            self.assertEqual(restarted.state('s')['chunk_index'],cursor)


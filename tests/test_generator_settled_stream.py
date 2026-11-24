"""Codex may omit message content in its terminal snapshot after tool execution."""
from types import SimpleNamespace as S
import unittest

from echo_sync.generator import PrivateCodexGenerator


class SettledStreamTests(unittest.TestCase):
    def generate(self, events):
        self.calls=0; self.closed=False
        owner=self
        class Stream:
            def __iter__(self):return iter(events)
            def close(self):owner.closed=True
        class Client:
            def __init__(self,**kwargs):self.responses=self
            def create(self,**kwargs):owner.calls+=1;return Stream()
            def close(self):pass
        return PrivateCodexGenerator(resolve=lambda:{'api_key':'a.b.c','base_url':'https://chatgpt.com/backend-api/codex'},
                                     headers=lambda *a,**kw:{},client_factory=Client).generate_cancellable('Как?',[],'',{},'offline')

    def test_settled_text_is_used_when_terminal_snapshot_has_no_messages(self):
        answer=self.generate([S(type='response.output_text.done',output_index=1,content_index=0,text='Проверенный полный ответ.'),
                              S(type='response.completed',response=S(output=[],status='completed'))])
        self.assertEqual(answer,'Проверенный полный ответ.')
        self.assertEqual(self.calls,1);self.assertTrue(self.closed)

    def test_multiple_settled_parts_are_ordered_and_duplicate_done_is_idempotent(self):
        answer=self.generate([S(type='response.output_text.done',output_index=1,content_index=1,text='Вторая часть.'),
                              S(type='response.output_text.done',output_index=1,content_index=0,text='Первая часть. '),
                              S(type='response.output_text.done',output_index=1,content_index=1,text='Вторая часть.'),
                              S(type='response.completed',response={'output':[],'status':'completed'})])
        self.assertEqual(answer,'Первая часть. Вторая часть.')

    def test_done_without_terminal_completion_is_never_published(self):
        with self.assertRaises(ValueError):
            self.generate([S(type='response.output_text.done',text='Нельзя выдавать до completed.')])
        self.assertTrue(self.closed)

    def test_terminal_incomplete_cannot_publish_preceding_settled_text(self):
        with self.assertRaises(ValueError):
            self.generate([S(type='response.output_text.done',text='Неполный ответ.'),
                           S(type='response.completed',response=S(output=[],status='incomplete'))])

    def test_unsettled_delta_is_not_a_fallback_answer(self):
        with self.assertRaises(ValueError):
            self.generate([S(type='response.output_text.delta',delta='Нестабильный prefix'),
                           S(type='response.completed',response=S(output=[],status='completed'))])

    def test_dictionary_terminal_messages_are_supported(self):
        answer=self.generate([S(type='response.completed',response={'status':'completed','output':[
            {'type':'message','content':[{'type':'output_text','text':'Словарный snapshot.'}]}]})])
        self.assertEqual(answer,'Словарный snapshot.')


if __name__=='__main__':unittest.main()

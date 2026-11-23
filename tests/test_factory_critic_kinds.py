"""W-critic 1: the paid critic asks a test card its own question; the contract reaches every critic of it; the
test-only classes never reach a prompt."""
import json
import types

from tests.test_factory_paid_critic import Net, answer, env  # noqa: <id>  (env: fixture)
from tools import factory_classes as C
from tools import factory_paid_critic as P

CONTRACT = json.dumps({'test': {'new': {'path': 'tests/test_x.py', 'given': 'GIVENTEXT', 'when': 'WHENTEXT',
                                         'then': 'THENTEXT', 'red_now_because': 'REDTEXT'}}})


def _card(kind):
    return types.SimpleNamespace(id='X_test', title='Test for X', kind=kind, touch_files=('tests/test_x.py',),
                                 goal='Test for X', contract=CONTRACT, tests=('tests/test_x.py',))


def test_a_test_card_gets_the_test_question_and_its_contract(env, monkeypatch):
    net = Net(answer('approve', '', '', ''))
    monkeypatch.setattr(P, '_post', net)
    P.control(_card('unit_test'), 'DIFF', '')
    sent = net.calls[0][2]['messages'][0]['content']
    assert sent.startswith(P.ASK_TEST) and 'is never a defect' in sent
    assert all(w in sent for w in ('GIVENTEXT', 'WHENTEXT', 'THENTEXT', 'REDTEXT'))


def test_a_code_card_keeps_the_old_question(env, monkeypatch):
    net = Net(answer('approve', '', '', ''))
    monkeypatch.setattr(P, '_post', net)
    P.control(_card('code'), 'DIFF', '')
    sent = net.calls[0][2]['messages'][0]['content']
    assert sent.startswith(P.ASK) and 'GIVENTEXT' not in sent


def test_the_free_critic_of_a_test_card_sees_the_contract():
    from tools import factory_cards as K
    spec = K.test_spec(_card('unit_test'))
    assert 'Given: GIVENTEXT' in spec and 'Red now because: REDTEXT' in spec
    assert K.test_spec(_card('code')) == ''


def test_test_only_classes_are_filtered_by_name():
    for cid in ('test-only-no-fix', 'test-only-no-implementation', 'no-source-fix-test-only',
                'test-only-no-fix-unrelated-scope'):
        assert C.is_test_only(cid)
    assert not C.is_test_only('hardcoded-expectation')


def test_test_only_paid_classes_do_not_enter_the_critic_lesson(env):
    for cls in ('test-only-no-fix', 'hardcoded-expectation'):
        P.record_class(types.SimpleNamespace(id='A', title='', kind='code', touch_files=['calc.py']),
                       dict(**{'class': cls}, symptom='s ' + cls, reason=''))
    text = P.lessons_for(types.SimpleNamespace(id='B', title='', kind='unit_test', touch_files=['calc.py']))
    assert 'hardcoded-expectation' in text and 'test-only' not in text
    assert C.lesson('test-only-no-fix', 'B', ['calc.py'], examples=['x']) == ''

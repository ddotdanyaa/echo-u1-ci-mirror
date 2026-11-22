"""<id> (owner: the cutter must cut tasks excellently, cheaply and with priorities). Live 19.11: 0 of 6 tests
written from backlog rows were good, and 20:00-00:35 only 5 of 20 ECHO tasks reached review - the rows are not machine
tasks. Before a test is written, one cheap call turns the row into a spec: is it a code defect testable by calling the
code at all, which function, called how, what it gives now, what it must give, and the one assertion. A row that is
not a testable code defect is kept with its reason instead of burning attempts; a spec naming a function that is not
in the code shown is refused (a guessed name is a test that crashes)."""
from tools import factory_spec as S

CODE = {'echo_sync/fast_text.py': 'def say_number(n):\n    return " ".join(str(n))\n'}
GOOD = ('{"testable": true, "why": "digits are spoken one by one", "function": "say_number", '
        '"call": "say_number(40000)", "now": "4 0 0 0 0", "expected": "сорок тысяч", '
        '"assert": "assert say_number(40000) == \'сорок тысяч\'"}')


def test_a_good_answer_becomes_a_spec():
    spec = S.parse(GOOD, CODE)
    assert spec['testable'] is True
    assert spec['function'] == 'say_number'
    assert spec['assert'].startswith('assert say_number(')


def test_a_function_not_in_the_code_is_refused():
    assert S.parse(GOOD.replace('"function": "say_number"', '"function": "speak"'), CODE) is None


def test_an_answer_without_json_or_without_its_fields_is_refused():
    assert S.parse('I think the test should check numbers', CODE) is None
    assert S.parse('{"testable": true}', CODE) is None


def test_a_row_that_is_not_testable_is_kept_with_its_reason():
    spec = S.parse('{"testable": false, "why": "a process rule, not a code defect"}', CODE)
    assert spec == {'testable': False, 'why': 'a process rule, not a code defect'}


def test_the_goal_of_the_test_task_is_the_spec():
    goal = S.goal(S.parse(GOOD, CODE), 'E89000')
    assert '# factory-backlog-id: E89000' in goal
    assert 'say_number(40000)' in goal
    assert 'сорок тысяч' in goal
    assert '4 0 0 0 0' in goal
    assert 'must fail on the current code' in goal


def test_the_prompt_carries_the_row_the_code_and_the_example():
    p = S.prompt('Числа вслух звучат неверно', CODE, example='def test_x():\n    assert 1\n')
    assert 'Числа вслух звучат неверно' in p
    assert 'def say_number' in p
    assert 'def test_x' in p
    assert '"testable"' in p


def test_json_inside_prose_and_a_dotted_function_name_are_understood():
    answer = 'Here is the spec:\n' + GOOD.replace('"function": "say_number"', '"function": "echo_sync.fast_text.say_number"')
    spec = S.parse(answer, CODE)
    assert spec['function'] == 'say_number'


def test_the_goal_names_the_rules_a_written_test_breaks_most():
    goal = S.goal(S.parse(GOOD, CODE), 'E89000')
    assert 'import the function from its module' in goal
    assert 'no network, no audio, no sleeps' in goal

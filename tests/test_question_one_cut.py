"""Question family, one owner each: a compound question is cut in ONE place (``followup.QuestionMap``) and ``engine`` keeps no cut of its own;
the follow-up of ``ControlledMedia`` is ``followup.is_followup`` and nothing else."""
import inspect

from echo_sync import engine
from echo_sync.cm_kind import KindMixin
from echo_sync.cm_memory import MemoryMixin


def _state(question, said):
    return {'history': [{'question': question, 'status': 'interrupted', 'at': 100.0, 'chunks': [said], 'spoken': 1}]}


def test_the_engine_has_no_cut_of_its_own_for_a_compound_question():
    for name in ('_parts', '_PART_SPLIT', '_PART_PREPOSITIONS', '_PART_LEADS'):
        assert not hasattr(engine, name), name
    assert 'QuestionMap' in inspect.getsource(engine.conversation_map)


def test_both_kinds_of_compound_question_reach_the_map_through_the_one_cut():
    by_preposition = engine.conversation_map(_state('Расскажи про НДС, про УСН и про патент', 'НДС это налог.'), now=110.0)
    assert by_preposition and by_preposition[0]['open_parts'] == ['про УСН', 'про патент']
    by_asking = engine.conversation_map(_state('Сколько стоит и когда привезут', 'Это стоит 500 рублей.'), now=110.0)
    assert by_asking and by_asking[0]['open_parts'] == ['когда привезут']
    plain = engine.conversation_map(_state('Что такое НДС', 'Налог.'), now=110.0)
    assert plain and 'open_parts' not in plain[0]


def test_the_follow_up_of_the_controller_is_the_one_predicate():
    assert 'is_followup(' in inspect.getsource(MemoryMixin._follows_on)
    assert not hasattr(MemoryMixin, '_context_followup') and '_follows_on' not in vars(KindMixin) and not hasattr(KindMixin, '_context_followup')


def test_the_topic_of_the_search_has_one_form_and_one_path():
    import pathlib
    source = pathlib.Path(inspect.getsourcefile(engine)).with_name('cm_question.py').read_text(encoding='utf-8')
    assert "' Тема: '" not in source and 'complete_followup(asked,[previous_topic])' in source

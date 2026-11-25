from echo_sync.portioner import stable_prefix

CFG={'portion_mode':'words','words_per_portion':3}

def test_incomplete_first_word_and_one_portion_are_held():
 assert stable_prefix('Электроэнцефало',CFG)==''
 assert stable_prefix('Первый второй третий ',CFG)==''

def test_one_lookahead_portion_allows_initial_complete_prefix():
 assert stable_prefix('Первый второй третий четвёртый пятый шестой ',CFG)=='Первый второй третий'
 assert stable_prefix('Первый второй третий четвёртый пятый шес',CFG)=='Первый второй третий'

def test_committed_prefix_does_not_get_replanned():
 before='Первый второй третий'
 text=before+' четвёртый пятый шестой седьмой восьмой девятый '
 assert stable_prefix(text,CFG,committed=before)==before+' четвёртый пятый шестой'
 assert stable_prefix('Переписанный ответ',CFG,committed=before) is None

def test_stream_with_expanding_abbreviations_waits_for_full_text():
 assert stable_prefix('НК РФ устанавливает порядок исчисления налогов ',{'abbreviations':{'НК РФ':'Налоговый кодекс Российской Федерации'}})==''

def test_quantifier_is_not_detached_from_its_predicate_noun():
 from echo_sync.portioner import portions
 cfg={'preset':'slow_assistive','min_words':2}
 chunks=portions('Доход — все поступления денег от деятельности.',cfg)
 assert chunks[0]=='Доход — все поступления'
 assert all(not chunk.rstrip(',.').endswith('все') for chunk in chunks[:-1])

def test_compact_spoken_copula_preserves_negation_and_verbatim_quotes():
 from echo_sync.textutil import compact_spoken_definition
 assert compact_spoken_definition('Доход — это все поступления')=='Доход — все поступления'
 assert compact_spoken_definition('Инерция — это не сила.')=='Инерция — не сила.'
 assert compact_spoken_definition('«Доход — это все поступления»')=='«Доход — это все поступления»'
 assert compact_spoken_definition('Это свойство тела.')=='Это свойство тела.'

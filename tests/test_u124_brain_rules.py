"""U124: ONE file of the instructions of the voice mode (``echo_sync/brain_rules.py``): every line of the text the model gets (``fast_text.BRAIN`` and ``BRAIN_KEEP``) is a row with the id of the error it was written for. The tag is in the structure, never in
the text: the instructions the model is sent are byte for byte what they were before the move (the hashes below were taken from the tree before it), and ``brain_short`` (its SHORT_POLICY carries BRAIN_KEEP) is the same."""
import hashlib
import re
from pathlib import Path

from echo_sync import brain_rules as R
from echo_sync import brain_short as S
from echo_sync import fast_text as F

H = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()      # noqa: E731
BEFORE = {'BRAIN': ('0b28d95ff1f79e2aeee7b901872aeb5dd60beffda4f77ab21576722fa5e46eb5', 4259), 'BRAIN_KEEP': ('86334e92d6dd2fa7cd94bf4a8564c823eb09c643a6caa0771fd127cb08276aee', 1374),
          'BRAIN_POLICY': ('ec026cbd5f7d4f0db6be2d14122046382683c31b92fff87f9fc6a28d06357bda', 5634), 'SHORT_POLICY': ('6f0b8595d381a6768977fe2bd4e6e01a28275a66cdceebf579ecb32ed47b8a1c', 3922)}


def test_the_instructions_are_byte_for_byte_what_they_were():
    got = {'BRAIN': F.BRAIN, 'BRAIN_KEEP': F.BRAIN_KEEP, 'BRAIN_POLICY': F.BRAIN_POLICY, 'SHORT_POLICY': S.SHORT_POLICY}
    assert {k: (H(v), len(v.encode('utf-8'))) for k, v in got.items()} == BEFORE
    assert F.BRAIN_POLICY == F.BRAIN + '\n' + F.BRAIN_KEEP and S.SHORT_POLICY == S.BRAIN_SHORT + '\n' + F.BRAIN_KEEP


def test_fast_text_has_no_copy_of_the_instructions():
    source = Path(F.__file__).read_text(encoding='utf-8')
    assert 'Ты суфлёр' not in source and 'Отвечай по-русски' not in source
    assert F.BRAIN is R.BRAIN and F.BRAIN_KEEP is R.BRAIN_KEEP


def test_every_row_is_tied_to_a_caught_error():
    rows = R.BRAIN_ROWS + R.KEEP_ROWS
    assert rows and all(isinstance(ids, tuple) and ids and isinstance(text, str) and text for ids, text in rows)
    assert {i for ids, _ in rows for i in ids} <= set(R.CAUGHT)
    assert set(R.CAUGHT) == {i for ids, _ in rows for i in ids}, 'an id with no line'
    for name, why in R.CAUGHT.items():
        assert why['where'] and why['what'], name


def test_an_id_names_a_commit_a_backlog_row_or_a_call():
    from tools.backlog_register import ROWS
    registered = {i for ids, *_ in ROWS for i in ids.split()}
    for name, why in R.CAUGHT.items():
        assert re.fullmatch(r'[0-9a-f]{7,8}|[NР]\d{2,3}|U\d{2,3}|call [0-9.]+ [0-9:]+', why['where']), (name, why['where'])
        if why['where'][0] in 'NР':
            assert why['where'] in registered, name


def test_the_text_is_the_rows_joined_and_the_tags_are_not_in_it():
    assert R.BRAIN == '\n'.join(t for _, t in R.BRAIN_ROWS) and R.BRAIN_KEEP == ' '.join(t for _, t in R.KEEP_ROWS)
    assert not any(i in F.BRAIN_POLICY for i in R.CAUGHT)      # the keys of the tags are not in what the model is sent

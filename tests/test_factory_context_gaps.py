"""<id> class (19.11 23:59: fac_parse_cache and fac_triage_example failed 4 passes each with 'SEARCH not found'). Two
shown parts with a few unseen lines between them (a module-level try/except between two assignments and a function)
made every SEARCH that spans them a miss: the model copies the view, the view skipped lines. Shown parts whose gap is
at most GAP_FILL_LINES lines are shown as ONE contiguous part, gap included, while the room allows; parts far apart
stay separate; a window overlapping a shown part is not shown twice. The header stays '# <name>, lines a-b' (the
form ERROR_PATTERNS strips when a model copies it into SEARCH)."""
from tools import factory_context as X
from tools import factory_patterns as P

SRC = ("import pickle\n\n"
       "_CACHE_FILE = 'a.pkl'\n"
       "_CACHE = {}\n"
       "try:\n"
       "    _CACHE = pickle.loads(b'')\n"
       "except Exception:\n"
       "    _CACHE = {}\n"
       "\n\n"
       "def _save_cache():\n"
       "    try:\n"
       "        open(_CACHE_FILE, 'wb').write(pickle.dumps(_CACHE))\n"
       "    except Exception:\n"
       "        pass\n\n\n"
       + "".join("def filler_%d():\n    return %d\n\n\n" % (i, i) for i in range(40))
       + "def far_away():\n    return 1\n")

BLOCK = ("_CACHE_FILE = 'a.pkl'\n_CACHE = {}\ntry:\n    _CACHE = pickle.loads(b'')\nexcept Exception:\n"
         "    _CACHE = {}\n\n\ndef _save_cache():\n    try:\n")


def test_close_parts_are_one_contiguous_part_with_the_unseen_lines():
    view = X._fragments(SRC, {'_CACHE_FILE', '_CACHE', '_save_cache'}, 20000)
    assert "_CACHE = pickle.loads(b'')" in view
    assert BLOCK in view
    assert view.count(', lines ') == 1
    assert view.splitlines()[0] == '# _CACHE_FILE, lines 3-15'
    assert P.VIEW_LINE.match(view.splitlines()[0])


def test_parts_far_apart_stay_separate():
    view = X._fragments(SRC, {'_save_cache', 'far_away'}, 20000)
    assert view.count(', lines ') == 2
    assert 'filler_3' not in view


def test_without_gap_fill_the_unseen_lines_stay_unseen(monkeypatch):
    monkeypatch.setattr(X, 'GAP_FILL_LINES', 0)
    view = X._fragments(SRC, {'_CACHE_FILE', '_CACHE', '_save_cache'}, 20000)
    assert "pickle.loads(b'')" not in view
    assert view.count(', lines ') == 2          # the two adjacent assignments still join: no gap between them


def test_the_gap_is_not_filled_beyond_the_room():
    tight = len(X._fragments(SRC, {'_CACHE_FILE', '_CACHE', '_save_cache'}, 20000)) - 40
    view = X._fragments(SRC, {'_CACHE_FILE', '_CACHE', '_save_cache'}, tight)
    assert len(view) <= tight
